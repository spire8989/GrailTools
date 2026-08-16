from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

try:
    import websocket
except ImportError:  # pragma: no cover - optional local browser-test dependency
    websocket = None

CONTENT_EDITOR = Path(__file__).resolve().parents[1]
GRAIL = CONTENT_EDITOR.parents[1] / "Grail"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
sys.path.insert(0, str(CONTENT_EDITOR))

from content_editor_core import load_catalog  # noqa: E402


def free_port() -> int:
    with socket.socket() as server_socket:
        server_socket.bind(("127.0.0.1", 0))
        return int(server_socket.getsockname()[1])


class EditorBrowser:
    def __init__(self) -> None:
        if websocket is None:
            raise unittest.SkipTest("websocket-client is required for browser regression tests")
        if not CHROME.is_file():
            raise unittest.SkipTest(f"Chrome not found at {CHROME}")
        self.http_port = free_port()
        self.debug_port = free_port()
        self.profile = Path(tempfile.mkdtemp(prefix="grail-content-editor-phase6-"))
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.server = subprocess.Popen(
            [sys.executable, "server.py", "--port", str(self.http_port)],
            cwd=CONTENT_EDITOR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        self.chrome = None
        self.websocket = None
        self.session_id = None
        self.message_id = 0
        try:
            self.wait_for_url(f"http://127.0.0.1:{self.http_port}/api/health")
            self.chrome = subprocess.Popen(
                [
                    str(CHROME),
                    "--headless=new",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-gpu-sandbox",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--remote-allow-origins=*",
                    f"--remote-debugging-port={self.debug_port}",
                    f"--user-data-dir={self.profile}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            version = self.wait_for_json(f"http://127.0.0.1:{self.debug_port}/json/version")
            self.websocket = websocket.create_connection(version["webSocketDebuggerUrl"], timeout=10)
            target_id = self.command("Target.createTarget", {"url": f"http://127.0.0.1:{self.http_port}/"})["result"]["targetId"]
            self.session_id = self.command("Target.attachToTarget", {"targetId": target_id, "flatten": True})["result"]["sessionId"]
            self.wait_for_expression("document.querySelector('#entry-list')?.children.length > 0")
        except Exception:
            self.close()
            raise

    @staticmethod
    def wait_for_url(url: str, timeout: float = 10) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1) as response:
                    return json.load(response)
            except Exception:
                time.sleep(0.1)
        raise RuntimeError(f"Timed out waiting for {url}")

    @classmethod
    def wait_for_json(cls, url: str, timeout: float = 10) -> dict:
        return cls.wait_for_url(url, timeout)

    def command(self, method: str, params: dict | None = None) -> dict:
        self.message_id += 1
        message = {"id": self.message_id, "method": method, "params": params or {}}
        if self.session_id:
            message["sessionId"] = self.session_id
        self.websocket.send(json.dumps(message))
        while True:
            response = json.loads(self.websocket.recv())
            if response.get("id") == self.message_id:
                return response

    def evaluate(self, expression: str):
        response = self.command("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        result = response["result"]
        if "exceptionDetails" in result:
            raise AssertionError(result["exceptionDetails"])
        return result["result"].get("value")

    def wait_for_expression(self, expression: str) -> None:
        deadline = time.time() + 10
        while time.time() < deadline:
            if self.evaluate(expression):
                return
            time.sleep(0.1)
        raise AssertionError(f"Timed out waiting for: {expression}")

    def json_eval(self, expression: str) -> dict:
        value = self.evaluate(f"JSON.stringify({expression})")
        return json.loads(value)

    def close(self) -> None:
        if self.websocket:
            try:
                self.websocket.close()
            except Exception:
                pass
        for process in (self.chrome, self.server):
            if not process:
                continue
            if process.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
                else:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        shutil.rmtree(self.profile, ignore_errors=True)


@unittest.skipUnless(websocket is not None and CHROME.is_file(), "Chrome browser regression prerequisites are unavailable")
class Phase6FilterBrowserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_catalog(GRAIL)
        self.browser = EditorBrowser()
        self.addCleanup(self.browser.close)

    def click_category(self, category: str) -> None:
        self.browser.evaluate(f"document.querySelector('[data-category={category}]').click()")

    def open_filters(self) -> None:
        if not self.browser.evaluate("Boolean(document.querySelector('.filter-drawer'))"):
            self.browser.evaluate("document.querySelector('[data-action=toggle-filters]').click()")

    def set_single(self, field: str, value: str) -> None:
        self.browser.evaluate(f"(() => {{ const el=document.querySelector('[data-filter-field={field}]'); el.value={json.dumps(value)}; el.dispatchEvent(new Event('change', {{bubbles:true}})); }})()")

    def set_multi(self, field: str, values: list[str]) -> None:
        self.browser.evaluate(f"(() => {{ const wanted=new Set({json.dumps(values)}); const el=document.querySelector('[data-filter-field={field}]'); Array.from(el.options).forEach(option => option.selected=wanted.has(option.value)); el.dispatchEvent(new Event('change', {{bubbles:true}})); }})()")

    def count(self) -> tuple[int, int]:
        value = self.browser.evaluate("document.querySelector('#entry-count').textContent")
        visible, total = value.split(" / ")
        return int(visible), int(total)

    def entry_ids(self) -> list[str]:
        return self.browser.evaluate("Array.from(document.querySelectorAll('#entry-list .entry-row')).map(row => row.dataset.id)")

    def item_count(self, predicate) -> int:
        return sum(1 for item in self.catalog["items"].values() if predicate(item))

    def encounter_count(self, predicate) -> int:
        return sum(1 for encounter in self.catalog["encounters"].values() if predicate(encounter))

    def clear_filters(self) -> None:
        if self.browser.evaluate("Boolean(document.querySelector('.filter-clear:not([disabled])'))"):
            self.browser.evaluate("document.querySelector('.filter-clear').click()")

    def test_recipe_provider_change_updates_draft_for_navigation_and_save(self) -> None:
        self.click_category("recipes")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=repair_kit]').click()")
        recipe_name = self.browser.evaluate("document.querySelector('#editor-root h2').textContent")
        current_provider = self.browser.evaluate("document.querySelector('#editor-root [data-field=craftingProvider]').value")
        target_provider = "blacksmith" if current_provider != "blacksmith" else "apothecary"
        self.browser.evaluate(f"(() => {{ const el=document.querySelector('#editor-root [data-field=craftingProvider]'); el.value={json.dumps(target_provider)}; el.dispatchEvent(new Event('change',{{bubbles:true}})); }})()")
        self.assertIn("Unsaved changes", self.browser.evaluate("document.querySelector('#dirty-indicator').textContent"))
        self.click_category("craftingProviders")
        self.browser.evaluate(f"document.querySelector('[data-action=select][data-id={target_provider}]').click()")
        self.assertIn(recipe_name, self.browser.evaluate("document.querySelector('#editor-root').innerText"))

    def test_encounter_outcome_type_refreshes_schema_fields(self) -> None:
        self.click_category("encounters")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=wild_boar]').click()")
        self.browser.evaluate("""
            (() => {
              const select = Array.from(document.querySelectorAll('#editor-root [data-object-row] select[data-object-field="type"]'))
                .find((element) => element.value === 'modifyResource');
              if (!select) throw new Error('No modifyResource outcome found');
              select.value = 'rollLootTable';
              select.dispatchEvent(new Event('change', {bubbles: true}));
            })()
        """)
        self.assertTrue(self.browser.evaluate("""
            Array.from(document.querySelectorAll('#editor-root [data-object-row]')).some((row) => {
              const type = row.querySelector('select[data-object-field="type"]');
              return type?.value === 'rollLootTable'
                && row.querySelector('[data-object-field="tableId"]')
                && row.querySelector('[data-object-field="rolls"]');
            })
        """))

    def test_phase6_direct_recipe_outcome_and_duration_fields_are_schema_aware(self) -> None:
        self.click_category("encounters")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=wild_boar]').click()")
        self.browser.evaluate("""
            (() => {
              const select = Array.from(document.querySelectorAll('#editor-root [data-object-row] select[data-object-field="type"]'))
                .find((element) => element.value === 'modifyResource');
              if (!select) throw new Error('No modifyResource outcome found');
              select.value = 'learnRecipe';
              select.dispatchEvent(new Event('change', {bubbles: true}));
            })()
        """)
        self.assertTrue(self.browser.evaluate("""
            Array.from(document.querySelectorAll('#editor-root [data-object-row]')).some((row) =>
              row.querySelector('select[data-object-field="type"]')?.value === 'learnRecipe'
              && row.querySelector('select[data-object-field="recipeId"]')
              && row.querySelector('select[data-object-field="recipeId"] option[value="glimmering_sword"]'))
        """))

        self.click_category("recipes")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=repair_kit]').click()")
        self.assertTrue(self.browser.evaluate("Boolean(document.querySelector('#editor-root [data-field=craftingDurationMs]'))"))

    def test_phase6_material_catalog_is_browsable_and_editable(self) -> None:
        self.click_category("materials")
        self.assertEqual(self.browser.evaluate("document.querySelector('#entry-heading').textContent.trim()"), "Materials")
        self.browser.evaluate("document.querySelector('[data-action=select]').click()")
        self.assertTrue(self.browser.evaluate("""
            Boolean(document.querySelector('#editor-root [data-field=id]'))
            && Boolean(document.querySelector('#editor-root [data-field=name]'))
            && Boolean(document.querySelector('#editor-root [data-field=description]'))
            && Boolean(document.querySelector('#editor-root [data-field=rarity]'))
        """))

        self.click_category("recipes")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=repair_kit]').click()")
        self.assertTrue(self.browser.evaluate("""Boolean(document.querySelector('[data-recipe-ingredient-field="id"] option'))"""))

    def test_loot_entry_type_refreshes_reference_fields(self) -> None:
        self.click_category("lootTables")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=bandit_leader_loot]').click()")
        self.browser.evaluate("""
            (() => {
              const select = Array.from(document.querySelectorAll('[data-loot-entry-type]'))
                .find((element) => element.value === 'item');
              if (!select) throw new Error('No item loot entry found');
              select.value = 'recipe';
              select.dispatchEvent(new Event('change', {bubbles: true}));
            })()
        """)
        self.assertTrue(self.browser.evaluate("""
            Array.from(document.querySelectorAll('.loot-entry-card')).some((card) =>
              card.querySelector('[data-loot-entry-type]')?.value === 'recipe'
              && card.querySelector('[data-loot-entry-field="recipeId"]')
              && !card.querySelector('[data-loot-entry-field="itemId"]'))
        """))

    def test_recipe_output_type_refreshes_output_fields(self) -> None:
        self.click_category("recipes")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=repair_kit]').click()")
        self.browser.evaluate("""
            (() => {
              const select = document.querySelector('[data-recipe-output-type]');
              select.value = 'provisions';
              select.dispatchEvent(new Event('change', {bubbles: true}));
            })()
        """)
        self.assertTrue(self.browser.evaluate("""
            document.querySelector('[data-recipe-output-type]')?.value === 'provisions'
            && document.querySelector('[data-recipe-output-field="provisions"]')
            && !document.querySelector('[data-recipe-output-field="itemId"]')
        """))

    def test_recipe_ingredient_type_refreshes_ingredient_options(self) -> None:
        self.click_category("recipes")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=repair_kit]').click()")
        self.browser.evaluate("""
            (() => {
              const select = document.querySelector('#editor-root [data-field=ingredientType]');
              select.value = 'item';
              select.dispatchEvent(new Event('change', {bubbles: true}));
            })()
        """)
        self.assertTrue(self.browser.evaluate("""
            document.querySelector('#editor-root [data-field=ingredientType]')?.value === 'item'
            && document.querySelector('[data-recipe-ingredient-field="id"] option[value="amber_beads"]')
            && !document.querySelector('.recipe-ref-kind')
        """))

    def test_item_category_refreshes_category_specific_fields(self) -> None:
        self.click_category("items")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=old_coin]').click()")
        self.browser.evaluate("""
            (() => {
              const select = document.querySelector('#editor-root [data-field=category]');
              select.value = 'weapon';
              select.dispatchEvent(new Event('change', {bubbles: true}));
            })()
        """)
        self.assertTrue(self.browser.evaluate("""
            document.querySelector('#editor-root [data-field=category]')?.value === 'weapon'
            && Boolean(document.querySelector('[data-item-effect-field="combatDamage.minimum"]'))
            && Boolean(document.querySelector('[data-item-effect-field="combatDamage.maximum"]'))
        """))

    def test_item_filters_stack_search_and_update_from_unsaved_draft(self) -> None:
        self.click_category("items")
        self.open_filters()
        item_total = len(self.catalog["items"])
        self.set_single("category", "weapon")
        self.set_single("equippable", "yes")
        self.set_single("equipmentSlot", "weapon")
        self.set_multi("tags", ["martial", "steel"])
        self.assertEqual(self.count(), (self.item_count(lambda item: item.get("category") == "weapon" and item.get("equippable") is True and item.get("equipmentSlot") == "weapon" and {"martial", "steel"}.issubset(item.get("tags", []))), item_total))

        self.clear_filters()
        self.set_single("equippable", "no")
        self.assertEqual(self.count(), (self.item_count(lambda item: item.get("equippable") is not True), item_total))
        self.set_single("equippable", "yes")
        self.assertEqual(self.count(), (self.item_count(lambda item: item.get("equippable") is True), item_total))
        self.set_single("equippable", "any")
        self.set_single("equipmentSlot", "armor")
        self.assertEqual(self.count(), (self.item_count(lambda item: item.get("equipmentSlot") == "armor"), item_total))
        self.set_single("equipmentSlot", "")
        self.set_single("consumable", "yes")
        self.assertEqual(self.count(), (self.item_count(lambda item: item.get("consumable") is True), item_total))
        self.set_single("consumable", "any")
        self.set_single("questItem", "yes")
        self.assertEqual(self.count(), (self.item_count(lambda item: item.get("questItem") is True), item_total))
        self.set_single("questItem", "any")
        self.set_single("campaignItem", "yes")
        self.assertEqual(self.count(), (self.item_count(lambda item: item.get("campaignItem") is True), item_total))
        self.set_single("campaignItem", "any")
        self.set_single("protected", "yes")
        self.assertEqual(self.count(), (self.item_count(lambda item: item.get("protected") is True), item_total))

        self.set_single("protected", "any")
        self.set_single("unique", "no")
        self.assertEqual(self.count(), (self.item_count(lambda item: item.get("unique") is not True), item_total))
        self.set_single("unique", "any")
        self.browser.evaluate("document.querySelector('#entry-search').value='arthur'; document.querySelector('#entry-search').dispatchEvent(new Event('input', {bubbles:true}))")
        self.assertEqual(self.count(), (1, item_total))
        self.assertEqual(self.entry_ids(), ["arthur_sword"])

        self.browser.evaluate("document.querySelector('[data-action=clear-filters]').click(); document.querySelector('#entry-search').value=''; document.querySelector('#entry-search').dispatchEvent(new Event('input', {bubbles:true}))")
        self.assertEqual(self.count(), (item_total, item_total))

        self.browser.evaluate("document.querySelector('[data-action=select][data-id=old_coin]').click()")
        self.browser.evaluate("(() => { const el=document.querySelector('#editor-root [data-field=category]'); el.value='weapon'; el.dispatchEvent(new Event('change',{bubbles:true})); const tags=document.querySelector('#editor-root [data-array-field=tags]'); tags.value='martial, steel'; tags.dispatchEvent(new Event('input',{bubbles:true})); })()")
        self.set_single("category", "weapon")
        self.set_multi("tags", ["martial"])
        self.assertIn("old_coin", self.entry_ids())

    def test_encounter_filters_cover_path_direction_distance_tags_and_combat(self) -> None:
        self.click_category("encounters")
        self.open_filters()
        encounter_total = len(self.catalog["encounters"])
        self.set_multi("pathIds", ["fountain_of_barenton"])
        barenton_ids = self.entry_ids()
        barenton_count = self.encounter_count(lambda encounter: "fountain_of_barenton" in encounter.get("pathIds", []))
        self.assertEqual(self.count(), (barenton_count, encounter_total))
        self.assertTrue(barenton_ids)

        self.browser.evaluate("document.querySelector('#entry-search').value='fountain'; document.querySelector('#entry-search').dispatchEvent(new Event('input',{bubbles:true}))")
        self.assertGreater(self.count()[0], 0)
        self.assertLessEqual(self.count()[0], 14)
        self.browser.evaluate("document.querySelector('#entry-search').value=''; document.querySelector('#entry-search').dispatchEvent(new Event('input',{bubbles:true}))")
        self.set_single("direction", "outbound")
        self.assertTrue(self.entry_ids())
        self.set_single("direction", "returning")
        self.assertTrue(self.entry_ids())
        self.set_single("direction", "all")
        self.set_single("minDistance", "75")
        self.set_single("maxDistance", "101")
        self.assertEqual(self.count(), (self.encounter_count(lambda encounter: "fountain_of_barenton" in encounter.get("pathIds", []) and (encounter.get("maximumDistance", float("inf")) >= 75) and (encounter.get("minimumDistance", float("-inf")) <= 101)), encounter_total))

        self.set_multi("pathIds", ["old_forest_road"])
        old_road_ids = self.entry_ids()
        self.assertTrue(old_road_ids)
        self.set_single("repeatable", "yes")
        self.assertTrue(self.entry_ids())
        self.set_multi("tags", ["discovery"])
        self.assertTrue(self.entry_ids())

        self.browser.evaluate("document.querySelector('[data-action=clear-filters]').click()")
        self.set_single("combat", "yes")
        self.assertTrue(self.entry_ids())
        self.assertIn("wild_boar", self.entry_ids())
        self.set_multi("pathIds", ["fountain_of_barenton"])
        self.assertTrue(set(self.entry_ids()).issubset(set(barenton_ids)))

        self.browser.evaluate("document.querySelector('[data-action=clear-filters]').click(); document.querySelector('[data-action=select][data-id=fork_in_the_road]').click()")
        self.set_multi("pathIds", ["fountain_of_barenton"])
        self.assertEqual(self.count(), (barenton_count, encounter_total))
        self.browser.evaluate("(() => { const el=document.querySelector('#editor-root [data-array-toggle=pathIds][data-array-value=fountain_of_barenton]'); el.checked=true; el.dispatchEvent(new Event('change',{bubbles:true})); })()")
        self.assertEqual(self.count(), (barenton_count + 1, encounter_total))

    def test_filter_state_survives_navigation_no_results_and_crafting_label(self) -> None:
        self.click_category("items")
        self.open_filters()
        item_total = len(self.catalog["items"])
        layout = self.browser.json_eval("(() => { const entry=document.querySelector('.entry-panel').getBoundingClientRect(); const drawer=document.querySelector('.filter-drawer').getBoundingClientRect(); const editor=document.querySelector('.editor-panel').getBoundingClientRect(); return {entryWidth:entry.width, drawerRight:drawer.right, editorLeft:editor.left}; })()")
        self.assertGreaterEqual(layout["entryWidth"], 350)
        self.assertLessEqual(layout["drawerRight"], layout["editorLeft"])
        self.set_single("category", "weapon")
        self.browser.evaluate("document.querySelector('#entry-search').value='arthur'; document.querySelector('#entry-search').dispatchEvent(new Event('input', {bubbles:true}))")
        self.click_category("encounters")
        self.click_category("items")
        self.assertEqual(self.count(), (1, item_total))
        self.assertEqual(self.browser.evaluate("document.querySelector('#entry-search').value"), "arthur")

        self.set_multi("tags", ["martial", "food"])
        self.assertEqual(self.count(), (0, item_total))
        self.assertIn("No matching entries", self.browser.evaluate("document.querySelector('#entry-list').innerText"))
        self.clear_filters()
        self.browser.evaluate("document.querySelector('#entry-search').value=''; document.querySelector('#entry-search').dispatchEvent(new Event('input', {bubbles:true}))")
        self.assertEqual(self.count(), (item_total, item_total))
        self.assertTrue(self.browser.evaluate("document.querySelector('[data-category=craftingProviders]').textContent.trim()").startswith("Crafting"))


if __name__ == "__main__":
    unittest.main()
