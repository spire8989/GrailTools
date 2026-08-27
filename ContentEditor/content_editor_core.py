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
import math
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from image_processing import ProcessedImage, optimize_image, profile_for_category


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
    "imageAssets": ("js/asset-data.js", "IMAGE_ASSET_DEFINITIONS"),
    "audioAssets": ("js/asset-data.js", "AUDIO_ASSET_DEFINITIONS"),
    "playerCharacter": ("js/data.js", "PLAYER_CHARACTER_DEFINITION"),
    "startingState": ("js/storage.js", "STARTING_PLAYER_STATE"),
    "companions": ("js/data.js", "COMPANION_DEFINITIONS"),
    "encounters": ("js/encounter-data.js", "ENCOUNTER_DEFINITIONS"),
    "injuries": ("js/injury-data.js", "INJURY_DEFINITIONS"),
    "campEvents": ("js/camp-data.js", "CAMP_EVENT_DEFINITIONS"),
    "dialogues": ("js/dialogue-data.js", "DIALOGUE_DEFINITIONS"),
    "expeditions": ("js/expedition-data.js", "EXPEDITION_DEFINITIONS"),
    "recipes": ("js/crafting-data.js", "RECIPE_DEFINITIONS"),
    "materials": ("js/crafting-data.js", "MATERIAL_DEFINITIONS"),
    "craftingProviders": ("js/crafting-data.js", "CRAFTING_PROVIDER_DEFINITIONS"),
    "shops": ("js/location-data.js", "SHOP_DEFINITIONS"),
    "npcs": ("js/location-data.js", "NPC_DEFINITIONS"),
    "destinations": ("js/location-data.js", "DESTINATION_DEFINITIONS"),
    "locations": ("js/location-data.js", "LOCATION_DEFINITIONS"),
    "items": ("js/data.js", "ITEM_DEFINITIONS"),
    "combats": ("js/combat-data.js", "COMBAT_DEFINITIONS"),
    "abilities": ("js/combat-data.js", "COMBAT_ABILITY_DEFINITIONS"),
    "combatStatuses": ("js/combat-data.js", "COMBAT_STATUS_DEFINITIONS"),
    "enemyDefinitions": ("js/combat-data.js", "COMBAT_ENEMY_DEFINITIONS"),
    "enemyActions": ("js/combat-data.js", "COMBAT_ENEMY_ACTION_DEFINITIONS"),
    "lootTables": ("js/loot-data.js", "LOOT_TABLE_DEFINITIONS"),
    "returnRewards": ("js/loot-data.js", "EXPEDITION_RETURN_REWARD_TIERS"),
}
EXPEDITION_TUNING_FILE = ("js/tuning.js", "EXPEDITION_TUNING")

ASSET_IMAGE_CATEGORIES = ("location", "town", "expedition", "encounter", "combat", "combat_scene", "portrait", "ui")
ASSET_AUDIO_CATEGORIES = ("ambience", "sfx", "music")
ASSET_IMAGE_EXTENSIONS = {".png", ".webp", ".jpg", ".jpeg", ".gif", ".avif"}
ASSET_AUDIO_EXTENSIONS = {".mp3", ".ogg", ".wav", ".m4a", ".aac", ".webm"}
ASSET_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
ASSET_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

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
    "dialogues": ("js/dialogue-data.js", "DIALOGUE_DEFINITIONS"),
    "npcs": ("js/location-data.js", "NPC_DEFINITIONS"),
    "destinations": ("js/location-data.js", "DESTINATION_DEFINITIONS"),
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
    if key in {"portraitAssetId", "visualAssetId", "backgroundAssetId", "travelVisualAssetId", "travelParallaxAssetId", "travelTransitionAssetId", "travelSeamForegroundAssetId", "campVisualAssetId", "combatVisualAssetId", "assetId"}:
        return "imageAssets"
    if key in {"travelAmbienceAssetId", "campAmbienceAssetId", "ambienceAssetId", "stingAssetId"}:
        return "audioAssets"
    return {
        "itemId": "items",
        "treatmentItemId": "items",
        "combatId": "combats",
        "abilityId": "abilities",
        "statusId": "combatStatuses",
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
        "selectedCompanion": "companions",
        "selectedCompanionId": "companions",
        "dialogueId": "dialogues",
        "dialogueSequenceId": "dialogues",
        "introDialogueSequenceId": "dialogues",
        "speakerId": "npcs",
        "npcId": "npcs",
        "destinationId": "destinations",
        "locationId": "locations",
    }.get(key)


