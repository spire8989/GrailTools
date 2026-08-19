from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

CONTENT_EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONTENT_EDITOR))

from content_editor_core import (  # noqa: E402
    clone,
    load_catalog,
    save_catalog,
    suggest_asset_id,
    upload_asset,
    validate_catalog,
)


GRAIL = CONTENT_EDITOR.parents[1] / "Grail"


class AssetPipelineTests(unittest.TestCase):
    def temporary_grail(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temp = tempfile.TemporaryDirectory(prefix="grail-asset-editor-")
        project = Path(temp.name) / "Grail"
        shutil.copytree(GRAIL, project)
        return temp, project

    def test_upload_replace_and_assign_preserve_canonical_sources(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        backup_dir = Path(temp.name) / "backups"
        before = load_catalog(project)
        unrelated_before = (project / "js" / "data.js").read_bytes()

        image = upload_asset(
            project,
            asset_type="image",
            category="portrait",
            asset_id="portrait_reeve",
            filename="reeve.png",
            content=b"first-image",
            expected_hash=before["sourceHashes"]["js/asset-data.js"],
            backup_dir=backup_dir,
        )
        self.assertEqual(image["assetResult"]["path"], "assets/images/portrait/reeve.png")
        self.assertEqual((project / "assets/images/portrait/reeve.png").read_bytes(), b"first-image")
        self.assertTrue(list(backup_dir.glob("asset-data.js.*.bak")))

        audio = upload_asset(
            project,
            asset_type="audio",
            category="ambience",
            asset_id="ambience_forest",
            filename="forest.ogg",
            content=b"first-audio",
            expected_hash=image["sourceHashes"]["js/asset-data.js"],
            backup_dir=backup_dir,
        )
        self.assertTrue(audio["audioAssets"]["ambience_forest"]["loop"])

        replaced = upload_asset(
            project,
            asset_type="image",
            category="portrait",
            asset_id="portrait_reeve",
            filename="replacement.png",
            content=b"replacement-image",
            expected_hash=audio["sourceHashes"]["js/asset-data.js"],
            replace=True,
            backup_dir=backup_dir,
        )
        self.assertTrue(replaced["assetResult"]["replaced"])
        self.assertEqual((project / "assets/images/portrait/reeve.png").read_bytes(), b"replacement-image")
        self.assertTrue(replaced["assetResult"]["binaryBackup"])

        current = load_catalog(project)
        incoming = {"npcs": clone(current["npcs"]), "imageAssets": clone(current["imageAssets"]), "audioAssets": clone(current["audioAssets"])}
        incoming["npcs"]["village_reeve"]["portraitAssetId"] = "portrait_reeve"
        saved = save_catalog(project, incoming, current["sourceHashes"], backup_dir)
        self.assertEqual(saved["validation"]["errors"], [])
        self.assertEqual(load_catalog(project)["npcs"]["village_reeve"]["portraitAssetId"], "portrait_reeve")
        self.assertEqual((project / "js" / "data.js").read_bytes(), unrelated_before)

    def test_asset_validation_rejects_unsafe_or_incompatible_definitions(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        with self.assertRaises(ValueError):
            upload_asset(
                project,
                asset_type="image",
                category="portrait",
                asset_id="portrait_bad",
                filename="../escape.png",
                content=b"x",
                backup_dir=Path(temp.name) / "backups",
            )

        image_path = project / "assets/images/location/village.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"image")
        incompatible = validate_catalog(
            {
                "imageAssets": {"scene_village": {"id": "scene_village", "category": "location", "path": "assets/images/location/village.png"}},
                "audioAssets": {},
                "npcs": {"village_reeve": {"portraitAssetId": "scene_village"}},
            },
            {"imageAssets": ["scene_village"], "audioAssets": [], "npcs": ["village_reeve"]},
            project_root=project,
        )
        self.assertTrue(any("incompatible with portraitAssetId" in issue["message"] for issue in incompatible["errors"]))

        missing = validate_catalog(
            {"imageAssets": {"scene_missing": {"id": "scene_missing", "category": "location", "path": "assets/images/location/missing.png"}}, "audioAssets": {}},
            {"imageAssets": ["scene_missing"], "audioAssets": []},
            project_root=project,
        )
        self.assertTrue(any("does not exist" in issue["message"] for issue in missing["errors"]))

    def test_upload_rejects_collisions_and_stale_catalog_hashes(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        backup_dir = Path(temp.name) / "backups"
        first = upload_asset(
            project,
            asset_type="image",
            category="ui",
            asset_id="ui_badge",
            filename="badge.webp",
            content=b"badge",
            backup_dir=backup_dir,
        )
        with self.assertRaises(ValueError):
            upload_asset(
                project,
                asset_type="image",
                category="ui",
                asset_id="ui_badge",
                filename="other.webp",
                content=b"other",
                backup_dir=backup_dir,
            )
        with self.assertRaises(ValueError):
            upload_asset(
                project,
                asset_type="audio",
                category="sfx",
                asset_id="ui_badge",
                filename="badge.ogg",
                content=b"sound",
                backup_dir=backup_dir,
            )

        source = project / "js" / "asset-data.js"
        source.write_text(source.read_text(encoding="utf-8") + "\n// stale editor fixture\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "changed on disk"):
            upload_asset(
                project,
                asset_type="image",
                category="ui",
                asset_id="ui_other",
                filename="other.webp",
                content=b"other",
                expected_hash=first["sourceHashes"]["js/asset-data.js"],
                backup_dir=backup_dir,
            )

    def test_asset_id_suggestion_is_stable_and_slug_safe(self) -> None:
        self.assertEqual(suggest_asset_id("Sir Kay Portrait.PNG", "image", "portrait", "Sir Kay"), "portrait_sir_kay_sir_kay_portrait")
        self.assertEqual(suggest_asset_id("Night Forest.ogg", "audio", "ambience", "Old Forest Road"), "ambience_old_forest_road_night_forest")


if __name__ == "__main__":
    unittest.main()
