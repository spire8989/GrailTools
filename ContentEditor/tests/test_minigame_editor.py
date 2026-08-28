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
            && Boolean(document.querySelector('[data-minigame-tutorial-field=text]'))
        """))
        self.browser.evaluate("document.querySelector('[data-action=add-minigame-hotspot]').click()")
        self.assertEqual(
            self.browser.evaluate("state.draft.hotspots.length"),
            4,
        )
        self.assertTrue(self.browser.evaluate("""
            document.querySelectorAll('[data-minigame-hotspot-marker]').length === 4
            && getComputedStyle(document.querySelector('[data-minigame-hotspot-marker]')).borderRadius === '50%'
        """))


if __name__ == "__main__":
    unittest.main()