def collect_references(value: Any, source: str, references: dict[str, list[dict[str, str]]]) -> None:
    """Collect known ID-shaped references, including shop map keys."""

    def visit(node: Any, path: str = "", parent_key: str | None = None) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                child_path = f"{path}.{key}" if path else str(key)
                ref_type = _ref_type_for_key(key)
                if ref_type and isinstance(child, str) and not (key == "speakerId" and child == "arthur"):
                    references.setdefault(ref_type, []).append({"source": source, "path": child_path, "id": child})
                elif key in {"pathIds", "shopIds", "shops", "expeditionIds", "availableExpeditions", "recipeIds", "npcIds", "locationIds", "destinationIds", "destinations", "npcs", "locations"} and isinstance(child, list) and not (source == "encounters" and key == "expeditionIds"):
                    ref_type = {
                        "pathIds": "paths", "shopIds": "shops", "shops": "shops",
                        "expeditionIds": "expeditions", "availableExpeditions": "expeditions",
                        "recipeIds": "recipes", "npcIds": "npcs", "locationIds": "locations",
                        "destinationIds": "destinations", "destinations": "destinations",
                        "npcs": "npcs", "locations": "locations",
                    }[key]
                    for index, item in enumerate(child):
                        if isinstance(item, str):
                            references.setdefault(ref_type, []).append({"source": source, "path": f"{child_path}[{index}]", "id": item})
                elif key in {"itemIds", "injuryIds", "prerequisites", "enemyIds", "abilityIds", "grantedAbilityIds", "combatAbilities", "actionPattern", "campEventTableIds", "suppressedByStatuses"} and isinstance(child, list):
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
                        "suppressedByStatuses": "combatStatuses",
                    }[key]
                    for index, item in enumerate(child):
                        if isinstance(item, str):
                            references.setdefault(ref_type, []).append({"source": source, "path": f"{child_path}[{index}]", "id": item})
                if key in {"itemsForSale", "sellValues"} and isinstance(child, dict):
                    for item_id in child:
                        references.setdefault("items", []).append({"source": source, "path": f"{child_path}.{item_id}", "id": item_id})
                if key in {"ownedItems", "equippedItems"} and isinstance(child, dict):
                    if key == "ownedItems":
                        for item_id in child:
                            references.setdefault("items", []).append({"source": source, "path": f"{child_path}.{item_id}", "id": item_id})
                    else:
                        for slot, item_id in child.items():
                            if isinstance(item_id, str):
                                references.setdefault("items", []).append({"source": source, "path": f"{child_path}.{slot}", "id": item_id})
                elif key in {"packedItems"} and isinstance(child, list):
                    for index, item_id in enumerate(child):
                        if isinstance(item_id, str):
                            references.setdefault("items", []).append({"source": source, "path": f"{child_path}[{index}]", "id": item_id})
                elif key in {"materials", "packedMaterials"} and isinstance(child, dict):
                    for material_id in child:
                        references.setdefault("materials", []).append({"source": source, "path": f"{child_path}.{material_id}", "id": material_id})
                elif key in {"learnedAbilityIds", "selectedActiveAbilityIds", "selectedPassiveAbilityIds"} and isinstance(child, list):
                    for index, ability_id in enumerate(child):
                        if isinstance(ability_id, str):
                            references.setdefault("abilities", []).append({"source": source, "path": f"{child_path}[{index}]", "id": ability_id})
                elif key in {"learnedRecipes"} and isinstance(child, list):
                    for index, recipe_id in enumerate(child):
                        if isinstance(recipe_id, str):
                            references.setdefault("recipes", []).append({"source": source, "path": f"{child_path}[{index}]", "id": recipe_id})
                elif key in {"unlockedCompanions", "selectedCompanions"} and isinstance(child, list):
                    for index, companion_id in enumerate(child):
                        if isinstance(companion_id, str):
                            references.setdefault("companions", []).append({"source": source, "path": f"{child_path}[{index}]", "id": companion_id})
                elif key in {"learnedKnowledge"} and isinstance(child, list):
                    for index, knowledge_id in enumerate(child):
                        if isinstance(knowledge_id, str):
                            references.setdefault("knowledge", []).append({"source": source, "path": f"{child_path}[{index}]", "id": knowledge_id})
                if key == "ingredients" and isinstance(child, dict):
                    ingredient_type = node.get("ingredientType", "material")
                    ref_type = "items" if ingredient_type == "item" else "materials"
                    for ingredient_id in child:
                        references.setdefault(ref_type, []).append({"source": source, "path": f"{child_path}.{ingredient_id}", "id": ingredient_id})
                elif key == "ingredients" and isinstance(child, list):
                    for index, ingredient in enumerate(child):
                        if not isinstance(ingredient, dict):
                            continue
                        ingredient_type = ingredient.get("type")
                        ref_type = "items" if ingredient_type == "item" else "materials" if ingredient_type == "material" else None
                        ingredient_id = ingredient.get("id")
                        if ref_type and isinstance(ingredient_id, str):
                            references.setdefault(ref_type, []).append({"source": source, "path": f"{child_path}[{index}].id", "id": ingredient_id})
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
        for field_name in ("description", "regionId", "kind", "danger", "minimumObjectiveDistance"):
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

    try:
        tuning, _source, raw, _parsed = _read_constant(project_root, *EXPEDITION_TUNING_FILE)
        source_hashes.setdefault(EXPEDITION_TUNING_FILE[0], _source_hash(raw))
    except (FileNotFoundError, JsParseError):
        tuning = {}

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
    known["combatStatuses"] = sorted(_id_map(values.get("combatStatuses")))
    known["injuries"] = sorted(_id_map(values.get("injuries")))
    known["campEvents"] = sorted(_id_map(values.get("campEvents")))
    known["dialogues"] = sorted(_id_map(values.get("dialogues")))
    known["npcs"] = sorted(_id_map(values.get("npcs")))
    known["destinations"] = sorted(_id_map(values.get("destinations")))
    known["locations"] = sorted(_id_map(values.get("locations")))
    known["enemies"] = sorted(_id_map(values.get("enemyDefinitions")))
    known["enemyActions"] = sorted(_id_map(values.get("enemyActions")))
    known["lootTables"] = sorted(_id_map(values.get("lootTables")))
    known["items"] = sorted(item_map)
    known["shops"] = sorted(_id_map(values.get("shops")))
    known["expeditions"] = sorted(_id_map(values.get("expeditions")))
    known["recipes"] = sorted(_id_map(values.get("recipes")))
    known["craftingProviders"] = sorted(_id_map(values.get("craftingProviders")))
    known["imageAssets"] = sorted(_id_map(values.get("imageAssets")))
    known["audioAssets"] = sorted(_id_map(values.get("audioAssets")))
    known["companions"] = sorted(_id_map(values.get("companions")))
    known["materials"] = sorted(set(known.get("materials", [])) | {
        item_id
        for item_id, item in item_map.items()
        if isinstance(item, dict) and (
            item.get("category") == "ingredient"
            or "ingredient" in item.get("tags", [])
        )
    })
    known["itemCategories"] = sorted({
        *(item.get("category") for item in item_map.values() if isinstance(item, dict) and isinstance(item.get("category"), str)),
        "other", "shield",
    })
    known["rarities"] = sorted({
        *(item.get("rarity") for item in item_map.values() if isinstance(item, dict) and isinstance(item.get("rarity"), str)),
        *known.get("rarities", []),
        "common", "uncommon", "rare",
    })
    known["equipmentSlots"] = sorted({
        *(item.get("equipmentSlot") for item in item_map.values() if isinstance(item, dict) and isinstance(item.get("equipmentSlot"), str)),
        "armor", "relic", "shield", "weapon",
    })

    validation = validate_catalog(values, known, refs, parse_duplicates, project_root)
    item_labels = {key: item.get("name", key) for key, item in item_map.items() if isinstance(item, dict)}
    material_map = {}
    try:
        material_map, *_ = _read_constant(project_root, *REFERENCE_FILES["materials"])
    except (FileNotFoundError, JsParseError):
        pass
    material_labels = {key: value.get("name", key) for key, value in _id_map(material_map).items() if isinstance(value, dict)}
    material_labels.update({
        key: value.get("name", key)
        for key, value in item_map.items()
        if key in known.get("materials", []) and isinstance(value, dict)
    })
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
    dialogue_map = _id_map(values.get("dialogues"))
    npc_map = _id_map(values.get("npcs"))
    destination_map = _id_map(values.get("destinations"))
    location_map = _id_map(values.get("locations"))

    return {
        "projectRoot": str(project_root),
        "files": source_paths,
        "sourceHashes": source_hashes,
        "tuning": tuning,
        "imageAssets": values["imageAssets"],
        "audioAssets": values["audioAssets"],
        "playerCharacter": values["playerCharacter"],
        "startingState": values["startingState"],
        "companions": values["companions"],
        "encounters": values["encounters"],
        "injuries": values["injuries"],
        "campEvents": values["campEvents"],
        "dialogues": values["dialogues"],
        "expeditions": values["expeditions"],
        "recipes": values["recipes"],
        "materials": values["materials"],
        "craftingProviders": values["craftingProviders"],
        "shops": values["shops"],
        "npcs": values["npcs"],
        "destinations": values["destinations"],
        "locations": values["locations"],
        "items": values["items"],
        "combats": values["combats"],
        "abilities": values["abilities"],
        "combatStatuses": values["combatStatuses"],
        "enemyDefinitions": values["enemyDefinitions"],
        "enemyActions": values["enemyActions"],
        "lootTables": values["lootTables"],
        "returnRewards": values["returnRewards"],
        "known": {key: sorted(set(items)) for key, items in known.items()},
        "campEventTables": reference_values.get("campEventTables", {}),
        "paths": build_path_index(values["encounters"], values["expeditions"]),
        "itemLabels": item_labels,
        "materialLabels": material_labels,
        "abilityLabels": ability_labels,
        "injuryLabels": injury_labels,
        "campEventLabels": camp_event_labels,
        "dialogueLabels": {key: value.get("title", value.get("name", key)) for key, value in dialogue_map.items() if isinstance(value, dict)},
        "npcLabels": {key: value.get("name", key) for key, value in npc_map.items() if isinstance(value, dict)},
        "destinationLabels": {key: value.get("name", key) for key, value in destination_map.items() if isinstance(value, dict)},
        "locationLabels": {key: value.get("name", key) for key, value in location_map.items() if isinstance(value, dict)},
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
        if requirement.get("type") in {"anyOf", "allOf"} and not isinstance(nested, list):
            errors.append(_issue("error", f"{requirement['type']} requires a nested requirements array.", source, f"{requirement_path}.requirements"))
        if nested is not None:
            _validate_requirements(nested, source, f"{requirement_path}.requirements", errors)


def _validate_positive_integer(value: Any, label: str, source: str, path: str, errors: list[dict[str, str]]) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        errors.append(_issue("error", f"{label} must be a positive integer.", source, path))


def _validate_loot_sources(sources: Any, known: dict[str, list[str]], source: str, path: str, errors: list[dict[str, str]], label: str) -> None:
    if sources is None:
        return
    if not isinstance(sources, list):
        errors.append(_issue("error", f"{label} must be an array of loot sources.", source, path))
        return
    known_tables = set(known.get("lootTables", []))
    for index, loot_source in enumerate(sources):
        source_path = f"{path}[{index}]"
        if not isinstance(loot_source, dict):
            errors.append(_issue("error", "Loot sources must be objects.", source, source_path))
            continue
        table_id = loot_source.get("tableId")
        if not isinstance(table_id, str) or not table_id:
            errors.append(_issue("error", "Loot sources require a tableId.", source, f"{source_path}.tableId"))
        elif table_id not in known_tables:
            errors.append(_issue("error", f"Unknown loot table ID {table_id!r}.", source, f"{source_path}.tableId"))
        if "rolls" not in loot_source:
            errors.append(_issue("error", "Loot sources require positive integer rolls.", source, f"{source_path}.rolls"))
        else:
            _validate_positive_integer(loot_source.get("rolls"), "Loot source rolls", source, f"{source_path}.rolls", errors)
        if "chance" in loot_source:
            chance = loot_source.get("chance")
            if not _is_number(chance) or not math.isfinite(chance) or not 0 <= chance <= 1:
                errors.append(_issue("error", "Loot source chance must be between 0 and 1.", source, f"{source_path}.chance"))


def _validate_resolution_outcomes(outcomes: Any, known: dict[str, list[str]], source: str, path: str, errors: list[dict[str, str]]) -> None:
    if not isinstance(outcomes, list):
        errors.append(_issue("error", "Combat resolution outcomes must be an array.", source, path))
        return
    for index, outcome in enumerate(outcomes):
        _validate_resolution_outcome(outcome, known, source, f"{path}[{index}]", errors)


def _validate_encounter_layout(layout: Any, source: str, path: str, errors: list[dict[str, str]], *, partial: bool = False) -> None:
    if not isinstance(layout, dict):
        errors.append(_issue("error", "Encounter layout must be an object.", source, path))
        return
    for slot_id, position in layout.items():
        slot_path = f"{path}.{slot_id}"
        if slot_id not in {"arthur", "companion1", "companion2"}:
            errors.append(_issue("error", f"Unknown encounter party slot {slot_id!r}.", source, slot_path))
            continue
        if not isinstance(position, dict):
            errors.append(_issue("error", "Encounter layout positions must be objects.", source, slot_path))
            continue
        for axis in ("x", "y"):
            if axis not in position:
                if not partial:
                    errors.append(_issue("error", f"Encounter layout {slot_id} {axis} must be a number from 0 to 1.", source, f"{slot_path}.{axis}"))
                continue
            value = position.get(axis)
            if not _is_number(value) or not math.isfinite(value) or not 0 <= value <= 1:
                errors.append(_issue("error", f"Encounter layout {slot_id} {axis} must be a number from 0 to 1.", source, f"{slot_path}.{axis}"))
        if "facing" in position and position.get("facing") not in {"left", "right"}:
            errors.append(_issue("error", "Encounter layout facing must be left or right.", source, f"{slot_path}.facing"))
        if "scale" in position:
            scale = position.get("scale")
            if not _is_number(scale) or not math.isfinite(scale) or not 0.4 <= scale <= 2:
                errors.append(_issue("error", "Encounter layout scale must be a finite number from 0.4 to 2.", source, f"{slot_path}.scale"))
        if "layer" in position:
            layer = position.get("layer")
            if not _is_number(layer) or not math.isfinite(layer) or int(layer) != layer:
                errors.append(_issue("error", "Encounter layout layer must be a finite integer.", source, f"{slot_path}.layer"))


def _validate_hidden_slots(hidden_slots: Any, source: str, path: str, errors: list[dict[str, str]]) -> None:
    if hidden_slots is not None and (not isinstance(hidden_slots, list) or not all(slot in {"arthur", "companion1", "companion2"} for slot in hidden_slots)):
        errors.append(_issue("error", "Encounter hiddenSlots must contain only arthur, companion1, or companion2.", source, path))


def _validate_visual_override(visual_override: Any, known: dict[str, list[str]], source: str, path: str, errors: list[dict[str, str]]) -> None:
    if not isinstance(visual_override, dict):
        errors.append(_issue("error", "visualOverride must be an object.", source, path))
        return
    if "backgroundAssetId" in visual_override:
        asset_id = visual_override.get("backgroundAssetId")
        if not isinstance(asset_id, str) or asset_id not in set(known.get("imageAssets", [])):
            errors.append(_issue("error", "visualOverride backgroundAssetId must reference a known image asset.", source, f"{path}.backgroundAssetId"))
    layout = visual_override.get("encounterLayout")
    if layout is not None:
        _validate_encounter_layout(layout, source, f"{path}.encounterLayout", errors, partial=True)
    hidden_slots = visual_override.get("hiddenSlots")
    if hidden_slots is not None and (not isinstance(hidden_slots, list) or not all(slot in {"arthur", "companion1", "companion2"} for slot in hidden_slots)):
        errors.append(_issue("error", "visualOverride hiddenSlots must contain only arthur, companion1, or companion2.", source, f"{path}.hiddenSlots"))


def _validate_resolution_outcome(outcome: Any, known: dict[str, list[str]], source: str, path: str, errors: list[dict[str, str]]) -> None:
    if not isinstance(outcome, dict) or not isinstance(outcome.get("type"), str) or not outcome.get("type"):
        errors.append(_issue("error", "Each outcome must be an object with a type.", source, path))
        return
    outcome_type = outcome["type"]
    for legacy_field in ("outcomeVisual", "visualOverride"):
        if legacy_field in outcome:
            errors.append(_issue("error", "Visual overrides belong on the parent choice, result, or stage, not on mechanical effects.", source, f"{path}.{legacy_field}"))
    if outcome_type == "setCampaignFlagOnSafeReturn":
        if not isinstance(outcome.get("flag"), str) or not outcome.get("flag"):
            errors.append(_issue("error", "setCampaignFlagOnSafeReturn requires a flag.", source, f"{path}.flag"))

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
            if "visualOverride" in branch:
                _validate_visual_override(branch.get("visualOverride"), known, source, f"{branch_path}.visualOverride", errors)
            if "outcomes" in branch:
                _validate_resolution_outcomes(branch.get("outcomes"), known, source, f"{branch_path}.outcomes", errors)
        return

    if outcome_type == "rollLootTable":
        if not isinstance(outcome.get("tableId"), str) or not outcome.get("tableId"):
            errors.append(_issue("error", "rollLootTable requires a tableId.", source, f"{path}.tableId"))
        elif outcome.get("tableId") not in set(known.get("lootTables", [])):
            errors.append(_issue("error", f"Unknown loot table ID {outcome['tableId']!r}.", source, f"{path}.tableId"))
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
        success_effects = outcome.get("effects")
        failure_effects = outcome.get("elseEffects")
        has_success_effects = isinstance(success_effects, list) and bool(success_effects)
        has_failure_effects = isinstance(failure_effects, list) and bool(failure_effects)
        if not has_success_effects and not has_failure_effects:
            errors.append(_issue("error", "randomChance must contain at least one success or failure effect.", source, path))
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
    elif outcome_type == "learnAbility":
        ability_id = outcome.get("abilityId")
        if not isinstance(ability_id, str) or ability_id not in set(known.get("abilities", [])):
            errors.append(_issue("error", "learnAbility requires a known abilityId.", source, f"{path}.abilityId"))
    elif outcome_type == "modifyResource":
        if not isinstance(outcome.get("resource"), str) or not outcome.get("resource"):
            errors.append(_issue("error", "modifyResource requires a resource.", source, f"{path}.resource"))
        amount = outcome.get("amount")
        if amount is None and ("randomMinimum" not in outcome or "randomMaximum" not in outcome):
            errors.append(_issue("error", "modifyResource requires amount or a random range.", source, path))

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
        if "encounterLayout" in encounter:
            _validate_encounter_layout(encounter.get("encounterLayout"), source, "encounterLayout", errors)
        if "hiddenSlots" in encounter:
            _validate_hidden_slots(encounter.get("hiddenSlots"), source, "hiddenSlots", errors)
        minimum = encounter.get("minimumDistance")
        maximum = encounter.get("maximumDistance")
        if minimum is not None and not isinstance(minimum, (int, float)):
            errors.append(_issue("error", "minimumDistance must be numeric.", source, "minimumDistance"))
        if maximum is not None and not isinstance(maximum, (int, float)):
            errors.append(_issue("error", "maximumDistance must be numeric.", source, "maximumDistance"))
        if isinstance(minimum, (int, float)) and isinstance(maximum, (int, float)) and minimum > maximum:
            errors.append(_issue("error", "minimumDistance cannot be greater than maximumDistance.", source, "maximumDistance"))
        _validate_requirements(encounter.get("requirements"), source, "requirements", errors)
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
                if "visualOverride" in stage:
                    _validate_visual_override(stage.get("visualOverride"), known, source, f"{stage_path}.visualOverride", errors)
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
                        if "visualOverride" in choice:
                            _validate_visual_override(choice.get("visualOverride"), known, source, f"{choice_path}.visualOverride", errors)
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
            if "visualOverride" in stage:
                _validate_visual_override(stage.get("visualOverride"), known, source, f"{stage_path}.visualOverride", errors)
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
                if "visualOverride" in choice:
                    _validate_visual_override(choice.get("visualOverride"), known, source, f"{choice_path}.visualOverride", errors)
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
        if "provisionsForSale" in shop:
            provision_offer = shop.get("provisionsForSale")
            if not isinstance(provision_offer, dict):
                errors.append(_issue("error", "provisionsForSale must be an object when provision purchasing is enabled.", source, "provisionsForSale"))
            else:
                price = provision_offer.get("price")
                if not _is_number(price) or price < 0:
                    errors.append(_issue("error", "Provision buy price must be a non-negative number.", source, "provisionsForSale.price"))
                stock = provision_offer.get("stock")
                if not _is_number(stock) or not isinstance(stock, int) or stock < 0:
                    errors.append(_issue("error", "Provision stock must be a non-negative integer.", source, "provisionsForSale.stock"))
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


def _validate_combat_statuses(statuses: Any, errors: list[dict[str, str]]) -> None:
    if not isinstance(statuses, dict):
        errors.append(_issue("error", "Combat status definitions must be an object.", "combatStatuses"))
        return
    for entry_id, status in statuses.items():
        source = f"combatStatus:{entry_id}"
        if not isinstance(status, dict):
            errors.append(_issue("error", "Combat status must be an object.", source))
            continue
        if status.get("id") != entry_id:
            errors.append(_issue("error", f"Definition key {entry_id!r} does not match its id field.", source, "id"))
        for field_name in ("name", "description"):
            if not isinstance(status.get(field_name), str) or not status.get(field_name):
                errors.append(_issue("error", f"Combat status {field_name} is required.", source, field_name))
        periodic_damage = status.get("periodicDamage")
        if not _is_number(periodic_damage) or periodic_damage < 0:
            errors.append(_issue("error", "periodicDamage must be a non-negative number.", source, "periodicDamage"))
        duration = status.get("durationActivations")
        if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
            errors.append(_issue("error", "durationActivations must be a positive integer.", source, "durationActivations"))
        if status.get("refreshBehavior") not in ("refresh",):
            errors.append(_issue("error", "refreshBehavior must be 'refresh'.", source, "refreshBehavior"))


EQUIPMENT_TRIGGER_EVENTS = {
    "combatStart", "actorReady", "turnStart", "beforeAction", "actionUsed", "beforeDamage",
    "damageDealt", "damageTaken", "damagePrevented", "afterDamage", "attackHit", "turnEnd",
    "actorDefeated", "enemyDefeated", "allyDefeated", "combatVictory", "combatDefeat",
    "combatFled", "combatEnd",
}
EQUIPMENT_TRIGGER_EFFECTS = {"applyStatus", "dealDamage", "modifyGauge", "randomChance"}
EQUIPMENT_EFFECT_TARGETS = {"target", "self", "eventSource"}
LEGACY_EQUIPMENT_TRIGGERS = {"defendDamagePrevented", "beforeNormalAttack"}
LEGACY_EQUIPMENT_TRIGGER_EFFECTS = {"storeCharge", "consumeChargeForBonusDamage"}


def _validate_equipment_trigger_conditions(
    conditions: Any, source: str, path: str, known: dict[str, list[str]], errors: list[dict[str, str]],
) -> None:
    if conditions is None:
        return
    if isinstance(conditions, list):
        for index, condition in enumerate(conditions):
            _validate_equipment_trigger_conditions(condition, source, f"{path}[{index}]", known, errors)
        return
    if not isinstance(conditions, dict):
        errors.append(_issue("error", "Combat trigger conditions must be objects or arrays.", source, path))
        return
    for combinator in ("all", "any"):
        if combinator in conditions:
            value = conditions[combinator]
            if not isinstance(value, list) or not value:
                errors.append(_issue("error", f"Condition {combinator} must be a non-empty array.", source, f"{path}.{combinator}"))
            else:
                for index, child in enumerate(value):
                    _validate_equipment_trigger_conditions(child, source, f"{path}.{combinator}[{index}]", known, errors)
    if "event" in conditions and (
        not isinstance(conditions["event"], str) or conditions["event"] not in EQUIPMENT_TRIGGER_EVENTS
    ):
        errors.append(_issue("error", f"Unknown combat event {conditions['event']!r}.", source, f"{path}.event"))
    for field_name in ("sourceSide", "targetSide"):
        if field_name in conditions and (
            not isinstance(conditions[field_name], str) or conditions[field_name] not in {"ally", "enemy"}
        ):
            errors.append(_issue("error", f"{field_name} must be ally or enemy.", source, f"{path}.{field_name}"))
    for field_name in ("healthBelowPercent", "healthAbovePercent", "targetHealthBelowPercent", "targetHealthAbovePercent", "chance"):
        if field_name in conditions and (
            not _is_number(conditions[field_name])
            or not math.isfinite(float(conditions[field_name]))
            or not 0 <= conditions[field_name] <= 1
        ):
            errors.append(_issue("error", f"Combat condition {field_name} must be between 0 and 1.", source, f"{path}.{field_name}"))
    for field_name in ("actionId", "event"):
        if field_name in conditions and not isinstance(conditions[field_name], str):
            errors.append(_issue("error", f"Combat condition {field_name} must be a string.", source, f"{path}.{field_name}"))
    for field_name in ("firstUse", "oncePerCombat"):
        if field_name in conditions and not isinstance(conditions[field_name], bool):
            errors.append(_issue("error", f"Combat condition {field_name} must be boolean.", source, f"{path}.{field_name}"))
    for field_name in ("hasStatus", "missingStatus"):
        if field_name in conditions:
            statuses = conditions[field_name] if isinstance(conditions[field_name], list) else [conditions[field_name]]
            for index, status_id in enumerate(statuses):
                if not isinstance(status_id, str) or status_id not in set(known.get("combatStatuses", [])):
                    errors.append(_issue("error", f"Combat condition {field_name} needs a known statusId.", source, f"{path}.{field_name}[{index}]"))


def _validate_equipment_trigger_effects(
    effects: Any, source: str, path: str, known: dict[str, list[str]], errors: list[dict[str, str]],
) -> None:
    if not isinstance(effects, list):
        errors.append(_issue("error", "Combat trigger effects must be an array.", source, path))
        return
    known_statuses = set(known.get("combatStatuses", []))
    for index, effect in enumerate(effects):
        effect_path = f"{path}[{index}]"
        if not isinstance(effect, dict):
            errors.append(_issue("error", "Combat trigger effects must be objects.", source, effect_path))
            continue
        effect_type = effect.get("type")
        if not isinstance(effect_type, str) or effect_type not in EQUIPMENT_TRIGGER_EFFECTS:
            errors.append(_issue("error", f"Unknown equipment combat effect {effect_type!r}.", source, f"{effect_path}.type"))
            continue
        if "target" in effect and (
            not isinstance(effect["target"], str) or effect["target"] not in EQUIPMENT_EFFECT_TARGETS
        ):
            errors.append(_issue("error", f"Invalid equipment combat effect target {effect['target']!r}.", source, f"{effect_path}.target"))
        if effect_type == "applyStatus":
            status_id = effect.get("statusId")
            if not isinstance(status_id, str) or status_id not in known_statuses:
                errors.append(_issue("error", "Reactive applyStatus effects need a known statusId.", source, f"{effect_path}.statusId"))
            if "chance" in effect:
                chance = effect.get("chance")
                if not _is_number(chance) or not math.isfinite(float(chance)) or not 0 <= chance <= 1:
                    errors.append(_issue("error", "Reactive applyStatus chance must be between 0 and 1.", source, f"{effect_path}.chance"))
        elif effect_type == "dealDamage":
            amount = effect.get("amount")
            if not _is_number(amount) or not math.isfinite(float(amount)) or amount < 0:
                errors.append(_issue("error", "Reactive dealDamage amount must be a non-negative number.", source, f"{effect_path}.amount"))
        elif effect_type == "modifyGauge":
            amount = effect.get("amount")
            if not _is_number(amount) or not math.isfinite(float(amount)):
                errors.append(_issue("error", "Reactive modifyGauge amount must be a number.", source, f"{effect_path}.amount"))
        elif effect_type == "randomChance":
            chance = effect.get("chance")
            if not _is_number(chance) or not math.isfinite(float(chance)) or not 0 <= chance <= 1:
                errors.append(_issue("error", "Reactive randomChance effects need a chance between 0 and 1.", source, f"{effect_path}.chance"))
            _validate_equipment_trigger_effects(effect.get("effects"), source, f"{effect_path}.effects", known, errors)
            if "elseEffects" in effect:
                _validate_equipment_trigger_effects(effect.get("elseEffects"), source, f"{effect_path}.elseEffects", known, errors)


def _validate_equipment_triggers(
    triggers: Any, known: dict[str, list[str]], source: str, path: str, errors: list[dict[str, str]],
) -> None:
    if not isinstance(triggers, list):
        errors.append(_issue("error", "combatTriggers must be an array.", source, path))
        return
    for index, trigger in enumerate(triggers):
        trigger_path = f"{path}[{index}]"
        if not isinstance(trigger, dict):
            errors.append(_issue("error", "Combat triggers must be objects.", source, trigger_path))
            continue
        trigger_definition = trigger.get("trigger")
        if isinstance(trigger_definition, dict):
            event = trigger_definition.get("event")
            if not isinstance(event, str) or not event:
                errors.append(_issue("error", "Generic combat triggers require a trigger event.", source, f"{trigger_path}.trigger.event"))
            elif event not in EQUIPMENT_TRIGGER_EVENTS:
                errors.append(_issue("error", f"Unknown combat trigger event {event!r}.", source, f"{trigger_path}.trigger.event"))
            _validate_equipment_trigger_conditions(
                trigger_definition.get("conditions"), source, f"{trigger_path}.trigger.conditions", known, errors,
            )
            if "oncePerCombat" in trigger_definition and not isinstance(trigger_definition["oncePerCombat"], bool):
                errors.append(_issue("error", "Combat trigger oncePerCombat must be boolean.", source, f"{trigger_path}.trigger.oncePerCombat"))
            _validate_equipment_trigger_effects(trigger.get("effects"), source, f"{trigger_path}.effects", known, errors)
            continue
        trigger_id = trigger_definition
        if not isinstance(trigger_id, str) or trigger_id not in LEGACY_EQUIPMENT_TRIGGERS:
            errors.append(_issue("error", f"Unknown combat trigger {trigger_id!r}.", source, f"{trigger_path}.trigger"))
        effect_id = trigger.get("effect")
        if not isinstance(effect_id, str) or effect_id not in LEGACY_EQUIPMENT_TRIGGER_EFFECTS:
            errors.append(_issue("error", f"Unknown combat trigger effect {effect_id!r}.", source, f"{trigger_path}.effect"))
        charge_id = trigger.get("chargeId")
        if not isinstance(charge_id, str) or not charge_id:
            errors.append(_issue("error", "Combat triggers need a chargeId.", source, f"{trigger_path}.chargeId"))
        if effect_id == "storeCharge":
            cap = trigger.get("cap")
            if not _is_number(cap) or cap < 0:
                errors.append(_issue("error", "storeCharge triggers need a non-negative cap.", source, f"{trigger_path}.cap"))


def _validate_items(items: Any, known: dict[str, list[str]], errors: list[dict[str, str]]) -> None:
    if not isinstance(items, dict):
        errors.append(_issue("error", "Item definitions must be an object.", "items"))
        return
    seen_ids: set[str] = set()
    boolean_fields = (
        "equippable", "carriable", "consumable", "questItem", "campaignItem",
        "unique", "sellable", "protected", "twoHanded",
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
        if item.get("twoHanded") is True and not (
            equippable and category == "weapon" and slot == "weapon"
        ):
            errors.append(_issue("error", "twoHanded can only be true on an equippable weapon.", source, "twoHanded"))
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
        speed = effects.get("combatSpeed")
        if speed is not None and not _is_number(speed):
            errors.append(_issue("error", "combatSpeed must be numeric.", source, "effects.combatSpeed"))
        on_hit_effects = effects.get("onHitEffects")
        if on_hit_effects is not None:
            if not isinstance(on_hit_effects, list):
                errors.append(_issue("error", "onHitEffects must be an array.", source, "effects.onHitEffects"))
            else:
                known_statuses = set(known.get("combatStatuses", []))
                for index, effect in enumerate(on_hit_effects):
                    path = f"effects.onHitEffects[{index}]"
                    if not isinstance(effect, dict):
                        errors.append(_issue("error", "On-hit effects must be objects.", source, path))
                        continue
                    if effect.get("type") != "applyStatus":
                        errors.append(_issue("error", "On-hit effect type must be 'applyStatus'.", source, f"{path}.type"))
                    status_id = effect.get("statusId")
                    if not isinstance(status_id, str) or not status_id:
                        errors.append(_issue("error", "On-hit effects need a statusId.", source, f"{path}.statusId"))
                    elif status_id not in known_statuses:
                        errors.append(_issue("error", f"Unknown combat status ID {status_id!r}.", source, f"{path}.statusId"))
                    chance = effect.get("chance")
                    if not _is_number(chance) or not 0 <= chance <= 1:
                        errors.append(_issue("error", "On-hit chance must be a number from 0 to 1.", source, f"{path}.chance"))
        combat_triggers = effects.get("combatTriggers")
        if combat_triggers is not None:
            _validate_equipment_triggers(combat_triggers, known, source, "effects.combatTriggers", errors)
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
        _validate_loot_sources(
            combat.get("victoryLootSources"),
            known,
            source,
            "victoryLootSources",
            errors,
            "Combat victoryLootSources",
        )


CHARACTER_VISUAL_SLOTS = ("idle", "walk", "attack")


def _validate_character_asset_fields(definition: Any, known: dict[str, list[str]], source: str, errors: list[dict[str, str]], fields: tuple[str, ...] = ("portraitAssetId", "combatVisualAssetId", "visualAssetId")) -> None:
    if not isinstance(definition, dict):
        return
    known_assets = set(known.get("imageAssets", []))
    for field_name in fields:
        if field_name not in definition or definition[field_name] is None:
            continue
        value = definition[field_name]
        if not isinstance(value, str) or not value:
            errors.append(_issue("error", f"{field_name} must be a non-empty image asset ID or null.", source, field_name))
        elif value not in known_assets:
            errors.append(_issue("error", f"Unknown image asset ID {value!r}.", source, field_name))


def _validate_character_visuals(definition: Any, known: dict[str, list[str]], source: str, errors: list[dict[str, str]]) -> None:
    if not isinstance(definition, dict) or "visuals" not in definition or definition.get("visuals") is None:
        return
    visuals = definition.get("visuals")
    if not isinstance(visuals, dict):
        errors.append(_issue("error", "visuals must be an object or null.", source, "visuals"))
        return
    known_assets = set(known.get("imageAssets", []))
    for slot, visual in visuals.items():
        path = f"visuals.{slot}"
        if slot not in CHARACTER_VISUAL_SLOTS:
            errors.append(_issue("error", f"Unknown character visual slot {slot!r}.", source, path))
            continue
        if visual is None:
            continue
        if not isinstance(visual, dict):
            errors.append(_issue("error", "Character visual slots must be objects or null.", source, path))
            continue
        if "assetId" in visual:
            asset_id = visual.get("assetId")
            if asset_id is not None and (not isinstance(asset_id, str) or not asset_id):
                errors.append(_issue("error", "Character visual assetId must be a non-empty image asset ID or null.", source, f"{path}.assetId"))
            elif isinstance(asset_id, str) and asset_id not in known_assets:
                errors.append(_issue("error", f"Unknown image asset ID {asset_id!r}.", source, f"{path}.assetId"))
            elif isinstance(asset_id, str):
                category = (known.get("imageAssetCategories") or {}).get(asset_id)
                if category != "combat":
                    errors.append(_issue("error", f"Character visual asset {asset_id!r} must use the combat image category.", source, f"{path}.assetId"))
        if "frameCount" in visual and (not isinstance(visual.get("frameCount"), int) or isinstance(visual.get("frameCount"), bool) or visual.get("frameCount") <= 0):
            errors.append(_issue("error", "Character visual frameCount must be a positive integer.", source, f"{path}.frameCount"))
        frame_count = visual.get("frameCount") if isinstance(visual.get("frameCount"), int) and not isinstance(visual.get("frameCount"), bool) and visual.get("frameCount") > 0 else 1
        if "impactFrame" in visual and (
            not isinstance(visual.get("impactFrame"), int)
            or isinstance(visual.get("impactFrame"), bool)
            or not 0 <= visual.get("impactFrame") < frame_count
        ):
            errors.append(_issue("error", "Character visual impactFrame must be an integer from 0 through frameCount - 1.", source, f"{path}.impactFrame"))
        if "columns" in visual and (not isinstance(visual.get("columns"), int) or isinstance(visual.get("columns"), bool) or visual.get("columns") <= 0):
            errors.append(_issue("error", "Character visual columns must be a positive integer.", source, f"{path}.columns"))
        elif "columns" in visual and isinstance(visual.get("frameCount"), int) and not isinstance(visual.get("frameCount"), bool) and visual["columns"] > visual["frameCount"]:
            errors.append(_issue("error", "Character visual columns cannot exceed frameCount.", source, f"{path}.columns"))
        if "fps" in visual and (not _is_number(visual.get("fps")) or visual.get("fps") < 0):
            errors.append(_issue("error", "Character visual fps must be a non-negative number.", source, f"{path}.fps"))
        if "scale" in visual and visual.get("scale") is not None and (not _is_number(visual.get("scale")) or not 0.25 <= visual.get("scale") <= 3):
            errors.append(_issue("error", "Character visual scale must be a number from 0.25 to 3.", source, f"{path}.scale"))
        for offset in ("offsetX", "offsetY"):
            if offset in visual and visual.get(offset) is not None and not _is_number(visual.get(offset)):
                errors.append(_issue("error", f"Character visual {offset} must be a finite number in normalized pixels.", source, f"{path}.{offset}"))


def _validate_character_scale(definition: Any, source: str, errors: list[dict[str, str]]) -> None:
    if not isinstance(definition, dict):
        return
    for field_name in ("visualScale", "combatVisualScale"):
        if field_name not in definition or definition.get(field_name) is None:
            continue
        scale = definition.get(field_name)
        if not _is_number(scale) or not 0.25 <= scale <= 3:
            errors.append(_issue("error", f"{field_name} must be a number from 0.25 to 3.", source, field_name))
    if "travelOffsetY" in definition and definition.get("travelOffsetY") is not None and not _is_number(definition.get("travelOffsetY")):
        errors.append(_issue("error", "travelOffsetY must be a finite number.", source, "travelOffsetY"))


def _validate_player_character(player: Any, known: dict[str, list[str]], errors: list[dict[str, str]]) -> None:
    source = "playerCharacter"
    if not isinstance(player, dict):
        errors.append(_issue("error", "Player character definition must be an object.", source))
        return
    if player.get("id") != "arthur":
        errors.append(_issue("error", "Player character id must be 'arthur'.", source, "id"))
    if not isinstance(player.get("name"), str) or not player.get("name"):
        errors.append(_issue("error", "Player character name is required.", source, "name"))
    for field_name in ("provisionCapacity", "provisionConsumptionMultiplier"):
        if field_name in player and (not _is_number(player[field_name]) or player[field_name] < 0):
            errors.append(_issue("error", f"Player character {field_name} must be a non-negative number.", source, field_name))
    combat = player.get("combat")
    if not isinstance(combat, dict):
        errors.append(_issue("error", "Player character combat must be an object.", source, "combat"))
    else:
        for field_name in ("maxHp", "speed"):
            if not _is_number(combat.get(field_name)) or combat[field_name] <= 0:
                errors.append(_issue("error", f"Player combat {field_name} must be a positive number.", source, f"combat.{field_name}"))
    _validate_character_asset_fields(player, known, source, errors, ("portraitAssetId", "combatVisualAssetId"))
    _validate_character_visuals(player, known, source, errors)
    _validate_character_scale(player, source, errors)


def _validate_starting_state(starting_state: Any, known: dict[str, list[str]], errors: list[dict[str, str]], items: Any = None) -> None:
    source = "startingState"
    if not isinstance(starting_state, dict):
        errors.append(_issue("error", "Starting player state must be an object.", source))
        return

    def non_negative_number(field_name: str, integer: bool = False) -> None:
        value = starting_state.get(field_name)
        valid = isinstance(value, int) and not isinstance(value, bool) if integer else _is_number(value)
        if not valid or value < 0:
            kind = "non-negative integer" if integer else "non-negative number"
            errors.append(_issue("error", f"Starting state {field_name} must be a {kind}.", source, field_name))

    for field_name in ("faith", "maxFaith", "currentGold", "provisions", "bestExpeditionDistance"):
        non_negative_number(field_name, field_name == "bestExpeditionDistance")
    if _is_number(starting_state.get("faith")) and _is_number(starting_state.get("maxFaith")) and starting_state["faith"] > starting_state["maxFaith"]:
        errors.append(_issue("error", "Starting state faith cannot exceed maxFaith.", source, "faith"))

    item_ids = set(known.get("items", [])) - set(known.get("materials", []))
    material_ids = set(known.get("materials", []))
    item_map = _id_map(items)

    def validate_quantity_map(field_name: str, valid_ids: set[str], label: str) -> None:
        values = starting_state.get(field_name)
        if not isinstance(values, dict):
            errors.append(_issue("error", f"Starting state {field_name} must be an object of {label} quantities.", source, field_name))
            return
        for entry_id, quantity in values.items():
            if entry_id not in valid_ids:
                errors.append(_issue("error", f"Starting state {field_name} references unknown {label} ID {entry_id!r}.", source, f"{field_name}.{entry_id}"))
            if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
                errors.append(_issue("error", f"Starting state {field_name} quantities must be positive integers.", source, f"{field_name}.{entry_id}"))

    validate_quantity_map("ownedItems", item_ids, "item")
    validate_quantity_map("materials", material_ids, "material")
    validate_quantity_map("packedMaterials", material_ids, "material")

    equipped = starting_state.get("equippedItems")
    if not isinstance(equipped, dict):
        errors.append(_issue("error", "Starting state equippedItems must be an object.", source, "equippedItems"))
    else:
        for slot, item_id in equipped.items():
            if slot not in set(known.get("equipmentSlots", [])):
                errors.append(_issue("error", f"Starting state equippedItems has unknown slot {slot!r}.", source, f"equippedItems.{slot}"))
            if not isinstance(item_id, str) or item_id not in item_ids:
                errors.append(_issue("error", "Starting state equipped items must reference known non-material item IDs.", source, f"equippedItems.{slot}"))
            elif not isinstance(starting_state.get("ownedItems"), dict) or starting_state["ownedItems"].get(item_id, 0) <= 0:
                errors.append(_issue("error", f"Starting state equipped item {item_id!r} must also be owned.", source, f"equippedItems.{slot}"))
            elif isinstance(item_map.get(item_id), dict) and item_map[item_id].get("equipmentSlot") != slot:
                errors.append(_issue("error", f"Starting state equipped item {item_id!r} does not fit the {slot} slot.", source, f"equippedItems.{slot}"))

    packed_items = starting_state.get("packedItems")
    if not isinstance(packed_items, list) or not all(isinstance(item_id, str) for item_id in packed_items):
        errors.append(_issue("error", "Starting state packedItems must be an array of item IDs.", source, "packedItems"))
    else:
        if len(packed_items) != len(set(packed_items)):
            errors.append(_issue("error", "Starting state packedItems cannot contain duplicates.", source, "packedItems"))
        for index, item_id in enumerate(packed_items):
            if item_id not in item_ids:
                errors.append(_issue("error", f"Starting state packedItems references unknown item ID {item_id!r}.", source, f"packedItems[{index}]"))
            elif not isinstance(starting_state.get("ownedItems"), dict) or starting_state["ownedItems"].get(item_id, 0) <= 0:
                errors.append(_issue("error", f"Starting state packed item {item_id!r} must also be owned.", source, f"packedItems[{index}]"))
            elif isinstance(item_map.get(item_id), dict) and item_map[item_id].get("carriable") is not True:
                errors.append(_issue("error", f"Starting state packed item {item_id!r} is not carriable.", source, f"packedItems[{index}]"))
            elif item_id in set((starting_state.get("equippedItems") or {}).values()):
                errors.append(_issue("error", f"Starting state packed item {item_id!r} is already equipped.", source, f"packedItems[{index}]"))

    def validate_id_list(field_name: str, known_key: str, label: str) -> None:
        values = starting_state.get(field_name)
        if not isinstance(values, list) or not all(isinstance(value, str) and value for value in values):
            errors.append(_issue("error", f"Starting state {field_name} must be an array of {label} IDs.", source, field_name))
            return
        if len(values) != len(set(values)):
            errors.append(_issue("error", f"Starting state {field_name} cannot contain duplicates.", source, field_name))
        valid_ids = set(known.get(known_key, []))
        for index, value in enumerate(values):
            if value not in valid_ids:
                errors.append(_issue("error", f"Starting state {field_name} references unknown {label} ID {value!r}.", source, f"{field_name}[{index}]"))

    validate_id_list("learnedAbilityIds", "abilities", "ability")
    validate_id_list("selectedActiveAbilityIds", "abilities", "ability")
    validate_id_list("selectedPassiveAbilityIds", "abilities", "ability")
    learned_abilities = set(starting_state.get("learnedAbilityIds", []))
    for field_name in ("selectedActiveAbilityIds", "selectedPassiveAbilityIds"):
        for index, ability_id in enumerate(starting_state.get(field_name, [])):
            if ability_id not in learned_abilities:
                errors.append(_issue("error", f"Starting state {field_name} must contain only learned abilities.", source, f"{field_name}[{index}]"))
    validate_id_list("learnedRecipes", "recipes", "recipe")
    validate_id_list("unlockedCompanions", "companions", "companion")
    validate_id_list("selectedCompanions", "companions", "companion")
    unlocked_companions = set(starting_state.get("unlockedCompanions", []))
    for index, companion_id in enumerate(starting_state.get("selectedCompanions", [])):
        if companion_id not in unlocked_companions:
            errors.append(_issue("error", "Starting state selectedCompanions must contain only unlocked companions.", source, f"selectedCompanions[{index}]"))
    selected_companion = starting_state.get("selectedCompanion")
    if selected_companion is not None and (not isinstance(selected_companion, str) or selected_companion not in unlocked_companions):
        errors.append(_issue("error", "Starting state selectedCompanion must be an unlocked companion ID.", source, "selectedCompanion"))
    validate_id_list("learnedKnowledge", "knowledge", "knowledge")

    for field_name, known_key, label in (("selectedExpeditionId", "expeditions", "expedition"), ("currentLocationId", "locations", "location")):
        value = starting_state.get(field_name)
        if not isinstance(value, str) or value not in set(known.get(known_key, [])):
            errors.append(_issue("error", f"Starting state {field_name} must reference a known {label} ID.", source, field_name))
    campaign_flags = starting_state.get("campaignFlags")
    if not isinstance(campaign_flags, dict) or not all(isinstance(value, bool) for value in campaign_flags.values()):
        errors.append(_issue("error", "Starting state campaignFlags must be an object of booleans.", source, "campaignFlags"))
    chapters = starting_state.get("completedChapters")
    if not isinstance(chapters, list) or not all(isinstance(value, str) and value for value in chapters):
        errors.append(_issue("error", "Starting state completedChapters must be an array of strings.", source, "completedChapters"))


def _validate_companions(companions: Any, known: dict[str, list[str]], errors: list[dict[str, str]]) -> None:
    if not isinstance(companions, dict):
        errors.append(_issue("error", "Companion definitions must be an object.", "companions"))
        return
    for entry_id, companion in companions.items():
        source = f"companion:{entry_id}"
        if not isinstance(companion, dict):
            errors.append(_issue("error", "Companion must be an object.", source))
            continue
        if companion.get("id") != entry_id:
            errors.append(_issue("error", f"Definition key {entry_id!r} does not match its id field.", source, "id"))
        for field_name in ("name", "description", "type"):
            if not isinstance(companion.get(field_name), str):
                errors.append(_issue("error", f"Companion {field_name} must be a string.", source, field_name))
        if "tags" in companion and (not isinstance(companion["tags"], list) or not all(isinstance(tag, str) for tag in companion["tags"])):
            errors.append(_issue("error", "Companion tags must be an array of strings.", source, "tags"))
        for field_name in ("provisionCapacityBonus", "provisionConsumptionBonus", "travelSpeedMultiplier"):
            if field_name in companion and (not _is_number(companion[field_name]) or companion[field_name] < 0):
                errors.append(_issue("error", f"Companion {field_name} must be a non-negative number.", source, field_name))
        capabilities = companion.get("capabilities")
        if capabilities is not None and (not isinstance(capabilities, dict) or not all(isinstance(value, bool) for value in capabilities.values())):
            errors.append(_issue("error", "Companion capabilities must be an object of booleans.", source, "capabilities"))
        combat = companion.get("combat")
        if not isinstance(combat, dict):
            errors.append(_issue("error", "Companion combat must be an object.", source, "combat"))
        else:
            for field_name in ("maxHp", "speed"):
                if not _is_number(combat.get(field_name)) or combat[field_name] <= 0:
                    errors.append(_issue("error", f"Companion combat {field_name} must be a positive number.", source, f"combat.{field_name}"))
            if "defense" in combat and (not _is_number(combat["defense"]) or combat["defense"] < 0):
                errors.append(_issue("error", "Companion combat defense must be non-negative.", source, "combat.defense"))
            damage = combat.get("basicDamage")
            if damage is not None and (not isinstance(damage, dict) or not _is_number(damage.get("minimum")) or not _is_number(damage.get("maximum")) or damage["minimum"] < 0 or damage["maximum"] < damage["minimum"]):
                errors.append(_issue("error", "Companion basicDamage must have non-negative minimum and maximum values.", source, "combat.basicDamage"))
        if "combatAbilities" in companion and (not isinstance(companion["combatAbilities"], list) or not all(isinstance(ability_id, str) for ability_id in companion["combatAbilities"])):
            errors.append(_issue("error", "Companion combatAbilities must be an array of ability IDs.", source, "combatAbilities"))
        if "noPermanentDeath" in companion and not isinstance(companion["noPermanentDeath"], bool):
            errors.append(_issue("error", "Companion noPermanentDeath must be boolean.", source, "noPermanentDeath"))
        _validate_character_asset_fields(companion, known, source, errors, ("portraitAssetId", "combatVisualAssetId", "visualAssetId"))
        _validate_character_visuals(companion, known, source, errors)
        _validate_character_scale(companion, source, errors)


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
        _validate_loot_sources(enemy.get("lootSources"), known, source, "lootSources", errors, "Enemy lootSources")
        _validate_character_asset_fields(enemy, known, source, errors)
        _validate_character_visuals(enemy, known, source, errors)
        _validate_character_scale(enemy, source, errors)
        traits = enemy.get("traits", [])
        if not isinstance(traits, list):
            errors.append(_issue("error", "Enemy traits must be an array.", source, "traits"))
        else:
            known_statuses = set(known.get("combatStatuses", []))
            for index, trait in enumerate(traits):
                path = f"traits[{index}]"
                if not isinstance(trait, dict):
                    errors.append(_issue("error", "Enemy traits must be objects.", source, path))
                    continue
                if trait.get("type") != "regeneration":
                    errors.append(_issue("error", "Enemy trait type must be 'regeneration'.", source, f"{path}.type"))
                if not _is_number(trait.get("amount")) or trait.get("amount") < 0:
                    errors.append(_issue("error", "Regeneration amount must be a non-negative number.", source, f"{path}.amount"))
                if trait.get("trigger") != "activation":
                    errors.append(_issue("error", "Enemy trait trigger must be 'activation'.", source, f"{path}.trigger"))
                suppressed = trait.get("suppressedByStatuses", [])
                if not isinstance(suppressed, list) or not all(isinstance(status_id, str) and status_id for status_id in suppressed):
                    errors.append(_issue("error", "suppressedByStatuses must be an array of status IDs.", source, f"{path}.suppressedByStatuses"))
                else:
                    for status_index, status_id in enumerate(suppressed):
                        if status_id not in known_statuses:
                            errors.append(_issue("error", f"Unknown combat status ID {status_id!r}.", source, f"{path}.suppressedByStatuses[{status_index}]"))


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
        if "telegraphed" in action and not isinstance(action.get("telegraphed"), bool):
            errors.append(_issue("error", "Enemy action telegraphed must be boolean.", source, "telegraphed"))


def _validate_abilities(abilities: Any, known: dict[str, list[str]], errors: list[dict[str, str]]) -> None:
    if not isinstance(abilities, dict):
        errors.append(_issue("error", "Combat ability definitions must be an object.", "abilities"))
        return
    allowed_targets = {"enemy", "ally", "self", "menu", "none"}
    allowed_target_modes = {"self", "singleEnemy", "singleAlly", "allEnemies", "allAllies", "none"}
    allowed_kinds = {"active", "passive"}
    allowed_effects = {
        "dealDamage", "weaponDamage", "heal", "modifyGauge", "applyStatus", "removeStatus",
        "modifyStat", "modifyResource", "storeCharge", "consumeCharge", "conditional",
        "randomChance", "setDefending", "setFlag", "attemptFlee", "applyInjury",
    }
    known_statuses = set(known.get("combatStatuses", []))
    allowed_events = {
        "combatStart", "actorReady", "turnStart", "beforeAction", "actionUsed",
        "beforeDamage", "damageDealt", "damageTaken", "damagePrevented", "afterDamage",
        "attackHit", "turnEnd", "actorDefeated", "enemyDefeated", "allyDefeated",
        "combatVictory", "combatDefeat", "combatFled", "combatEnd",
    }

    def validate_conditions(conditions: Any, source: str, path: str) -> None:
        if conditions is None:
            return
        if isinstance(conditions, list):
            for index, condition in enumerate(conditions):
                validate_conditions(condition, source, f"{path}[{index}]")
            return
        if not isinstance(conditions, dict):
            errors.append(_issue("error", "Combat conditions must be objects or arrays.", source, path))
            return
        for combinator in ("all", "any"):
            if combinator in conditions:
                value = conditions[combinator]
                if not isinstance(value, list) or not value:
                    errors.append(_issue("error", f"Condition {combinator} must be a non-empty array.", source, f"{path}.{combinator}"))
                else:
                    for index, child in enumerate(value):
                        validate_conditions(child, source, f"{path}.{combinator}[{index}]")
        if "event" in conditions and (not isinstance(conditions["event"], str) or conditions["event"] not in allowed_events):
            errors.append(_issue("error", f"Unknown combat event {conditions['event']!r}.", source, f"{path}.event"))
        for field_name in ("sourceSide", "targetSide"):
            if field_name in conditions and (not isinstance(conditions[field_name], str) or conditions[field_name] not in {"ally", "enemy"}):
                errors.append(_issue("error", f"{field_name} must be ally or enemy.", source, f"{path}.{field_name}"))
        for field_name in ("healthBelowPercent", "healthAbovePercent", "targetHealthBelowPercent", "targetHealthAbovePercent", "chance"):
            if field_name in conditions and (not _is_number(conditions[field_name]) or not 0 <= conditions[field_name] <= 1):
                errors.append(_issue("error", f"Combat condition {field_name} must be between 0 and 1.", source, f"{path}.{field_name}"))
        for field_name in ("actionId", "event"):
            if field_name in conditions and not isinstance(conditions[field_name], str):
                errors.append(_issue("error", f"Combat condition {field_name} must be a string.", source, f"{path}.{field_name}"))
        for field_name in ("firstUse", "oncePerCombat"):
            if field_name in conditions and not isinstance(conditions[field_name], bool):
                errors.append(_issue("error", f"Combat condition {field_name} must be boolean.", source, f"{path}.{field_name}"))
        for field_name in ("hasStatus", "missingStatus"):
            if field_name in conditions:
                statuses = conditions[field_name] if isinstance(conditions[field_name], list) else [conditions[field_name]]
                for index, status_id in enumerate(statuses):
                    if not isinstance(status_id, str) or status_id not in known_statuses:
                        errors.append(_issue("error", f"Combat condition {field_name} needs a known statusId.", source, f"{path}.{field_name}[{index}]"))

    def validate_effects(effects: Any, source: str, path: str) -> None:
        if not isinstance(effects, list):
            errors.append(_issue("error", "Ability effects must be an array.", source, path))
            return
        for index, effect in enumerate(effects):
            effect_path = f"{path}[{index}]"
            if not isinstance(effect, dict):
                errors.append(_issue("error", "Ability effects must be objects.", source, effect_path))
                continue
            effect_type = effect.get("type")
            if effect_type not in allowed_effects:
                errors.append(_issue("error", f"Unknown combat effect {effect_type!r}.", source, f"{effect_path}.type"))
            if effect_type in {"applyStatus", "removeStatus"}:
                status_id = effect.get("statusId")
                if not isinstance(status_id, str) or status_id not in known_statuses:
                    errors.append(_issue("error", "Combat status effects need a known statusId.", source, f"{effect_path}.statusId"))
            if effect_type == "modifyResource":
                if not isinstance(effect.get("resource"), str) or not effect.get("resource"):
                    errors.append(_issue("error", "modifyResource effects need a resource.", source, f"{effect_path}.resource"))
            if effect_type == "applyInjury":
                injury_id = effect.get("injuryId")
                if not isinstance(injury_id, str) or injury_id not in set(known.get("injuries", [])):
                    errors.append(_issue("error", "applyInjury effects need a known injuryId.", source, f"{effect_path}.injuryId"))
            if effect_type == "modifyResource" and not isinstance(effect.get("resource"), str):
                errors.append(_issue("error", "modifyResource effects need a string resource.", source, f"{effect_path}.resource"))
            for field_name in ("amount", "multiplier", "cap"):
                value = effect.get(field_name)
                minimum = 0 if field_name in {"multiplier", "cap"} or effect_type in {"dealDamage", "heal"} else None
                if field_name in effect and value != "damagePrevented" and (not _is_number(value) or (minimum is not None and value < minimum)):
                    errors.append(_issue("error", f"Combat effect {field_name} must be a non-negative number.", source, f"{effect_path}.{field_name}"))
            if effect_type == "modifyStat" and (not isinstance(effect.get("stat"), str) or not effect.get("stat")):
                errors.append(_issue("error", "modifyStat effects need a stat name.", source, f"{effect_path}.stat"))
            if effect_type == "setFlag" and (not isinstance(effect.get("flag"), str) or not effect.get("flag")):
                errors.append(_issue("error", "setFlag effects need a flag name.", source, f"{effect_path}.flag"))
            if effect_type in {"storeCharge", "consumeCharge"} and (not isinstance(effect.get("chargeId"), str) or not effect.get("chargeId")):
                errors.append(_issue("error", f"{effect_type} effects need a chargeId.", source, f"{effect_path}.chargeId"))
            for field_name in ("triggersOnHit", "onHit"):
                if field_name in effect and not isinstance(effect.get(field_name), bool):
                    errors.append(_issue("error", f"Combat effect {field_name} must be boolean.", source, f"{effect_path}.{field_name}"))
            chance = effect.get("chance")
            if chance is not None:
                _validate_chance(chance, source, f"{effect_path}.chance", errors)
            if effect_type in {"conditional", "randomChance"}:
                if effect_type == "conditional":
                    validate_conditions(effect.get("condition", effect.get("conditions")), source, f"{effect_path}.condition")
                elif not _is_number(effect.get("chance")) or not 0 <= effect.get("chance") <= 1:
                    errors.append(_issue("error", "randomChance effects need a chance between 0 and 1.", source, f"{effect_path}.chance"))
                validate_effects(effect.get("effects", []), source, f"{effect_path}.effects")
                if "elseEffects" in effect:
                    validate_effects(effect.get("elseEffects"), source, f"{effect_path}.elseEffects")

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
        kind = ability.get("kind", "active")
        if kind not in allowed_kinds:
            errors.append(_issue("error", f"Unknown ability kind {kind!r}.", source, "kind"))
        if not isinstance(ability.get("name"), str) or not ability.get("name"):
            errors.append(_issue("error", "Ability name is required.", source, "name"))
        if kind == "active" and (not isinstance(ability.get("target"), str) or not ability.get("target")):
            errors.append(_issue("error", "Active abilities require a target.", source, "target"))
        if "target" in ability and isinstance(ability.get("target"), str) and ability["target"] not in allowed_targets:
            errors.append(_issue("error", f"Unknown ability target {ability['target']!r}.", source, "target"))
        for field_name in ("damageMultiplier", "gaugeReduction"):
            if field_name in ability and (not _is_number(ability.get(field_name)) or ability[field_name] < 0):
                errors.append(_issue("error", f"Ability {field_name} must be a non-negative number.", source, field_name))
        for field_name in ("description", "selectionPrompt", "effectType", "category"):
            if field_name in ability and not isinstance(ability.get(field_name), str):
                errors.append(_issue("error", f"Ability {field_name} must be a string.", source, field_name))
        for field_name in ("cooldownActivations", "chargesPerCombat"):
            if field_name in ability and (not isinstance(ability.get(field_name), int) or isinstance(ability.get(field_name), bool) or ability[field_name] <= 0):
                errors.append(_issue("error", f"Ability {field_name} must be a positive integer.", source, field_name))
        for field_name in ("triggersOnHit",):
            if field_name in ability and not isinstance(ability.get(field_name), bool):
                errors.append(_issue("error", f"Ability {field_name} must be boolean.", source, field_name))
        if kind == "passive":
            trigger = ability.get("trigger")
            if not isinstance(trigger, dict) or not isinstance(trigger.get("event"), str) or not trigger.get("event"):
                errors.append(_issue("error", "Passive abilities require a trigger event.", source, "trigger.event"))
            elif trigger.get("event") not in allowed_events:
                errors.append(_issue("error", f"Unknown passive trigger event {trigger.get('event')!r}.", source, "trigger.event"))
            if isinstance(trigger, dict):
                validate_conditions(trigger.get("conditions"), source, "trigger.conditions")
                if "effects" in trigger:
                    validate_effects(trigger.get("effects"), source, "trigger.effects")
                if "oncePerCombat" in trigger and not isinstance(trigger.get("oncePerCombat"), bool):
                    errors.append(_issue("error", "Passive trigger oncePerCombat must be boolean.", source, "trigger.oncePerCombat"))
        target_mode = ability.get("targetMode")
        if target_mode is not None and target_mode not in allowed_target_modes:
            errors.append(_issue("error", f"Unknown ability targetMode {target_mode!r}.", source, "targetMode"))
        tags = ability.get("tags")
        if tags is not None and (not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags)):
            errors.append(_issue("error", "Ability tags must be an array of strings.", source, "tags"))
        effects = ability.get("effects")
        if effects is not None:
            validate_effects(effects, source, "effects")
        if "conditions" in ability:
            validate_conditions(ability.get("conditions"), source, "conditions")
        cost = ability.get("cost")
        if cost is not None:
            if not isinstance(cost, dict):
                errors.append(_issue("error", "Ability cost must be an object.", source, "cost"))
            else:
                if not isinstance(cost.get("resource"), str) or not cost.get("resource"):
                    errors.append(_issue("error", "Ability costs need a resource.", source, "cost.resource"))
                if not _is_number(cost.get("amount")) or cost.get("amount") < 0:
                    errors.append(_issue("error", "Ability cost amount must be non-negative.", source, "cost.amount"))


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


def _validate_return_reward_tiers(tiers: Any, known: dict[str, list[str]], errors: list[dict[str, str]]) -> None:
    """Validate the ordered expedition return reward tier array."""
    source = "returnRewards"
    if not isinstance(tiers, list):
        errors.append(_issue("error", "Return reward tiers must be an array.", source))
        return

    table_ids = set(known.get("lootTables", []))
    seen_ids: set[str] = set()
    previous_distance: int | float | None = None
    for index, tier in enumerate(tiers):
        tier_path = f"tiers[{index}]"
        if not isinstance(tier, dict):
            errors.append(_issue("error", "Return reward tier must be an object.", source, tier_path))
            continue

        tier_id = tier.get("id")
        if not isinstance(tier_id, str) or not tier_id:
            errors.append(_issue("error", "Return reward tier ID is required.", source, f"{tier_path}.id"))
        elif tier_id in seen_ids:
            errors.append(_issue("error", f"Duplicate return reward tier ID {tier_id!r}.", source, f"{tier_path}.id"))
        else:
            seen_ids.add(tier_id)

        minimum_distance = tier.get("minimumDistance")
        if not _is_number(minimum_distance) or minimum_distance < 0:
            errors.append(_issue("error", "Return reward minimumDistance must be non-negative.", source, f"{tier_path}.minimumDistance"))
        elif previous_distance is not None and minimum_distance < previous_distance:
            errors.append(_issue("error", "Return reward tiers must be sorted by ascending minimumDistance.", source, f"{tier_path}.minimumDistance"))
        if _is_number(minimum_distance):
            previous_distance = minimum_distance

        sources = tier.get("sources")
        if not isinstance(sources, list):
            errors.append(_issue("error", "Return reward tier sources must be an array.", source, f"{tier_path}.sources"))
            continue
        for source_index, reward_source in enumerate(sources):
            source_path = f"{tier_path}.sources[{source_index}]"
            if not isinstance(reward_source, dict):
                errors.append(_issue("error", "Return reward source must be an object.", source, source_path))
                continue
            table_id = reward_source.get("tableId")
            if not isinstance(table_id, str) or not table_id:
                errors.append(_issue("error", "Return reward source tableId is required.", source, f"{source_path}.tableId"))
            elif table_id not in table_ids:
                errors.append(_issue("error", f"Return reward source references unknown loot table {table_id!r}.", source, f"{source_path}.tableId"))
            rolls = reward_source.get("rolls")
            if not isinstance(rolls, int) or isinstance(rolls, bool) or rolls < 1:
                errors.append(_issue("error", "Return reward source rolls must be a positive integer.", source, f"{source_path}.rolls"))
            if "chance" in reward_source:
                chance = reward_source.get("chance")
                if not _is_number(chance) or not 0 <= chance <= 1:
                    errors.append(_issue("error", "Return reward source chance must be a number from 0 to 1.", source, f"{source_path}.chance"))


def _validate_expedition_cadence(expedition: dict[str, Any], source: str, errors: list[dict[str, str]]) -> None:
    spacing = expedition.get("encounterSpacing")
    if spacing is not None:
        if not isinstance(spacing, dict):
            errors.append(_issue("error", "encounterSpacing must be an object.", source, "encounterSpacing"))
        else:
            for direction in ("outbound", "returning"):
                if direction not in spacing:
                    continue
                direction_path = f"encounterSpacing.{direction}"
                values = spacing[direction]
                if not isinstance(values, dict):
                    errors.append(_issue("error", f"{direction_path} must be an object.", source, direction_path))
                    continue
                valid_distances: dict[str, float] = {}
                for field_name in ("minimumDistance", "maximumDistance"):
                    if field_name not in values:
                        continue
                    value = values[field_name]
                    field_path = f"{direction_path}.{field_name}"
                    if not _is_number(value) or not math.isfinite(float(value)) or value < 0:
                        errors.append(_issue("error", f"{field_path} must be a non-negative number.", source, field_path))
                    else:
                        valid_distances[field_name] = float(value)
                if (
                    "minimumDistance" in valid_distances
                    and "maximumDistance" in valid_distances
                    and valid_distances["maximumDistance"] < valid_distances["minimumDistance"]
                ):
                    errors.append(_issue(
                        "error",
                        f"{direction_path}.maximumDistance must be greater than or equal to minimumDistance.",
                        source,
                        f"{direction_path}.maximumDistance",
                    ))
    if "returnSpeedMultiplier" in expedition:
        value = expedition.get("returnSpeedMultiplier")
        if not _is_number(value) or not math.isfinite(float(value)) or value <= 0:
            errors.append(_issue("error", "returnSpeedMultiplier must be a number greater than 0.", source, "returnSpeedMultiplier"))


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
        if "minimumObjectiveDistance" in expedition:
            objective_distance = expedition.get("minimumObjectiveDistance")
            if not _is_number(objective_distance) or objective_distance < 0:
                errors.append(_issue("error", "minimumObjectiveDistance must be a non-negative number.", source, "minimumObjectiveDistance"))
        _validate_expedition_cadence(expedition, source, errors)
        for field_name, label in (("campEventTableIds", "camp event table IDs"), ("prerequisites", "prerequisites")):
            value = expedition.get(field_name)
            if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
                errors.append(_issue("error", f"Expedition {label} must be an array of IDs.", source, field_name))
        if "travelScenes" in expedition:
            travel_scenes = expedition.get("travelScenes")
            if not isinstance(travel_scenes, list):
                errors.append(_issue("error", "Expedition travelScenes must be an array.", source, "travelScenes"))
            else:
                previous_distance: float | None = None
                seen_distances: set[float] = set()
                for index, scene in enumerate(travel_scenes):
                    scene_path = f"travelScenes[{index}]"
                    if not isinstance(scene, dict):
                        errors.append(_issue("error", "Travel scene must be an object.", source, scene_path))
                        continue
                    min_distance = scene.get("minDistance")
                    if not _is_number(min_distance) or min_distance < 0:
                        errors.append(_issue("error", "Travel scene minDistance must be a non-negative number.", source, f"{scene_path}.minDistance"))
                    else:
                        numeric_distance = float(min_distance)
                        if numeric_distance in seen_distances:
                            errors.append(_issue("error", f"Travel scene minDistance {min_distance!r} is duplicated.", source, f"{scene_path}.minDistance"))
                        seen_distances.add(numeric_distance)
                        if previous_distance is not None and numeric_distance < previous_distance:
                            errors.append(_issue("error", "Travel scenes must be sorted by ascending minDistance.", source, "travelScenes"))
                        previous_distance = numeric_distance
                    visual_asset_id = scene.get("visualAssetId")
                    if not isinstance(visual_asset_id, str) or not visual_asset_id:
                        errors.append(_issue("error", "Travel scene visualAssetId must reference an expedition image asset.", source, f"{scene_path}.visualAssetId"))
                    motion = scene.get("motion", "loop")
                    if motion not in {"loop", "pan"}:
                        errors.append(_issue("error", "Travel scene motion must be 'loop' or 'pan'.", source, f"{scene_path}.motion"))
                    if "showSeamForegroundBetweenLoops" in scene and not isinstance(scene.get("showSeamForegroundBetweenLoops"), bool):
                        errors.append(_issue("error", "Travel scene showSeamForegroundBetweenLoops must be true or false.", source, f"{scene_path}.showSeamForegroundBetweenLoops"))
        if "routeBranches" in expedition:
            branches = expedition.get("routeBranches")
            if not isinstance(branches, dict):
                errors.append(_issue("error", "Expedition routeBranches must be an object keyed by stable branch IDs.", source, "routeBranches"))
            else:
                path_ids = set(known.get("paths", []))
                for branch_id, branch in branches.items():
                    branch_source = f"{source}.routeBranches.{branch_id}"
                    if not isinstance(branch, dict):
                        errors.append(_issue("error", "Route branch must be an object.", branch_source))
                        continue
                    if branch.get("id") != branch_id:
                        errors.append(_issue("error", f"Route branch key {branch_id!r} must match its id field.", branch_source, "id"))
                    for field_name in ("entryPathId", "rejoinPathId"):
                        path_id = branch.get(field_name)
                        if not isinstance(path_id, str) or not path_id:
                            errors.append(_issue("error", f"Route branch {field_name} is required.", branch_source, field_name))
                        elif path_id not in path_ids:
                            errors.append(_issue("error", f"Route branch references unknown path {path_id!r}.", branch_source, field_name))
                    for field_name in ("entryDistance", "rejoinDistance"):
                        distance = branch.get(field_name)
                        if not _is_number(distance) or distance < 0:
                            errors.append(_issue("error", f"Route branch {field_name} must be a non-negative number.", branch_source, field_name))
                    entry_distance = branch.get("entryDistance")
                    rejoin_distance = branch.get("rejoinDistance")
                    if _is_number(entry_distance) and _is_number(rejoin_distance) and rejoin_distance <= entry_distance:
                        errors.append(_issue("error", "Route branch rejoinDistance must be greater than entryDistance.", branch_source, "rejoinDistance"))
                    if "mapEntryDistance" in branch:
                        map_distance = branch.get("mapEntryDistance")
                        if not _is_number(map_distance) or map_distance < 0:
                            errors.append(_issue("error", "Route branch mapEntryDistance must be a non-negative number.", branch_source, "mapEntryDistance"))
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
        ingredients = recipe.get("ingredients")
        if isinstance(ingredients, list):
            if not ingredients:
                errors.append(_issue("error", "Recipe ingredients must be a non-empty array.", source, "ingredients"))
            seen_ingredients: set[tuple[str, str]] = set()
            for index, ingredient in enumerate(ingredients):
                ingredient_path = f"ingredients[{index}]"
                if not isinstance(ingredient, dict):
                    errors.append(_issue("error", "Canonical recipe ingredients must be objects.", source, ingredient_path))
                    continue
                ingredient_type = ingredient.get("type")
                ingredient_id = ingredient.get("id")
                quantity = ingredient.get("quantity")
                if ingredient_type not in {"material", "item"}:
                    errors.append(_issue("error", "Recipe ingredient type must be item or material.", source, f"{ingredient_path}.type"))
                valid_ids = material_ids if ingredient_type == "material" else item_ids if ingredient_type == "item" else set()
                if not isinstance(ingredient_id, str) or not ingredient_id:
                    errors.append(_issue("error", "Recipe ingredients need an id.", source, f"{ingredient_path}.id"))
                elif ingredient_id not in valid_ids:
                    errors.append(_issue("error", f"Unknown {ingredient_type or 'ingredient'} ID {ingredient_id!r}.", source, f"{ingredient_path}.id"))
                if not _is_number(quantity) or quantity <= 0 or float(quantity) != int(quantity):
                    errors.append(_issue("error", "Recipe ingredient quantity must be a positive integer.", source, f"{ingredient_path}.quantity"))
                if ingredient_type in {"material", "item"} and isinstance(ingredient_id, str):
                    key = (ingredient_type, ingredient_id)
                    if key in seen_ingredients:
                        errors.append(_issue("error", "Recipe ingredients may not repeat the same typed ID.", source, f"{ingredient_path}.id"))
                    seen_ingredients.add(key)
        elif isinstance(ingredients, dict) and ingredients:
            ingredient_type = recipe.get("ingredientType", "material")
            if ingredient_type not in {"material", "item"}:
                errors.append(_issue("error", f"Unknown recipe ingredient type {ingredient_type!r}.", source, "ingredientType"))
            for ingredient_id, quantity in ingredients.items():
                if ingredient_type == "material" and ingredient_id not in material_ids:
                    errors.append(_issue("error", f"Unknown material ID {ingredient_id!r}.", source, f"ingredients.{ingredient_id}"))
                elif ingredient_type == "item" and ingredient_id not in item_ids:
                    errors.append(_issue("error", f"Unknown item ID {ingredient_id!r}.", source, f"ingredients.{ingredient_id}"))
                if not _is_number(quantity) or quantity <= 0:
                    errors.append(_issue("error", "Recipe ingredient quantity must be a positive number.", source, f"ingredients.{ingredient_id}"))
        else:
            errors.append(_issue("error", "Recipe ingredients must be a non-empty typed array.", source, "ingredients"))
        output = recipe.get("output")
        if not isinstance(output, dict):
            errors.append(_issue("error", "Recipe output must be an object.", source, "output"))
        else:
            has_item_output = isinstance(output.get("itemId"), str) and bool(output.get("itemId"))
            has_provision_output = _is_number(output.get("provisions")) and output.get("provisions") > 0
            has_resource_output = isinstance(output.get("resource"), str) and bool(output.get("resource"))
            output_kinds = sum((has_item_output, has_provision_output, has_resource_output))
            if output_kinds != 1:
                errors.append(_issue("error", "Recipe output must define exactly one positive itemId, provisions, or resource result.", source, "output"))
            if has_item_output:
                if output["itemId"] not in item_ids:
                    errors.append(_issue("error", f"Unknown item ID {output['itemId']!r}.", source, "output.itemId"))
                if not _is_number(output.get("quantity")) or output.get("quantity") <= 0:
                    errors.append(_issue("error", "Item recipe output quantity must be positive.", source, "output.quantity"))
            if "provisions" in output and not has_provision_output:
                errors.append(_issue("error", "Recipe provisions output must be a positive number.", source, "output.provisions"))
            if "resource" in output:
                if not has_resource_output:
                    errors.append(_issue("error", "Recipe resource output must name a resource.", source, "output.resource"))
                if not _is_number(output.get("amount")) or output.get("amount") <= 0:
                    errors.append(_issue("error", "Recipe resource output amount must be positive.", source, "output.amount"))
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


def _validate_dialogues(dialogues: Any, known: dict[str, list[str]], errors: list[dict[str, str]]) -> None:
    if not isinstance(dialogues, dict):
        errors.append(_issue("error", "Dialogue definitions must be an object.", "dialogues"))
        return
    for entry_id, dialogue in dialogues.items():
        source = f"dialogue:{entry_id}"
        if not isinstance(dialogue, dict):
            errors.append(_issue("error", "Dialogue must be an object.", source))
            continue
        if dialogue.get("id") != entry_id:
            errors.append(_issue("error", f"Definition key {entry_id!r} does not match its id field.", source, "id"))
        if not isinstance(dialogue.get("start"), str) or not dialogue.get("start"):
            errors.append(_issue("error", "Dialogue start node is required.", source, "start"))
        nodes = dialogue.get("nodes")
        if not isinstance(nodes, dict) or not nodes:
            errors.append(_issue("error", "Dialogue must contain a non-empty nodes object.", source, "nodes"))
            continue
        if isinstance(dialogue.get("start"), str) and dialogue["start"] not in nodes:
            errors.append(_issue("error", f"Dialogue start node {dialogue['start']!r} does not exist.", source, "start"))
        for node_id, node in nodes.items():
            node_path = f"nodes.{node_id}"
            if not isinstance(node, dict):
                errors.append(_issue("error", "Dialogue node must be an object.", source, node_path))
                continue
            if not isinstance(node.get("speakerId"), str) or not node.get("speakerId"):
                errors.append(_issue("error", "Dialogue node speakerId is required.", source, f"{node_path}.speakerId"))
            if not isinstance(node.get("text"), str):
                errors.append(_issue("error", "Dialogue node text is required.", source, f"{node_path}.text"))
            if "next" in node and (not isinstance(node.get("next"), str) or node.get("next") not in nodes):
                errors.append(_issue("error", f"Dialogue node next target {node.get('next')!r} does not exist.", source, f"{node_path}.next"))
            _validate_requirements(node.get("requirements"), source, f"{node_path}.requirements", errors)
            if "effects" in node:
                _validate_resolution_outcomes(node.get("effects"), known, source, f"{node_path}.effects", errors)
            choices = node.get("choices", [])
            if not isinstance(choices, list):
                errors.append(_issue("error", "Dialogue node choices must be an array.", source, f"{node_path}.choices"))
                continue
            choice_ids: set[str] = set()
            for index, choice in enumerate(choices):
                choice_path = f"{node_path}.choices[{index}]"
                if not isinstance(choice, dict):
                    errors.append(_issue("error", "Dialogue choice must be an object.", source, choice_path))
                    continue
                choice_id = choice.get("id")
                if not isinstance(choice_id, str) or not choice_id:
                    errors.append(_issue("error", "Dialogue choice id is required.", source, f"{choice_path}.id"))
                elif choice_id in choice_ids:
                    errors.append(_issue("error", f"Duplicate dialogue choice ID {choice_id!r} in node.", source, f"{choice_path}.id"))
                else:
                    choice_ids.add(choice_id)
                if not isinstance(choice.get("label"), str) or not choice.get("label"):
                    errors.append(_issue("error", "Dialogue choice label is required.", source, f"{choice_path}.label"))
                if "next" in choice and (not isinstance(choice.get("next"), str) or choice.get("next") not in nodes):
                    errors.append(_issue("error", f"Dialogue choice next target {choice.get('next')!r} does not exist.", source, f"{choice_path}.next"))
                _validate_requirements(choice.get("requirements"), source, f"{choice_path}.requirements", errors)
                _validate_requirements(choice.get("conditions"), source, f"{choice_path}.conditions", errors)
                if "effects" in choice:
                    _validate_resolution_outcomes(choice.get("effects"), known, source, f"{choice_path}.effects", errors)


def _validate_npcs(npcs: Any, known: dict[str, list[str]], errors: list[dict[str, str]]) -> None:
    if not isinstance(npcs, dict):
        errors.append(_issue("error", "NPC definitions must be an object.", "npcs"))
        return
    for entry_id, npc in npcs.items():
        source = f"npc:{entry_id}"
        if not isinstance(npc, dict):
            errors.append(_issue("error", "NPC must be an object.", source))
            continue
        if npc.get("id") != entry_id:
            errors.append(_issue("error", f"Definition key {entry_id!r} does not match its id field.", source, "id"))
        for field_name in ("name", "role", "description"):
            if not isinstance(npc.get(field_name), str):
                errors.append(_issue("error", f"NPC {field_name} must be a string.", source, field_name))
        for field_name in ("dialogue", "rumors", "locationIds"):
            if field_name in npc and not isinstance(npc[field_name], list):
                errors.append(_issue("error", f"NPC {field_name} must be an array.", source, field_name))


def _validate_destinations(destinations: Any, known: dict[str, list[str]], errors: list[dict[str, str]]) -> None:
    if not isinstance(destinations, dict):
        errors.append(_issue("error", "Destination definitions must be an object.", "destinations"))
        return
    for entry_id, destination in destinations.items():
        source = f"destination:{entry_id}"
        if not isinstance(destination, dict):
            errors.append(_issue("error", "Destination must be an object.", source))
            continue
        if destination.get("id") != entry_id:
            errors.append(_issue("error", f"Definition key {entry_id!r} does not match its id field.", source, "id"))
        for field_name in ("name", "type", "description"):
            if field_name in destination and not isinstance(destination[field_name], str):
                errors.append(_issue("error", f"Destination {field_name} must be a string.", source, field_name))
        if "hotspot" in destination:
            hotspot = destination["hotspot"]
            if not isinstance(hotspot, dict):
                errors.append(_issue("error", "Destination hotspot must be an object.", source, "hotspot"))
            else:
                for axis in ("x", "y"):
                    value = hotspot.get(axis)
                    if not _is_number(value) or not 0 <= value <= 1:
                        errors.append(_issue("error", f"Destination hotspot {axis} must be a number from 0 to 1.", source, f"hotspot.{axis}"))
        for field_name in ("npcIds", "actions"):
            if field_name in destination and not isinstance(destination[field_name], list):
                errors.append(_issue("error", f"Destination {field_name} must be an array.", source, field_name))
        if "restConfig" in destination:
            rest_config = destination.get("restConfig")
            if not isinstance(rest_config, dict):
                errors.append(_issue("error", "Destination restConfig must be an object.", source, "restConfig"))
            else:
                for field_name in ("restoration", "goldCost", "recoveryDistanceReduction"):
                    if field_name in rest_config and (not _is_number(rest_config[field_name]) or rest_config[field_name] < 0):
                        errors.append(_issue("error", f"Destination restConfig {field_name} must be a non-negative number.", source, f"restConfig.{field_name}"))


def _validate_locations(locations: Any, known: dict[str, list[str]], errors: list[dict[str, str]]) -> None:
    if not isinstance(locations, dict):
        errors.append(_issue("error", "Location definitions must be an object.", "locations"))
        return
    for entry_id, location in locations.items():
        source = f"location:{entry_id}"
        if not isinstance(location, dict):
            errors.append(_issue("error", "Location must be an object.", source))
            continue
        if location.get("id") != entry_id:
            errors.append(_issue("error", f"Definition key {entry_id!r} does not match its id field.", source, "id"))
        for field_name in ("name", "type", "description"):
            if field_name in location and not isinstance(location[field_name], str):
                errors.append(_issue("error", f"Location {field_name} must be a string.", source, field_name))
        if "markerStyle" in location and location["markerStyle"] not in {"tag", "ribbon", "ink"}:
            errors.append(_issue("error", "Location markerStyle must be one of: tag, ribbon, ink.", source, "markerStyle"))
        for field_name in ("destinations", "npcs", "shops", "availableExpeditions", "availableQuests", "requirements"):
            if field_name in location and not isinstance(location[field_name], list):
                errors.append(_issue("error", f"Location {field_name} must be an array.", source, field_name))
        if "serviceConfig" in location:
            service_config = location.get("serviceConfig")
            if not isinstance(service_config, dict):
                errors.append(_issue("error", "Location serviceConfig must be an object.", source, "serviceConfig"))
            else:
                if "autoProvisionGrant" in service_config and not isinstance(service_config["autoProvisionGrant"], bool):
                    errors.append(_issue("error", "Location autoProvisionGrant must be true or false.", source, "serviceConfig.autoProvisionGrant"))
                for field_name in ("provisionShopId", "restockProvisionShopId"):
                    if field_name not in service_config or service_config[field_name] is None:
                        continue
                    shop_id = service_config[field_name]
                    if not isinstance(shop_id, str) or shop_id not in set(known.get("shops", [])):
                        errors.append(_issue("error", f"Location {field_name} references unknown shop ID {shop_id!r}.", source, f"serviceConfig.{field_name}"))


def _validate_asset_map(
    assets: Any,
    asset_type: str,
    project_root: Path | None,
    errors: list[dict[str, str]],
) -> None:
    categories = ASSET_IMAGE_CATEGORIES if asset_type == "image" else ASSET_AUDIO_CATEGORIES
    extensions = ASSET_IMAGE_EXTENSIONS if asset_type == "image" else ASSET_AUDIO_EXTENSIONS
    root_prefix = "assets/images/" if asset_type == "image" else "assets/audio/"
    if not isinstance(assets, dict):
        errors.append(_issue("error", f"{asset_type.title()} asset definitions must be an object.", f"{asset_type}Assets"))
        return
    for entry_id, asset in assets.items():
        source = f"{asset_type}Asset:{entry_id}"
        if not isinstance(asset, dict):
            errors.append(_issue("error", "Asset must be an object.", source))
            continue
        if asset.get("id") != entry_id:
            errors.append(_issue("error", f"Definition key {entry_id!r} does not match its id field.", source, "id"))
        if not isinstance(entry_id, str) or not ASSET_ID_PATTERN.fullmatch(entry_id):
            errors.append(_issue("error", f"Asset ID {entry_id!r} must be lowercase slug-like text.", source, "id"))
        category = asset.get("category")
        if category not in categories:
            errors.append(_issue("error", f"Asset category {category!r} is not valid for {asset_type} assets.", source, "category"))
        path = asset.get("path")
        path_object = Path(path) if isinstance(path, str) else None
        safe_path = bool(
            isinstance(path, str)
            and path.startswith(root_prefix)
            and not path_object.is_absolute()
            and "\\" not in path
            and ".." not in path_object.parts
            and all(part not in {"", "."} for part in path_object.parts)
            and Path(path).suffix.lower() in extensions
        )
        if not safe_path:
            errors.append(_issue("error", f"Asset path must be a relative file inside {root_prefix[:-1]}/ with a supported extension.", source, "path"))
        elif project_root is not None and not (project_root / path).is_file():
            errors.append(_issue("error", f"Referenced asset file does not exist: {path!r}.", source, "path"))
        if asset_type == "audio" and not isinstance(asset.get("loop", False), bool):
            errors.append(_issue("error", "Audio loop must be true or false.", source, "loop"))


def _validate_asset_references(values: dict[str, Any], errors: list[dict[str, str]]) -> None:
    image_assets = _id_map(values.get("imageAssets"))
    audio_assets = _id_map(values.get("audioAssets"))
    image_fields = {
        "portraitAssetId": {"portrait"},
        "travelVisualAssetId": {"expedition"},
        "travelParallaxAssetId": {"expedition"},
        "travelTransitionAssetId": {"expedition"},
        "travelSeamForegroundAssetId": {"expedition"},
        "campVisualAssetId": {"expedition"},
        "combatVisualAssetId": {"combat"},
    }
    audio_fields = {
        "travelAmbienceAssetId": {"ambience"},
        "campAmbienceAssetId": {"ambience"},
        "ambienceAssetId": {"ambience"},
        "stingAssetId": {"sfx"},
    }
    visual_field_categories = {
        "locations": {"location", "town"},
        "destinations": {"location"},
        "encounters": {"encounter"},
        "campEvents": {"encounter"},
        "expeditions": {"expedition"},
        "enemyDefinitions": {"combat"},
        "companions": {"combat"},
        "playerCharacter": {"combat"},
    }

    def visit(node: Any, source: str, path: str = "") -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                child_path = f"{path}.{key}" if path else str(key)
                allowed_image_categories = image_fields.get(key)
                if key == "visualAssetId":
                    allowed_image_categories = visual_field_categories.get(source)
                elif key == "combatVisualAssetId":
                    allowed_image_categories = {"combat_scene"} if source in {"encounters", "expeditions"} else {"combat"}
                if isinstance(child, str) and allowed_image_categories:
                    asset = image_assets.get(child)
                    if asset and asset.get("category") not in allowed_image_categories:
                        errors.append(_issue("error", f"Image asset {child!r} has category {asset.get('category')!r}, incompatible with {key}.", source, child_path))
                elif isinstance(child, str) and key in audio_fields:
                    asset = audio_assets.get(child)
                    if asset and asset.get("category") not in audio_fields[key]:
                        errors.append(_issue("error", f"Audio asset {child!r} has category {asset.get('category')!r}, incompatible with {key}.", source, child_path))
                visit(child, source, child_path)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, source, f"{path}[{index}]")

    for category, value in values.items():
        if category not in {"imageAssets", "audioAssets"}:
            visit(value, category)


