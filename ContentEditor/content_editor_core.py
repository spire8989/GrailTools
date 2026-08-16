"""Core loading, validation, and safe persistence for the Grail Content Editor.

The game content is JavaScript source rather than JSON.  The current authored
data uses a deliberately small object-literal subset, so this module parses
that subset with a tokenizer instead of evaluating arbitrary project code.
Only changed top-level definition properties are replaced when saving; the
rest of a source file remains byte-for-byte untouched.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


class JsParseError(ValueError):
    """Raised when a supported JavaScript data literal cannot be parsed."""


@dataclass
class Token:
    kind: str
    value: Any
    position: int
    end: int


@dataclass
class ParsedProperty:
    """Source spans for one direct property of a parsed object literal."""

    key: str
    key_start: int
    value_start: int
    value_end: int
    index: int


class JsTokenizer:
    """Tokenizer for the data-only JavaScript subset used by Grail."""

    _identifier = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
    _number = re.compile(r"-?(?:0[xX][0-9A-Fa-f]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)")

    def __init__(self, source: str):
        self.source = source
        self.length = len(source)
        self.position = 0

    def tokens(self) -> Iterable[Token]:
        while True:
            self._skip_space_and_comments()
            if self.position >= self.length:
                yield Token("eof", None, self.position, self.position)
                return

            start = self.position
            character = self.source[self.position]
            if self.source.startswith("...", self.position):
                self.position += 3
                yield Token("spread", "...", start, self.position)
                continue

            if character in "{}[]():,.":
                self.position += 1
                yield Token(character, character, start, self.position)
                continue

            if character in "'\"`":
                value = self._read_string(character)
                yield Token("string", value, start, self.position)
                continue

            number = self._number.match(self.source, self.position)
            if number:
                raw = number.group(0)
                self.position = number.end()
                if raw.lower().startswith("0x") or raw.lower().startswith("-0x"):
                    value = int(raw, 16)
                else:
                    value = float(raw) if any(marker in raw for marker in ".eE") else int(raw)
                yield Token("number", value, start, self.position)
                continue

            identifier = self._identifier.match(self.source, self.position)
            if identifier:
                value = identifier.group(0)
                self.position = identifier.end()
                yield Token("identifier", value, start, self.position)
                continue

            raise JsParseError(f"Unsupported character {character!r} at offset {start}")

    def _skip_space_and_comments(self) -> None:
        while self.position < self.length:
            if self.source[self.position].isspace():
                self.position += 1
                continue
            if self.source.startswith("//", self.position):
                line_end = self.source.find("\n", self.position + 2)
                self.position = self.length if line_end < 0 else line_end + 1
                continue
            if self.source.startswith("/*", self.position):
                comment_end = self.source.find("*/", self.position + 2)
                if comment_end < 0:
                    raise JsParseError("Unterminated block comment")
                self.position = comment_end + 2
                continue
            return

    def _read_string(self, quote: str) -> str:
        self.position += 1
        output: list[str] = []
        while self.position < self.length:
            character = self.source[self.position]
            self.position += 1
            if character == quote:
                return "".join(output)
            if character != "\\":
                output.append(character)
                continue
            if self.position >= self.length:
                raise JsParseError("Unterminated string escape")
            escaped = self.source[self.position]
            self.position += 1
            escapes = {
                "n": "\n",
                "r": "\r",
                "t": "\t",
                "b": "\b",
                "f": "\f",
                "v": "\v",
                "0": "\0",
                "\\": "\\",
                "'": "'",
                '"': '"',
                "`": "`",
            }
            if escaped in escapes:
                output.append(escapes[escaped])
            elif escaped == "\n":
                continue
            elif escaped == "x":
                output.append(chr(int(self._take(2), 16)))
            elif escaped == "u":
                output.append(chr(int(self._take(4), 16)))
            else:
                # JavaScript preserves unknown escaped characters as the
                # character itself in this content format.
                output.append(escaped)
        raise JsParseError("Unterminated string")

    def _take(self, count: int) -> str:
        value = self.source[self.position:self.position + count]
        if len(value) != count:
            raise JsParseError("Incomplete string escape")
        self.position += count
        return value


class JsValueParser:
    def __init__(self, source: str):
        self.source = source
        self.tokens = list(JsTokenizer(source).tokens())
        self.index = 0
        self.duplicate_keys: list[str] = []
        self.top_level_properties: list[ParsedProperty] = []

    @property
    def position(self) -> int:
        return self.tokens[self.index].position

    def parse(self) -> Any:
        value = self._object(capture_properties=True) if self._peek().kind == "{" else self._value()
        if self._peek().kind != "eof":
            token = self._peek()
            raise JsParseError(f"Unexpected token {token.value!r} at offset {token.position}")
        return value

    def _value(self) -> Any:
        token = self._peek()
        if token.kind == "{":
            return self._object()
        if token.kind == "[":
            return self._array()
        if token.kind in {"string", "number"}:
            self.index += 1
            return token.value
        if token.kind == "identifier":
            self.index += 1
            if token.value == "true":
                return True
            if token.value == "false":
                return False
            if token.value == "null":
                return None
            if token.value == "undefined":
                return None
            if token.value == "NaN":
                return None
            if token.value == "Infinity":
                return None
            if token.value in {"Object", "Array"} and self._peek().kind == ".":
                raise JsParseError("Unexpected member expression")
            raise JsParseError(f"Unsupported bare identifier {token.value!r}")
        raise JsParseError(f"Expected a value at offset {token.position}")

    def _object(self, capture_properties: bool = False) -> dict[str, Any]:
        self._expect("{")
        result: dict[str, Any] = {}
        while self._peek().kind != "}":
            key_token = self._peek()
            if key_token.kind not in {"identifier", "string", "number"}:
                raise JsParseError(f"Expected an object key at offset {key_token.position}")
            self.index += 1
            key = str(key_token.value)
            self._expect(":")
            if key in result:
                self.duplicate_keys.append(key)
            value_start = self._peek().position
            result[key] = self._value_or_wrapper()
            if capture_properties:
                value_end = self.tokens[self.index - 1].end
                self.top_level_properties.append(
                    ParsedProperty(key, key_token.position, value_start, value_end, len(self.top_level_properties))
                )
            if self._peek().kind == ",":
                self.index += 1
            elif self._peek().kind != "}":
                token = self._peek()
                raise JsParseError(f"Expected comma or object end at offset {token.position}")
        self._expect("}")
        return result

    def _array(self) -> list[Any]:
        self._expect("[")
        result: list[Any] = []
        while self._peek().kind != "]":
            result.append(self._value_or_wrapper())
            if self._peek().kind == ",":
                self.index += 1
            elif self._peek().kind != "]":
                token = self._peek()
                raise JsParseError(f"Expected comma or array end at offset {token.position}")
        self._expect("]")
        return result

    def _value_or_wrapper(self) -> Any:
        if self._peek().kind == "identifier" and self._peek().value in {"Object", "Array"}:
            saved = self.index
            name = self._peek().value
            self.index += 1
            if self._peek().kind == ".":
                self.index += 1
                member = self._expect("identifier").value
                if member == "freeze" and self._peek().kind == "(":
                    self.index += 1
                    value = self._value_or_wrapper()
                    self._expect(")")
                    return value
            self.index = saved
            if name == "Array" and self._peek().kind == "(":
                raise JsParseError("Array expressions are not supported")
        return self._value()

    def _peek(self) -> Token:
        return self.tokens[self.index]

    def _expect(self, kind: str) -> Token:
        token = self._peek()
        if token.kind != kind:
            raise JsParseError(f"Expected {kind!r} at offset {token.position}, got {token.value!r}")
        self.index += 1
        return token


@dataclass
class ParsedConstant:
    value: Any
    value_start: int
    value_end: int
    duplicate_keys: list[str] = field(default_factory=list)
    properties: list[ParsedProperty] = field(default_factory=list)


def extract_constant(source: str, name: str) -> ParsedConstant:
    """Extract and parse `const NAME = Object.freeze(<value>)`."""

    pattern = re.compile(rf"\bconst\s+{re.escape(name)}\s*=\s*Object\.freeze\s*\(")
    match = pattern.search(source)
    if not match:
        raise JsParseError(f"Could not find Object.freeze constant {name}")
    value_start = match.end()
    literal_start = value_start
    while literal_start < len(source) and source[literal_start].isspace():
        literal_start += 1
    value_end = _find_literal_end(source, literal_start)
    parser = JsValueParser(source[literal_start:value_end])
    value = parser.parse()
    if not isinstance(value, (dict, list)):
        raise JsParseError(f"Constant {name} is not an object or array")
    properties = [
        ParsedProperty(
            property_span.key,
            property_span.key_start + literal_start,
            property_span.value_start + literal_start,
            property_span.value_end + literal_start,
            property_span.index,
        )
        for property_span in parser.top_level_properties
    ]
    return ParsedConstant(value, literal_start, value_end, parser.duplicate_keys, properties)


def _find_literal_end(source: str, start: int) -> int:
    """Find the end of the first object/array literal after *start*.

    This scanner deliberately understands only nesting, strings, and comments;
    the actual syntax is still validated by :class:`JsValueParser`.
    """

    position = start
    while position < len(source) and source[position].isspace():
        position += 1
    if position >= len(source) or source[position] not in "[{":
        raise JsParseError(f"Expected an object or array at offset {position}")
    opening = source[position]
    closing = {"[": "]", "{": "}"}
    stack = [opening]
    position += 1
    quote: str | None = None
    while position < len(source):
        character = source[position]
        if quote:
            if character == "\\":
                position += 2
                continue
            if character == quote:
                quote = None
            position += 1
            continue
        if character in "'\"`":
            quote = character
            position += 1
            continue
        if source.startswith("//", position):
            line_end = source.find("\n", position + 2)
            position = len(source) if line_end < 0 else line_end + 1
            continue
        if source.startswith("/*", position):
            comment_end = source.find("*/", position + 2)
            if comment_end < 0:
                raise JsParseError("Unterminated block comment")
            position = comment_end + 2
            continue
        if character in "[{":
            stack.append(character)
        elif character in "]}":
            if not stack or character != closing[stack[-1]]:
                raise JsParseError(f"Mismatched closing bracket at offset {position}")
            stack.pop()
            if not stack:
                return position + 1
        position += 1
    raise JsParseError("Unterminated object or array literal")


def parse_file_constant(path: Path, name: str) -> tuple[ParsedConstant, str, bytes]:
    raw = path.read_bytes()
    source = raw.decode("utf-8")
    return extract_constant(source, name), source, raw


def constant_property_blocks(source: str, parsed: ParsedConstant) -> dict[str, str]:
    """Return each direct definition's authored source block.

    The block starts at the property key and ends at the end of its value,
    excluding the neighboring comma and whitespace. This is useful for
    regression tests and diagnostics; save operations replace only a property's
    value span, not its key or surrounding delimiters.
    """

    blocks: dict[str, str] = {}
    for property_span in parsed.properties:
        blocks[property_span.key] = source[property_span.key_start:property_span.value_end]
    return blocks


def clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _is_identifier(key: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", key))


def js_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def serialize_js(value: Any, indent: int = 0, newline: str = "\n") -> str:
    """Serialize parsed data as readable JavaScript object-literal syntax."""

    padding = " " * indent
    child_padding = " " * (indent + 2)
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return js_string(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return repr(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        if all(not isinstance(item, (dict, list)) for item in value):
            return "[" + ", ".join(serialize_js(item, indent, newline) for item in value) + "]"
        lines = ["["]
        for index, item in enumerate(value):
            suffix = "," if index < len(value) - 1 else ""
            lines.append(child_padding + serialize_js(item, indent + 2, newline) + suffix)
        lines.append(padding + "]")
        return newline.join(lines)
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines = ["{"]
        entries = list(value.items())
        for index, (key, item) in enumerate(entries):
            rendered_key = key if _is_identifier(str(key)) else js_string(str(key))
            suffix = "," if index < len(entries) - 1 else ""
            lines.append(child_padding + rendered_key + ": " + serialize_js(item, indent + 2, newline) + suffix)
        lines.append(padding + "}")
        return newline.join(lines)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


CONTENT_FILES = {
    "encounters": ("js/encounter-data.js", "ENCOUNTER_DEFINITIONS"),
    "injuries": ("js/injury-data.js", "INJURY_DEFINITIONS"),
    "campEvents": ("js/camp-data.js", "CAMP_EVENT_DEFINITIONS"),
    "expeditions": ("js/expedition-data.js", "EXPEDITION_DEFINITIONS"),
    "recipes": ("js/crafting-data.js", "RECIPE_DEFINITIONS"),
    "materials": ("js/crafting-data.js", "MATERIAL_DEFINITIONS"),
    "craftingProviders": ("js/crafting-data.js", "CRAFTING_PROVIDER_DEFINITIONS"),
    "shops": ("js/location-data.js", "SHOP_DEFINITIONS"),
    "items": ("js/data.js", "ITEM_DEFINITIONS"),
    "combats": ("js/combat-data.js", "COMBAT_DEFINITIONS"),
    "abilities": ("js/combat-data.js", "COMBAT_ABILITY_DEFINITIONS"),
    "enemyDefinitions": ("js/combat-data.js", "COMBAT_ENEMY_DEFINITIONS"),
    "enemyActions": ("js/combat-data.js", "COMBAT_ENEMY_ACTION_DEFINITIONS"),
    "lootTables": ("js/loot-data.js", "LOOT_TABLE_DEFINITIONS"),
}

REFERENCE_FILES = {
    "combats": ("js/combat-data.js", "COMBAT_DEFINITIONS"),
    "abilities": ("js/combat-data.js", "COMBAT_ABILITY_DEFINITIONS"),
    "injuries": ("js/injury-data.js", "INJURY_DEFINITIONS"),
    "lootTables": ("js/loot-data.js", "LOOT_TABLE_DEFINITIONS"),
    "expeditions": ("js/expedition-data.js", "EXPEDITION_DEFINITIONS"),
    "materials": ("js/crafting-data.js", "MATERIAL_DEFINITIONS"),
    "rarities": ("js/crafting-data.js", "RARITY_DEFINITIONS"),
    "campEventTables": ("js/camp-data.js", "CAMP_EVENT_TABLE_DEFINITIONS"),
    "campEvents": ("js/camp-data.js", "CAMP_EVENT_DEFINITIONS"),
    "locations": ("js/location-data.js", "LOCATION_DEFINITIONS"),
    "knowledge": ("js/data.js", "KNOWLEDGE_DEFINITIONS"),
    "companions": ("js/data.js", "COMPANION_DEFINITIONS"),
}


def _read_constant(project_root: Path, relative: str, name: str) -> tuple[Any, str, bytes, ParsedConstant]:
    path = project_root / relative
    parsed, source, raw = parse_file_constant(path, name)
    return parsed.value, source, raw, parsed


def _source_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _walk(value: Any, path: str = "") -> Iterable[tuple[str, Any, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield child_path, key, child
            yield from _walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            yield child_path, index, child
            yield from _walk(child, child_path)


def _ref_type_for_key(key: str) -> str | None:
    return {
        "itemId": "items",
        "treatmentItemId": "items",
        "combatId": "combats",
        "abilityId": "abilities",
        "injuryId": "injuries",
        "tableId": "lootTables",
        "lootTableId": "lootTables",
        "pathId": "paths",
        "expeditionId": "expeditions",
        "nextExpeditionId": "expeditions",
        "regionId": "regions",
        "shopId": "shops",
        "materialId": "materials",
        "recipeId": "recipes",
        "craftingProvider": "craftingProviders",
        "craftingProviderId": "craftingProviders",
        "eventId": "campEvents",
        "campEventId": "campEvents",
        "knowledgeId": "knowledge",
        "companionId": "companions",
    }.get(key)


def collect_references(value: Any, source: str, references: dict[str, list[dict[str, str]]]) -> None:
    """Collect known ID-shaped references, including shop map keys."""

    def visit(node: Any, path: str = "", parent_key: str | None = None) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                child_path = f"{path}.{key}" if path else str(key)
                ref_type = _ref_type_for_key(key)
                if ref_type and isinstance(child, str):
                    references.setdefault(ref_type, []).append({"source": source, "path": child_path, "id": child})
                elif key in {"pathIds", "shopIds", "shops", "expeditionIds", "availableExpeditions", "recipeIds"} and isinstance(child, list):
                    ref_type = "paths" if key == "pathIds" else "shops" if key in {"shopIds", "shops"} else "expeditions" if key in {"expeditionIds", "availableExpeditions"} else "recipes"
                    for index, item in enumerate(child):
                        if isinstance(item, str):
                            references.setdefault(ref_type, []).append({"source": source, "path": f"{child_path}[{index}]", "id": item})
                elif key in {"itemIds", "injuryIds", "prerequisites", "enemyIds", "abilityIds", "grantedAbilityIds", "combatAbilities", "actionPattern", "campEventTableIds"} and isinstance(child, list):
                    ref_type = {
                        "itemIds": "items",
                        "injuryIds": "injuries",
                        "prerequisites": "items",
                        "enemyIds": "enemies",
                        "abilityIds": "abilities",
                        "grantedAbilityIds": "abilities",
                        "combatAbilities": "abilities",
                        "actionPattern": "enemyActions",
                        "campEventTableIds": "campEventTables",
                    }[key]
                    for index, item in enumerate(child):
                        if isinstance(item, str):
                            references.setdefault(ref_type, []).append({"source": source, "path": f"{child_path}[{index}]", "id": item})
                if key in {"itemsForSale", "sellValues"} and isinstance(child, dict):
                    for item_id in child:
                        references.setdefault("items", []).append({"source": source, "path": f"{child_path}.{item_id}", "id": item_id})
                if key == "ingredients" and isinstance(child, dict):
                    ingredient_type = node.get("ingredientType", "material")
                    ref_type = "items" if ingredient_type == "item" else "materials"
                    for ingredient_id in child:
                        references.setdefault(ref_type, []).append({"source": source, "path": f"{child_path}.{ingredient_id}", "id": ingredient_id})
                visit(child, child_path, key)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, f"{path}[{index}]", parent_key)

    visit(value)


def _id_map(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _humanize_id(value: str) -> str:
    return " ".join(part.capitalize() for part in value.replace("_", " ").split())


def build_path_index(encounters: Any, expeditions: Any) -> dict[str, dict[str, Any]]:
    """Build the editor's derived path view from live authored relationships.

    Grail has no standalone PATH_DEFINITIONS constant.  Path IDs are authored
    on encounter membership arrays and expedition pathId fields, so this index
    deliberately remains read-only metadata rather than becoming a second
    source of truth.
    """
    index: dict[str, dict[str, Any]] = {}
    for entry_id, encounter in _id_map(encounters).items():
        if not isinstance(encounter, dict):
            continue
        for path_id in encounter.get("pathIds", []):
            if not isinstance(path_id, str):
                continue
            index.setdefault(path_id, {
                "id": path_id,
                "name": _humanize_id(path_id),
                "derived": True,
                "encounterCount": 0,
                "expeditionIds": [],
            })["encounterCount"] += 1
    for expedition_id, expedition in _id_map(expeditions).items():
        if not isinstance(expedition, dict):
            continue
        path_id = expedition.get("pathId")
        if not isinstance(path_id, str):
            continue
        path = index.setdefault(path_id, {
            "id": path_id,
            "name": _humanize_id(path_id),
            "derived": True,
            "encounterCount": 0,
            "expeditionIds": [],
        })
        if expedition_id not in path["expeditionIds"]:
            path["expeditionIds"].append(expedition_id)
        # The linked expedition is the only live authored display/metadata
        # source for a path, when one exists.
        if isinstance(expedition.get("name"), str) and expedition["name"]:
            path["name"] = expedition["name"]
        for field_name in ("description", "regionId", "kind", "danger"):
            if field_name in expedition:
                path[field_name] = expedition[field_name]
    for path in index.values():
        path["expeditionIds"] = sorted(path["expeditionIds"])
        if len(path["expeditionIds"]) == 1:
            path["expeditionId"] = path["expeditionIds"][0]
    return dict(sorted(index.items()))


def load_catalog(project_root: Path) -> dict[str, Any]:
    project_root = project_root.resolve()
    values: dict[str, Any] = {}
    source_hashes: dict[str, str] = {}
    source_paths: dict[str, str] = {}
    parse_duplicates: list[dict[str, str]] = []

    for category, (relative, name) in CONTENT_FILES.items():
        value, _source, raw, parsed = _read_constant(project_root, relative, name)
        values[category] = value
        source_hashes[relative] = _source_hash(raw)
        source_paths[category] = relative
        for duplicate in parsed.duplicate_keys:
            parse_duplicates.append({"source": relative, "id": duplicate})

    refs: dict[str, list[dict[str, str]]] = {}
    reference_values: dict[str, Any] = {}
    for category, value in values.items():
        collect_references(value, category, refs)

    known: dict[str, list[str]] = {}
    for category, (relative, name) in REFERENCE_FILES.items():
        try:
            value, _source, raw, parsed = _read_constant(project_root, relative, name)
            reference_values[category] = value
            source_hashes.setdefault(relative, _source_hash(raw))
            known[category] = sorted(_id_map(value))
            if category not in CONTENT_FILES:
                collect_references(value, category, refs)
            if category == "expeditions":
                for expedition in _id_map(value).values():
                    if isinstance(expedition, dict):
                        path_id = expedition.get("pathId")
                        region_id = expedition.get("regionId")
                        if isinstance(path_id, str):
                            known.setdefault("paths", []).append(path_id)
                        if isinstance(region_id, str):
                            known.setdefault("regions", []).append(region_id)
            for duplicate in parsed.duplicate_keys:
                parse_duplicates.append({"source": relative, "id": duplicate})
        except (FileNotFoundError, JsParseError):
            known[category] = []

    encounter_regions = [entry.get("regionId") for entry in values["encounters"].values() if isinstance(entry, dict)]
    encounter_paths = [path for entry in values["encounters"].values() if isinstance(entry, dict) for path in entry.get("pathIds", [])]
    known["paths"] = sorted(set(known.get("paths", []) + [path for path in encounter_paths if isinstance(path, str)]))
    known["regions"] = sorted(set(known.get("regions", []) + [region for region in encounter_regions if isinstance(region, str)]))

    item_map = _id_map(values.get("items"))
    known["combats"] = sorted(_id_map(values.get("combats")))
    known["abilities"] = sorted(_id_map(values.get("abilities")))
    known["injuries"] = sorted(_id_map(values.get("injuries")))
    known["campEvents"] = sorted(_id_map(values.get("campEvents")))
    known["enemies"] = sorted(_id_map(values.get("enemyDefinitions")))
    known["enemyActions"] = sorted(_id_map(values.get("enemyActions")))
    known["lootTables"] = sorted(_id_map(values.get("lootTables")))
    known["items"] = sorted(item_map)
    known["shops"] = sorted(_id_map(values.get("shops")))
    known["expeditions"] = sorted(_id_map(values.get("expeditions")))
    known["recipes"] = sorted(_id_map(values.get("recipes")))
    known["craftingProviders"] = sorted(_id_map(values.get("craftingProviders")))
    known["itemCategories"] = sorted({
        *(item.get("category") for item in item_map.values() if isinstance(item, dict) and isinstance(item.get("category"), str)),
        "other",
    })
    known["rarities"] = sorted({
        *(item.get("rarity") for item in item_map.values() if isinstance(item, dict) and isinstance(item.get("rarity"), str)),
        *known.get("rarities", []),
        "common", "uncommon", "rare",
    })
    known["equipmentSlots"] = sorted({
        *(item.get("equipmentSlot") for item in item_map.values() if isinstance(item, dict) and isinstance(item.get("equipmentSlot"), str)),
        "armor", "relic", "weapon",
    })

    validation = validate_catalog(values, known, refs, parse_duplicates)
    item_labels = {key: item.get("name", key) for key, item in item_map.items() if isinstance(item, dict)}
    material_map = {}
    try:
        material_map, *_ = _read_constant(project_root, *REFERENCE_FILES["materials"])
    except (FileNotFoundError, JsParseError):
        pass
    material_labels = {key: value.get("name", key) for key, value in _id_map(material_map).items() if isinstance(value, dict)}
    ability_map = {}
    try:
        ability_map, *_ = _read_constant(project_root, *REFERENCE_FILES["abilities"])
    except (FileNotFoundError, JsParseError):
        pass
    ability_labels = {key: value.get("name", key) for key, value in _id_map(ability_map).items() if isinstance(value, dict)}
    injury_map = _id_map(values.get("injuries"))
    injury_labels = {key: value.get("name", key) for key, value in injury_map.items() if isinstance(value, dict)}
    camp_event_map = _id_map(values.get("campEvents"))
    camp_event_labels = {key: value.get("title", key) for key, value in camp_event_map.items() if isinstance(value, dict)}

    return {
        "projectRoot": str(project_root),
        "files": source_paths,
        "sourceHashes": source_hashes,
        "encounters": values["encounters"],
        "injuries": values["injuries"],
        "campEvents": values["campEvents"],
        "expeditions": values["expeditions"],
        "recipes": values["recipes"],
        "materials": values["materials"],
        "craftingProviders": values["craftingProviders"],
        "shops": values["shops"],
        "items": values["items"],
        "combats": values["combats"],
        "abilities": values["abilities"],
        "enemyDefinitions": values["enemyDefinitions"],
        "enemyActions": values["enemyActions"],
        "lootTables": values["lootTables"],
        "known": {key: sorted(set(items)) for key, items in known.items()},
        "campEventTables": reference_values.get("campEventTables", {}),
        "paths": build_path_index(values["encounters"], values["expeditions"]),
        "itemLabels": item_labels,
        "materialLabels": material_labels,
        "abilityLabels": ability_labels,
        "injuryLabels": injury_labels,
        "campEventLabels": camp_event_labels,
        "references": refs,
        "validation": validation,
    }


def _issue(severity: str, message: str, source: str, path: str | None = None) -> dict[str, str]:
    result = {"severity": severity, "message": message, "source": source}
    if path:
        result["path"] = path
    return result


def _validate_chance(value: Any, source: str, path: str, errors: list[dict[str, str]]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in {"chance", "injuryChance"}:
                if not isinstance(child, (int, float)) or isinstance(child, bool) or not 0 <= child <= 1:
                    errors.append(_issue("error", f"Chance must be between 0 and 1; got {child!r}.", source, child_path))
            _validate_chance(child, source, child_path, errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_chance(child, source, f"{path}[{index}]", errors)


def _validate_reference(value: Any, known: dict[str, list[str]], source: str, errors: list[dict[str, str]]) -> None:
    references: dict[str, list[dict[str, str]]] = {}
    collect_references(value, source, references)
    for ref_type, entries in references.items():
        valid = set(known.get(ref_type, []))
        for entry in entries:
            if entry["id"] not in valid:
                errors.append(_issue("error", f"Unknown {ref_type[:-1] if ref_type.endswith('s') else ref_type} ID {entry['id']!r}.", source, entry["path"]))


def _validate_requirements(requirements: Any, source: str, path: str, errors: list[dict[str, str]]) -> None:
    if requirements is None:
        return
    if not isinstance(requirements, list):
        errors.append(_issue("error", "Requirements must be an array.", source, path))
        return
    for index, requirement in enumerate(requirements):
        if not isinstance(requirement, dict) or not isinstance(requirement.get("type"), str):
            errors.append(_issue("error", "Each requirement must be an object with a type.", source, f"{path}[{index}]"))
            continue
        requirement_path = f"{path}[{index}]"
        nested = requirement.get("requirements")
        if nested is not None:
            _validate_requirements(nested, source, f"{requirement_path}.requirements", errors)


def _validate_positive_integer(value: Any, label: str, source: str, path: str, errors: list[dict[str, str]]) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        errors.append(_issue("error", f"{label} must be a positive integer.", source, path))


def _validate_resolution_outcomes(outcomes: Any, known: dict[str, list[str]], source: str, path: str, errors: list[dict[str, str]]) -> None:
    if not isinstance(outcomes, list):
        errors.append(_issue("error", "Combat resolution outcomes must be an array.", source, path))
        return
    for index, outcome in enumerate(outcomes):
        _validate_resolution_outcome(outcome, known, source, f"{path}[{index}]", errors)


def _validate_resolution_outcome(outcome: Any, known: dict[str, list[str]], source: str, path: str, errors: list[dict[str, str]]) -> None:
    if not isinstance(outcome, dict) or not isinstance(outcome.get("type"), str) or not outcome.get("type"):
        errors.append(_issue("error", "Each outcome must be an object with a type.", source, path))
        return
    outcome_type = outcome["type"]

    if "requirements" in outcome:
        _validate_requirements(outcome.get("requirements"), source, f"{path}.requirements", errors)

    if outcome_type == "startCombat":
        combat_id = outcome.get("combatId")
        if not isinstance(combat_id, str) or not combat_id:
            errors.append(_issue("error", "startCombat requires a combatId.", source, f"{path}.combatId"))
        for branch_name in ("victory", "fled"):
            if branch_name not in outcome:
                continue
            branch = outcome.get(branch_name)
            branch_path = f"{path}.{branch_name}"
            if not isinstance(branch, dict):
                errors.append(_issue("error", f"startCombat {branch_name} branch must be an object.", source, branch_path))
                continue
            if "resultText" in branch and not isinstance(branch.get("resultText"), str):
                errors.append(_issue("error", f"startCombat {branch_name} resultText must be a string.", source, f"{branch_path}.resultText"))
            if "outcomes" in branch:
                _validate_resolution_outcomes(branch.get("outcomes"), known, source, f"{branch_path}.outcomes", errors)
        return

    if outcome_type == "rollLootTable":
        if not isinstance(outcome.get("tableId"), str) or not outcome.get("tableId"):
            errors.append(_issue("error", "rollLootTable requires a tableId.", source, f"{path}.tableId"))
        if "rolls" in outcome:
            _validate_positive_integer(outcome.get("rolls"), "Loot table rolls", source, f"{path}.rolls", errors)
    elif outcome_type in {"gainUnsecuredItem", "gainUniqueUnsecuredItem", "gainRandomUnsecuredItem", "consumeExpeditionItem"}:
        if outcome_type == "gainRandomUnsecuredItem":
            item_ids = outcome.get("itemIds")
            if not isinstance(item_ids, list) or not item_ids or not all(isinstance(item_id, str) and item_id for item_id in item_ids):
                errors.append(_issue("error", "Random item rewards require a non-empty itemIds array.", source, f"{path}.itemIds"))
        elif not isinstance(outcome.get("itemId"), str) or not outcome.get("itemId"):
            errors.append(_issue("error", f"{outcome_type} requires an itemId.", source, f"{path}.itemId"))
        if "quantity" in outcome:
            _validate_positive_integer(outcome.get("quantity"), "Item quantity", source, f"{path}.quantity", errors)
    elif outcome_type == "gainWeightedRandomUnsecuredItem":
        items = outcome.get("items")
        if not isinstance(items, list) or not items:
            errors.append(_issue("error", "Weighted item rewards require a non-empty items array.", source, f"{path}.items"))
        else:
            for index, item in enumerate(items):
                item_path = f"{path}.items[{index}]"
                if not isinstance(item, dict) or not isinstance(item.get("itemId"), str) or not item.get("itemId"):
                    errors.append(_issue("error", "Weighted item entries require an itemId.", source, item_path))
                elif not _is_number(item.get("weight")) or item.get("weight") <= 0:
                    errors.append(_issue("error", "Weighted item entries require a positive weight.", source, f"{item_path}.weight"))
        if "quantity" in outcome:
            _validate_positive_integer(outcome.get("quantity"), "Item quantity", source, f"{path}.quantity", errors)
    elif outcome_type == "randomChance":
        chance = outcome.get("chance")
        if not _is_number(chance) or not 0 <= chance <= 1:
            errors.append(_issue("error", "Chance must be between 0 and 1.", source, f"{path}.chance"))
    elif outcome_type == "randomOne":
        options = outcome.get("options")
        if not isinstance(options, list) or not options:
            errors.append(_issue("error", "randomOne requires a non-empty options array.", source, f"{path}.options"))
        else:
            for index, option in enumerate(options):
                option_path = f"{path}.options[{index}]"
                if not isinstance(option, dict):
                    errors.append(_issue("error", "randomOne options must be objects.", source, option_path))
                    continue
                if "resultText" in option and not isinstance(option.get("resultText"), str):
                    errors.append(_issue("error", "randomOne option resultText must be a string.", source, f"{option_path}.resultText"))
                if "effects" in option:
                    _validate_resolution_outcomes(option.get("effects"), known, source, f"{option_path}.effects", errors)
                if "elseEffects" in option:
                    _validate_resolution_outcomes(option.get("elseEffects"), known, source, f"{option_path}.elseEffects", errors)
                if "requirements" in option:
                    _validate_requirements(option.get("requirements"), source, f"{option_path}.requirements", errors)

    for collection_name in ("effects", "elseEffects"):
        if collection_name in outcome:
            _validate_resolution_outcomes(outcome.get(collection_name), known, source, f"{path}.{collection_name}", errors)
    if "secondaryOutcome" in outcome:
        secondary = outcome.get("secondaryOutcome")
        secondary_path = f"{path}.secondaryOutcome"
        if not isinstance(secondary, dict):
            errors.append(_issue("error", "secondaryOutcome must be an object.", source, secondary_path))
        else:
            secondary_chance = secondary.get("chance")
            if not _is_number(secondary_chance) or not 0 <= secondary_chance <= 1:
                errors.append(_issue("error", "Chance must be between 0 and 1.", source, f"{secondary_path}.chance"))
            if "effects" in secondary:
                _validate_resolution_outcomes(secondary.get("effects"), known, source, f"{secondary_path}.effects", errors)


def _validate_encounters(encounters: Any, known: dict[str, list[str]], errors: list[dict[str, str]]) -> None:
    if not isinstance(encounters, dict):
        errors.append(_issue("error", "Encounter definitions must be an object.", "encounters"))
        return
    seen_ids: set[str] = set()
    for entry_id, encounter in encounters.items():
        source = f"encounter:{entry_id}"
        if not isinstance(encounter, dict):
            errors.append(_issue("error", "Encounter must be an object.", source))
            continue
        if encounter.get("id") != entry_id:
            errors.append(_issue("error", f"Definition key {entry_id!r} does not match its id field.", source, "id"))
        elif entry_id in seen_ids:
            errors.append(_issue("error", f"Duplicate encounter ID {entry_id!r}.", source, "id"))
        else:
            seen_ids.add(entry_id)
        for field_name in ("title", "description", "regionId", "pathIds", "directions", "stages"):
            if field_name not in encounter:
                errors.append(_issue("error", f"Missing required encounter field {field_name!r}.", source, field_name))
        if not isinstance(encounter.get("pathIds"), list) or not all(isinstance(item, str) for item in encounter.get("pathIds", [])):
            errors.append(_issue("error", "pathIds must be an array of path IDs.", source, "pathIds"))
        if not isinstance(encounter.get("directions"), list) or not all(isinstance(item, str) for item in encounter.get("directions", [])):
            errors.append(_issue("error", "directions must be an array of strings.", source, "directions"))
        minimum = encounter.get("minimumDistance")
        maximum = encounter.get("maximumDistance")
        if minimum is not None and not isinstance(minimum, (int, float)):
            errors.append(_issue("error", "minimumDistance must be numeric.", source, "minimumDistance"))
        if maximum is not None and not isinstance(maximum, (int, float)):
            errors.append(_issue("error", "maximumDistance must be numeric.", source, "maximumDistance"))
        if isinstance(minimum, (int, float)) and isinstance(maximum, (int, float)) and minimum > maximum:
            errors.append(_issue("error", "minimumDistance cannot be greater than maximumDistance.", source, "maximumDistance"))
        stages = encounter.get("stages")
        if not isinstance(stages, dict) or not stages:
            errors.append(_issue("error", "An encounter must have at least one stage.", source, "stages"))
        elif isinstance(stages, dict):
            for stage_id, stage in stages.items():
                stage_path = f"stages.{stage_id}"
                if not isinstance(stage, dict):
                    errors.append(_issue("error", "Stage must be an object.", source, stage_path))
                    continue
                if not isinstance(stage.get("text"), str):
                    errors.append(_issue("error", "Stage text is required.", source, f"{stage_path}.text"))
                choices = stage.get("choices")
                if stage.get("resultStage") is True and "choices" not in stage:
                    choices = []
                if not isinstance(choices, list):
                    errors.append(_issue("error", "Stage choices must be an array unless this is a resultStage.", source, f"{stage_path}.choices"))
                else:
                    choice_ids: set[str] = set()
                    for index, choice in enumerate(choices):
                        choice_path = f"{stage_path}.choices[{index}]"
                        if not isinstance(choice, dict):
                            errors.append(_issue("error", "Choice must be an object.", source, choice_path))
                            continue
                        choice_id = choice.get("id")
                        if not isinstance(choice_id, str) or not choice_id:
                            errors.append(_issue("error", "Choice ID is required.", source, f"{choice_path}.id"))
                        elif choice_id in choice_ids:
                            errors.append(_issue("error", f"Duplicate choice ID {choice_id!r} in stage.", source, f"{choice_path}.id"))
                        else:
                            choice_ids.add(choice_id)
                        if "label" in choice and not isinstance(choice.get("label"), str):
                            errors.append(_issue("error", "Choice label must be a string when present.", source, f"{choice_path}.label"))
                        _validate_requirements(choice.get("requirements"), source, f"{choice_path}.requirements", errors)
                        for collection_name in ("costs", "outcomes"):
                            collection = choice.get(collection_name)
                            if collection is not None and not isinstance(collection, list):
                                errors.append(_issue("error", f"{collection_name} must be an array.", source, f"{choice_path}.{collection_name}"))
                            elif collection_name == "outcomes" and collection is not None:
                                _validate_resolution_outcomes(collection, known, source, f"{choice_path}.outcomes", errors)
                        _validate_chance(choice, source, choice_path, errors)
                if "outcomes" in stage:
                    _validate_resolution_outcomes(stage.get("outcomes"), known, source, f"{stage_path}.outcomes", errors)


def _validate_injuries(injuries: Any, known: dict[str, list[str]], errors: list[dict[str, str]]) -> None:
    if not isinstance(injuries, dict):
        errors.append(_issue("error", "Injury definitions must be an object.", "injuries"))
        return
    seen_ids: set[str] = set()
    for entry_id, injury in injuries.items():
        source = f"injury:{entry_id}"
        if not isinstance(injury, dict):
            errors.append(_issue("error", "Injury must be an object.", source))
            continue
        injury_id = injury.get("id")
        if not isinstance(injury_id, str) or not injury_id:
            errors.append(_issue("error", "Injury id is required.", source, "id"))
        elif injury_id != entry_id:
            errors.append(_issue("error", f"Definition key {entry_id!r} does not match its id field.", source, "id"))
        elif injury_id in seen_ids:
            errors.append(_issue("error", f"Duplicate injury ID {injury_id!r}.", source, "id"))
        else:
            seen_ids.add(injury_id)
        for field_name in ("name", "shortName", "description"):
            if not isinstance(injury.get(field_name), str) or not injury.get(field_name):
                errors.append(_issue("error", f"Injury {field_name} is required.", source, field_name))
        if "effects" in injury and not isinstance(injury.get("effects"), dict):
            errors.append(_issue("error", "Injury effects must be an object.", source, "effects"))
        recovery = injury.get("recoveryDistanceRange")
        if recovery is not None:
            if not isinstance(recovery, dict):
                errors.append(_issue("error", "recoveryDistanceRange must be an object.", source, "recoveryDistanceRange"))
            else:
                minimum = recovery.get("minimum")
                maximum = recovery.get("maximum")
                if minimum is not None and (not _is_number(minimum) or minimum < 0):
                    errors.append(_issue("error", "Recovery minimum must be a non-negative number.", source, "recoveryDistanceRange.minimum"))
                if maximum is not None and (not _is_number(maximum) or maximum < 0):
                    errors.append(_issue("error", "Recovery maximum must be a non-negative number.", source, "recoveryDistanceRange.maximum"))
                if _is_number(minimum) and _is_number(maximum) and minimum > maximum:
                    errors.append(_issue("error", "Recovery minimum cannot exceed maximum.", source, "recoveryDistanceRange.maximum"))
        for field_name in ("infectionCheckDistance", "travelDamageAmount", "travelDamageInterval"):
            if field_name in injury and (not _is_number(injury.get(field_name)) or injury[field_name] < 0):
                errors.append(_issue("error", f"{field_name} must be a non-negative number.", source, field_name))
        if "infectionChance" in injury and (not _is_number(injury.get("infectionChance")) or not 0 <= injury["infectionChance"] <= 1):
            errors.append(_issue("error", "infectionChance must be between 0 and 1.", source, "infectionChance"))
        if "treatmentItemId" in injury and injury.get("treatmentItemId") is not None and injury.get("treatmentItemId") not in set(known.get("items", [])):
            errors.append(_issue("error", f"Unknown treatment item ID {injury.get('treatmentItemId')!r}.", source, "treatmentItemId"))


def _validate_staged_events(events: Any, known: dict[str, list[str]], errors: list[dict[str, str]], source_prefix: str, label: str) -> None:
    if not isinstance(events, dict):
        errors.append(_issue("error", f"{label} definitions must be an object.", label))
        return
    seen_ids: set[str] = set()
    for entry_id, event in events.items():
        source = f"{label[:-1] if label.endswith('s') else label}:{entry_id}"
        if not isinstance(event, dict):
            errors.append(_issue("error", f"{label[:-1].capitalize()} must be an object.", source))
            continue
        if event.get("id") != entry_id:
            errors.append(_issue("error", f"Definition key {entry_id!r} does not match its id field.", source, "id"))
        elif entry_id in seen_ids:
            errors.append(_issue("error", f"Duplicate {label[:-1]} ID {entry_id!r}.", source, "id"))
        else:
            seen_ids.add(entry_id)
        for field_name in ("title", "description", "regionId", "requirements", "stages"):
            if field_name not in event:
                errors.append(_issue("error", f"Missing required {label[:-1]} field {field_name!r}.", source, field_name))
        if "pathIds" in event and (not isinstance(event.get("pathIds"), list) or not all(isinstance(item, str) for item in event.get("pathIds", []))):
            errors.append(_issue("error", "pathIds must be an array of path IDs.", source, "pathIds"))
        for field_name in ("weight", "minimumDistance", "maximumDistance"):
            if field_name in event and event.get(field_name) is not None and not _is_number(event.get(field_name)):
                errors.append(_issue("error", f"{field_name} must be numeric.", source, field_name))
        minimum = event.get("minimumDistance")
        maximum = event.get("maximumDistance")
        if _is_number(minimum) and _is_number(maximum) and minimum > maximum:
            errors.append(_issue("error", "minimumDistance cannot be greater than maximumDistance.", source, "maximumDistance"))
        _validate_requirements(event.get("requirements"), source, "requirements", errors)
        stages = event.get("stages")
        if not isinstance(stages, dict) or not stages:
            errors.append(_issue("error", f"A {label[:-1]} must have at least one stage.", source, "stages"))
            continue
        for stage_id, stage in stages.items():
            stage_path = f"stages.{stage_id}"
            if not isinstance(stage, dict):
                errors.append(_issue("error", "Stage must be an object.", source, stage_path))
                continue
            if not isinstance(stage.get("text"), str):
                errors.append(_issue("error", "Stage text is required.", source, f"{stage_path}.text"))
            choices = stage.get("choices", [] if stage.get("resultStage") is True else None)
            if not isinstance(choices, list):
                errors.append(_issue("error", "Stage choices must be an array unless this is a resultStage.", source, f"{stage_path}.choices"))
                choices = []
            for index, choice in enumerate(choices):
                choice_path = f"{stage_path}.choices[{index}]"
                if not isinstance(choice, dict):
                    errors.append(_issue("error", "Choice must be an object.", source, choice_path))
                    continue
                if not isinstance(choice.get("id"), str) or not choice.get("id"):
                    errors.append(_issue("error", "Choice ID is required.", source, f"{choice_path}.id"))
                _validate_requirements(choice.get("requirements"), source, f"{choice_path}.requirements", errors)
                if "outcomes" in choice:
                    _validate_resolution_outcomes(choice.get("outcomes"), known, source, f"{choice_path}.outcomes", errors)
                if "costs" in choice and not isinstance(choice.get("costs"), list):
                    errors.append(_issue("error", "costs must be an array.", source, f"{choice_path}.costs"))
                _validate_chance(choice, source, choice_path, errors)
            if "outcomes" in stage:
                _validate_resolution_outcomes(stage.get("outcomes"), known, source, f"{stage_path}.outcomes", errors)


def _validate_camp_events(events: Any, known: dict[str, list[str]], errors: list[dict[str, str]]) -> None:
    _validate_staged_events(events, known, errors, "campEvents", "campEvents")


def _validate_shops(shops: Any, known: dict[str, list[str]], errors: list[dict[str, str]]) -> None:
    if not isinstance(shops, dict):
        errors.append(_issue("error", "Shop definitions must be an object.", "shops"))
        return
    seen_ids: set[str] = set()
    for entry_id, shop in shops.items():
        source = f"shop:{entry_id}"
        if not isinstance(shop, dict):
            errors.append(_issue("error", "Shop must be an object.", source))
            continue
        if shop.get("id") != entry_id:
            errors.append(_issue("error", f"Definition key {entry_id!r} does not match its id field.", source, "id"))
        elif entry_id in seen_ids:
            errors.append(_issue("error", f"Duplicate shop ID {entry_id!r}.", source, "id"))
        else:
            seen_ids.add(entry_id)
        if not isinstance(shop.get("displayName"), str) or not shop.get("displayName"):
            errors.append(_issue("error", "Shop displayName is required.", source, "displayName"))
        stock = shop.get("itemsForSale")
        if not isinstance(stock, dict):
            errors.append(_issue("error", "itemsForSale must be an object.", source, "itemsForSale"))
        else:
            for item_id, listing in stock.items():
                if item_id not in set(known.get("items", [])):
                    errors.append(_issue("error", f"Shop points to unknown item ID {item_id!r}.", source, f"itemsForSale.{item_id}"))
                if not isinstance(listing, dict) or not isinstance(listing.get("price"), (int, float)) or listing.get("price") < 0:
                    errors.append(_issue("error", "Each shop item needs a non-negative numeric price.", source, f"itemsForSale.{item_id}.price"))
                elif "stock" in listing and (not isinstance(listing["stock"], (int, float)) or isinstance(listing["stock"], bool) or listing["stock"] < 0):
                    errors.append(_issue("error", "Stock must be a non-negative number; omit it for unlimited stock.", source, f"itemsForSale.{item_id}.stock"))
        sell_values = shop.get("sellValues", {})
        if not isinstance(sell_values, dict):
            errors.append(_issue("error", "sellValues must be an object.", source, "sellValues"))
        else:
            for item_id, value in sell_values.items():
                if item_id not in set(known.get("items", [])):
                    errors.append(_issue("error", f"Shop sellValues points to unknown item ID {item_id!r}.", source, f"sellValues.{item_id}"))
                if not isinstance(value, (int, float)) or value < 0:
                    errors.append(_issue("error", "Sell values must be non-negative numbers.", source, f"sellValues.{item_id}"))
        for list_field in ("acceptedCategories", "acceptedTags"):
            if list_field in shop and (not isinstance(shop[list_field], list) or not all(isinstance(item, str) for item in shop[list_field])):
                errors.append(_issue("error", f"{list_field} must be an array of strings.", source, list_field))


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_items(items: Any, known: dict[str, list[str]], errors: list[dict[str, str]]) -> None:
    if not isinstance(items, dict):
        errors.append(_issue("error", "Item definitions must be an object.", "items"))
        return
    seen_ids: set[str] = set()
    boolean_fields = (
        "equippable", "carriable", "consumable", "questItem", "campaignItem",
        "unique", "sellable", "protected",
    )
    for entry_id, item in items.items():
        source = f"item:{entry_id}"
        if not isinstance(item, dict):
            errors.append(_issue("error", "Item must be an object.", source))
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            errors.append(_issue("error", "Item id is required.", source, "id"))
        elif item_id != entry_id:
            errors.append(_issue("error", f"Definition key {entry_id!r} does not match its id field.", source, "id"))
        elif item_id in seen_ids:
            errors.append(_issue("error", f"Duplicate item ID {item_id!r}.", source, "id"))
        else:
            seen_ids.add(item_id)
        for field_name in ("name", "category"):
            if not isinstance(item.get(field_name), str) or not item.get(field_name):
                errors.append(_issue("error", f"Item {field_name} is required.", source, field_name))
        category = item.get("category")
        if isinstance(category, str) and category not in set(known.get("itemCategories", [])):
            errors.append(_issue("error", f"Unknown item category {category!r}.", source, "category"))
        if "description" in item and not isinstance(item.get("description"), str):
            errors.append(_issue("error", "Item description must be a string.", source, "description"))
        if "tags" in item and (not isinstance(item.get("tags"), list) or not all(isinstance(tag, str) for tag in item.get("tags", []))):
            errors.append(_issue("error", "Item tags must be an array of strings.", source, "tags"))
        if "rarity" in item and item.get("rarity") is not None and item.get("rarity") not in set(known.get("rarities", [])):
            errors.append(_issue("error", f"Unknown item rarity {item.get('rarity')!r}.", source, "rarity"))
        for field_name in boolean_fields:
            if field_name in item and not isinstance(item.get(field_name), bool):
                errors.append(_issue("error", f"{field_name} must be boolean.", source, field_name))
        equippable = item.get("equippable") is True
        slot = item.get("equipmentSlot")
        if slot is not None and slot not in set(known.get("equipmentSlots", [])):
            errors.append(_issue("error", f"Unknown equipment slot {slot!r}.", source, "equipmentSlot"))
        if equippable and not isinstance(slot, str):
            errors.append(_issue("error", "Equippable items need an equipmentSlot.", source, "equipmentSlot"))
        if "maxStack" in item:
            max_stack = item.get("maxStack")
            if not isinstance(max_stack, int) or isinstance(max_stack, bool) or max_stack <= 0:
                errors.append(_issue("error", "maxStack must be a positive integer.", source, "maxStack"))

        effects = item.get("effects")
        if not isinstance(effects, dict):
            errors.append(_issue("error", "Item effects must be an object.", source, "effects"))
            continue
        damage = effects.get("combatDamage")
        if damage is not None:
            if not isinstance(damage, dict):
                errors.append(_issue("error", "combatDamage must be an object.", source, "effects.combatDamage"))
            else:
                minimum = damage.get("minimum")
                maximum = damage.get("maximum")
                if not _is_number(minimum) or not _is_number(maximum):
                    errors.append(_issue("error", "combatDamage minimum and maximum must be numeric.", source, "effects.combatDamage"))
                elif minimum < 0 or maximum < 0 or minimum > maximum:
                    errors.append(_issue("error", "combatDamage must use non-negative minimum/maximum values with minimum <= maximum.", source, "effects.combatDamage"))
        defense = effects.get("combatDefense")
        if defense is not None and (not _is_number(defense) or defense < 0):
            errors.append(_issue("error", "combatDefense must be a non-negative number.", source, "effects.combatDefense"))
        granted = effects.get("grantedAbilityIds")
        if granted is not None:
            if not isinstance(granted, list) or not all(isinstance(ability_id, str) for ability_id in granted):
                errors.append(_issue("error", "grantedAbilityIds must be an array of ability IDs.", source, "effects.grantedAbilityIds"))
            else:
                if len(granted) != len(set(granted)):
                    errors.append(_issue("error", "grantedAbilityIds cannot contain duplicates.", source, "effects.grantedAbilityIds"))
                for index, ability_id in enumerate(granted):
                    if ability_id not in set(known.get("abilities", [])):
                        errors.append(_issue("error", f"Unknown combat ability ID {ability_id!r}.", source, f"effects.grantedAbilityIds[{index}]"))
        combat = effects.get("combat")
        if combat is not None:
            if not isinstance(combat, dict):
                errors.append(_issue("error", "combat effects must be an object.", source, "effects.combat"))
            else:
                if "usable" in combat and not isinstance(combat.get("usable"), bool):
                    errors.append(_issue("error", "combat.usable must be boolean.", source, "effects.combat.usable"))
                if "effectType" in combat and not isinstance(combat.get("effectType"), str):
                    errors.append(_issue("error", "combat.effectType must be a string.", source, "effects.combat.effectType"))
                if "amount" in combat and (not _is_number(combat.get("amount")) or combat.get("amount") < 0):
                    errors.append(_issue("error", "combat.amount must be a non-negative number.", source, "effects.combat.amount"))
                for field_name in ("target", "selectionPrompt", "description"):
                    if field_name in combat and not isinstance(combat.get(field_name), str):
                        errors.append(_issue("error", f"combat.{field_name} must be a string.", source, f"effects.combat.{field_name}"))
        treatment = effects.get("treatment")
        if treatment is not None:
            if not isinstance(treatment, dict):
                errors.append(_issue("error", "treatment effects must be an object.", source, "effects.treatment"))
            else:
                injury_ids = treatment.get("injuryIds")
                if not isinstance(injury_ids, list) or not all(isinstance(injury_id, str) for injury_id in injury_ids):
                    errors.append(_issue("error", "treatment.injuryIds must be an array of injury IDs.", source, "effects.treatment.injuryIds"))
                else:
                    if len(injury_ids) != len(set(injury_ids)):
                        errors.append(_issue("error", "treatment.injuryIds cannot contain duplicates.", source, "effects.treatment.injuryIds"))
                    for index, injury_id in enumerate(injury_ids):
                        if injury_id not in set(known.get("injuries", [])):
                            errors.append(_issue("error", f"Unknown injury ID {injury_id!r}.", source, f"effects.treatment.injuryIds[{index}]"))


def _validate_combat_definitions(combats: Any, known: dict[str, list[str]], errors: list[dict[str, str]]) -> None:
    if not isinstance(combats, dict):
        errors.append(_issue("error", "Combat definitions must be an object.", "combats"))
        return
    seen_ids: set[str] = set()
    for entry_id, combat in combats.items():
        source = f"combat:{entry_id}"
        if not isinstance(combat, dict):
            errors.append(_issue("error", "Combat must be an object.", source))
            continue
        combat_id = combat.get("id")
        if not isinstance(combat_id, str) or not combat_id:
            errors.append(_issue("error", "Combat id is required.", source, "id"))
        elif combat_id != entry_id:
            errors.append(_issue("error", f"Definition key {entry_id!r} does not match its id field.", source, "id"))
        elif combat_id in seen_ids:
            errors.append(_issue("error", f"Duplicate combat ID {combat_id!r}.", source, "id"))
        else:
            seen_ids.add(combat_id)
        enemy_ids = combat.get("enemyIds")
        if not isinstance(enemy_ids, list) or not enemy_ids or not all(isinstance(enemy_id, str) and enemy_id for enemy_id in enemy_ids):
            errors.append(_issue("error", "enemyIds must be a non-empty array of enemy IDs.", source, "enemyIds"))


def _validate_enemy_definitions(enemies: Any, known: dict[str, list[str]], errors: list[dict[str, str]]) -> None:
    if not isinstance(enemies, dict):
        errors.append(_issue("error", "Enemy definitions must be an object.", "enemyDefinitions"))
        return
    seen_ids: set[str] = set()
    for entry_id, enemy in enemies.items():
        source = f"enemy:{entry_id}"
        if not isinstance(enemy, dict):
            errors.append(_issue("error", "Enemy must be an object.", source))
            continue
        enemy_id = enemy.get("id")
        if not isinstance(enemy_id, str) or not enemy_id:
            errors.append(_issue("error", "Enemy id is required.", source, "id"))
        elif enemy_id != entry_id:
            errors.append(_issue("error", f"Definition key {entry_id!r} does not match its id field.", source, "id"))
        elif enemy_id in seen_ids:
            errors.append(_issue("error", f"Duplicate enemy ID {enemy_id!r}.", source, "id"))
        else:
            seen_ids.add(enemy_id)
        for field_name in ("name", "maxHp", "speed", "defense", "actionPattern"):
            if field_name not in enemy:
                errors.append(_issue("error", f"Missing required enemy field {field_name!r}.", source, field_name))
        if not isinstance(enemy.get("name"), str) or not enemy.get("name"):
            errors.append(_issue("error", "Enemy name is required.", source, "name"))
        for field_name in ("maxHp", "speed"):
            value = enemy.get(field_name)
            if not _is_number(value) or value <= 0:
                errors.append(_issue("error", f"Enemy {field_name} must be a positive number.", source, field_name))
        defense = enemy.get("defense")
        if not _is_number(defense) or defense < 0:
            errors.append(_issue("error", "Enemy defense must be a non-negative number.", source, "defense"))
        pattern = enemy.get("actionPattern")
        if not isinstance(pattern, list) or not pattern or not all(isinstance(action_id, str) and action_id for action_id in pattern):
            errors.append(_issue("error", "Enemy actionPattern must be a non-empty array of action IDs.", source, "actionPattern"))


def _validate_enemy_actions(actions: Any, known: dict[str, list[str]], errors: list[dict[str, str]]) -> None:
    if not isinstance(actions, dict):
        errors.append(_issue("error", "Enemy action definitions must be an object.", "enemyActions"))
        return
    seen_ids: set[str] = set()
    for entry_id, action in actions.items():
        source = f"enemyAction:{entry_id}"
        if not isinstance(action, dict):
            errors.append(_issue("error", "Enemy action must be an object.", source))
            continue
        action_id = action.get("id")
        if not isinstance(action_id, str) or not action_id:
            errors.append(_issue("error", "Enemy action id is required.", source, "id"))
        elif action_id != entry_id:
            errors.append(_issue("error", f"Definition key {entry_id!r} does not match its id field.", source, "id"))
        elif action_id in seen_ids:
            errors.append(_issue("error", f"Duplicate enemy action ID {action_id!r}.", source, "id"))
        else:
            seen_ids.add(action_id)
        for field_name in ("name", "damage", "target"):
            if field_name not in action:
                errors.append(_issue("error", f"Missing required enemy action field {field_name!r}.", source, field_name))
        if not isinstance(action.get("name"), str) or not action.get("name"):
            errors.append(_issue("error", "Enemy action name is required.", source, "name"))
        damage = action.get("damage")
        if not isinstance(damage, dict) or not _is_number(damage.get("minimum")) or not _is_number(damage.get("maximum")):
            errors.append(_issue("error", "Enemy action damage needs numeric minimum and maximum values.", source, "damage"))
        elif damage["minimum"] < 0 or damage["maximum"] < 0 or damage["minimum"] > damage["maximum"]:
            errors.append(_issue("error", "Enemy action damage must be non-negative with minimum <= maximum.", source, "damage"))
        if not isinstance(action.get("target"), str) or not action.get("target"):
            errors.append(_issue("error", "Enemy action target is required.", source, "target"))
        if "injuryChance" in action:
            chance = action.get("injuryChance")
            if not _is_number(chance) or not 0 <= chance <= 1:
                errors.append(_issue("error", "Enemy action injuryChance must be between 0 and 1.", source, "injuryChance"))


def _validate_abilities(abilities: Any, known: dict[str, list[str]], errors: list[dict[str, str]]) -> None:
    if not isinstance(abilities, dict):
        errors.append(_issue("error", "Combat ability definitions must be an object.", "abilities"))
        return
    allowed_targets = {"enemy", "ally", "self", "menu", "none"}
    seen_ids: set[str] = set()
    for entry_id, ability in abilities.items():
        source = f"ability:{entry_id}"
        if not isinstance(ability, dict):
            errors.append(_issue("error", "Combat ability must be an object.", source))
            continue
        ability_id = ability.get("id")
        if not isinstance(ability_id, str) or not ability_id:
            errors.append(_issue("error", "Ability id is required.", source, "id"))
        elif ability_id != entry_id:
            errors.append(_issue("error", f"Definition key {entry_id!r} does not match its id field.", source, "id"))
        elif ability_id in seen_ids:
            errors.append(_issue("error", f"Duplicate ability ID {ability_id!r}.", source, "id"))
        else:
            seen_ids.add(ability_id)
        for field_name in ("name", "target"):
            if not isinstance(ability.get(field_name), str) or not ability.get(field_name):
                errors.append(_issue("error", f"Ability {field_name} is required.", source, field_name))
        if isinstance(ability.get("target"), str) and ability["target"] not in allowed_targets:
            errors.append(_issue("error", f"Unknown ability target {ability['target']!r}.", source, "target"))
        for field_name in ("damageMultiplier", "gaugeReduction"):
            if field_name in ability and (not _is_number(ability.get(field_name)) or ability[field_name] < 0):
                errors.append(_issue("error", f"Ability {field_name} must be a non-negative number.", source, field_name))
        for field_name in ("description", "selectionPrompt", "effectType", "category"):
            if field_name in ability and not isinstance(ability.get(field_name), str):
                errors.append(_issue("error", f"Ability {field_name} must be a string.", source, field_name))


def _validate_quantity_fields(entry: dict[str, Any], source: str, errors: list[dict[str, str]]) -> None:
    if "quantity" in entry:
        quantity = entry.get("quantity")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            errors.append(_issue("error", "Loot quantity must be a positive integer.", source, "quantity"))
    for field_name in ("minimum", "maximum"):
        if field_name in entry:
            value = entry.get(field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                errors.append(_issue("error", f"Loot {field_name} must be a positive integer.", source, field_name))
    minimum = entry.get("minimum")
    maximum = entry.get("maximum")
    if isinstance(minimum, int) and isinstance(maximum, int) and minimum > maximum:
        errors.append(_issue("error", "Loot minimum cannot be greater than maximum.", source, "maximum"))


def _validate_loot_tables(tables: Any, known: dict[str, list[str]], errors: list[dict[str, str]]) -> None:
    if not isinstance(tables, dict):
        errors.append(_issue("error", "Loot table definitions must be an object.", "lootTables"))
        return
    seen_ids: set[str] = set()
    allowed_types = {"gold", "item", "material", "recipe", "table"}
    for entry_id, table in tables.items():
        source = f"lootTable:{entry_id}"
        if not isinstance(table, dict):
            errors.append(_issue("error", "Loot table must be an object.", source))
            continue
        table_id = table.get("id")
        if not isinstance(table_id, str) or not table_id:
            errors.append(_issue("error", "Loot table id is required.", source, "id"))
        elif table_id != entry_id:
            errors.append(_issue("error", f"Definition key {entry_id!r} does not match its id field.", source, "id"))
        elif table_id in seen_ids:
            errors.append(_issue("error", f"Duplicate loot table ID {table_id!r}.", source, "id"))
        else:
            seen_ids.add(table_id)
        entries = table.get("entries")
        if not isinstance(entries, list):
            errors.append(_issue("error", "Loot table entries must be an array.", source, "entries"))
            continue
        if "rolls" in table:
            rolls = table.get("rolls")
            if not isinstance(rolls, int) or isinstance(rolls, bool) or rolls <= 0:
                errors.append(_issue("error", "Loot table rolls must be a positive integer.", source, "rolls"))
        for index, entry in enumerate(entries):
            entry_source = f"{source}.entries[{index}]"
            if not isinstance(entry, dict):
                errors.append(_issue("error", "Loot entry must be an object.", entry_source))
                continue
            entry_type = entry.get("type")
            if entry_type not in allowed_types:
                errors.append(_issue("error", f"Unknown loot entry type {entry_type!r}.", entry_source, "type"))
                continue
            weight = entry.get("weight")
            if not _is_number(weight) or weight <= 0:
                errors.append(_issue("error", "Loot entry weight must be a positive number.", entry_source, "weight"))
            _validate_quantity_fields(entry, entry_source, errors)
            required_field = {"item": "itemId", "material": "materialId", "recipe": "recipeId", "table": "tableId"}.get(entry_type)
            if required_field and (not isinstance(entry.get(required_field), str) or not entry.get(required_field)):
                errors.append(_issue("error", f"{entry_type} loot entries require {required_field}.", entry_source, required_field))
    table_ids = set(_id_map(tables))
    for table_id, table in tables.items():
        for index, entry in enumerate(table.get("entries", []) if isinstance(table, dict) else []):
            if isinstance(entry, dict) and entry.get("type") == "table" and entry.get("tableId") == table_id:
                errors.append(_issue("error", "Loot table cannot reference itself.", f"lootTable:{table_id}", f"entries[{index}].tableId"))


def _validate_expeditions(expeditions: Any, known: dict[str, list[str]], errors: list[dict[str, str]]) -> None:
    """Validate the actual fields in EXPEDITION_DEFINITIONS."""
    if not isinstance(expeditions, dict):
        errors.append(_issue("error", "Expedition definitions must be an object.", "expeditions"))
        return
    seen_ids: set[str] = set()
    for entry_id, expedition in expeditions.items():
        source = f"expedition:{entry_id}"
        if not isinstance(expedition, dict):
            errors.append(_issue("error", "Expedition must be an object.", source))
            continue
        expedition_id = expedition.get("id")
        if not isinstance(expedition_id, str) or not expedition_id:
            errors.append(_issue("error", "Expedition id is required.", source, "id"))
        elif expedition_id != entry_id:
            errors.append(_issue("error", f"Definition key {entry_id!r} does not match its id field.", source, "id"))
        elif expedition_id in seen_ids:
            errors.append(_issue("error", f"Duplicate expedition ID {expedition_id!r}.", source, "id"))
        else:
            seen_ids.add(expedition_id)
        for field_name in ("name", "description", "regionId", "pathId", "kind"):
            if not isinstance(expedition.get(field_name), str) or not expedition.get(field_name):
                errors.append(_issue("error", f"Expedition {field_name} is required.", source, field_name))
        danger = expedition.get("danger")
        if not _is_number(danger) or danger < 0:
            errors.append(_issue("error", "Expedition danger must be a non-negative number.", source, "danger"))
        for field_name, label in (("campEventTableIds", "camp event table IDs"), ("prerequisites", "prerequisites")):
            value = expedition.get(field_name)
            if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
                errors.append(_issue("error", f"Expedition {label} must be an array of IDs.", source, field_name))
        if isinstance(expedition.get("kind"), str) and not expedition["kind"]:
            errors.append(_issue("error", "Expedition kind cannot be empty.", source, "kind"))


def _validate_crafting_providers(providers: Any, errors: list[dict[str, str]]) -> None:
    if not isinstance(providers, dict):
        errors.append(_issue("error", "Crafting provider definitions must be an object.", "craftingProviders"))
        return
    seen_ids: set[str] = set()
    for entry_id, provider in providers.items():
        source = f"craftingProvider:{entry_id}"
        if not isinstance(provider, dict):
            errors.append(_issue("error", "Crafting provider must be an object.", source))
            continue
        provider_id = provider.get("id")
        if not isinstance(provider_id, str) or not provider_id:
            errors.append(_issue("error", "Crafting provider id is required.", source, "id"))
        elif provider_id != entry_id:
            errors.append(_issue("error", f"Definition key {entry_id!r} does not match its id field.", source, "id"))
        elif provider_id in seen_ids:
            errors.append(_issue("error", f"Duplicate crafting provider ID {provider_id!r}.", source, "id"))
        else:
            seen_ids.add(provider_id)
        if not isinstance(provider.get("name"), str) or not provider.get("name"):
            errors.append(_issue("error", "Crafting provider name is required.", source, "name"))


def _validate_materials(materials: Any, known: dict[str, list[str]], errors: list[dict[str, str]]) -> None:
    if not isinstance(materials, dict):
        errors.append(_issue("error", "Material definitions must be an object.", "materials"))
        return
    seen_ids: set[str] = set()
    rarity_ids = set(known.get("rarities", []))
    for entry_id, material in materials.items():
        source = f"material:{entry_id}"
        if not isinstance(material, dict):
            errors.append(_issue("error", "Material must be an object.", source))
            continue
        material_id = material.get("id")
        if not isinstance(material_id, str) or not material_id:
            errors.append(_issue("error", "Material id is required.", source, "id"))
        elif material_id != entry_id:
            errors.append(_issue("error", f"Definition key {entry_id!r} does not match its id field.", source, "id"))
        elif material_id in seen_ids:
            errors.append(_issue("error", f"Duplicate material ID {material_id!r}.", source, "id"))
        else:
            seen_ids.add(material_id)
        for field_name in ("name", "description", "rarity"):
            if field_name not in material:
                errors.append(_issue("error", f"Missing required material field {field_name!r}.", source, field_name))
        if not isinstance(material.get("name"), str) or not material.get("name"):
            errors.append(_issue("error", "Material name is required.", source, "name"))
        if not isinstance(material.get("description"), str):
            errors.append(_issue("error", "Material description must be a string.", source, "description"))
        if not isinstance(material.get("rarity"), str) or material.get("rarity") not in rarity_ids:
            errors.append(_issue("error", f"Unknown material rarity {material.get('rarity')!r}.", source, "rarity"))


def _validate_recipes(recipes: Any, known: dict[str, list[str]], errors: list[dict[str, str]]) -> None:
    if not isinstance(recipes, dict):
        errors.append(_issue("error", "Recipe definitions must be an object.", "recipes"))
        return
    seen_ids: set[str] = set()
    item_ids = set(known.get("items", []))
    material_ids = set(known.get("materials", []))
    provider_ids = set(known.get("craftingProviders", []))
    rarity_ids = set(known.get("rarities", []))
    for entry_id, recipe in recipes.items():
        source = f"recipe:{entry_id}"
        if not isinstance(recipe, dict):
            errors.append(_issue("error", "Recipe must be an object.", source))
            continue
        recipe_id = recipe.get("id")
        if not isinstance(recipe_id, str) or not recipe_id:
            errors.append(_issue("error", "Recipe id is required.", source, "id"))
        elif recipe_id != entry_id:
            errors.append(_issue("error", f"Definition key {entry_id!r} does not match its id field.", source, "id"))
        elif recipe_id in seen_ids:
            errors.append(_issue("error", f"Duplicate recipe ID {recipe_id!r}.", source, "id"))
        else:
            seen_ids.add(recipe_id)
        for field_name in ("name", "description", "craftingProvider", "ingredients", "output", "goldCost"):
            if field_name not in recipe:
                errors.append(_issue("error", f"Missing required recipe field {field_name!r}.", source, field_name))
        if not isinstance(recipe.get("name"), str) or not recipe.get("name"):
            errors.append(_issue("error", "Recipe name is required.", source, "name"))
        if not isinstance(recipe.get("description"), str):
            errors.append(_issue("error", "Recipe description must be a string.", source, "description"))
        provider_id = recipe.get("craftingProvider")
        if not isinstance(provider_id, str) or provider_id not in provider_ids:
            errors.append(_issue("error", f"Unknown crafting provider ID {provider_id!r}.", source, "craftingProvider"))
        ingredient_type = recipe.get("ingredientType", "material")
        if ingredient_type not in {"material", "item"}:
            errors.append(_issue("error", f"Unknown recipe ingredient type {ingredient_type!r}.", source, "ingredientType"))
        ingredients = recipe.get("ingredients")
        if not isinstance(ingredients, dict) or not ingredients:
            errors.append(_issue("error", "Recipe ingredients must be a non-empty object.", source, "ingredients"))
        elif ingredient_type in {"material", "item"}:
            for ingredient_id, quantity in ingredients.items():
                if ingredient_type == "material" and ingredient_id not in material_ids:
                    errors.append(_issue("error", f"Unknown material ID {ingredient_id!r}.", source, f"ingredients.{ingredient_id}"))
                elif ingredient_type == "item" and ingredient_id not in item_ids and ingredient_id not in material_ids:
                    errors.append(_issue("error", f"Unknown item or material ID {ingredient_id!r}.", source, f"ingredients.{ingredient_id}"))
                if not _is_number(quantity) or quantity <= 0:
                    errors.append(_issue("error", "Recipe ingredient quantity must be a positive number.", source, f"ingredients.{ingredient_id}"))
        output = recipe.get("output")
        if not isinstance(output, dict):
            errors.append(_issue("error", "Recipe output must be an object.", source, "output"))
        else:
            has_item_output = isinstance(output.get("itemId"), str) and bool(output.get("itemId"))
            has_provision_output = _is_number(output.get("provisions")) and output.get("provisions") > 0
            if has_item_output == has_provision_output:
                errors.append(_issue("error", "Recipe output must define exactly one positive itemId or provisions result.", source, "output"))
            if has_item_output:
                if output["itemId"] not in item_ids:
                    errors.append(_issue("error", f"Unknown item ID {output['itemId']!r}.", source, "output.itemId"))
                if not _is_number(output.get("quantity")) or output.get("quantity") <= 0:
                    errors.append(_issue("error", "Item recipe output quantity must be positive.", source, "output.quantity"))
            if "provisions" in output and not has_provision_output:
                errors.append(_issue("error", "Recipe provisions output must be a positive number.", source, "output.provisions"))
        if not _is_number(recipe.get("goldCost")) or recipe.get("goldCost") < 0:
            errors.append(_issue("error", "Recipe goldCost must be a non-negative number.", source, "goldCost"))
        if "rarity" in recipe and (not isinstance(recipe.get("rarity"), str) or recipe.get("rarity") not in rarity_ids):
            errors.append(_issue("error", f"Unknown recipe rarity {recipe.get('rarity')!r}.", source, "rarity"))
        if "starter" in recipe and not isinstance(recipe.get("starter"), bool):
            errors.append(_issue("error", "Recipe starter must be boolean.", source, "starter"))
        if "craftingDurationMs" in recipe and (
            not _is_number(recipe.get("craftingDurationMs")) or recipe.get("craftingDurationMs") <= 0
        ):
            errors.append(_issue("error", "Recipe craftingDurationMs must be a positive number when authored.", source, "craftingDurationMs"))


def validate_catalog(values: dict[str, Any], known: dict[str, list[str]], references: dict[str, list[dict[str, str]]] | None = None, parse_duplicates: list[dict[str, str]] | None = None) -> dict[str, list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    effective_known = {key: list(value) for key, value in known.items()}
    item_ids = sorted(_id_map(values.get("items"))) if "items" in values else list(known.get("items", []))
    effective_known["items"] = item_ids
    for value_key, known_key in (("combats", "combats"), ("abilities", "abilities"), ("injuries", "injuries"), ("campEvents", "campEvents"), ("enemyDefinitions", "enemies"), ("enemyActions", "enemyActions"), ("lootTables", "lootTables")):
        if value_key in values:
            effective_known[known_key] = sorted(_id_map(values.get(value_key)))
    if "expeditions" in values:
        effective_known["expeditions"] = sorted(_id_map(values.get("expeditions")))
    if "recipes" in values:
        effective_known["recipes"] = sorted(_id_map(values.get("recipes")))
    if "craftingProviders" in values:
        effective_known["craftingProviders"] = sorted(_id_map(values.get("craftingProviders")))
    if "materials" in values:
        effective_known["materials"] = sorted(_id_map(values.get("materials")))
    for duplicate in parse_duplicates or []:
        errors.append(_issue("error", f"Duplicate object key {duplicate['id']!r}.", duplicate["source"]))
    if "encounters" in values:
        _validate_encounters(values.get("encounters"), effective_known, errors)
    if "injuries" in values:
        _validate_injuries(values.get("injuries"), effective_known, errors)
    if "campEvents" in values:
        _validate_camp_events(values.get("campEvents"), effective_known, errors)
    if "expeditions" in values:
        _validate_expeditions(values.get("expeditions"), effective_known, errors)
    if "recipes" in values:
        _validate_recipes(values.get("recipes"), effective_known, errors)
    if "materials" in values:
        _validate_materials(values.get("materials"), effective_known, errors)
    if "craftingProviders" in values:
        _validate_crafting_providers(values.get("craftingProviders"), errors)
    if "shops" in values:
        _validate_shops(values.get("shops"), effective_known, errors)
    if "items" in values:
        _validate_items(values.get("items"), effective_known, errors)
    if "combats" in values:
        _validate_combat_definitions(values.get("combats"), effective_known, errors)
    if "enemyDefinitions" in values:
        _validate_enemy_definitions(values.get("enemyDefinitions"), effective_known, errors)
    if "enemyActions" in values:
        _validate_enemy_actions(values.get("enemyActions"), effective_known, errors)
    if "abilities" in values:
        _validate_abilities(values.get("abilities"), effective_known, errors)
    if "lootTables" in values:
        _validate_loot_tables(values.get("lootTables"), effective_known, errors)

    effective_references: dict[str, list[dict[str, str]]] = {}
    editable_categories = {category for category in CONTENT_FILES if category in values}
    for category in editable_categories:
        collect_references(values.get(category), category, effective_references)
    if references:
        for ref_type, entries in references.items():
            for entry in entries:
                if entry.get("source") not in editable_categories:
                    effective_references.setdefault(ref_type, []).append(entry)

    for ref_type, entries in effective_references.items():
        valid = set(effective_known.get(ref_type, []))
        for entry in entries:
            if entry["id"] not in valid:
                label = {
                    "abilities": "ability", "lootTables": "loot table", "enemyActions": "enemy action",
                    "combats": "combat", "items": "item", "shops": "shop", "materials": "material",
                    "recipes": "recipe", "enemies": "enemy", "injuries": "injury", "expeditions": "expedition",
                    "craftingProviders": "crafting provider", "campEvents": "camp event",
                }.get(ref_type, ref_type[:-1] if ref_type.endswith("s") else ref_type)
                errors.append(_issue("error", f"Unknown {label} ID {entry['id']!r}.", entry["source"], entry["path"]))

    # A deleted shop is unsafe when a currently understood location still
    # points at it.  This check intentionally blocks save, rather than
    # silently repairing location-data.js.
    if effective_references and "shops" in values:
        shop_ids = set(_id_map(values.get("shops")).keys())
        for reference in effective_references.get("shops", []):
            if reference["id"] not in shop_ids:
                errors.append(_issue("error", f"Deleted shop {reference['id']!r} is still referenced by {reference['source']}.", "shops", reference["path"]))
    return {"errors": errors, "warnings": warnings}


def merged_state(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = {category: current[category] for category in CONTENT_FILES}
    for category in result:
        if category in incoming:
            result[category] = incoming[category]
    return result


def _line_indent(source: str, position: int, fallback: int = 2) -> int:
    line_start = source.rfind("\n", 0, position) + 1
    prefix = source[line_start:position]
    return len(prefix) if prefix.strip() == "" else fallback


def _render_property(source: str, key: str, value: Any, property_indent: int, newline: str) -> str:
    rendered_key = key if _is_identifier(key) else js_string(key)
    return " " * property_indent + rendered_key + ": " + serialize_js(value, indent=property_indent, newline=newline)


def _apply_source_edits(source: str, edits: list[tuple[int, int, str]]) -> str:
    previous_start = len(source) + 1
    for start, end, replacement in sorted(edits, key=lambda edit: edit[0], reverse=True):
        if end > previous_start:
            raise JsParseError("Overlapping source edits")
        source = source[:start] + replacement + source[end:]
        previous_start = start
    return source


def _remove_property(source: str, parsed: ParsedConstant, key: str) -> str:
    properties = parsed.properties
    target_index = next((index for index, property_span in enumerate(properties) if property_span.key == key), None)
    if target_index is None:
        raise JsParseError(f"Could not find property {key!r} while deleting")
    target = properties[target_index]
    object_end = parsed.value_end - 1
    if target_index < len(properties) - 1:
        # Keep the previous property's comma and the next property's authored
        # key/indentation. This removes only the target property and the
        # whitespace/delimiter immediately following it.
        return source[:target.key_start] + source[properties[target_index + 1].key_start:]
    if target_index > 0:
        # The last property has no following key to anchor against. Remove the
        # preceding comma/whitespace as delimiter cleanup, leaving the prior
        # definition's value bytes intact.
        return source[:properties[target_index - 1].value_end] + source[object_end:]
    return source[:target.key_start] + source[object_end:]


def _insert_property(source: str, constant_name: str, key: str, value: Any, newline: str) -> str:
    parsed = extract_constant(source, constant_name)
    if any(property_span.key == key for property_span in parsed.properties):
        raise JsParseError(f"Property {key!r} already exists")
    object_end = parsed.value_end - 1
    if parsed.properties:
        last = parsed.properties[-1]
        between = source[last.value_end:object_end]
        # Existing source may or may not use a trailing comma. The new entry is
        # appended at the end, so ensure the prior entry is separated without
        # touching its value or any other definition.
        if "," not in between:
            source = source[:last.value_end] + "," + source[last.value_end:]
            parsed = extract_constant(source, constant_name)
            object_end = parsed.value_end - 1
        property_indent = _line_indent(source, parsed.properties[-1].key_start)
        rendered = _render_property(source, key, value, property_indent, newline)
        between = source[parsed.properties[-1].value_end:object_end]
        prefix = "" if "\n" in between else newline
        return source[:object_end] + prefix + rendered + newline + source[object_end:]

    property_indent = 2
    rendered = _render_property(source, key, value, property_indent, newline)
    return source[:parsed.value_start + 1] + newline + rendered + newline + source[object_end:]


def _surgical_source_update(source: str, constant_name: str, incoming: dict[str, Any], newline: str) -> str:
    parsed = extract_constant(source, constant_name)
    current = parsed.value
    if not isinstance(current, dict):
        raise JsParseError(f"{constant_name} must be an object definition map")

    existing_properties = {property_span.key: property_span for property_span in parsed.properties}
    updates: list[tuple[int, int, str]] = []
    for key in current.keys() & incoming.keys():
        if current[key] == incoming[key]:
            continue
        property_span = existing_properties.get(key)
        if property_span is None:
            raise JsParseError(f"Could not find source property for {key!r}")
        property_indent = _line_indent(source, property_span.key_start)
        updates.append((
            property_span.value_start,
            property_span.value_end,
            serialize_js(incoming[key], indent=property_indent, newline=newline),
        ))
    source = _apply_source_edits(source, updates)

    # Delete from the end toward the beginning, reparsing after each operation
    # so all later spans remain structurally correct even for multiple deletes.
    deletion_keys = set(current) - set(incoming)
    while deletion_keys:
        parsed = extract_constant(source, constant_name)
        candidates = [property_span for property_span in parsed.properties if property_span.key in deletion_keys]
        if not candidates:
            raise JsParseError("Could not locate a definition scheduled for deletion")
        target = max(candidates, key=lambda property_span: property_span.index)
        source = _remove_property(source, parsed, target.key)
        deletion_keys.remove(target.key)

    # Additions are appended predictably. Existing definition order and source
    # bytes are not rebuilt or reserialized.
    for key, value in incoming.items():
        if key not in current:
            source = _insert_property(source, constant_name, key, value, newline)
    return source


def _write_source_constants(
    project_root: Path,
    relative: str,
    definitions: dict[str, Any],
    backup_dir: Path,
    expected_hash: str | None = None,
) -> dict[str, str]:
    path = project_root / relative
    raw = path.read_bytes()
    source = raw.decode("utf-8")
    if expected_hash and _source_hash(raw) != expected_hash:
        raise RuntimeError(f"Conflict: {relative} changed on disk since the editor loaded it. Reload before saving.")
    newline = "\r\n" if "\r\n" in source else "\n"
    updated = source
    for name, value in definitions.items():
        updated = _surgical_source_update(updated, name, value, newline)
    updated_bytes = updated.encode("utf-8")
    if updated_bytes == raw:
        return {"file": relative, "status": "unchanged"}

    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"{path.name}.{stamp}.bak"
    shutil.copy2(path, backup_path)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(updated_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return {"file": relative, "status": "updated", "backup": str(backup_path)}


def _write_constant(project_root: Path, category: str, value: Any, backup_dir: Path, expected_hash: str | None = None) -> dict[str, str]:
    relative, name = CONTENT_FILES[category]
    return _write_source_constants(project_root, relative, {name: value}, backup_dir, expected_hash)


def save_catalog(project_root: Path, incoming: dict[str, Any], expected_hashes: dict[str, str] | None = None, backup_dir: Path | None = None) -> dict[str, Any]:
    current = load_catalog(project_root)
    expected_hashes = expected_hashes or {}
    for category, (relative, _name) in CONTENT_FILES.items():
        if category not in incoming:
            continue
        expected = expected_hashes.get(relative)
        actual = current["sourceHashes"].get(relative)
        if expected and actual != expected:
            raise RuntimeError(f"Conflict: {relative} changed on disk since the editor loaded it. Reload before saving.")

    merged = merged_state(current, incoming)
    validation = validate_catalog(merged, current["known"], current["references"])
    if validation["errors"]:
        raise ValueError(json.dumps(validation))

    changed_categories = [category for category in CONTENT_FILES if category in incoming and incoming[category] != current[category]]
    results = []
    backup_dir = backup_dir or (Path(__file__).resolve().parent / ".backups")
    updates_by_file: dict[str, dict[str, Any]] = {}
    for category in changed_categories:
        relative, name = CONTENT_FILES[category]
        updates_by_file.setdefault(relative, {})[name] = incoming[category]
    for relative, definitions in updates_by_file.items():
        results.append(_write_source_constants(project_root, relative, definitions, backup_dir, current["sourceHashes"].get(relative)))
    result = load_catalog(project_root)
    result["saveResults"] = results
    return result
