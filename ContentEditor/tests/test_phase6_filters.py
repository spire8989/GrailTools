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

    def test_starting_state_editor_surfaces_and_updates_draft(self) -> None:
        self.click_category("startingState")
        self.assertEqual(self.browser.evaluate("document.querySelector('#entry-heading').textContent.trim()"), "Starting State")
        self.assertTrue(self.browser.evaluate("Boolean(document.querySelector('#editor-root [data-starting-field=currentGold]'))"))
        self.assertTrue(self.browser.evaluate("Boolean(document.querySelector('#editor-root [data-starting-map-field=ownedItems]'))"))
        self.browser.evaluate("(() => { const input=document.querySelector('#editor-root [data-starting-field=currentGold]'); input.value='33'; input.dispatchEvent(new Event('input',{bubbles:true})); })()")
        self.assertEqual(self.browser.evaluate("state.draft.currentGold"), 33)
        self.browser.evaluate("(() => { const input=document.querySelector('#editor-root [data-starting-map-field=ownedItems][data-starting-map-id=rope]'); input.value='2'; input.dispatchEvent(new Event('input',{bubbles:true})); })()")
        self.assertEqual(self.browser.evaluate("state.draft.ownedItems.rope"), 2)

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

    def test_item_loot_table_rows_open_the_full_table_editor(self) -> None:
        self.click_category("items")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=old_coin]').click()")
        self.assertTrue(self.browser.evaluate("Boolean(document.querySelector('[data-action=open-reference][data-reference-category=lootTables][data-reference-id=bandit_ambush_loot]'))"))
        self.assertTrue(self.browser.evaluate("""
            (() => {
                const row = [...document.querySelectorAll('.loot-row')].find((candidate) =>
                    candidate.querySelector('[data-reference-id="bandit_ambush_loot"]')
                );
                const actions = row?.querySelector('.loot-row-actions');
                return Boolean(
                    actions
                    && actions.querySelector('[data-loot-field="weight"]')
                    && actions.querySelector('[data-action="remove-loot-item"]')
                    && actions.querySelector('[data-action="remove-loot-item"]').parentElement === actions
                );
            })()
        """))
        self.browser.evaluate("document.querySelector('[data-action=open-reference][data-reference-category=lootTables][data-reference-id=bandit_ambush_loot]').click()")
        self.assertEqual(self.browser.evaluate("document.querySelector('#entry-heading').textContent.trim()"), "Loot Tables")
        self.assertEqual(self.browser.evaluate("document.querySelector('#editor-root h2').textContent.trim()"), "bandit_ambush_loot")
        self.assertTrue(self.browser.evaluate("Boolean(document.querySelector('#editor-root [data-loot-entry-field]'))"))
        self.browser.evaluate("document.querySelector('[data-action=back-reference]').click()")
        self.assertEqual(self.browser.evaluate("document.querySelector('#entry-heading').textContent.trim()"), "Items")
        self.assertEqual(self.browser.evaluate("document.querySelector('#editor-root h2').textContent.trim()"), "Old Silver Coins")

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

    def test_phase7_recursive_requirements_effects_and_combat_branches_are_visible(self) -> None:
        self.click_category("encounters")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=road_behind_you]').click()")
        self.assertTrue(self.browser.evaluate("""
            (() => {
              const nested = Array.from(document.querySelectorAll('[data-object-row]'));
              return nested.some(row => row.querySelector('select[data-object-field="type"]')?.value === 'conditional'
                && nested.some(child => child.dataset.collectionName === 'requirements' && child.dataset.parentPath?.includes('outcomes[0]'))
                && nested.some(child => child.dataset.collectionName === 'effects' && child.dataset.parentPath?.includes('outcomes[0]'))
                && nested.some(child => child.dataset.collectionName === 'elseEffects' && child.dataset.parentPath?.includes('outcomes[0]')));
            })()
        """))

        self.browser.evaluate("document.querySelector('[data-action=select][data-id=barenton_fountain_ritual]').click()")
        self.assertTrue(self.browser.evaluate("""
            Array.from(document.querySelectorAll('[data-object-row]')).some(row =>
              row.querySelector('select[data-object-field="type"]')?.value === 'conditional'
              && row.dataset.parentPath?.includes('.victory'))
            && Array.from(document.querySelectorAll('[data-object-row]')).some(row =>
              row.dataset.collectionName === 'requirements' && row.dataset.parentPath?.includes('victory.outcomes'))
        """))

    def test_phase7_injury_and_camp_event_editors_expose_live_nested_data(self) -> None:
        self.click_category("injuries")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=poisoned]').click()")
        self.assertTrue(self.browser.evaluate("""
            Boolean(document.querySelector('#editor-root [data-field=travelDamageAmount]'))
            && Boolean(document.querySelector('#editor-root [data-field=travelDamageInterval]'))
            && Boolean(document.querySelector('#editor-root [data-injury-effect-field=incomingDamageMultiplier]'))
        """))
        self.browser.evaluate("""
            (() => {
              const input = document.querySelector('#editor-root [data-field=travelDamageInterval]');
              input.value = '6';
              input.dispatchEvent(new Event('change', {bubbles: true}));
            })()
        """)
        self.assertIn("Unsaved changes", self.browser.evaluate("document.querySelector('#dirty-indicator').textContent"))

        self.click_category("campEvents")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=stranger_approaches]').click()")
        self.assertTrue(self.browser.evaluate("""
            Boolean(document.querySelector('#editor-root [data-field=title]'))
            && Array.from(document.querySelectorAll('#editor-root select[data-object-field="type"]')).some(select => select.value === 'randomOne')
            && document.querySelectorAll('.resolution-option').length === 3
            && Array.from(document.querySelectorAll('[data-object-row]')).some(row =>
              row.dataset.collectionName === 'effects' && row.dataset.parentPath?.includes('options[0]'))
        """))
        self.browser.evaluate("document.querySelector('[data-action=add-resolution-option]').click()")
        self.assertEqual(self.browser.evaluate("document.querySelectorAll('.resolution-option').length"), 4)

    def test_phase7_enemy_and_action_categories_are_first_class_editors(self) -> None:
        self.click_category("enemyDefinitions")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=wild_boar]').click()")
        self.assertTrue(self.browser.evaluate("""
            Boolean(document.querySelector('#editor-root [data-enemy-field=maxHp]'))
            && Boolean(document.querySelector('#editor-root [data-enemy-pattern-field=actionId]'))
            && Boolean(document.querySelector('#editor-root [data-reference-category=enemyActions]'))
            && Boolean(document.querySelector('#editor-root [data-reference-category=combats]'))
        """))
        self.browser.evaluate("""
            (() => {
              const input = document.querySelector('#editor-root [data-enemy-field=maxHp]');
              input.value = '33';
              input.dispatchEvent(new Event('change', {bubbles: true}));
            })()
        """)
        self.assertIn("Unsaved changes", self.browser.evaluate("document.querySelector('#dirty-indicator').textContent"))

        self.click_category("enemyActions")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=wolf_lunge]').click()")
        self.assertTrue(self.browser.evaluate("""
            Boolean(document.querySelector('#editor-root [data-enemy-action-field="damage.minimum"]'))
            && Boolean(document.querySelector('#editor-root [data-enemy-action-field=target]'))
            && Boolean(document.querySelector('#editor-root [data-field=injuryId]'))
            && document.querySelector('#editor-root [data-field=injuryId]').value === 'sprained_ankle'
        """))

    def test_phase7_combat_is_roster_composition_with_open_enemy_navigation(self) -> None:
        self.click_category("combats")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=wolves]').click()")
        self.assertTrue(self.browser.evaluate("""
            document.querySelectorAll('#editor-root [data-combat-enemy-row]').length === 3
            && document.querySelectorAll('#editor-root [data-action=open-reference][data-reference-category=enemyDefinitions]').length === 3
            && !document.querySelector('#editor-root [data-enemy-field]')
            && !document.querySelector('#editor-root [data-enemy-action-field]')
        """))
        self.browser.evaluate("document.querySelector('#editor-root [data-action=open-reference][data-reference-id=wolf]').click()")
        self.assertEqual(self.browser.evaluate("document.querySelector('#entry-heading').textContent"), "Enemies")
        self.assertEqual(self.browser.evaluate("document.querySelector('#editor-root [data-field=id]').value"), "wolf")

    def test_phase7_dialogue_npc_destination_location_categories_are_first_class(self) -> None:
        self.click_category("dialogues")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=reeve_after_intro]').click()")
        self.assertTrue(self.browser.evaluate("""
            Boolean(document.querySelector('#editor-root [data-field=start]'))
            && Boolean(document.querySelector('#editor-root [data-dialogue-node-field=portraitKey]'))
            && Boolean(document.querySelector('#editor-root [data-dialogue-choice-field=next]'))
        """))
        self.browser.evaluate("document.querySelector('#editor-root [data-action=add-object][data-owner=dialogue-effects]').click()")
        self.browser.evaluate("""
            (() => {
              const type = Array.from(document.querySelectorAll('#editor-root [data-object-field="type"]'))
                .find((select) => select.value === 'modifyResource');
              if (!type) throw new Error('No dialogue effect type found');
              type.value = 'startDialogue';
              type.dispatchEvent(new Event('change', {bubbles: true}));
            })()
        """)
        self.assertTrue(self.browser.evaluate("Boolean(document.querySelector('#editor-root [data-object-field=dialogueId]'))"))

        self.click_category("npcs")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=village_reeve]').click()")
        self.assertTrue(self.browser.evaluate("""
            Boolean(document.querySelector('#editor-root [data-field=dialogueSequenceId]'))
            && Boolean(document.querySelector('#editor-root [data-field=introDialogueSequenceId]'))
            && Boolean(document.querySelector('#editor-root [data-lines-field=dialogue]'))
            && Boolean(document.querySelector('#editor-root [data-reference-category=locations]'))
        """))

        self.click_category("destinations")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=inn]').click()")
        self.assertTrue(self.browser.evaluate("""
            Boolean(document.querySelector('#editor-root [data-field=scenePosition]'))
            && Boolean(document.querySelector('#editor-root [data-destination-npc-index]'))
            && Boolean(document.querySelector('#editor-root [data-field=shopId]'))
        """))

        self.click_category("locations")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=broceliande_village]').click()")
        self.assertTrue(self.browser.evaluate("""
            Boolean(document.querySelector('#editor-root [data-field=visualKey]'))
            && Boolean(document.querySelector('#editor-root [data-reference-array-field=destinations]'))
            && Boolean(document.querySelector('#editor-root [data-action=add-string-array][data-string-array-field=availableQuests]'))
            && Boolean(document.querySelector('#editor-root [data-action=add-object][data-owner=location-requirements]'))
        """))

    def test_town_layout_editor_renders_and_updates_normalized_hotspot(self) -> None:
        self.click_category("locations")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=broceliande_village]').click()")
        self.assertTrue(self.browser.evaluate("Boolean(document.querySelector('[data-town-layout-editor] img.town-layout-image'))"))
        self.assertEqual(self.browser.evaluate("document.querySelectorAll('[data-town-layout-marker]').length"), 5)
        self.assertTrue(self.browser.evaluate("document.querySelector('[data-field=markerStyle]').value===state.draft.markerStyle"))
        self.browser.evaluate("(() => { const select=document.querySelector('[data-field=markerStyle]'); select.value='ink'; select.dispatchEvent(new Event('change',{bubbles:true})); })()")
        self.assertTrue(self.browser.evaluate("state.draft.markerStyle==='ink' && [...document.querySelectorAll('[data-town-layout-marker]')].every(marker=>marker.classList.contains('town-hotspot-style-ink'))"))
        self.assertTrue(self.browser.evaluate("state.dirty"))
        self.assertTrue(self.browser.evaluate("Math.abs(document.querySelector('[data-town-layout-stage]').getBoundingClientRect().width / document.querySelector('[data-town-layout-stage]').getBoundingClientRect().height - 2 / 3) < 0.02"))
        self.browser.evaluate("(() => { const input=document.querySelector('[data-town-hotspot-input][data-town-destination-id=inn][data-town-hotspot-axis=x]'); input.value='0.333'; input.dispatchEvent(new Event('change',{bubbles:true})); })()")
        self.assertEqual(self.browser.evaluate("state.catalog.destinations.inn.hotspot.x"), 0.333)
        self.assertIn("33.3", self.browser.evaluate("document.querySelector('[data-town-layout-marker][data-town-destination-id=inn]').style.left"))

    def test_encounter_layout_editor_renders_and_updates_normalized_party_slots(self) -> None:
        self.click_category("encounters")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=abandoned_camp]').click()")
        self.assertTrue(self.browser.evaluate("Boolean(document.querySelector('[data-encounter-layout-editor] img.encounter-layout-image'))"))
        self.assertEqual(self.browser.evaluate("document.querySelectorAll('[data-encounter-layout-marker]').length"), 3)
        self.assertTrue(self.browser.evaluate("document.querySelector('[data-encounter-layout-marker][data-encounter-layout-slot=arthur]').style.left==='60.9375%'"))
        self.assertTrue(self.browser.evaluate("Math.abs(document.querySelector('[data-encounter-layout-stage]').getBoundingClientRect().width / document.querySelector('[data-encounter-layout-stage]').getBoundingClientRect().height - 16 / 9) < 0.02"))
        self.assertTrue(self.browser.evaluate("document.querySelectorAll('[data-character-preview][data-preview-encounter-layout] canvas.character-preview-canvas').length===3 && [...document.querySelectorAll('[data-character-preview][data-preview-encounter-layout]')].every(root=>root.classList.contains('is-ready') && root.querySelector('canvas').width>0 && root.querySelector('canvas').height>0)"))
        self.assertEqual(self.browser.evaluate("document.querySelector('[data-encounter-layout-preview][data-encounter-layout-slot=companion1]').value"), "sir_kay")
        self.assertEqual(self.browser.evaluate("document.querySelector('[data-encounter-layout-preview][data-encounter-layout-slot=companion2]').value"), "llamrei")
        self.browser.evaluate("(() => { const input=document.querySelector('[data-encounter-layout-input][data-encounter-layout-slot=arthur][data-encounter-layout-axis=x]'); input.value='0.333'; input.dispatchEvent(new Event('change',{bubbles:true})); })()")
        self.assertEqual(self.browser.evaluate("state.draft.encounterLayout.arthur.x"), 0.333)
        self.assertIn("33.3", self.browser.evaluate("document.querySelector('[data-encounter-layout-marker][data-encounter-layout-slot=arthur]').style.left"))
        self.browser.evaluate("(() => { const select=document.querySelector('[data-encounter-layout-field=facing][data-encounter-layout-slot=companion1]'); select.value='left'; select.dispatchEvent(new Event('change',{bubbles:true})); const scale=document.querySelector('[data-encounter-layout-field=scale][data-encounter-layout-slot=companion2]'); scale.value='0.8'; scale.dispatchEvent(new Event('input',{bubbles:true})); const layer=document.querySelector('[data-encounter-layout-field=layer][data-encounter-layout-slot=companion1]'); layer.value='2'; layer.dispatchEvent(new Event('input',{bubbles:true})); })()")
        self.assertTrue(self.browser.evaluate("state.draft.encounterLayout.companion1.facing==='left' && state.draft.encounterLayout.companion1.layer===2 && state.draft.encounterLayout.companion2.scale===0.8 && document.querySelector('[data-encounter-layout-marker][data-encounter-layout-slot=companion1] [data-character-preview]').classList.contains('is-mirrored')"))
        self.browser.evaluate("(() => { const checkbox=document.querySelector('[data-encounter-layout-field=visible][data-encounter-layout-slot=companion2]'); checkbox.checked=false; checkbox.dispatchEvent(new Event('change',{bubbles:true})); })()")
        self.assertTrue(self.browser.evaluate("state.draft.hiddenSlots.includes('companion2') && document.querySelector('[data-encounter-layout-marker][data-encounter-layout-slot=companion2]').classList.contains('is-hidden')"))
        self.browser.evaluate("(() => { const select=document.querySelector('[data-encounter-layout-preview][data-encounter-layout-slot=companion2]'); select.value='sir_kay'; select.dispatchEvent(new Event('change',{bubbles:true})); })()")
        self.assertTrue(self.browser.evaluate("document.querySelector('[data-character-preview][data-preview-encounter-layout][data-preview-character-id=sir_kay][data-preview-label=\"Companion 2\"]') && !JSON.stringify(state.draft).includes('sir_kay')"))
        self.browser.evaluate("updateEncounterLayoutMarker('arthur', -1, 2)")
        self.assertTrue(self.browser.evaluate("state.draft.encounterLayout.arthur.x===0 && state.draft.encounterLayout.arthur.y===1"))

    def test_outcome_visual_editor_supports_inherit_custom_and_hidden_slots(self) -> None:
        self.click_category("encounters")
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=abandoned_camp]').click()")
        self.browser.evaluate("(() => { const choice=state.draft.stages.start.choices[0]; delete choice.visualOverride; render(); })()")
        self.assertTrue(self.browser.evaluate("[...document.querySelectorAll('[data-outcome-visual-editor]')].find(node=>node.dataset.outcomeVisualPath==='stages.start.choices[0]')?.querySelector('summary').textContent.includes('Inherit encounter')"))
        self.browser.evaluate("(() => { const select=[...document.querySelectorAll('[data-outcome-visual-field=layoutMode]')].find(node=>node.dataset.outcomeVisualPath==='stages.start.choices[0]'); select.value='custom'; select.dispatchEvent(new Event('change',{bubbles:true})); })()")
        self.assertTrue(self.browser.evaluate("Boolean(state.draft.stages.start.choices[0].visualOverride.encounterLayout) && document.querySelectorAll('[data-outcome-layout-marker]').length===3 && document.querySelectorAll('[data-object-row] [data-outcome-visual-editor]').length===0"))
        self.assertTrue(self.browser.evaluate("Math.abs(document.querySelector('[data-outcome-layout-stage]').getBoundingClientRect().width / document.querySelector('[data-outcome-layout-stage]').getBoundingClientRect().height - 16 / 9) < 0.02"))
        self.browser.evaluate("(() => { const select=[...document.querySelectorAll('[data-outcome-visual-field=backgroundMode]')].find(node=>node.dataset.outcomeVisualPath==='stages.start.choices[0]'); select.value='custom'; select.dispatchEvent(new Event('change',{bubbles:true})); })()")
        self.assertTrue(self.browser.evaluate("Boolean(state.draft.stages.start.choices[0].visualOverride.backgroundAssetId) && document.querySelector('[data-outcome-visual-field=backgroundAssetId]')"))
        self.browser.evaluate("(() => { const checkbox=[...document.querySelectorAll('[data-outcome-visual-field=hiddenSlot][data-outcome-visual-slot=companion2]')].find(node=>node.dataset.outcomeVisualPath==='stages.start.choices[0]'); checkbox.checked=true; checkbox.dispatchEvent(new Event('change',{bubbles:true})); })()")
        self.assertTrue(self.browser.evaluate("state.draft.stages.start.choices[0].visualOverride.hiddenSlots.includes('companion2') && [...document.querySelectorAll('[data-outcome-visual-editor]')].find(node=>node.dataset.outcomeVisualPath==='stages.start.choices[0]').querySelector('summary').textContent.includes('Custom')"))


if __name__ == "__main__":
    unittest.main()