def validate_catalog(values: dict[str, Any], known: dict[str, list[str]], references: dict[str, list[dict[str, str]]] | None = None, parse_duplicates: list[dict[str, str]] | None = None, project_root: Path | None = None) -> dict[str, list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    effective_known = {key: list(value) for key, value in known.items()}
    item_ids = sorted(_id_map(values.get("items"))) if "items" in values else list(known.get("items", []))
    effective_known["items"] = item_ids
    for value_key, known_key in (("combats", "combats"), ("abilities", "abilities"), ("injuries", "injuries"), ("campEvents", "campEvents"), ("dialogues", "dialogues"), ("npcs", "npcs"), ("destinations", "destinations"), ("locations", "locations"), ("enemyDefinitions", "enemies"), ("enemyActions", "enemyActions"), ("lootTables", "lootTables")):
        if value_key in values:
            effective_known[known_key] = sorted(_id_map(values.get(value_key)))
    if "combatStatuses" in values:
        effective_known["combatStatuses"] = sorted(_id_map(values.get("combatStatuses")))
    if "expeditions" in values:
        effective_known["expeditions"] = sorted(_id_map(values.get("expeditions")))
    if "recipes" in values:
        effective_known["recipes"] = sorted(_id_map(values.get("recipes")))
    if "craftingProviders" in values:
        effective_known["craftingProviders"] = sorted(_id_map(values.get("craftingProviders")))
    if "materials" in values:
        item_values = _id_map(values.get("items"))
        material_ids = set(_id_map(values.get("materials")))
        if "items" not in values:
            material_ids.update(
                entry["id"]
                for entry in (references or {}).get("materials", [])
                if entry.get("source") == "startingState" and isinstance(entry.get("id"), str)
            )
        material_ids.update({
            item_id
            for item_id, item in item_values.items()
            if isinstance(item, dict) and (
                item.get("category") == "ingredient"
                or "ingredient" in item.get("tags", [])
            )
        })
        effective_known["materials"] = sorted(material_ids)
    if "imageAssets" in values:
        effective_known["imageAssets"] = sorted(_id_map(values.get("imageAssets")))
        effective_known["imageAssetCategories"] = {
            asset_id: asset.get("category")
            for asset_id, asset in _id_map(values.get("imageAssets")).items()
            if isinstance(asset, dict)
        }
    if "audioAssets" in values:
        effective_known["audioAssets"] = sorted(_id_map(values.get("audioAssets")))
    if "companions" in values:
        effective_known["companions"] = sorted(_id_map(values.get("companions")))
    for duplicate in parse_duplicates or []:
        errors.append(_issue("error", f"Duplicate object key {duplicate['id']!r}.", duplicate["source"]))
    if "encounters" in values:
        _validate_encounters(values.get("encounters"), effective_known, errors)
        for entry_id, encounter in _id_map(values.get("encounters")).items():
            if isinstance(encounter, dict) and "expeditionIds" in encounter:
                warnings.append(_issue("warning", "Legacy encounter expeditionIds field is ignored; use pathIds instead.", f"encounter:{entry_id}", "expeditionIds"))
    if "injuries" in values:
        _validate_injuries(values.get("injuries"), effective_known, errors)
    if "campEvents" in values:
        _validate_camp_events(values.get("campEvents"), effective_known, errors)
    if "dialogues" in values:
        _validate_dialogues(values.get("dialogues"), effective_known, errors)
    if "npcs" in values:
        _validate_npcs(values.get("npcs"), effective_known, errors)
    if "destinations" in values:
        _validate_destinations(values.get("destinations"), effective_known, errors)
    if "locations" in values:
        _validate_locations(values.get("locations"), effective_known, errors)
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
    if "combatStatuses" in values:
        _validate_combat_statuses(values.get("combatStatuses"), errors)
    if "combats" in values:
        _validate_combat_definitions(values.get("combats"), effective_known, errors)
    if "enemyDefinitions" in values:
        _validate_enemy_definitions(values.get("enemyDefinitions"), effective_known, errors)
    if "playerCharacter" in values:
        _validate_player_character(values.get("playerCharacter"), effective_known, errors)
    if "startingState" in values:
        _validate_starting_state(values.get("startingState"), effective_known, errors, values.get("items"))
    if "companions" in values:
        _validate_companions(values.get("companions"), effective_known, errors)
    if "enemyActions" in values:
        _validate_enemy_actions(values.get("enemyActions"), effective_known, errors)
    if "abilities" in values:
        _validate_abilities(values.get("abilities"), effective_known, errors)
    if "lootTables" in values:
        _validate_loot_tables(values.get("lootTables"), effective_known, errors)
    if "returnRewards" in values:
        _validate_return_reward_tiers(values.get("returnRewards"), effective_known, errors)
    if "imageAssets" in values:
        _validate_asset_map(values.get("imageAssets"), "image", project_root, errors)
    if "audioAssets" in values:
        _validate_asset_map(values.get("audioAssets"), "audio", project_root, errors)
    if "imageAssets" in values and "audioAssets" in values:
        duplicate_asset_ids = set(_id_map(values.get("imageAssets"))) & set(_id_map(values.get("audioAssets")))
        for asset_id in sorted(duplicate_asset_ids):
            errors.append(_issue("error", f"Duplicate asset ID {asset_id!r} is used by both an image and audio asset.", "assets"))
    _validate_asset_references(values, errors)

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
                    "dialogues": "dialogue", "npcs": "NPC", "destinations": "destination", "locations": "location",
                    "combatStatuses": "combat status",
                    "imageAssets": "image asset", "audioAssets": "audio asset",
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


def _validation_issue_key(issue: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        issue.get("severity", ""),
        issue.get("message", ""),
        issue.get("source", ""),
        issue.get("path", ""),
    )


def _validation_issue_scope(issue: dict[str, str]) -> tuple[str, str | None] | None:
    source = issue.get("source", "")
    prefixes = {
        "encounter:": "encounters",
        "campEvent:": "campEvents",
        "dialogue:": "dialogues",
        "npc:": "npcs",
        "destination:": "destinations",
        "location:": "locations",
        "expedition:": "expeditions",
        "recipe:": "recipes",
        "material:": "materials",
        "craftingProvider:": "craftingProviders",
        "shop:": "shops",
        "item:": "items",
        "combat:": "combats",
        "enemyDefinition:": "enemyDefinitions",
        "enemyAction:": "enemyActions",
        "ability:": "abilities",
        "injury:": "injuries",
        "lootTable:": "lootTables",
        "companion:": "companions",
    }
    for prefix, category in prefixes.items():
        if source.startswith(prefix):
            return category, source[len(prefix):]
    return (source, None) if source in CONTENT_FILES else None

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


def _surgical_source_update(source: str, constant_name: str, incoming: Any, newline: str) -> str:
    parsed = extract_constant(source, constant_name)
    current = parsed.value
    if isinstance(current, list):
        if not isinstance(incoming, list):
            raise JsParseError(f"{constant_name} must remain an array")
        # Ordered arrays have no stable property keys to patch individually.
        # Replace only the literal span, keeping the surrounding declaration
        # and every other constant in the source file byte-for-byte intact.
        indent = _line_indent(source, parsed.value_start)
        return _apply_source_edits(source, [(parsed.value_start, parsed.value_end, serialize_js(incoming, indent=indent, newline=newline))])
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
    validation = validate_catalog(merged, current["known"], current["references"], project_root=project_root)
    changed_categories = [category for category in CONTENT_FILES if category in incoming and incoming[category] != current[category]]
    current_error_keys = {_validation_issue_key(issue) for issue in current["validation"].get("errors", [])}
    blocking_errors = [
        issue for issue in validation["errors"]
        if _validation_issue_key(issue) not in current_error_keys
        or (
            (scope := _validation_issue_scope(issue))
            and scope[0] in changed_categories
            and (
                scope[1] is None
                or current.get(scope[0], {}).get(scope[1]) != incoming.get(scope[0], {}).get(scope[1])
            )
        )
    ]
    if blocking_errors:
        raise ValueError(json.dumps({"errors": blocking_errors, "warnings": validation["warnings"]}))

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


def suggest_asset_id(filename: str, asset_type: str, category: str, context: str | None = None) -> str:
    stem = Path(filename).stem.lower()
    stem = re.sub(r"[^a-z0-9]+", "_", stem).strip("_") or "asset"
    prefix = "portrait" if category == "portrait" else category
    pieces = [prefix]
    if context:
        context_slug = re.sub(r"[^a-z0-9]+", "_", context.lower()).strip("_")
        if context_slug:
            pieces.append(context_slug)
    pieces.append(stem)
    base = "_".join(pieces)
    if asset_type == "audio" and category not in base.split("_"):
        base = f"{category}_{base}"
    return base[:64].rstrip("_") or "asset"


def _validate_upload_metadata(asset_type: str, category: str, asset_id: str, filename: str, content: bytes) -> str:
    if asset_type not in {"image", "audio"}:
        raise ValueError("Asset type must be image or audio.")
    categories = ASSET_IMAGE_CATEGORIES if asset_type == "image" else ASSET_AUDIO_CATEGORIES
    extensions = ASSET_IMAGE_EXTENSIONS if asset_type == "image" else ASSET_AUDIO_EXTENSIONS
    if category not in categories:
        raise ValueError(f"Unsupported {asset_type} asset category {category!r}.")
    if not ASSET_ID_PATTERN.fullmatch(asset_id or ""):
        raise ValueError("Asset ID must be lowercase slug-like text (2-64 characters).")
    if not ASSET_FILENAME_PATTERN.fullmatch(filename or "") or Path(filename).name != filename:
        raise ValueError("Filename must be a simple name without folders or unsafe characters.")
    suffix = Path(filename).suffix.lower()
    if suffix not in extensions:
        supported = ", ".join(sorted(extensions))
        raise ValueError(f"Unsupported {asset_type} format {suffix or '(none)'}; use {supported}.")
    if not content:
        raise ValueError("Uploaded asset is empty.")
    return suffix


def preview_image(
    *,
    category: str,
    filename: str,
    content: bytes,
    optimize_for_game: bool = True,
    optimization_profile: str | None = None,
    crop_anchor: str = "center",
    sam_mask_json: str | bytes | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prepare an image for the import dialog without writing project files."""
    _validate_upload_metadata("image", category, "preview_asset", filename, content)
    if sam_mask_json is not None and category != "expedition":
        raise ValueError("SAM foreground masks are currently supported only for expedition travel images.")
    selected_profile = profile_for_category(category, optimization_profile) if optimize_for_game else "none"
    processed = optimize_image(
        content,
        category=category,
        profile=selected_profile,
        crop_anchor=crop_anchor,
        filename=filename,
    )
    result = {
        "imageProcessing": _image_processing_result(processed),
        "previewDataUrl": processed.preview_data_url,
        "optimized": bool(optimize_for_game and selected_profile != "none"),
    }
    if sam_mask_json is not None:
        parallax = optimize_image(
            content,
            category=category,
            profile=selected_profile,
            crop_anchor=crop_anchor,
            filename=filename,
            mask_json=sam_mask_json,
        )
        result["parallaxImageProcessing"] = _image_processing_result(parallax)
        result["parallaxPreviewDataUrl"] = parallax.preview_data_url
    return result


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _safe_runtime_stem(filename: str, asset_id: str) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", Path(filename).stem.lower()).strip("-")
    return stem[:120] or asset_id


def _image_processing_result(processed: ProcessedImage) -> dict[str, Any]:
    result = {
        "profile": processed.profile,
        "profileLabel": processed.profile_label,
        "cropAnchor": processed.crop_anchor,
        "source": {
            "width": processed.source.width,
            "height": processed.source.height,
            "format": processed.source.format,
            "mode": processed.source.mode,
            "hasAlpha": processed.source.has_alpha,
            "bytes": processed.source.size,
        },
        "output": {
            "width": processed.output.width,
            "height": processed.output.height,
            "format": processed.output.format,
            "mode": processed.output.mode,
            "hasAlpha": processed.output.has_alpha,
            "bytes": processed.output.size,
        },
        "warnings": list(processed.warnings),
    }
    if processed.foreground_offset and processed.foreground_canvas:
        result["foregroundAlignment"] = {
            "offset": {
                "x": processed.foreground_offset[0],
                "y": processed.foreground_offset[1],
            },
            "canvas": {
                "width": processed.foreground_canvas[0],
                "height": processed.foreground_canvas[1],
            },
            "size": {
                "width": processed.output.width,
                "height": processed.output.height,
            },
        }
    return result


def _parallax_asset_id(asset_id: str) -> str:
    suffix = "_parallax"
    return f"{asset_id[:64 - len(suffix)].rstrip('_-')}{suffix}"


def _parallax_relative_path(relative_path: str) -> str:
    path = Path(relative_path)
    return (path.parent / f"{path.stem}-parallax.webp").as_posix()


def upload_asset(
    project_root: Path,
    *,
    asset_type: str,
    category: str,
    asset_id: str,
    filename: str,
    content: bytes,
    expected_hash: str | None = None,
    replace: bool = False,
    backup_dir: Path | None = None,
    optimize_for_game: bool = False,
    optimization_profile: str | None = None,
    crop_anchor: str = "center",
    sam_mask_json: str | bytes | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Safely add or explicitly replace a binary asset and its catalog entry.

    Image optimization is opt-in at this Python API boundary for compatibility
    with existing scripts. The Content Editor UI sends it enabled by default.
    """
    project_root = project_root.resolve()
    input_suffix = _validate_upload_metadata(asset_type, category, asset_id, filename, content)
    if sam_mask_json is not None and asset_type != "image":
        raise ValueError("SAM foreground masks can only be attached to image uploads.")
    if sam_mask_json is not None and category != "expedition":
        raise ValueError("SAM foreground masks are currently supported only for expedition travel images.")
    processed: ProcessedImage | None = None
    parallax_processed: ProcessedImage | None = None
    selected_profile = None
    if asset_type == "image" and optimize_for_game:
        selected_profile = profile_for_category(category, optimization_profile)
        processed = optimize_image(
            content,
            category=category,
            profile=selected_profile,
            crop_anchor=crop_anchor,
            filename=filename,
        )
    if sam_mask_json is not None:
        selected_profile = selected_profile or "none"
        parallax_processed = optimize_image(
            content,
            category=category,
            profile=selected_profile,
            crop_anchor=crop_anchor,
            filename=filename,
            mask_json=sam_mask_json,
        )
    output_content = processed.content if processed is not None else content
    optimized_webp = bool(processed is not None and processed.profile != "none")
    current = load_catalog(project_root)
    source_relative = "js/asset-data.js"
    actual_hash = current["sourceHashes"].get(source_relative)
    if expected_hash and actual_hash != expected_hash:
        raise RuntimeError("Conflict: js/asset-data.js changed on disk since the editor loaded it. Reload before saving.")

    image_assets = clone(current["imageAssets"])
    audio_assets = clone(current["audioAssets"])
    target_map = image_assets if asset_type == "image" else audio_assets
    other_map = audio_assets if asset_type == "image" else image_assets
    existing = target_map.get(asset_id)
    if asset_id in other_map:
        raise ValueError(f"Asset ID {asset_id!r} already belongs to the other asset type.")
    if existing and not replace:
        raise ValueError(f"Asset ID {asset_id!r} already exists. Use Replace File explicitly.")
    if replace and not existing:
        raise ValueError(f"Cannot replace missing asset ID {asset_id!r}.")

    parallax_asset_id = _parallax_asset_id(asset_id) if parallax_processed is not None else None
    parallax_existing = image_assets.get(parallax_asset_id) if parallax_asset_id else None
    if parallax_asset_id and parallax_asset_id in audio_assets:
        raise ValueError(f"Generated parallax ID {parallax_asset_id!r} already belongs to an audio asset.")
    if parallax_existing and parallax_existing.get("category") != "expedition":
        raise ValueError("An existing generated parallax asset must keep the expedition category.")
    if parallax_existing and not replace and existing is None:
        raise ValueError(f"Generated parallax asset ID {parallax_asset_id!r} already exists; replace the source explicitly.")

    if existing:
        if existing.get("category") != category:
            raise ValueError("Replacement files must keep the existing asset category.")
        old_path = existing.get("path")
        expected_root = "assets/images/" if asset_type == "image" else "assets/audio/"
        if not isinstance(old_path, str) or not old_path.startswith(expected_root) or ".." in Path(old_path).parts:
            raise ValueError(f"Existing asset {asset_id!r} has an unsafe catalog path.")
        old_suffix = Path(old_path).suffix.lower()
        if optimized_webp:
            relative_path = old_path if old_suffix == ".webp" else str(Path(old_path).with_suffix(".webp")).replace("\\", "/")
        else:
            relative_path = old_path
        if not optimized_webp and old_suffix != input_suffix:
            raise ValueError("Replacement files must keep the existing asset file extension.")
    else:
        root = "assets/images" if asset_type == "image" else "assets/audio"
        runtime_filename = f"{_safe_runtime_stem(filename, asset_id)}.webp" if optimized_webp else filename
        relative_path = f"{root}/{category}/{runtime_filename}"
        if (project_root / relative_path).exists():
            raise ValueError(f"Asset file {relative_path!r} already exists. Choose a new filename or replace the asset explicitly.")

    destination = (project_root / relative_path).resolve()
    assets_root = (project_root / "assets").resolve()
    if assets_root not in destination.parents:
        raise ValueError("Asset destination must remain inside the game assets directory.")
    if optimized_webp and destination.suffix.lower() != ".webp":
        raise ValueError("Optimized image assets must use a .webp runtime path.")

    old_destination = None
    if existing:
        old_destination = (project_root / existing["path"]).resolve()
        if assets_root not in old_destination.parents:
            raise ValueError("Existing asset path must remain inside the game assets directory.")
    if existing and old_destination != destination and destination.exists():
        raise ValueError(f"Optimized replacement destination {relative_path!r} already exists; remove it or choose another source name.")
    catalog_paths = {
        asset.get("path")
        for key, asset in target_map.items()
        if key != asset_id and isinstance(asset, dict) and isinstance(asset.get("path"), str)
    }
    if relative_path in catalog_paths:
        raise ValueError(f"Asset path {relative_path!r} is already assigned to another asset.")

    parallax_destination = None
    parallax_old_destination = None
    parallax_relative_path = None
    if parallax_processed is not None and parallax_asset_id:
        if parallax_existing:
            parallax_relative_path = parallax_existing.get("path")
            if not isinstance(parallax_relative_path, str) or not parallax_relative_path.startswith("assets/images/") or ".." in Path(parallax_relative_path).parts:
                raise ValueError(f"Existing asset {parallax_asset_id!r} has an unsafe catalog path.")
            if Path(parallax_relative_path).suffix.lower() != ".webp":
                parallax_relative_path = _parallax_relative_path(relative_path)
        else:
            parallax_relative_path = _parallax_relative_path(relative_path)
        parallax_destination = (project_root / parallax_relative_path).resolve()
        if assets_root not in parallax_destination.parents or parallax_destination == destination:
            raise ValueError("Generated parallax destination must remain separate inside the game assets directory.")
        if parallax_existing:
            parallax_old_destination = (project_root / parallax_existing["path"]).resolve()
            if assets_root not in parallax_old_destination.parents:
                raise ValueError("Existing parallax asset path must remain inside the game assets directory.")
            if parallax_old_destination != parallax_destination and parallax_destination.exists():
                raise ValueError(f"Generated parallax destination {parallax_relative_path!r} already exists.")
        elif parallax_destination.exists():
            raise ValueError(f"Generated parallax file {parallax_relative_path!r} already exists; replace the source explicitly.")
        image_paths = {
            asset.get("path")
            for key, asset in image_assets.items()
            if key not in {asset_id, parallax_asset_id} and isinstance(asset, dict) and isinstance(asset.get("path"), str)
        }
        if parallax_relative_path in image_paths:
            raise ValueError(f"Generated parallax path {parallax_relative_path!r} is already assigned to another asset.")

    backup_dir = backup_dir or (Path(__file__).resolve().parent / ".backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    write_records: list[dict[str, Any]] = []
    binary_backups: dict[str, str] = {}
    destinations = [(asset_id, destination, old_destination, output_content)]
    if parallax_processed is not None and parallax_asset_id and parallax_destination is not None:
        destinations.append((parallax_asset_id, parallax_destination, parallax_old_destination, parallax_processed.content))
    for write_id, write_destination, old_write_destination, _write_content in destinations:
        previous_write_bytes = write_destination.read_bytes() if write_destination.is_file() else None
        old_write_bytes = old_write_destination.read_bytes() if old_write_destination and old_write_destination.is_file() else None
        backup_bytes = old_write_bytes if old_write_bytes is not None else previous_write_bytes
        if backup_bytes is not None:
            binary_backup_path = backup_dir / f"asset-{write_id}.{stamp}.bak"
            binary_backup_path.write_bytes(backup_bytes)
            binary_backups[write_id] = str(binary_backup_path)
        write_records.append({
            "destination": write_destination,
            "previous": previous_write_bytes,
            "old_destination": old_write_destination,
            "old": old_write_bytes,
        })

    definition = {
        **(existing or {}),
        "id": asset_id,
        "path": relative_path.replace("\\", "/"),
        "category": category,
    }
    if asset_type == "audio":
        definition.setdefault("loop", category == "ambience")
    target_map[asset_id] = definition
    if parallax_processed is not None and parallax_asset_id and parallax_relative_path:
        parallax_definition = {
            **(parallax_existing or {}),
            "id": parallax_asset_id,
            "path": parallax_relative_path,
            "category": "expedition",
            "generatedFromAssetId": asset_id,
        }
        if parallax_processed.foreground_offset and parallax_processed.foreground_canvas:
            parallax_definition["foregroundAlignment"] = {
                "offset": {
                    "x": parallax_processed.foreground_offset[0],
                    "y": parallax_processed.foreground_offset[1],
                },
                "canvas": {
                    "width": parallax_processed.foreground_canvas[0],
                    "height": parallax_processed.foreground_canvas[1],
                },
                "size": {
                    "width": parallax_processed.output.width,
                    "height": parallax_processed.output.height,
                },
            }
        image_assets[parallax_asset_id] = parallax_definition
    source_written = False
    try:
        for write_id, write_destination, _old_write_destination, write_content in destinations:
            _atomic_write_bytes(write_destination, write_content)
        _write_source_constants(
            project_root,
            source_relative,
            {"IMAGE_ASSET_DEFINITIONS": image_assets, "AUDIO_ASSET_DEFINITIONS": audio_assets},
            backup_dir,
            actual_hash,
        )
        source_written = True
        written_destinations = {record["destination"] for record in write_records}
        for record in write_records:
            old_write_destination = record["old_destination"]
            if old_write_destination and old_write_destination != record["destination"] and old_write_destination not in written_destinations:
                old_write_destination.unlink(missing_ok=True)
    except Exception:
        for record in reversed(write_records):
            write_destination = record["destination"]
            old_write_destination = record["old_destination"]
            if old_write_destination and old_write_destination != write_destination:
                if record["previous"] is None:
                    write_destination.unlink(missing_ok=True)
                else:
                    _atomic_write_bytes(write_destination, record["previous"])
                if record["old"] is None:
                    old_write_destination.unlink(missing_ok=True)
                else:
                    _atomic_write_bytes(old_write_destination, record["old"])
            elif record["previous"] is None:
                write_destination.unlink(missing_ok=True)
            else:
                _atomic_write_bytes(write_destination, record["previous"])
        raise

    result = load_catalog(project_root)
    result["assetResult"] = {
        "assetId": asset_id,
        "type": asset_type,
        "path": relative_path.replace("\\", "/"),
        "replaced": bool(existing),
        "binaryBackup": binary_backups.get(asset_id),
        "sourceWritten": source_written,
    }
    if processed is not None:
        result["assetResult"]["imageProcessing"] = _image_processing_result(processed)
    if parallax_processed is not None and parallax_asset_id and parallax_relative_path:
        result["assetResult"]["parallaxAssetId"] = parallax_asset_id
        result["assetResult"]["parallaxPath"] = parallax_relative_path
        result["assetResult"]["parallaxReplaced"] = bool(parallax_existing)
        result["assetResult"]["parallaxBinaryBackup"] = binary_backups.get(parallax_asset_id)
        result["assetResult"]["parallaxImageProcessing"] = _image_processing_result(parallax_processed)
    return result
