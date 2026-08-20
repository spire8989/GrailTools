from __future__ import annotations

import difflib
import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


CONTENT_EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONTENT_EDITOR))

from content_editor_core import (  # noqa: E402
    JsValueParser,
    build_path_index,
    clone,
    collect_references,
    constant_property_blocks,
    load_catalog,
    parse_file_constant,
    save_catalog,
    serialize_js,
    validate_catalog,
)


GRAIL = CONTENT_EDITOR.parents[1] / "Grail"


class ContentEditorTests(unittest.TestCase):
    def test_current_real_definitions_load(self) -> None:
        catalog = load_catalog(GRAIL)
        self.assertGreaterEqual(len(catalog["encounters"]), 50)
        self.assertEqual(len(catalog["shops"]), 3)
        self.assertGreaterEqual(len(catalog["known"]["items"]), 40)
        self.assertEqual(len(catalog["injuries"]), 6)
        self.assertGreaterEqual(len(catalog["campEvents"]), 6)
        self.assertEqual(catalog["validation"]["errors"], [])

    def test_asset_browser_exposes_travel_panorama_and_travel_rows_select_it(self) -> None:
        index = (CONTENT_EDITOR / "static" / "index.html").read_text(encoding="utf-8")
        app = (CONTENT_EDITOR / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('value="travel_panorama"', index)
        self.assertIn('value="town"', index)
        self.assertIn('data-asset-profile="travel_panorama"', app)
        self.assertIn('locations: ["Visual asset", "visualAssetId", "town"]', app)
        self.assertIn('data-travel-scene-field="motion"', app)
        self.assertIn('motion: "loop"', app)
        self.assertIn('travelTransitionAssetId', app)
        self.assertIn("Optional foreground artwork used to hide Travel Scene changes", app)
        self.assertIn("Recommended: 3:1 panoramic artwork", app)
        self.assertIn('renderAssetSelector("Camp visual"', app)

    def test_town_hotspots_round_trip_and_layout_editor_surface(self) -> None:
        catalog = load_catalog(GRAIL)
        inn_hotspot = catalog["destinations"]["inn"]["hotspot"]
        self.assertTrue(all(0 <= inn_hotspot[axis] <= 1 for axis in ("x", "y")))
        self.assertIn(catalog["locations"]["broceliande_village"]["markerStyle"], {"tag", "ribbon", "ink"})
        app = (CONTENT_EDITOR / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("data-town-layout-editor", app)
        self.assertIn("data-town-layout-marker", app)
        self.assertIn("data-town-hotspot-input", app)
        self.assertIn('data-field="markerStyle"', app)

        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before = load_catalog(project)
        destinations = clone(before["destinations"])
        destinations["inn"]["hotspot"] = {"x": 0.123, "y": 0.987}
        locations = clone(before["locations"])
        locations["broceliande_village"]["markerStyle"] = "ink"
        save_catalog(project, {"destinations": destinations, "locations": locations}, before["sourceHashes"], Path(temp.name) / "backups")
        after = load_catalog(project)
        self.assertEqual(after["destinations"]["inn"]["hotspot"], {"x": 0.123, "y": 0.987})
        self.assertEqual(after["locations"]["broceliande_village"]["markerStyle"], "ink")

        invalid_locations = clone(after["locations"])
        invalid_locations["broceliande_village"]["markerStyle"] = "plaque"
        validation = validate_catalog({"locations": invalid_locations}, after["known"], after["references"])
        self.assertTrue(any("Location markerStyle must be one of" in issue["message"] for issue in validation["errors"]))

    def test_encounter_layout_round_trip_and_editor_surface(self) -> None:
        catalog = load_catalog(GRAIL)
        layout = catalog["encounters"]["abandoned_camp"]["encounterLayout"]
        self.assertEqual(layout["arthur"], {"x": 0.42, "y": 0.66})
        app = (CONTENT_EDITOR / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("data-encounter-layout-editor", app)
        self.assertIn("data-encounter-layout-marker", app)
        self.assertIn("data-encounter-layout-input", app)

        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before = load_catalog(project)
        encounters = clone(before["encounters"])
        encounters["abandoned_camp"]["encounterLayout"] = {
            "arthur": {"x": 0.123, "y": 0.987},
            "companion1": {"x": 0.5, "y": 0.25},
        }
        save_catalog(project, {"encounters": encounters}, before["sourceHashes"], Path(temp.name) / "backups")
        after = load_catalog(project)
        self.assertEqual(after["encounters"]["abandoned_camp"]["encounterLayout"], encounters["abandoned_camp"]["encounterLayout"])

        invalid = clone(after["encounters"])
        invalid["abandoned_camp"]["encounterLayout"]["arthur"]["x"] = 1.2
        validation = validate_catalog({"encounters": invalid}, after["known"], after["references"])
        self.assertTrue(any("Encounter layout arthur x must be a number from 0 to 1" in issue["message"] for issue in validation["errors"]))

    def test_outcome_visual_round_trip_and_editor_surface(self) -> None:
        catalog = load_catalog(GRAIL)
        app = (CONTENT_EDITOR / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("data-outcome-visual-editor", app)
        self.assertIn("data-outcome-layout-marker", app)

        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before = load_catalog(project)
        encounters = clone(before["encounters"])
        choice = encounters["abandoned_camp"]["stages"]["start"]["choices"][0]
        choice["visualOverride"] = {
            "backgroundAssetId": "encounter_abandoned_camp",
            "encounterLayout": {"arthur": {"x": 0.62, "y": 0.68}},
            "hiddenSlots": ["companion2"],
        }
        save_catalog(project, {"encounters": encounters}, before["sourceHashes"], Path(temp.name) / "backups")
        after = load_catalog(project)
        self.assertEqual(after["encounters"]["abandoned_camp"]["stages"]["start"]["choices"][0]["visualOverride"], choice["visualOverride"])
        self.assertNotIn("outcomeVisual", after["encounters"]["abandoned_camp"]["stages"]["start"]["choices"][0]["outcomes"][0])

        invalid = clone(after["encounters"])
        invalid["abandoned_camp"]["stages"]["start"]["choices"][0]["visualOverride"]["hiddenSlots"] = ["companion9"]
        validation = validate_catalog({"encounters": invalid}, after["known"], after["references"])
        self.assertTrue(any("hiddenSlots must contain only" in issue["message"] for issue in validation["errors"]))

    def test_unchanged_values_round_trip_semantically(self) -> None:
        encounter_path = GRAIL / "js" / "encounter-data.js"
        shop_path = GRAIL / "js" / "location-data.js"
        encounter, _, _ = parse_file_constant(encounter_path, "ENCOUNTER_DEFINITIONS")
        shop, _, _ = parse_file_constant(shop_path, "SHOP_DEFINITIONS")
        encounter_round_trip = JsValueParser(serialize_js(encounter.value)).parse()
        shop_round_trip = JsValueParser(serialize_js(shop.value)).parse()
        self.assertEqual(encounter_round_trip, encounter.value)
        self.assertEqual(shop_round_trip, shop.value)

    def temporary_grail(self):
        temp = tempfile.TemporaryDirectory(prefix="grail-content-editor-")
        destination = Path(temp.name) / "Grail"
        shutil.copytree(GRAIL, destination)
        return temp, destination

    def test_encounter_edit_writes_and_parses_back(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before = load_catalog(project)
        incoming = {
            "encounters": clone(before["encounters"]),
            "shops": clone(before["shops"]),
        }
        incoming["encounters"]["fallen_tree"]["title"] = "Fallen Tree (Editor Test)"
        result = save_catalog(project, incoming, before["sourceHashes"], Path(temp.name) / "backups")
        self.assertTrue(any(item["file"] == "js/encounter-data.js" and item["status"] == "updated" for item in result["saveResults"]))
        after = load_catalog(project)
        self.assertEqual(after["encounters"]["fallen_tree"]["title"], "Fallen Tree (Editor Test)")
        self.assertTrue(list((Path(temp.name) / "backups").glob("encounter-data.js.*.bak")))

    def test_existing_encounter_scalar_edit_is_surgical(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before_parsed, before_source, _ = parse_file_constant(project / "js" / "encounter-data.js", "ENCOUNTER_DEFINITIONS")
        before_blocks = constant_property_blocks(before_source, before_parsed)
        before_order = [property_span.key for property_span in before_parsed.properties]
        before_target = next(property_span for property_span in before_parsed.properties if property_span.key == "fallen_tree")

        catalog = load_catalog(project)
        incoming = {"encounters": clone(catalog["encounters"]), "shops": clone(catalog["shops"])}
        old_description = incoming["encounters"]["fallen_tree"]["description"]
        new_description = old_description + " (surgical test)"
        incoming["encounters"]["fallen_tree"]["description"] = new_description
        save_catalog(project, incoming, catalog["sourceHashes"], Path(temp.name) / "backups")

        after_parsed, after_source, _ = parse_file_constant(project / "js" / "encounter-data.js", "ENCOUNTER_DEFINITIONS")
        after_blocks = constant_property_blocks(after_source, after_parsed)
        after_order = [property_span.key for property_span in after_parsed.properties]
        after_target = next(property_span for property_span in after_parsed.properties if property_span.key == "fallen_tree")
        self.assertEqual(after_parsed.value["fallen_tree"]["description"], new_description)
        self.assertEqual(after_order, before_order)
        self.assertEqual(after_order.index("fallen_tree"), before_order.index("fallen_tree"))
        self.assertEqual({key: after_blocks[key] for key in before_blocks if key != "fallen_tree"}, {key: before_blocks[key] for key in before_blocks if key != "fallen_tree"})
        self.assertEqual(before_source[:before_target.key_start], after_source[:after_target.key_start])
        self.assertEqual(before_source[before_target.value_end:], after_source[after_target.value_end:])

        diff = "\n".join(difflib.unified_diff(before_source.splitlines(), after_source.splitlines(), n=0))
        changed_lines = [line for line in diff.splitlines() if (line.startswith("+") or line.startswith("-")) and not line.startswith(("+++", "---"))]
        self.assertEqual(len(changed_lines), 2)
        self.assertIn(old_description, changed_lines[0])
        self.assertIn(new_description, changed_lines[1])
        self.assertNotIn("abandoned_camp", diff)

    def test_fallen_tree_road_to_path_reproduction_is_one_line_localized(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        path = project / "js" / "encounter-data.js"
        source = path.read_bytes()
        road = b'A large fallen tree blocks the road through the forest.'
        path_value = b'A large fallen tree blocks the path through the forest.'
        self.assertIn(path_value, source)
        path.write_bytes(source.replace(path_value, road, 1))

        catalog = load_catalog(project)
        before_source = path.read_text(encoding="utf-8")
        incoming = {"encounters": clone(catalog["encounters"]), "shops": clone(catalog["shops"])}
        incoming["encounters"]["fallen_tree"]["description"] = path_value.decode("utf-8")
        save_catalog(project, incoming, catalog["sourceHashes"], Path(temp.name) / "backups")
        after_source = path.read_text(encoding="utf-8")
        diff = "\n".join(difflib.unified_diff(before_source.splitlines(), after_source.splitlines(), n=0))
        changed_lines = [line for line in diff.splitlines() if (line.startswith("+") or line.startswith("-")) and not line.startswith(("+++", "---"))]
        self.assertEqual(len(changed_lines), 2)
        self.assertIn(road.decode("utf-8"), changed_lines[0])
        self.assertIn(path_value.decode("utf-8"), changed_lines[1])
        self.assertLess(len(diff.splitlines()), 10)
        self.assertEqual(load_catalog(project)["encounters"]["fallen_tree"]["description"], path_value.decode("utf-8"))

    def test_nested_encounter_edit_changes_only_that_definition(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before_parsed, before_source, _ = parse_file_constant(project / "js" / "encounter-data.js", "ENCOUNTER_DEFINITIONS")
        before_blocks = constant_property_blocks(before_source, before_parsed)
        catalog = load_catalog(project)
        incoming = {"encounters": clone(catalog["encounters"]), "shops": clone(catalog["shops"])}
        incoming["encounters"]["fallen_tree"]["stages"]["start"]["choices"][0]["outcomes"][0]["chance"] = 0.35
        save_catalog(project, incoming, catalog["sourceHashes"], Path(temp.name) / "backups")
        after_parsed, after_source, _ = parse_file_constant(project / "js" / "encounter-data.js", "ENCOUNTER_DEFINITIONS")
        after_blocks = constant_property_blocks(after_source, after_parsed)
        self.assertEqual(after_parsed.value["fallen_tree"]["stages"]["start"]["choices"][0]["outcomes"][0]["chance"], 0.35)
        for key in before_blocks:
            if key != "fallen_tree":
                self.assertEqual(after_blocks[key], before_blocks[key], key)

    def test_added_encounter_is_appended_without_rewriting_existing_blocks(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before = load_catalog(project)
        before_parsed, before_source, _ = parse_file_constant(project / "js" / "encounter-data.js", "ENCOUNTER_DEFINITIONS")
        before_blocks = constant_property_blocks(before_source, before_parsed)
        test_id = "__content_editor_added_encounter"
        new_encounter = {
            "id": test_id,
            "title": "Editor Test Encounter",
            "description": "Temporary fixture content.",
            "regionId": "broceliande",
            "pathIds": ["old_forest_road"],
            "directions": ["outbound"],
            "weight": 1,
            "minimumDistance": 1,
            "tags": ["test"],
            "repeatable": False,
            "requirements": [],
            "stages": {"start": {"text": "A test stage.", "choices": [{"id": "leave", "label": "Leave", "endEncounter": True}]}},
        }
        incoming = {"encounters": clone(before["encounters"]), "shops": clone(before["shops"])}
        incoming["encounters"][test_id] = new_encounter
        save_catalog(project, incoming, before["sourceHashes"], Path(temp.name) / "backups")
        after_parsed, after_source, _ = parse_file_constant(project / "js" / "encounter-data.js", "ENCOUNTER_DEFINITIONS")
        after_blocks = constant_property_blocks(after_source, after_parsed)
        after_order = [property_span.key for property_span in after_parsed.properties]
        before_order = [property_span.key for property_span in before_parsed.properties]
        self.assertEqual(after_order[:-1], before_order)
        self.assertEqual(after_order[-1], test_id)
        self.assertEqual(after_parsed.value[test_id], new_encounter)
        for key, block in before_blocks.items():
            self.assertEqual(after_blocks[key], block, key)

    def test_deleted_encounter_removes_only_that_definition(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        test_id = "__content_editor_deleted_encounter"
        before = load_catalog(project)
        new_encounter = {
            "id": test_id,
            "title": "Editor Delete Fixture",
            "description": "Temporary fixture content.",
            "regionId": "broceliande",
            "pathIds": ["old_forest_road"],
            "directions": ["outbound"],
            "weight": 1,
            "minimumDistance": 1,
            "tags": ["test"],
            "repeatable": False,
            "requirements": [],
            "stages": {"start": {"text": "A test stage.", "choices": [{"id": "leave", "label": "Leave", "endEncounter": True}]}},
        }
        added = {"encounters": clone(before["encounters"]), "shops": clone(before["shops"])}
        added["encounters"][test_id] = new_encounter
        save_catalog(project, added, before["sourceHashes"], Path(temp.name) / "backups")
        before_delete = load_catalog(project)
        before_delete_parsed, before_delete_source, _ = parse_file_constant(project / "js" / "encounter-data.js", "ENCOUNTER_DEFINITIONS")
        before_delete_blocks = constant_property_blocks(before_delete_source, before_delete_parsed)
        deleting = {"encounters": clone(before_delete["encounters"]), "shops": clone(before_delete["shops"])}
        del deleting["encounters"][test_id]
        save_catalog(project, deleting, before_delete["sourceHashes"], Path(temp.name) / "backups")
        after_parsed, after_source, _ = parse_file_constant(project / "js" / "encounter-data.js", "ENCOUNTER_DEFINITIONS")
        after_blocks = constant_property_blocks(after_source, after_parsed)
        self.assertNotIn(test_id, after_parsed.value)
        self.assertNotIn(test_id, after_source)
        for key, block in before_delete_blocks.items():
            if key != test_id:
                self.assertEqual(after_blocks[key], block, key)
        self.assertEqual([property_span.key for property_span in after_parsed.properties], [property_span.key for property_span in before_delete_parsed.properties if property_span.key != test_id])

    def test_shop_edit_changes_only_that_shop_definition(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        path = project / "js" / "location-data.js"
        before_shop, before_source, _ = parse_file_constant(path, "SHOP_DEFINITIONS")
        before_blocks = constant_property_blocks(before_source, before_shop)
        before_npcs, _, _ = parse_file_constant(path, "NPC_DEFINITIONS")
        before_locations, _, _ = parse_file_constant(path, "LOCATION_DEFINITIONS")
        catalog = load_catalog(project)
        incoming = {"encounters": clone(catalog["encounters"]), "shops": clone(catalog["shops"])}
        incoming["shops"]["village_general_goods"]["itemsForSale"]["bandages"]["price"] = 19
        save_catalog(project, incoming, catalog["sourceHashes"], Path(temp.name) / "backups")
        after_shop, after_source, _ = parse_file_constant(path, "SHOP_DEFINITIONS")
        after_blocks = constant_property_blocks(after_source, after_shop)
        after_npcs, _, _ = parse_file_constant(path, "NPC_DEFINITIONS")
        after_locations, _, _ = parse_file_constant(path, "LOCATION_DEFINITIONS")
        self.assertEqual(after_shop.value["village_general_goods"]["itemsForSale"]["bandages"]["price"], 19)
        self.assertEqual([property_span.key for property_span in after_shop.properties], [property_span.key for property_span in before_shop.properties])
        for key in before_blocks:
            if key != "village_general_goods":
                self.assertEqual(after_blocks[key], before_blocks[key], key)
        self.assertEqual(after_npcs.value, before_npcs.value)
        self.assertEqual(after_locations.value, before_locations.value)

    def test_shop_price_and_stock_edit_writes_and_parses_back(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before = load_catalog(project)
        incoming = {"encounters": clone(before["encounters"]), "shops": clone(before["shops"])}
        listing = incoming["shops"]["village_general_goods"]["itemsForSale"]["bandages"]
        listing["price"] = 17
        listing["stock"] = 3
        save_catalog(project, incoming, before["sourceHashes"], Path(temp.name) / "backups")
        after = load_catalog(project)
        self.assertEqual(after["shops"]["village_general_goods"]["itemsForSale"]["bandages"], {"price": 17, "stock": 3})

    def test_invalid_item_reference_is_reported(self) -> None:
        catalog = load_catalog(GRAIL)
        incoming = {"encounters": clone(catalog["encounters"]), "shops": clone(catalog["shops"])}
        incoming["shops"]["village_general_goods"]["itemsForSale"]["missing_item"] = {"price": 1}
        validation = validate_catalog(incoming, catalog["known"], catalog["references"])
        self.assertTrue(any("unknown item ID 'missing_item'" in issue["message"] for issue in validation["errors"]))

    def test_unrelated_grail_file_is_not_modified(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        unrelated = project / "js" / "game.js"
        before_hash = hashlib.sha256(unrelated.read_bytes()).hexdigest()
        before = load_catalog(project)
        incoming = {"encounters": clone(before["encounters"]), "shops": clone(before["shops"])}
        incoming["shops"]["village_smithy"]["displayName"] = "Smithy Test"
        save_catalog(project, incoming, before["sourceHashes"], Path(temp.name) / "backups")
        self.assertEqual(hashlib.sha256(unrelated.read_bytes()).hexdigest(), before_hash)

    def test_shop_deletion_reference_is_blocked(self) -> None:
        catalog = load_catalog(GRAIL)
        incoming = {"encounters": clone(catalog["encounters"]), "shops": clone(catalog["shops"])}
        del incoming["shops"]["village_general_goods"]
        validation = validate_catalog(incoming, catalog["known"], catalog["references"])
        self.assertTrue(any("Deleted shop 'village_general_goods'" in issue["message"] for issue in validation["errors"]))

    def test_stale_source_is_rejected(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before = load_catalog(project)
        changed_path = project / "js" / "encounter-data.js"
        changed_path.write_bytes(changed_path.read_bytes() + b"\n")
        incoming = {"encounters": clone(before["encounters"]), "shops": clone(before["shops"])}
        with self.assertRaises(RuntimeError):
            save_catalog(project, incoming, before["sourceHashes"], Path(temp.name) / "backups")

    def test_current_items_load_and_validate(self) -> None:
        catalog = load_catalog(GRAIL)
        self.assertGreaterEqual(len(catalog["items"]), 40)
        self.assertIn("arthur_sword", catalog["items"])
        self.assertIn("pommel_strike", catalog["known"]["abilities"])
        self.assertEqual(catalog["validation"]["errors"], [])

    def test_item_scalar_edit_is_surgical(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        path = project / "js" / "data.js"
        before_parsed, before_source, _ = parse_file_constant(path, "ITEM_DEFINITIONS")
        before_blocks = constant_property_blocks(before_source, before_parsed)
        before_order = [property_span.key for property_span in before_parsed.properties]
        target = next(property_span for property_span in before_parsed.properties if property_span.key == "arthur_sword")
        catalog = load_catalog(project)
        incoming = {"items": clone(catalog["items"])}
        incoming["items"]["arthur_sword"]["name"] = "Iron Longsword (Editor Test)"
        save_catalog(project, incoming, catalog["sourceHashes"], Path(temp.name) / "backups")
        after_parsed, after_source, _ = parse_file_constant(path, "ITEM_DEFINITIONS")
        after_blocks = constant_property_blocks(after_source, after_parsed)
        after_target = next(property_span for property_span in after_parsed.properties if property_span.key == "arthur_sword")
        self.assertEqual(after_parsed.value["arthur_sword"]["name"], "Iron Longsword (Editor Test)")
        self.assertEqual(before_order, [property_span.key for property_span in after_parsed.properties])
        self.assertEqual(before_source[:target.key_start], after_source[:after_target.key_start])
        self.assertEqual(before_source[target.value_end:], after_source[after_target.value_end:])
        for key, block in before_blocks.items():
            if key != "arthur_sword":
                self.assertEqual(after_blocks[key], block, key)

    def test_weapon_stat_edit_round_trips_and_validates(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        catalog = load_catalog(project)
        incoming = {"items": clone(catalog["items"])}
        incoming["items"]["arthur_sword"]["effects"]["combatDamage"] = {"minimum": 11, "maximum": 19}
        incoming["items"]["arthur_sword"]["effects"]["grantedAbilityIds"] = ["pommel_strike", "charge"]
        save_catalog(project, incoming, catalog["sourceHashes"], Path(temp.name) / "backups")
        after = load_catalog(project)
        self.assertEqual(after["items"]["arthur_sword"]["effects"]["combatDamage"], {"minimum": 11, "maximum": 19})
        self.assertEqual(after["items"]["arthur_sword"]["effects"]["grantedAbilityIds"], ["pommel_strike", "charge"])

    def test_item_add_and_duplicate_are_unique_and_surgical(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        catalog = load_catalog(project)
        path = project / "js" / "data.js"
        before_parsed, before_source, _ = parse_file_constant(path, "ITEM_DEFINITIONS")
        before_blocks = constant_property_blocks(before_source, before_parsed)
        new_item = {
            "id": "__content_editor_weapon",
            "name": "Editor Test Blade",
            "description": "Temporary fixture content.",
            "category": "weapon",
            "rarity": "common",
            "tags": ["test"],
            "equippable": True,
            "equipmentSlot": "weapon",
            "carriable": False,
            "consumable": False,
            "effects": {"combatDamage": {"minimum": 3, "maximum": 5}, "grantedAbilityIds": []},
            "questItem": False,
            "unique": False,
        }
        incoming = {"items": clone(catalog["items"])}
        incoming["items"][new_item["id"]] = new_item
        save_catalog(project, incoming, catalog["sourceHashes"], Path(temp.name) / "backups")
        after_add = load_catalog(project)
        duplicate = clone(after_add["items"][new_item["id"]])
        duplicate["id"] = "__content_editor_weapon_copy"
        duplicate["name"] = "Editor Test Blade Copy"
        incoming = {"items": clone(after_add["items"])}
        incoming["items"][duplicate["id"]] = duplicate
        save_catalog(project, incoming, after_add["sourceHashes"], Path(temp.name) / "backups")
        after_parsed, after_source, _ = parse_file_constant(path, "ITEM_DEFINITIONS")
        self.assertEqual(after_parsed.value[duplicate["id"]], duplicate)
        for key, block in before_blocks.items():
            self.assertEqual(constant_property_blocks(after_source, after_parsed)[key], block, key)

    def test_unreferenced_item_delete_is_allowed_and_referenced_delete_is_blocked(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        catalog = load_catalog(project)
        new_item = {
            "id": "__content_editor_delete_me",
            "name": "Delete Me",
            "description": "Temporary fixture content.",
            "category": "valuable",
            "tags": [],
            "equippable": False,
            "equipmentSlot": None,
            "carriable": True,
            "consumable": False,
            "effects": {},
            "questItem": False,
        }
        added = {"items": clone(catalog["items"])}
        added["items"][new_item["id"]] = new_item
        save_catalog(project, added, catalog["sourceHashes"], Path(temp.name) / "backups")
        after_add = load_catalog(project)
        deleting = {"items": clone(after_add["items"])}
        del deleting["items"][new_item["id"]]
        save_catalog(project, deleting, after_add["sourceHashes"], Path(temp.name) / "backups")
        self.assertNotIn(new_item["id"], load_catalog(project)["items"])

        current = load_catalog(project)
        referenced_delete = {"items": clone(current["items"])}
        del referenced_delete["items"]["raw_meat"]
        validation = validate_catalog(referenced_delete, current["known"], current["references"])
        self.assertTrue(any("Unknown item ID 'raw_meat'" in issue["message"] for issue in validation["errors"]))

    def test_item_reference_browser_covers_current_sources(self) -> None:
        catalog = load_catalog(GRAIL)
        raw_meat_sources = {reference["source"] for reference in catalog["references"]["items"] if reference["id"] == "raw_meat"}
        self.assertTrue({"encounters", "lootTables", "campEvents"}.issubset(raw_meat_sources))
        bandages_sources = {reference["source"] for reference in catalog["references"]["items"] if reference["id"] == "bandages"}
        self.assertIn("shops", bandages_sources)
        self.assertIn("recipes", bandages_sources)

    def test_item_ability_and_damage_validation(self) -> None:
        catalog = load_catalog(GRAIL)
        invalid_ability = {"items": clone(catalog["items"])}
        invalid_ability["items"]["arthur_sword"]["effects"]["grantedAbilityIds"] = ["missing_ability"]
        validation = validate_catalog(invalid_ability, catalog["known"], catalog["references"])
        self.assertTrue(any("Unknown combat ability ID 'missing_ability'" in issue["message"] for issue in validation["errors"]))
        invalid_damage = {"items": clone(catalog["items"])}
        invalid_damage["items"]["arthur_sword"]["effects"]["combatDamage"] = {"minimum": 20, "maximum": 2}
        validation = validate_catalog(invalid_damage, catalog["known"], catalog["references"])
        self.assertTrue(any("combatDamage" in issue["message"] for issue in validation["errors"]))

    def test_new_item_can_be_used_by_an_encounter_in_same_save(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        catalog = load_catalog(project)
        item = {
            "id": "__content_editor_encounter_item",
            "name": "Encounter Test Token",
            "description": "Temporary fixture content.",
            "category": "curiosity",
            "tags": [],
            "equippable": False,
            "equipmentSlot": None,
            "carriable": True,
            "consumable": False,
            "effects": {},
            "questItem": False,
        }
        incoming = {"encounters": clone(catalog["encounters"]), "shops": clone(catalog["shops"]), "items": clone(catalog["items"])}
        incoming["items"][item["id"]] = item
        incoming["encounters"]["fallen_tree"]["stages"]["start"]["choices"][2]["requirements"][0]["itemId"] = item["id"]
        save_catalog(project, incoming, catalog["sourceHashes"], Path(temp.name) / "backups")
        after = load_catalog(project)
        self.assertEqual(after["encounters"]["fallen_tree"]["stages"]["start"]["choices"][2]["requirements"][0]["itemId"], item["id"])
        self.assertTrue(any(reference["id"] == item["id"] and reference["source"] == "encounters" for reference in after["references"]["items"]))

    def test_new_item_can_be_added_to_bandit_leader_loot_table(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        catalog = load_catalog(project)
        item = {
            "id": "__content_editor_bandit_drop",
            "name": "Bandit Test Blade",
            "description": "Temporary fixture content.",
            "category": "weapon",
            "rarity": "uncommon",
            "tags": ["test"],
            "equippable": True,
            "equipmentSlot": "weapon",
            "carriable": False,
            "consumable": False,
            "effects": {"combatDamage": {"minimum": 4, "maximum": 7}, "grantedAbilityIds": []},
            "questItem": False,
            "unique": True,
        }
        incoming = {
            "items": clone(catalog["items"]),
            "lootTables": clone(catalog["lootTables"]),
        }
        incoming["items"][item["id"]] = item
        incoming["lootTables"]["bandit_leader_loot"]["entries"].append({"type": "item", "itemId": item["id"], "weight": 1})
        save_catalog(project, incoming, catalog["sourceHashes"], Path(temp.name) / "backups")
        after = load_catalog(project)
        self.assertIn({"type": "item", "itemId": item["id"], "weight": 1}, after["lootTables"]["bandit_leader_loot"]["entries"])
        self.assertTrue(any(reference["id"] == item["id"] and reference["source"] == "lootTables" for reference in after["references"]["items"]))

    def test_current_combat_ability_and_loot_definitions_load(self) -> None:
        catalog = load_catalog(GRAIL)
        self.assertGreaterEqual(len(catalog["combats"]), 7)
        self.assertEqual(len(catalog["abilities"]), 18)
        self.assertEqual(len(catalog["lootTables"]), 15)
        self.assertIn("bandit_leader", catalog["combats"])
        self.assertIn("pommel_strike", catalog["abilities"])
        self.assertIn("bandit_leader_loot", catalog["lootTables"])
        self.assertEqual(catalog["validation"]["errors"], [])

    def test_combat_roster_edit_is_surgical_and_shared_file_save_is_grouped(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        path = project / "js" / "combat-data.js"
        before_combat, before_source, _ = parse_file_constant(path, "COMBAT_DEFINITIONS")
        before_combat_blocks = constant_property_blocks(before_source, before_combat)
        before_ability, _, _ = parse_file_constant(path, "COMBAT_ABILITY_DEFINITIONS")
        before_enemy, _, _ = parse_file_constant(path, "COMBAT_ENEMY_DEFINITIONS")
        catalog = load_catalog(project)
        incoming = {"combats": clone(catalog["combats"]), "enemyDefinitions": clone(catalog["enemyDefinitions"])}
        incoming["combats"]["bandit_leader"]["enemyIds"] = ["bandit_leader", "bandit"]
        incoming["enemyDefinitions"]["bandit_leader"]["maxHp"] = 46
        result = save_catalog(project, incoming, catalog["sourceHashes"], Path(temp.name) / "backups")
        self.assertEqual([entry["file"] for entry in result["saveResults"]], ["js/combat-data.js"])
        after_combat, after_source, _ = parse_file_constant(path, "COMBAT_DEFINITIONS")
        after_ability, _, _ = parse_file_constant(path, "COMBAT_ABILITY_DEFINITIONS")
        after_enemy, _, _ = parse_file_constant(path, "COMBAT_ENEMY_DEFINITIONS")
        self.assertEqual(after_combat.value["bandit_leader"]["enemyIds"], ["bandit_leader", "bandit"])
        self.assertEqual(after_enemy.value["bandit_leader"]["maxHp"], 46)
        self.assertEqual(after_ability.value, before_ability.value)
        for key, block in before_combat_blocks.items():
            if key != "bandit_leader":
                self.assertEqual(constant_property_blocks(after_source, after_combat)[key], block, key)
        self.assertEqual(after_enemy.value["wolf"], before_enemy.value["wolf"])

    def test_nested_enemy_action_edit_is_localized(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        path = project / "js" / "combat-data.js"
        before, before_source, _ = parse_file_constant(path, "COMBAT_ENEMY_ACTION_DEFINITIONS")
        before_blocks = constant_property_blocks(before_source, before)
        catalog = load_catalog(project)
        incoming = {"enemyActions": clone(catalog["enemyActions"])}
        incoming["enemyActions"]["leader_strike"]["damage"]["maximum"] = 14
        save_catalog(project, incoming, catalog["sourceHashes"], Path(temp.name) / "backups")
        after, after_source, _ = parse_file_constant(path, "COMBAT_ENEMY_ACTION_DEFINITIONS")
        self.assertEqual(after.value["leader_strike"]["damage"]["maximum"], 14)
        for key, block in before_blocks.items():
            if key != "leader_strike":
                self.assertEqual(constant_property_blocks(after_source, after)[key], block, key)

    def test_combat_add_and_delete_are_localized(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        path = project / "js" / "combat-data.js"
        catalog = load_catalog(project)
        test_id = "__content_editor_combat"
        new_combat = {"id": test_id, "enemyIds": ["wolf"]}
        added = {"combats": clone(catalog["combats"])}
        added["combats"][test_id] = new_combat
        save_catalog(project, added, catalog["sourceHashes"], Path(temp.name) / "backups")
        after_add = load_catalog(project)
        before_delete, before_delete_source, _ = parse_file_constant(path, "COMBAT_DEFINITIONS")
        before_blocks = constant_property_blocks(before_delete_source, before_delete)
        deleting = {"combats": clone(after_add["combats"])}
        del deleting["combats"][test_id]
        save_catalog(project, deleting, after_add["sourceHashes"], Path(temp.name) / "backups")
        after_delete, after_delete_source, _ = parse_file_constant(path, "COMBAT_DEFINITIONS")
        self.assertNotIn(test_id, after_delete.value)
        self.assertEqual([span.key for span in after_delete.properties], [span.key for span in before_delete.properties if span.key != test_id])
        for key, block in before_blocks.items():
            if key != test_id:
                self.assertEqual(constant_property_blocks(after_delete_source, after_delete)[key], block, key)

    def test_ability_edit_add_and_delete_are_surgical(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        path = project / "js" / "combat-data.js"
        catalog = load_catalog(project)
        before, before_source, _ = parse_file_constant(path, "COMBAT_ABILITY_DEFINITIONS")
        before_blocks = constant_property_blocks(before_source, before)
        incoming = {"abilities": clone(catalog["abilities"])}
        incoming["abilities"]["pommel_strike"]["description"] = "Editor test ability description."
        save_catalog(project, incoming, catalog["sourceHashes"], Path(temp.name) / "backups")
        after = load_catalog(project)
        new_ability = {"id": "__content_editor_ability", "name": "Editor Ability", "description": "Temporary", "target": "enemy", "effectType": "damageAndGauge", "damageMultiplier": 0.5, "gaugeReduction": 4}
        added = {"abilities": clone(after["abilities"])}
        added["abilities"][new_ability["id"]] = new_ability
        save_catalog(project, added, after["sourceHashes"], Path(temp.name) / "backups")
        after_add = load_catalog(project)
        deleting = {"abilities": clone(after_add["abilities"])}
        del deleting["abilities"][new_ability["id"]]
        save_catalog(project, deleting, after_add["sourceHashes"], Path(temp.name) / "backups")
        final, final_source, _ = parse_file_constant(path, "COMBAT_ABILITY_DEFINITIONS")
        self.assertEqual(final.value["pommel_strike"]["description"], "Editor test ability description.")
        self.assertNotIn(new_ability["id"], final.value)
        for key, block in before_blocks.items():
            if key != "pommel_strike":
                self.assertEqual(constant_property_blocks(final_source, final)[key], block, key)

    def test_loot_table_edit_add_and_delete_entry_are_localized(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        path = project / "js" / "loot-data.js"
        catalog = load_catalog(project)
        before, before_source, _ = parse_file_constant(path, "LOOT_TABLE_DEFINITIONS")
        before_blocks = constant_property_blocks(before_source, before)
        incoming = {"lootTables": clone(catalog["lootTables"])}
        incoming["lootTables"]["bandit_leader_loot"]["entries"][1]["weight"] = 9
        save_catalog(project, incoming, catalog["sourceHashes"], Path(temp.name) / "backups")
        after_edit = load_catalog(project)
        self.assertEqual(after_edit["lootTables"]["bandit_leader_loot"]["entries"][1]["weight"], 9)
        add_entry = {"lootTables": clone(after_edit["lootTables"])}
        temporary_entry = {"type": "item", "itemId": "raw_meat", "quantity": 2, "weight": 1}
        add_entry["lootTables"]["bandit_leader_loot"]["entries"].append(temporary_entry)
        save_catalog(project, add_entry, after_edit["sourceHashes"], Path(temp.name) / "backups")
        after_add = load_catalog(project)
        self.assertIn(temporary_entry, after_add["lootTables"]["bandit_leader_loot"]["entries"])
        delete_entry = {"lootTables": clone(after_add["lootTables"])}
        delete_entry["lootTables"]["bandit_leader_loot"]["entries"].pop()
        save_catalog(project, delete_entry, after_add["sourceHashes"], Path(temp.name) / "backups")
        final, final_source, _ = parse_file_constant(path, "LOOT_TABLE_DEFINITIONS")
        self.assertNotIn(temporary_entry, final.value["bandit_leader_loot"]["entries"])
        for key, block in before_blocks.items():
            if key != "bandit_leader_loot":
                self.assertEqual(constant_property_blocks(final_source, final)[key], block, key)

    def test_current_start_combat_branches_parse_as_typed_resolution_data(self) -> None:
        catalog = load_catalog(GRAIL)
        start_combat = catalog["encounters"]["bandit_leader"]["stages"]["start"]["choices"][0]["outcomes"][0]
        self.assertEqual(start_combat["type"], "startCombat")
        self.assertEqual(start_combat["combatId"], "bandit_leader")
        self.assertEqual(start_combat["victory"]["outcomes"][0], {"type": "rollLootTable", "tableId": "bandit_leader_loot", "rolls": 2})
        self.assertIn("resultText", start_combat["victory"])
        self.assertEqual(start_combat["fled"]["outcomes"], [])
        self.assertIn("resultText", start_combat["fled"])

    def test_start_combat_loot_roll_edit_is_localized_and_does_not_touch_other_sources(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        catalog = load_catalog(project)
        encounter_path = project / "js" / "encounter-data.js"
        combat_path = project / "js" / "combat-data.js"
        loot_path = project / "js" / "loot-data.js"
        before_parsed, before_source, _ = parse_file_constant(encounter_path, "ENCOUNTER_DEFINITIONS")
        before_blocks = constant_property_blocks(before_source, before_parsed)
        combat_before = combat_path.read_bytes()
        loot_before = loot_path.read_bytes()
        incoming = {"encounters": clone(catalog["encounters"])}
        outcome = incoming["encounters"]["bandit_leader"]["stages"]["start"]["choices"][0]["outcomes"][0]
        outcome["victory"]["outcomes"][0]["rolls"] = 3
        save_catalog(project, incoming, catalog["sourceHashes"], Path(temp.name) / "backups")
        after_parsed, after_source, _ = parse_file_constant(encounter_path, "ENCOUNTER_DEFINITIONS")
        after_blocks = constant_property_blocks(after_source, after_parsed)
        self.assertEqual(after_parsed.value["bandit_leader"]["stages"]["start"]["choices"][0]["outcomes"][0]["victory"]["outcomes"][0]["rolls"], 3)
        for key, block in before_blocks.items():
            if key != "bandit_leader":
                self.assertEqual(after_blocks[key], block, key)
        self.assertEqual(combat_path.read_bytes(), combat_before)
        self.assertEqual(loot_path.read_bytes(), loot_before)

    def test_start_combat_loot_table_reference_edit_validates_and_writes_locally(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        catalog = load_catalog(project)
        encounter_path = project / "js" / "encounter-data.js"
        before_parsed, before_source, _ = parse_file_constant(encounter_path, "ENCOUNTER_DEFINITIONS")
        before_blocks = constant_property_blocks(before_source, before_parsed)
        incoming = {"encounters": clone(catalog["encounters"])}
        outcome = incoming["encounters"]["bandit_leader"]["stages"]["start"]["choices"][0]["outcomes"][0]
        outcome["victory"]["outcomes"][0]["tableId"] = "bandit_ambush_loot"
        validation = validate_catalog(incoming, catalog["known"], catalog["references"])
        self.assertEqual(validation["errors"], [])
        save_catalog(project, incoming, catalog["sourceHashes"], Path(temp.name) / "backups")
        after_parsed, after_source, _ = parse_file_constant(encounter_path, "ENCOUNTER_DEFINITIONS")
        self.assertEqual(after_parsed.value["bandit_leader"]["stages"]["start"]["choices"][0]["outcomes"][0]["victory"]["outcomes"][0]["tableId"], "bandit_ambush_loot")
        after_blocks = constant_property_blocks(after_source, after_parsed)
        for key, block in before_blocks.items():
            if key != "bandit_leader":
                self.assertEqual(after_blocks[key], block, key)
        invalid = {"encounters": clone(catalog["encounters"])}
        invalid["encounters"]["bandit_leader"]["stages"]["start"]["choices"][0]["outcomes"][0]["victory"]["outcomes"][0]["tableId"] = "missing_loot_table"
        invalid_validation = validate_catalog(invalid, catalog["known"], catalog["references"])
        self.assertTrue(any("Unknown loot table ID 'missing_loot_table'" in issue["message"] for issue in invalid_validation["errors"]))

    def test_start_combat_victory_item_outcome_add_and_remove_are_localized(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        catalog = load_catalog(project)
        encounter_path = project / "js" / "encounter-data.js"
        before_parsed, before_source, _ = parse_file_constant(encounter_path, "ENCOUNTER_DEFINITIONS")
        before_blocks = constant_property_blocks(before_source, before_parsed)
        incoming = {"encounters": clone(catalog["encounters"])}
        victory_outcomes = incoming["encounters"]["bandit_leader"]["stages"]["start"]["choices"][0]["outcomes"][0]["victory"]["outcomes"]
        added = {"type": "gainUnsecuredItem", "itemId": "raw_meat", "quantity": 1}
        victory_outcomes.append(added)
        save_catalog(project, incoming, catalog["sourceHashes"], Path(temp.name) / "backups")
        after_add = load_catalog(project)
        self.assertIn(added, after_add["encounters"]["bandit_leader"]["stages"]["start"]["choices"][0]["outcomes"][0]["victory"]["outcomes"])
        remove = {"encounters": clone(after_add["encounters"])}
        remove["encounters"]["bandit_leader"]["stages"]["start"]["choices"][0]["outcomes"][0]["victory"]["outcomes"].pop()
        save_catalog(project, remove, after_add["sourceHashes"], Path(temp.name) / "backups")
        final_parsed, final_source, _ = parse_file_constant(encounter_path, "ENCOUNTER_DEFINITIONS")
        self.assertNotIn(added, final_parsed.value["bandit_leader"]["stages"]["start"]["choices"][0]["outcomes"][0]["victory"]["outcomes"])
        final_blocks = constant_property_blocks(final_source, final_parsed)
        for key, block in before_blocks.items():
            if key != "bandit_leader":
                self.assertEqual(final_blocks[key], block, key)

    def test_start_combat_fled_result_text_edit_is_localized(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        catalog = load_catalog(project)
        encounter_path = project / "js" / "encounter-data.js"
        before_parsed, before_source, _ = parse_file_constant(encounter_path, "ENCOUNTER_DEFINITIONS")
        before_blocks = constant_property_blocks(before_source, before_parsed)
        incoming = {"encounters": clone(catalog["encounters"])}
        fled = incoming["encounters"]["bandit_leader"]["stages"]["start"]["choices"][0]["outcomes"][0]["fled"]
        fled["resultText"] = "The company withdraws in an editor fixture."
        save_catalog(project, incoming, catalog["sourceHashes"], Path(temp.name) / "backups")
        after_parsed, after_source, _ = parse_file_constant(encounter_path, "ENCOUNTER_DEFINITIONS")
        self.assertEqual(after_parsed.value["bandit_leader"]["stages"]["start"]["choices"][0]["outcomes"][0]["fled"]["resultText"], fled["resultText"])
        after_blocks = constant_property_blocks(after_source, after_parsed)
        for key, block in before_blocks.items():
            if key != "bandit_leader":
                self.assertEqual(after_blocks[key], block, key)

    def test_start_combat_invalid_direct_item_reward_is_reported(self) -> None:
        catalog = load_catalog(GRAIL)
        incoming = {"encounters": clone(catalog["encounters"])}
        incoming["encounters"]["bandit_leader"]["stages"]["start"]["choices"][0]["outcomes"][0]["victory"]["outcomes"].append({"type": "gainUnsecuredItem", "itemId": "missing_item", "quantity": 0})
        validation = validate_catalog(incoming, catalog["known"], catalog["references"])
        messages = [issue["message"] for issue in validation["errors"]]
        self.assertTrue(any("Unknown item ID 'missing_item'" in message for message in messages))
        self.assertTrue(any("Item quantity must be a positive integer" in message for message in messages))

    def test_nested_combat_resolution_references_are_used_by_and_preserve_unknown_fields(self) -> None:
        catalog = load_catalog(GRAIL)
        loot_refs = [reference for reference in catalog["references"]["lootTables"] if reference["id"] == "bandit_leader_loot"]
        item_refs = [reference for reference in catalog["references"]["items"] if reference["id"] == "raw_meat"]
        self.assertTrue(any(reference["source"] == "encounters" and ".victory.outcomes" in reference["path"] for reference in loot_refs))
        self.assertTrue(any(reference["source"] == "encounters" and ".victory.outcomes" in reference["path"] for reference in item_refs))
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        catalog = load_catalog(project)
        incoming = {"encounters": clone(catalog["encounters"])}
        victory = incoming["encounters"]["bandit_leader"]["stages"]["start"]["choices"][0]["outcomes"][0]["victory"]
        victory["uncommonResolutionField"] = {"preserve": True, "value": 17}
        victory["outcomes"][0]["rolls"] = 4
        save_catalog(project, incoming, catalog["sourceHashes"], Path(temp.name) / "backups")
        after = load_catalog(project)
        saved_victory = after["encounters"]["bandit_leader"]["stages"]["start"]["choices"][0]["outcomes"][0]["victory"]
        self.assertEqual(saved_victory["uncommonResolutionField"], {"preserve": True, "value": 17})
        self.assertEqual(saved_victory["outcomes"][0]["rolls"], 4)

    def test_combat_ability_and_loot_reference_validation_and_used_by(self) -> None:
        catalog = load_catalog(GRAIL)
        self.assertTrue(any(reference["source"] == "encounters" for reference in catalog["references"]["combats"] if reference["id"] == "bandit_leader"))
        self.assertTrue(any(reference["source"] == "items" for reference in catalog["references"]["abilities"] if reference["id"] == "pommel_strike"))
        self.assertTrue(any(reference["source"] == "encounters" for reference in catalog["references"]["lootTables"] if reference["id"] == "bandit_leader_loot"))
        invalid_ability = {"abilities": clone(catalog["abilities"]), "combats": clone(catalog["combats"]), "enemyDefinitions": clone(catalog["enemyDefinitions"])}
        invalid_ability["items"] = clone(catalog["items"])
        invalid_ability["items"]["arthur_sword"]["effects"]["grantedAbilityIds"] = ["missing_ability"]
        validation = validate_catalog(invalid_ability, catalog["known"], catalog["references"])
        self.assertTrue(any("Unknown ability ID 'missing_ability'" in issue["message"] for issue in validation["errors"]))
        invalid_table = {"lootTables": clone(catalog["lootTables"])}
        invalid_table["lootTables"]["forest_materials"]["entries"].append({"type": "table", "tableId": "missing_table", "weight": 1})
        validation = validate_catalog(invalid_table, catalog["known"], catalog["references"])
        self.assertTrue(any("Unknown loot table ID 'missing_table'" in issue["message"] for issue in validation["errors"]))

    def test_referenced_combat_ability_and_loot_deletions_are_blocked(self) -> None:
        catalog = load_catalog(GRAIL)
        without_combat = {"combats": clone(catalog["combats"]), "items": clone(catalog["items"]), "lootTables": clone(catalog["lootTables"])}
        del without_combat["combats"]["bandit_leader"]
        validation = validate_catalog(without_combat, catalog["known"], catalog["references"])
        self.assertTrue(any("Unknown combat ID 'bandit_leader'" in issue["message"] for issue in validation["errors"]))
        without_ability = {"abilities": clone(catalog["abilities"]), "items": clone(catalog["items"])}
        del without_ability["abilities"]["pommel_strike"]
        validation = validate_catalog(without_ability, catalog["known"], catalog["references"])
        self.assertTrue(any("Unknown ability ID 'pommel_strike'" in issue["message"] for issue in validation["errors"]))
        without_table = {"lootTables": clone(catalog["lootTables"]), "encounters": clone(catalog["encounters"])}
        del without_table["lootTables"]["bandit_leader_loot"]
        validation = validate_catalog(without_table, catalog["known"], catalog["references"])
        self.assertTrue(any("Unknown loot table ID 'bandit_leader_loot'" in issue["message"] for issue in validation["errors"]))

    def test_new_ability_and_item_reference_validate_in_memory_without_reload(self) -> None:
        catalog = load_catalog(GRAIL)
        ability_id = "__content_editor_memory_ability"
        incoming = {"abilities": clone(catalog["abilities"]), "items": clone(catalog["items"])}
        incoming["abilities"][ability_id] = {"id": ability_id, "name": "Memory Ability", "target": "enemy", "effectType": "damageAndGauge", "damageMultiplier": 0.8, "gaugeReduction": 3}
        incoming["items"]["arthur_sword"]["effects"]["grantedAbilityIds"].append(ability_id)
        validation = validate_catalog(incoming, catalog["known"], catalog["references"])
        self.assertFalse(any("Unknown ability ID" in issue["message"] for issue in validation["errors"]))

    def test_phase4_loads_expeditions_and_derives_paths_from_live_memberships(self) -> None:
        catalog = load_catalog(GRAIL)
        self.assertEqual(set(catalog["expeditions"]), {"old_forest_road", "fountain_of_barenton", "val_sans_retour", "search_for_merlin"})
        self.assertEqual(set(catalog["paths"]), {"old_forest_road", "overgrown_trail", "fountain_of_barenton", "val_sans_retour", "search_for_merlin", "legacy_fountain"})
        fountain = catalog["paths"]["fountain_of_barenton"]
        self.assertTrue(fountain["derived"])
        self.assertEqual(fountain["encounterCount"], 21)
        self.assertEqual(fountain["expeditionIds"], ["fountain_of_barenton"])
        self.assertEqual(catalog["expeditions"]["fountain_of_barenton"]["pathId"], "fountain_of_barenton")
        self.assertFalse(catalog["validation"]["errors"])

    def test_phase4_path_membership_add_and_remove_preserve_other_memberships(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before = load_catalog(project)
        incoming = {"encounters": clone(before["encounters"])}
        existing = incoming["encounters"]["abandoned_camp"]["pathIds"]
        incoming["encounters"]["abandoned_camp"]["pathIds"] = existing + ["fountain_of_barenton"]
        save_catalog(project, incoming, before["sourceHashes"], Path(temp.name) / "backups")
        after_add = load_catalog(project)
        self.assertEqual(after_add["encounters"]["abandoned_camp"]["pathIds"], ["old_forest_road", "overgrown_trail", "fountain_of_barenton"])
        self.assertEqual(after_add["paths"]["fountain_of_barenton"]["encounterCount"], 22)

        removing = {"encounters": clone(after_add["encounters"])}
        removing["encounters"]["abandoned_camp"]["pathIds"].remove("fountain_of_barenton")
        save_catalog(project, removing, after_add["sourceHashes"], Path(temp.name) / "backups")
        after_remove = load_catalog(project)
        self.assertEqual(after_remove["encounters"]["abandoned_camp"]["pathIds"], ["old_forest_road", "overgrown_trail"])
        self.assertEqual(after_remove["paths"]["fountain_of_barenton"]["encounterCount"], 21)

    def test_phase4_expedition_scalar_edit_is_surgical_and_preserves_unknown_fields(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        path = project / "js" / "expedition-data.js"
        before_parsed, before_source, _ = parse_file_constant(path, "EXPEDITION_DEFINITIONS")
        before_blocks = constant_property_blocks(before_source, before_parsed)
        catalog = load_catalog(project)
        incoming = {"expeditions": clone(catalog["expeditions"])}
        incoming["expeditions"]["fountain_of_barenton"]["name"] = "Fountain of Barenton (Editor Test)"
        incoming["expeditions"]["fountain_of_barenton"]["editorOnlyMetadata"] = {"keep": True}
        save_catalog(project, incoming, catalog["sourceHashes"], Path(temp.name) / "backups")
        after_parsed, after_source, _ = parse_file_constant(path, "EXPEDITION_DEFINITIONS")
        after_blocks = constant_property_blocks(after_source, after_parsed)
        self.assertEqual(after_parsed.value["fountain_of_barenton"]["name"], "Fountain of Barenton (Editor Test)")
        self.assertEqual(after_parsed.value["fountain_of_barenton"]["editorOnlyMetadata"], {"keep": True})
        for key in before_blocks:
            if key != "fountain_of_barenton":
                self.assertEqual(after_blocks[key], before_blocks[key], key)

    def test_distance_based_travel_scenes_validate_and_round_trip(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        catalog = load_catalog(project)
        expedition_assets = sorted(
            asset_id for asset_id, asset in catalog["imageAssets"].items()
            if asset.get("category") == "expedition"
        )
        self.assertTrue(expedition_assets)
        expedition_id = "fountain_of_barenton"
        incoming = {"expeditions": clone(catalog["expeditions"]), "imageAssets": clone(catalog["imageAssets"])}
        incoming["expeditions"][expedition_id]["travelScenes"] = [
            {"minDistance": 0, "visualAssetId": expedition_assets[0], "motion": "loop"},
            {"minDistance": 40, "visualAssetId": expedition_assets[-1], "motion": "pan"},
        ]
        incoming["expeditions"][expedition_id]["travelTransitionAssetId"] = expedition_assets[0]
        validation = validate_catalog(incoming, catalog["known"], catalog["references"], project_root=project)
        self.assertFalse(validation["errors"])
        save_catalog(project, incoming, catalog["sourceHashes"], Path(temp.name) / "backups")
        self.assertEqual(
            load_catalog(project)["expeditions"][expedition_id]["travelScenes"],
            incoming["expeditions"][expedition_id]["travelScenes"],
        )
        self.assertEqual(
            load_catalog(project)["expeditions"][expedition_id]["travelTransitionAssetId"],
            expedition_assets[0],
        )

        invalid = clone(incoming)
        invalid["expeditions"][expedition_id]["travelScenes"] = [
            {"minDistance": 40, "visualAssetId": expedition_assets[0]},
            {"minDistance": 40, "visualAssetId": "missing_expedition_scene"},
            {"minDistance": 20, "visualAssetId": expedition_assets[-1]},
            {"minDistance": -1, "visualAssetId": expedition_assets[-1], "motion": "teleport"},
        ]
        invalid_validation = validate_catalog(invalid, catalog["known"], catalog["references"], project_root=project)
        messages = [issue["message"] for issue in invalid_validation["errors"]]
        self.assertTrue(any("duplicated" in message for message in messages))
        self.assertTrue(any("sorted" in message for message in messages))
        self.assertTrue(any("non-negative" in message for message in messages))
        self.assertTrue(any("Unknown image asset ID 'missing_expedition_scene'" in message for message in messages))
        self.assertTrue(any("motion must be 'loop' or 'pan'" in message for message in messages))

    def test_phase4_path_and_expedition_references_validate_and_protect_deletion(self) -> None:
        catalog = load_catalog(GRAIL)
        invalid_encounters = {"encounters": clone(catalog["encounters"])}
        invalid_encounters["encounters"]["fallen_tree"]["pathIds"] = ["missing_path"]
        validation = validate_catalog(invalid_encounters, catalog["known"], catalog["references"])
        self.assertTrue(any("Unknown path ID 'missing_path'" in issue["message"] for issue in validation["errors"]))

        invalid_expeditions = {"expeditions": clone(catalog["expeditions"])}
        invalid_expeditions["expeditions"]["fountain_of_barenton"]["pathId"] = "missing_path"
        validation = validate_catalog(invalid_expeditions, catalog["known"], catalog["references"])
        self.assertTrue(any("Unknown path ID 'missing_path'" in issue["message"] for issue in validation["errors"]))

        without_expedition = {"expeditions": clone(catalog["expeditions"])}
        del without_expedition["expeditions"]["fountain_of_barenton"]
        validation = validate_catalog(without_expedition, catalog["known"], catalog["references"])
        self.assertTrue(any("Unknown expedition ID 'fountain_of_barenton'" in issue["message"] for issue in validation["errors"]))

    def test_phase4_derived_path_index_is_stable_when_rebuilt(self) -> None:
        catalog = load_catalog(GRAIL)
        first = build_path_index(catalog["encounters"], catalog["expeditions"])
        second = build_path_index(catalog["encounters"], catalog["expeditions"])
        self.assertEqual(first, second)
        self.assertEqual(first["fountain_of_barenton"]["encounterCount"], 21)

    def test_phase5_current_recipe_and_provider_shapes_load(self) -> None:
        catalog = load_catalog(GRAIL)
        self.assertGreaterEqual(len(catalog["recipes"]), 9)
        self.assertEqual(set(catalog["craftingProviders"]), {"apothecary", "blacksmith", "campfire"})
        self.assertEqual(catalog["recipes"]["roasted_meat"]["ingredients"], [{"type": "item", "id": "raw_meat", "quantity": 1}])
        self.assertEqual(catalog["recipes"]["roasted_meat"]["output"], {"provisions": 3})
        self.assertEqual(catalog["recipes"]["repair_kit"]["output"], {"itemId": "repair_kit", "quantity": 1})
        self.assertFalse(catalog["validation"]["errors"])

    def test_phase7_mixed_recipe_and_legacy_ingredient_normalization_validate(self) -> None:
        catalog = load_catalog(GRAIL)
        mixed = clone(catalog["recipes"]["threefold_seal"])
        self.assertEqual(
            mixed["ingredients"],
            [
                {"type": "item", "id": "white_stag_shard", "quantity": 1},
                {"type": "item", "id": "barenton_stone", "quantity": 1},
                {"type": "item", "id": "black_glass_tear", "quantity": 1},
                {"type": "material", "id": "silver", "quantity": 2},
                {"type": "material", "id": "sacred_oil", "quantity": 1},
            ],
        )
        incoming = {"recipes": clone(catalog["recipes"])}
        incoming["recipes"]["mixed_fixture"] = {
            "id": "mixed_fixture", "name": "Mixed Fixture", "description": "A mixed source fixture.",
            "craftingProvider": "blacksmith", "ingredients": [
                {"type": "item", "id": "white_stag_shard", "quantity": 1},
                {"type": "material", "id": "silver", "quantity": 2},
            ], "output": {"itemId": "threefold_seal", "quantity": 1}, "goldCost": 0, "rarity": "rare",
        }
        validation = validate_catalog(incoming, catalog["known"], catalog["references"])
        self.assertFalse(validation["errors"])
        references = {}
        collect_references(incoming["recipes"], "recipes", references)
        self.assertTrue(any(entry["id"] == "white_stag_shard" for entry in references["items"]))
        self.assertTrue(any(entry["id"] == "silver" for entry in references["materials"]))
        legacy = {"id": "legacy_fixture", "name": "Legacy Fixture", "description": "Compatibility.",
                  "craftingProvider": "blacksmith", "ingredientType": "item", "ingredients": {"rusted_sword": 1},
                  "output": {"itemId": "glimmering_sword", "quantity": 1}, "goldCost": 0, "rarity": "rare"}
        legacy_catalog = clone(catalog["recipes"])
        legacy_catalog["legacy_fixture"] = legacy
        validation = validate_catalog({"recipes": legacy_catalog}, catalog["known"], catalog["references"])
        self.assertFalse(validation["errors"])
        malformed = clone(catalog["recipes"])
        malformed["malformed_fixture"] = {**clone(mixed), "id": "malformed_fixture", "ingredients": [{"type": "item", "id": {"bad": True}, "quantity": 1}]}
        validation = validate_catalog({"recipes": malformed}, catalog["known"], catalog["references"])
        self.assertTrue(any("Recipe ingredients need an id" in issue["message"] for issue in validation["errors"]))

    def test_phase7_structured_active_and_passive_ability_round_trip(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before = load_catalog(project)
        active_id = "__content_editor_phase7_active"
        passive_id = "__content_editor_phase7_passive"
        incoming = {"abilities": clone(before["abilities"])}
        incoming["abilities"][active_id] = {
            "id": active_id, "name": "Structured Active", "description": "Multiple effects.",
            "kind": "active", "tags": ["faith", "test"], "target": "enemy", "targetMode": "singleEnemy",
            "cost": {"resource": "faith", "amount": 2}, "cooldownActivations": 2, "chargesPerCombat": 1,
            "effects": [
                {"type": "dealDamage", "amount": 4},
                {"type": "conditional", "condition": {"targetHealthBelowPercent": 0.5}, "effects": [{"type": "applyStatus", "statusId": "bleeding", "chance": 0.5}], "elseEffects": [{"type": "modifyGauge", "target": "target", "amount": -10}]},
            ],
        }
        incoming["abilities"][passive_id] = {
            "id": passive_id, "name": "Structured Passive", "description": "Event trigger.", "kind": "passive",
            "tags": ["faith"], "trigger": {"event": "enemyDefeated", "oncePerCombat": True,
            "conditions": {"all": [{"sourceSide": "ally"}, {"chance": 1}]},
            "effects": [{"type": "modifyResource", "resource": "faith", "amount": 1}]},
        }
        validation = validate_catalog(incoming, before["known"], before["references"])
        self.assertFalse(validation["errors"])
        save_catalog(project, incoming, before["sourceHashes"], Path(temp.name) / "backups")
        after = load_catalog(project)
        self.assertEqual(after["abilities"][active_id]["effects"][1]["elseEffects"][0]["amount"], -10)
        self.assertEqual(after["abilities"][passive_id]["trigger"]["event"], "enemyDefeated")
        invalid = {"abilities": clone(after["abilities"])}
        invalid["abilities"][active_id]["effects"][1]["effects"][0]["statusId"] = "missing_status"
        self.assertTrue(validate_catalog(invalid, after["known"], after["references"])["errors"])

    def test_phase5_recipe_scalar_and_unknown_field_edits_are_surgical(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        path = project / "js" / "crafting-data.js"
        before_parsed, before_source, _ = parse_file_constant(path, "RECIPE_DEFINITIONS")
        before_blocks = constant_property_blocks(before_source, before_parsed)
        catalog = load_catalog(project)
        incoming = {"recipes": clone(catalog["recipes"])}
        incoming["recipes"]["repair_kit"]["name"] = "Repair Kit (Editor Test)"
        incoming["recipes"]["repair_kit"]["editorOnlyMetadata"] = {"preserve": True}
        save_catalog(project, incoming, catalog["sourceHashes"], Path(temp.name) / "backups")
        after_parsed, after_source, _ = parse_file_constant(path, "RECIPE_DEFINITIONS")
        after_blocks = constant_property_blocks(after_source, after_parsed)
        self.assertEqual(after_parsed.value["repair_kit"]["name"], "Repair Kit (Editor Test)")
        self.assertEqual(after_parsed.value["repair_kit"]["editorOnlyMetadata"], {"preserve": True})
        for key in before_blocks:
            if key != "repair_kit":
                self.assertEqual(after_blocks[key], before_blocks[key], key)

    def test_phase5_recipe_ingredient_quantity_add_remove_and_output_edit(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before = load_catalog(project)
        incoming = {"recipes": clone(before["recipes"])}
        recipe = incoming["recipes"]["repair_kit"]
        recipe["ingredients"] = [
            {"type": "material", "id": "iron", "quantity": 3},
            {"type": "material", "id": "leather", "quantity": 1},
            {"type": "material", "id": "silver", "quantity": 1},
        ]
        recipe["output"] = {"itemId": "reinforced_mail", "quantity": 1}
        save_catalog(project, incoming, before["sourceHashes"], Path(temp.name) / "backups")
        after = load_catalog(project)
        self.assertEqual(after["recipes"]["repair_kit"]["ingredients"], [
            {"type": "material", "id": "iron", "quantity": 3},
            {"type": "material", "id": "leather", "quantity": 1},
            {"type": "material", "id": "silver", "quantity": 1},
        ])
        self.assertEqual(after["recipes"]["repair_kit"]["output"], {"itemId": "reinforced_mail", "quantity": 1})

    def test_phase5_new_equipment_recipe_fixture_validates_and_round_trips(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before = load_catalog(project)
        incoming = {"items": clone(before["items"]), "recipes": clone(before["recipes"])}
        item_id = "__content_editor_test_equipment"
        recipe_id = "__content_editor_test_equipment_recipe"
        incoming["items"][item_id] = {
            "id": item_id, "name": "Test Equipment", "description": "Temporary fixture.",
            "category": "weapon", "rarity": "common", "tags": ["test"],
            "equippable": True, "equipmentSlot": "weapon", "carriable": False,
            "consumable": False, "effects": {"combatDamage": {"minimum": 2, "maximum": 3}},
        }
        incoming["recipes"][recipe_id] = {
            "id": recipe_id, "name": "Test Equipment Recipe", "description": "Temporary fixture.",
            "craftingProvider": "blacksmith", "ingredients": [
                {"type": "material", "id": "iron", "quantity": 2},
                {"type": "material", "id": "leather", "quantity": 1},
            ],
            "output": {"itemId": item_id, "quantity": 1}, "goldCost": 1, "rarity": "common",
        }
        validation = validate_catalog(incoming, before["known"], before["references"])
        self.assertFalse(validation["errors"])
        save_catalog(project, incoming, before["sourceHashes"], Path(temp.name) / "backups")
        after = load_catalog(project)
        self.assertEqual(after["recipes"][recipe_id]["output"]["itemId"], item_id)

    def test_phase5_recipe_and_provider_duplicate_add_delete_are_guarded(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before = load_catalog(project)
        recipe_id = "__content_editor_recipe_copy"
        provider_id = "__content_editor_provider"
        incoming = {"recipes": clone(before["recipes"]), "craftingProviders": clone(before["craftingProviders"])}
        incoming["recipes"][recipe_id] = clone(incoming["recipes"]["bandages"])
        incoming["recipes"][recipe_id]["id"] = recipe_id
        incoming["craftingProviders"][provider_id] = {"id": provider_id, "name": "Fixture Provider"}
        incoming["recipes"][recipe_id]["craftingProvider"] = provider_id
        save_catalog(project, incoming, before["sourceHashes"], Path(temp.name) / "backups")
        after_add = load_catalog(project)
        self.assertIn(recipe_id, after_add["recipes"])
        self.assertIn(provider_id, after_add["craftingProviders"])
        deleting_provider = {"recipes": clone(after_add["recipes"]), "craftingProviders": clone(after_add["craftingProviders"])}
        del deleting_provider["craftingProviders"][provider_id]
        validation = validate_catalog(deleting_provider, after_add["known"], after_add["references"])
        self.assertTrue(any(provider_id in issue["message"] for issue in validation["errors"]))
        deleting_recipe = {"recipes": clone(after_add["recipes"]), "craftingProviders": clone(after_add["craftingProviders"])}
        del deleting_recipe["recipes"][recipe_id]
        del deleting_recipe["craftingProviders"][provider_id]
        validation = validate_catalog(deleting_recipe, after_add["known"], after_add["references"])
        self.assertFalse(any(recipe_id in issue["message"] for issue in validation["errors"]))

    def test_phase5_recipe_validation_catches_missing_refs_quantities_and_provider(self) -> None:
        catalog = load_catalog(GRAIL)
        invalid = {"recipes": clone(catalog["recipes"])}
        recipe = invalid["recipes"]["repair_kit"]
        recipe["craftingProvider"] = "missing_provider"
        recipe["ingredients"].append({"type": "material", "id": "missing_material", "quantity": 1})
        next(ingredient for ingredient in recipe["ingredients"] if ingredient["id"] == "iron")["quantity"] = 0
        recipe["output"] = {"itemId": "missing_item", "quantity": 0}
        validation = validate_catalog(invalid, catalog["known"], catalog["references"])
        messages = [issue["message"] for issue in validation["errors"]]
        self.assertTrue(any("Unknown crafting provider ID 'missing_provider'" in message for message in messages))
        self.assertTrue(any("Unknown material ID 'missing_material'" in message for message in messages))

    def test_phase6_material_add_edit_delete_and_recipe_reference_validation(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before = load_catalog(project)
        material_id = "__content_editor_phase6_material"
        incoming = {"materials": clone(before["materials"]), "recipes": clone(before["recipes"])}
        incoming["materials"][material_id] = {
            "id": material_id,
            "name": "Phase 6 Material",
            "description": "A temporary material for editor coverage.",
            "rarity": "rare",
        }
        incoming["recipes"]["repair_kit"]["ingredients"].append({"type": "material", "id": material_id, "quantity": 1})
        validation = validate_catalog(incoming, before["known"], before["references"])
        self.assertFalse(validation["errors"])
        save_catalog(project, incoming, before["sourceHashes"], Path(temp.name) / "backups")
        after = load_catalog(project)
        self.assertEqual(after["materials"][material_id]["name"], "Phase 6 Material")
        self.assertIn({"type": "material", "id": material_id, "quantity": 1}, after["recipes"]["repair_kit"]["ingredients"])

        deleting = {"materials": clone(after["materials"]), "recipes": clone(after["recipes"])}
        del deleting["materials"][material_id]
        validation = validate_catalog(deleting, after["known"], after["references"])
        self.assertTrue(any(material_id in issue["message"] for issue in validation["errors"]))

        deleting["recipes"]["repair_kit"]["ingredients"] = [ingredient for ingredient in deleting["recipes"]["repair_kit"]["ingredients"] if ingredient["id"] != material_id]
        validation = validate_catalog(deleting, after["known"], after["references"])
        self.assertFalse(validation["errors"])
        save_catalog(project, deleting, after["sourceHashes"], Path(temp.name) / "backups")
        self.assertNotIn(material_id, load_catalog(project)["materials"])

    def test_phase6_recipe_duration_and_direct_recipe_outcome_references_validate(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before = load_catalog(project)
        incoming = {"recipes": clone(before["recipes"]), "encounters": clone(before["encounters"])}
        incoming["recipes"]["repair_kit"]["craftingDurationMs"] = 4321
        outcomes = incoming["encounters"]["bandit_leader"]["stages"]["start"]["choices"][0]["outcomes"]
        outcomes.append({"type": "learnRecipe", "recipeId": "glimmering_sword"})
        validation = validate_catalog(incoming, before["known"], before["references"])
        self.assertFalse(validation["errors"])
        save_catalog(project, incoming, before["sourceHashes"], Path(temp.name) / "backups")
        after = load_catalog(project)
        self.assertEqual(after["recipes"]["repair_kit"]["craftingDurationMs"], 4321)
        self.assertEqual(outcomes[-1], {"type": "learnRecipe", "recipeId": "glimmering_sword"})

        invalid = {"recipes": clone(after["recipes"]), "encounters": clone(after["encounters"])}
        invalid["recipes"]["repair_kit"]["craftingDurationMs"] = 0
        invalid["encounters"]["bandit_leader"]["stages"]["start"]["choices"][0]["outcomes"].append({"type": "learnRecipe", "recipeId": "missing_recipe"})
        validation = validate_catalog(invalid, after["known"], after["references"])
        self.assertTrue(any("craftingDurationMs" in issue["message"] for issue in validation["errors"]))
        self.assertTrue(any("Unknown recipe ID 'missing_recipe'" in issue["message"] for issue in validation["errors"]))

    def test_phase5_item_recipe_reverse_references_and_deletion_safety(self) -> None:
        catalog = load_catalog(GRAIL)
        recipe_item_refs = [reference for reference in catalog["references"]["items"] if reference["source"] == "recipes"]
        self.assertTrue(any(reference["id"] == "repair_kit" and ".output.itemId" in reference["path"] for reference in recipe_item_refs))
        self.assertTrue(any(reference["id"] == "raw_meat" and ".ingredients[0].id" in reference["path"] for reference in recipe_item_refs))
        self.assertTrue(any(reference["source"] == "lootTables" and reference["id"] == "healing_poultice" for reference in catalog["references"]["recipes"]))

        without_item = {"items": clone(catalog["items"])}
        del without_item["items"]["repair_kit"]
        validation = validate_catalog(without_item, catalog["known"], catalog["references"])
        self.assertTrue(any("Unknown item ID 'repair_kit'" in issue["message"] for issue in validation["errors"]))

        referenced_recipe_id = next(reference["id"] for reference in catalog["references"]["recipes"] if reference["source"] == "lootTables")
        without_recipe = {"recipes": clone(catalog["recipes"])}
        del without_recipe["recipes"][referenced_recipe_id]
        validation = validate_catalog(without_recipe, catalog["known"], catalog["references"])
        self.assertTrue(any(f"Unknown recipe ID '{referenced_recipe_id}'" in issue["message"] for issue in validation["errors"]))

    def test_phase5_recipe_unlock_loot_edit_is_surgical(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before = load_catalog(project)
        path = project / "js" / "loot-data.js"
        parsed, source, _ = parse_file_constant(path, "LOOT_TABLE_DEFINITIONS")
        blocks = constant_property_blocks(source, parsed)
        incoming = {"lootTables": clone(before["lootTables"])}
        incoming["lootTables"]["common_materials"]["entries"].append({"type": "recipe", "recipeId": "repair_kit", "weight": 1})
        save_catalog(project, incoming, before["sourceHashes"], Path(temp.name) / "backups")
        after = load_catalog(project)
        self.assertIn({"type": "recipe", "recipeId": "repair_kit", "weight": 1}, after["lootTables"]["common_materials"]["entries"])
        after_parsed, after_source, _ = parse_file_constant(path, "LOOT_TABLE_DEFINITIONS")
        after_blocks = constant_property_blocks(after_source, after_parsed)
        for key, block in blocks.items():
            if key != "common_materials":
                self.assertEqual(after_blocks[key], block, key)

    def test_phase7_injury_edit_and_reference_aware_delete(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before = load_catalog(project)
        self.assertTrue(any(reference["id"] == "poisoned" for reference in before["references"].get("injuries", [])))
        incoming = {"injuries": clone(before["injuries"])}
        incoming["injuries"]["poisoned"]["travelDamageAmount"] = 2
        incoming["injuries"]["poisoned"]["travelDamageInterval"] = 7
        save_catalog(project, incoming, before["sourceHashes"], Path(temp.name) / "backups")
        after = load_catalog(project)
        self.assertEqual(after["injuries"]["poisoned"]["travelDamageAmount"], 2)
        self.assertEqual(after["injuries"]["poisoned"]["travelDamageInterval"], 7)
        deleting = {"injuries": clone(after["injuries"])}
        del deleting["injuries"]["poisoned"]
        with self.assertRaises(ValueError):
            save_catalog(project, deleting, after["sourceHashes"], Path(temp.name) / "backups")
        self.assertIn("poisoned", load_catalog(project)["injuries"])

    def test_phase7_recursive_camp_event_edit_add_save_reload_and_validation(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before = load_catalog(project)
        camp_events = clone(before["campEvents"])
        friendly = camp_events["friendly_animal"]
        outcome = friendly["stages"]["start"]["choices"][0]["outcomes"][0]
        outcome["chance"] = 0.65
        outcome["effects"].append({
            "type": "conditional",
            "requirements": [{"type": "ownsItem", "itemId": "wild_berries"}],
            "effects": [{"type": "learnRecipe", "recipeId": sorted(before["recipes"])[0]}],
            "elseEffects": [{"type": "setRunFlag", "flag": "camp_event_tested"}],
        })
        added = clone(friendly)
        added["id"] = "__phase7_camp_event"
        added["title"] = "Phase 7 Camp Event"
        camp_events[added["id"]] = added
        save_catalog(project, {"campEvents": camp_events}, before["sourceHashes"], Path(temp.name) / "backups")
        after = load_catalog(project)
        saved_outcome = after["campEvents"]["friendly_animal"]["stages"]["start"]["choices"][0]["outcomes"][0]
        self.assertEqual(saved_outcome["chance"], 0.65)
        self.assertEqual(saved_outcome["effects"][-1]["requirements"][0]["itemId"], "wild_berries")
        self.assertEqual(saved_outcome["effects"][-1]["effects"][0]["type"], "learnRecipe")
        self.assertIn("__phase7_camp_event", after["campEvents"])

        invalid = clone(after["campEvents"])
        invalid["friendly_animal"]["stages"]["start"]["choices"][0]["outcomes"][0]["effects"][-1]["requirements"][0]["itemId"] = "missing_nested_item"
        validation = validate_catalog({"campEvents": invalid}, after["known"], after["references"])
        self.assertTrue(any("Unknown item ID 'missing_nested_item'" in issue["message"] for issue in validation["errors"]))

    def test_phase7_enemy_definition_edit_add_save_reload_and_safe_delete(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before = load_catalog(project)
        enemy_path = project / "js" / "combat-data.js"
        parsed, source, _ = parse_file_constant(enemy_path, "COMBAT_ENEMY_DEFINITIONS")
        blocks = constant_property_blocks(source, parsed)
        enemies = clone(before["enemyDefinitions"])
        enemies["bandit_leader"]["maxHp"] += 1
        added_id = "__phase7_enemy"
        enemies[added_id] = {
            "id": added_id,
            "name": "Phase 7 Enemy",
            "maxHp": 18,
            "speed": 9,
            "defense": 0,
            "actionPattern": ["wolf_bite"],
        }
        save_catalog(project, {"enemyDefinitions": enemies}, before["sourceHashes"], Path(temp.name) / "backups")
        after = load_catalog(project)
        self.assertEqual(after["enemyDefinitions"]["bandit_leader"]["maxHp"], before["enemyDefinitions"]["bandit_leader"]["maxHp"] + 1)
        self.assertEqual(after["enemyDefinitions"][added_id]["actionPattern"], ["wolf_bite"])

        after_parsed, after_source, _ = parse_file_constant(enemy_path, "COMBAT_ENEMY_DEFINITIONS")
        after_blocks = constant_property_blocks(after_source, after_parsed)
        for key, block in blocks.items():
            if key != "bandit_leader":
                self.assertEqual(after_blocks[key], block, key)

        deleting = {"enemyDefinitions": clone(after["enemyDefinitions"])}
        del deleting["enemyDefinitions"]["wolf"]
        validation = validate_catalog(deleting, after["known"], after["references"])
        self.assertTrue(any("Unknown enemy ID 'wolf'" in issue["message"] for issue in validation["errors"]))
        del deleting["enemyDefinitions"][added_id]
        validation = validate_catalog(deleting, after["known"], after["references"])
        self.assertTrue(any("Unknown enemy ID 'wolf'" in issue["message"] for issue in validation["errors"]))

    def test_phase7_enemy_action_edit_add_save_reload_and_reference_validation(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before = load_catalog(project)
        actions = clone(before["enemyActions"])
        actions["leader_strike"]["damage"]["maximum"] += 1
        added_id = "__phase7_enemy_action"
        actions[added_id] = {
            "id": added_id,
            "name": "Phase 7 Action",
            "damage": {"minimum": 2, "maximum": 4},
            "target": "arthur",
            "injuryId": "deep_cut",
            "injuryChance": 0.1,
        }
        save_catalog(project, {"enemyActions": actions}, before["sourceHashes"], Path(temp.name) / "backups")
        after = load_catalog(project)
        self.assertEqual(after["enemyActions"]["leader_strike"]["damage"]["maximum"], before["enemyActions"]["leader_strike"]["damage"]["maximum"] + 1)
        self.assertEqual(after["enemyActions"][added_id]["injuryId"], "deep_cut")

        deleting = {"enemyActions": clone(after["enemyActions"])}
        del deleting["enemyActions"]["wolf_bite"]
        validation = validate_catalog(deleting, after["known"], after["references"])
        self.assertTrue(any("Unknown enemy action ID 'wolf_bite'" in issue["message"] for issue in validation["errors"]))

        invalid = {"enemyActions": clone(after["enemyActions"])}
        invalid["enemyActions"][added_id]["injuryId"] = "missing_injury"
        validation = validate_catalog(invalid, after["known"], after["references"])
        self.assertTrue(any("Unknown injury ID 'missing_injury'" in issue["message"] for issue in validation["errors"]))

    def test_phase7_dialogue_npc_destination_location_round_trip_and_links(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before = load_catalog(project)

        dialogues = clone(before["dialogues"])
        dialogue = dialogues["reeve_after_intro"]
        dialogue["nodes"]["objective"]["requirements"] = [{"type": "campaignFlag", "flag": "broceliande_intro_complete"}]
        dialogue["nodes"]["objective"]["effects"] = [{"type": "setCampaignFlag", "flag": "dialogue_editor_test", "value": True}]
        dialogue["nodes"]["objective"]["choices"][0]["label"] = "Ask about the forest (edited)"
        added_id = "__phase7_dialogue"
        added = clone(dialogue)
        added["id"] = added_id
        added["start"] = "objective"
        dialogues[added_id] = added

        npcs = clone(before["npcs"])
        npcs["village_reeve"]["description"] += " (editor test)"
        destinations = clone(before["destinations"])
        destinations["inn"]["scenePosition"] = "north"
        locations = clone(before["locations"])
        locations["broceliande_village"]["visualKey"] = "broceliande_village_editor_test"
        locations["broceliande_village"]["availableQuests"].append("__phase7_quest")

        save_catalog(
            project,
            {"dialogues": dialogues, "npcs": npcs, "destinations": destinations, "locations": locations},
            before["sourceHashes"],
            Path(temp.name) / "backups",
        )
        after = load_catalog(project)
        self.assertEqual(after["dialogues"]["reeve_after_intro"]["nodes"]["objective"]["choices"][0]["label"], "Ask about the forest (edited)")
        self.assertEqual(after["dialogues"][added_id]["nodes"]["objective"]["effects"][0]["type"], "setCampaignFlag")
        self.assertIn("dialogue_editor_test", after["dialogues"]["reeve_after_intro"]["nodes"]["objective"]["effects"][0]["flag"])
        self.assertTrue(after["npcs"]["village_reeve"]["description"].endswith("(editor test)"))
        self.assertEqual(after["destinations"]["inn"]["scenePosition"], "north")
        self.assertEqual(after["locations"]["broceliande_village"]["availableQuests"], ["__phase7_quest"])

        invalid_link = clone(after["dialogues"])
        invalid_link["reeve_after_intro"]["start"] = "missing_node"
        validation = validate_catalog({"dialogues": invalid_link}, after["known"], after["references"])
        self.assertTrue(any("start node 'missing_node' does not exist" in issue["message"].lower() for issue in validation["errors"]))

    def test_phase7_dialogue_npc_destination_location_deletion_is_reference_safe(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        before = load_catalog(project)

        deleting_dialogue = {"dialogues": clone(before["dialogues"])}
        del deleting_dialogue["dialogues"]["reeve_after_intro"]
        validation = validate_catalog(deleting_dialogue, before["known"], before["references"])
        self.assertTrue(any("Deleted dialogue" in issue["message"] or "Unknown dialogue ID 'reeve_after_intro'" in issue["message"] for issue in validation["errors"]))

        encounter_reference = clone(before["encounters"])
        encounter_reference["fallen_tree"]["stages"]["start"]["choices"][0].setdefault("outcomes", []).append({"type": "startDialogue", "dialogueId": "reeve_after_intro"})
        validation = validate_catalog({"dialogues": deleting_dialogue["dialogues"], "encounters": encounter_reference}, before["known"], before["references"])
        self.assertTrue(any("Unknown dialogue ID 'reeve_after_intro'" in issue["message"] for issue in validation["errors"]))

        deleting_npc = {"npcs": clone(before["npcs"])}
        del deleting_npc["npcs"]["village_reeve"]
        validation = validate_catalog(deleting_npc, before["known"], before["references"])
        self.assertTrue(any("Deleted NPC" in issue["message"] or "Unknown NPC ID 'village_reeve'" in issue["message"] for issue in validation["errors"]))

        deleting_destination = {"destinations": clone(before["destinations"])}
        del deleting_destination["destinations"]["hall"]
        validation = validate_catalog(deleting_destination, before["known"], before["references"])
        self.assertTrue(any("Deleted destination" in issue["message"] or "Unknown destination ID 'hall'" in issue["message"] for issue in validation["errors"]))

    def test_phase8_combat_status_and_equipment_schema_validation(self) -> None:
        catalog = load_catalog(GRAIL)
        self.assertIn("bleeding", catalog["combatStatuses"])
        self.assertIn("poisoned", catalog["known"]["combatStatuses"])

        invalid_items = clone(catalog["items"])
        invalid_items["thorn_of_the_dolorous_vale"]["effects"]["onHitEffects"][0]["statusId"] = "missing_status"
        invalid_items["shard_of_the_perron"]["effects"]["combatTriggers"][0]["cap"] = -1
        validation = validate_catalog({"items": invalid_items}, catalog["known"], catalog["references"])
        messages = [issue["message"] for issue in validation["errors"]]
        self.assertTrue(any("Unknown combat status ID 'missing_status'" in message for message in messages))
        self.assertTrue(any("non-negative cap" in message for message in messages))

        invalid_statuses = clone(catalog["combatStatuses"])
        invalid_statuses["bleeding"]["durationActivations"] = 0
        validation = validate_catalog({"combatStatuses": invalid_statuses}, catalog["known"], catalog["references"])
        self.assertTrue(any("durationActivations must be a positive integer" in issue["message"] for issue in validation["errors"]))

        deleted_statuses = clone(catalog["combatStatuses"])
        del deleted_statuses["poisoned"]
        validation = validate_catalog({"combatStatuses": deleted_statuses}, catalog["known"], catalog["references"])
        self.assertTrue(any("poisoned" in issue["message"] for issue in validation["errors"]))

    def test_phase9_ability_cooldown_charge_hit_and_learning_schema_validation(self) -> None:
        catalog = load_catalog(GRAIL)
        invalid_abilities = clone(catalog["abilities"])
        invalid_abilities["healing_prayer"]["cooldownActivations"] = 0
        invalid_abilities["healing_prayer"]["chargesPerCombat"] = "two"
        invalid_abilities["healing_prayer"]["effects"][0]["triggersOnHit"] = "yes"
        validation = validate_catalog({"abilities": invalid_abilities}, catalog["known"], catalog["references"])
        messages = [issue["message"] for issue in validation["errors"]]
        self.assertTrue(any("cooldownActivations must be a positive integer" in message for message in messages))
        self.assertTrue(any("chargesPerCombat must be a positive integer" in message for message in messages))
        self.assertTrue(any("triggersOnHit must be boolean" in message for message in messages))

        encounter = clone(catalog["encounters"]["bandit_leader"])
        outcomes = encounter["stages"]["start"]["choices"][0]["outcomes"]
        outcomes.append({"type": "learnAbility", "abilityId": "healing_prayer"})
        validation = validate_catalog(
            {"encounters": {"bandit_leader": encounter}}, catalog["known"], catalog["references"],
        )
        self.assertEqual(validation["errors"], [])
        outcomes.append({"type": "learnAbility", "abilityId": "missing_ability"})
        validation = validate_catalog(
            {"encounters": {"bandit_leader": encounter}}, catalog["known"], catalog["references"],
        )
        self.assertTrue(any("learnAbility requires a known abilityId" in issue["message"] for issue in validation["errors"]))

        resource_recipes = clone(catalog["recipes"])
        resource_recipes["repair_kit"]["output"] = {"resource": "faith", "amount": 2}
        validation = validate_catalog({"recipes": resource_recipes}, catalog["known"], catalog["references"])
        self.assertEqual(validation["errors"], [])
        resource_recipes["repair_kit"]["output"]["amount"] = 0
        validation = validate_catalog({"recipes": resource_recipes}, catalog["known"], catalog["references"])
        self.assertTrue(any("Recipe resource output amount must be positive" in issue["message"] for issue in validation["errors"]))

    def test_discovery_gate_and_safe_return_effects_validate(self) -> None:
        catalog = load_catalog(GRAIL)
        encounter = clone(catalog["encounters"]["barenton_fountain_ritual"])
        encounter["requirements"].append({
            "type": "allOf",
            "requirements": [
                {"type": "anyOf", "requirements": [{"type": "campaignFlag", "flag": "known"}]},
            ],
        })
        encounter["stages"]["start"]["choices"][0]["outcomes"].append({
            "type": "setCampaignFlagOnSafeReturn",
            "flag": "known",
            "value": True,
        })
        validation = validate_catalog(
            {"encounters": {"barenton_fountain_ritual": encounter}},
            catalog["known"], catalog["references"],
        )
        self.assertEqual(validation["errors"], [])

        invalid_group = clone(encounter)
        invalid_group["requirements"][-1].pop("requirements")
        invalid_effect = clone(encounter)
        invalid_effect["stages"]["start"]["choices"][0]["outcomes"][-1].pop("flag")
        validation = validate_catalog(
            {"encounters": {"barenton_fountain_ritual": invalid_group, "val_morgans_offer": invalid_effect}},
            catalog["known"], catalog["references"],
        )
        messages = [issue["message"] for issue in validation["errors"]]
        self.assertTrue(any("allOf requires a nested requirements array" in message for message in messages))
        self.assertTrue(any("setCampaignFlagOnSafeReturn requires a flag" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
