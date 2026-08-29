from __future__ import annotations

import unittest

from test_phase6_filters import CHROME, EditorBrowser, GRAIL, load_catalog, websocket


@unittest.skipUnless(
    websocket is not None and CHROME.is_file(),
    "Chrome and websocket-client are required for the minigame editor browser test",
)
class MinigameEditorBrowserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_catalog(GRAIL)
        self.browser = EditorBrowser()
        self.addCleanup(self.browser.close)

    def test_fishing_editor_exposes_stage_hotspots_and_crud(self) -> None:
        self.browser.evaluate("document.querySelector('[data-category=minigames]').click()")
        self.assertEqual(
            self.browser.evaluate("document.querySelector('#entry-heading').textContent.trim()"),
            "Minigames",
        )
        self.assertEqual(
            self.browser.evaluate("document.querySelector('#entry-count').textContent"),
            "2 / 2",
        )
        self.browser.evaluate(
            "document.querySelector('[data-action=select][data-id=woodland_stream_fishing]').click()",
        )
        self.assertTrue(self.browser.evaluate("""
            Boolean(document.querySelector('[data-minigame-stage]'))
            && document.querySelectorAll('[data-minigame-hotspot-marker]').length === 3
            && Boolean(document.querySelector('[data-minigame-default-field=biteChance]'))
            && Boolean(document.querySelector('[data-minigame-hotspot-field=radius]'))
            && [...document.querySelector('[data-field=musicTrackId]').options].some(option => option.value === '__inherit__' && option.textContent === 'Inherit contextual music')
            && Boolean(document.querySelector('[data-minigame-tutorial-field=text]'))
            && Math.abs((() => { const stage=document.querySelector('[data-minigame-stage]').getBoundingClientRect(); return stage.width / stage.height; })() - 2 / 3) < 0.02
            && Number(document.querySelector('[data-minigame-default-field=hookWindowMs]').value) >= 800
        """))
        self.browser.evaluate(
            "document.querySelector('[data-action=select][data-id=fishing_teacher_tutorial]').click()",
        )
        self.assertTrue(self.browser.evaluate("""
            document.querySelector('[data-minigame-tutorial-field=enabled]').checked
            && document.querySelector('[data-minigame-tutorial-field=title]').value === 'Read the Water'
        """))
        self.browser.evaluate("document.querySelector('[data-action=select][data-id=woodland_stream_fishing]').click()")
        self.browser.evaluate("document.querySelector('[data-action=add-minigame-hotspot]').click()")
        self.assertEqual(
            self.browser.evaluate("state.draft.hotspots.length"),
            4,
        )
        self.assertTrue(self.browser.evaluate("""
            document.querySelectorAll('[data-minigame-hotspot-marker]').length === 4
            && getComputedStyle(document.querySelector('[data-minigame-hotspot-marker]')).borderRadius === '50%'
        """))
        self.browser.evaluate("window.__duplicateSource = JSON.parse(JSON.stringify(state.draft.hotspots[0])); document.querySelector('[data-action=duplicate-minigame-hotspot][data-minigame-hotspot-index=\"0\"]').click()")
        self.assertTrue(self.browser.evaluate("""
            state.draft.hotspots.length === 5
            && new Set(state.draft.hotspots.map(hotspot => hotspot.id)).size === 5
            && state.minigameHotspotSelectedId === state.draft.hotspots[1].id
            && state.draftDirty === true
            && state.draft.hotspots[1].name === `${window.__duplicateSource.name} Copy`
            && state.draft.hotspots[1].x !== window.__duplicateSource.x
            && state.draft.hotspots[1].y !== window.__duplicateSource.y
            && state.draft.hotspots[1].radius === window.__duplicateSource.radius
            && state.draft.hotspots[1].lootTableId === window.__duplicateSource.lootTableId
        """))


if __name__ == "__main__":
    unittest.main()
