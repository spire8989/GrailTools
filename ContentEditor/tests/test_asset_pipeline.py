from __future__ import annotations

import base64
import json
import shutil
import sys
import tempfile
from io import BytesIO
import unittest
from pathlib import Path

from PIL import Image

CONTENT_EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONTENT_EDITOR))

from content_editor_core import (  # noqa: E402
    clone,
    load_catalog,
    preview_image,
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

    @staticmethod
    def image_bytes(size: tuple[int, int], color: tuple[int, ...], image_format: str = "PNG") -> bytes:
        image = Image.new("RGBA" if len(color) == 4 else "RGB", size, color)
        output = BytesIO()
        image.save(output, format=image_format)
        return output.getvalue()

    @staticmethod
    def webp_info(content: bytes) -> Image.Image:
        image = Image.open(BytesIO(content))
        image.load()
        return image

    def test_optimized_portrait_is_webp_and_does_not_touch_source_bytes(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        source = self.image_bytes((1122, 1402), (80, 120, 180))
        original_source = source[:]
        result = upload_asset(
            project,
            asset_type="image",
            category="portrait",
            asset_id="portrait_high_res",
            filename="Reeve_Final_v3.PNG",
            content=source,
            optimize_for_game=True,
            backup_dir=Path(temp.name) / "backups",
        )
        self.assertEqual(source, original_source)
        self.assertEqual(result["assetResult"]["path"], "assets/images/portrait/reeve-final-v3.webp")
        output = project / result["assetResult"]["path"]
        with self.webp_info(output.read_bytes()) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(image.size, (480, 600))
        self.assertEqual(load_catalog(project)["imageAssets"]["portrait_high_res"]["path"], result["assetResult"]["path"])

    def test_portrait_crop_anchor_changes_fixed_aspect_crop(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        source_image = Image.new("RGB", (1000, 1000), (0, 0, 255))
        for x in range(0, 500):
            for y in range(1000):
                source_image.putpixel((x, y), (255, 0, 0))
        source = BytesIO()
        source_image.save(source, format="PNG")
        preview = preview_image(category="portrait", filename="anchor.png", content=source.getvalue(), crop_anchor="left")
        with self.webp_info(base64.b64decode(preview["previewDataUrl"].split(",", 1)[1])) as image:
            self.assertEqual(image.size, (480, 600))
            self.assertGreater(image.getpixel((20, 300))[0], 200)
            self.assertLess(image.getpixel((20, 300))[2], 100)

    def test_sam_mask_import_creates_transparent_foreground_asset(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        source = self.image_bytes((4, 4), (160, 100, 60))
        mask = json.dumps({
            "masks": {"data": [[0, 1], [1, 0]], "shape": [2, 2]},
            "offset": [1, 1],
        })
        result = upload_asset(
            project,
            asset_type="image",
            category="expedition",
            asset_id="forest_background",
            filename="forest.png",
            content=source,
            optimize_for_game=True,
            optimization_profile="none",
            sam_mask_json=mask,
            backup_dir=Path(temp.name) / "backups",
        )
        self.assertEqual(result["assetResult"]["assetId"], "forest_background")
        self.assertEqual(result["assetResult"]["parallaxAssetId"], "forest_background_parallax")
        self.assertEqual((project / result["assetResult"]["path"]).read_bytes(), source)
        foreground_path = project / result["assetResult"]["parallaxPath"]
        with self.webp_info(foreground_path.read_bytes()) as image:
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.getpixel((1, 1))[3], 0)
            self.assertGreater(image.getpixel((2, 1))[3], 200)
            self.assertGreater(image.getpixel((1, 2))[3], 200)
            self.assertEqual(image.getpixel((2, 2))[3], 0)
        catalog = load_catalog(project)
        self.assertEqual(catalog["imageAssets"]["forest_background_parallax"]["generatedFromAssetId"], "forest_background")

    def test_scene_profile_resizes_large_source_to_16_by_9(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        result = upload_asset(
            project,
            asset_type="image",
            category="location",
            asset_id="location_large",
            filename="village.png",
            content=self.image_bytes((2000, 1200), (50, 90, 110)),
            optimize_for_game=True,
            backup_dir=Path(temp.name) / "backups",
        )
        with self.webp_info((project / result["assetResult"]["path"]).read_bytes()) as image:
            self.assertEqual(image.size, (1280, 720))

    def test_town_profile_defaults_to_2_by_3_webp(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        result = upload_asset(
            project,
            asset_type="image",
            category="town",
            asset_id="town_background",
            filename="town.png",
            content=self.image_bytes((1200, 1800), (50, 90, 110)),
            optimize_for_game=True,
            backup_dir=Path(temp.name) / "backups",
        )
        processing = result["assetResult"]["imageProcessing"]
        self.assertEqual(processing["profile"], "town")
        self.assertEqual(processing["profileLabel"], "Town Background 2:3")
        self.assertEqual(result["assetResult"]["path"], "assets/images/town/town.webp")
        with self.webp_info((project / result["assetResult"]["path"]).read_bytes()) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(image.size, (832, 1248))

    def test_travel_panorama_profile_caps_large_3_by_1_source(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        result = upload_asset(
            project,
            asset_type="image",
            category="expedition",
            asset_id="expedition_panorama_large",
            filename="forest-panorama.png",
            content=self.image_bytes((3000, 1000), (50, 90, 110)),
            optimize_for_game=True,
            optimization_profile="travel_panorama",
            backup_dir=Path(temp.name) / "backups",
        )
        self.assertEqual(result["assetResult"]["imageProcessing"]["profile"], "travel_panorama")
        self.assertEqual(result["assetResult"]["imageProcessing"]["profileLabel"], "Travel Panorama 3:1")
        with self.webp_info((project / result["assetResult"]["path"]).read_bytes()) as image:
            self.assertEqual(image.size, (2400, 800))

    def test_small_travel_panorama_is_not_upscaled_or_cropped_to_16_by_9(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        result = upload_asset(
            project,
            asset_type="image",
            category="expedition",
            asset_id="expedition_panorama_small",
            filename="small-panorama.png",
            content=self.image_bytes((1800, 600), (50, 90, 110)),
            optimize_for_game=True,
            optimization_profile="travel_panorama",
            backup_dir=Path(temp.name) / "backups",
        )
        with self.webp_info((project / result["assetResult"]["path"]).read_bytes()) as image:
            self.assertEqual(image.size, (1800, 600))
        self.assertTrue(any("not upscaled" in warning for warning in result["assetResult"]["imageProcessing"]["warnings"]))

    def test_expedition_default_and_travel_scene_profiles_stay_distinct(self) -> None:
        source = self.image_bytes((2000, 1200), (50, 90, 110))
        default_scene = preview_image(category="expedition", filename="camp.png", content=source)
        self.assertEqual(default_scene["imageProcessing"]["profile"], "scene")
        self.assertEqual(
            (default_scene["imageProcessing"]["output"]["width"], default_scene["imageProcessing"]["output"]["height"]),
            (1280, 720),
        )
        panorama = preview_image(
            category="expedition",
            filename="travel.png",
            content=self.image_bytes((1800, 600), (50, 90, 110)),
            optimization_profile="travel_panorama",
        )
        self.assertEqual(panorama["imageProcessing"]["profile"], "travel_panorama")
        self.assertEqual(
            (panorama["imageProcessing"]["output"]["width"], panorama["imageProcessing"]["output"]["height"]),
            (1800, 600),
        )

    def test_travel_panorama_replacement_preserves_stable_asset_id(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        backup_dir = Path(temp.name) / "backups"
        first = upload_asset(
            project,
            asset_type="image",
            category="expedition",
            asset_id="expedition_panorama_replace",
            filename="forest-a.png",
            content=self.image_bytes((1800, 600), (120, 30, 30)),
            optimize_for_game=True,
            optimization_profile="travel_panorama",
            backup_dir=backup_dir,
        )
        replaced = upload_asset(
            project,
            asset_type="image",
            category="expedition",
            asset_id="expedition_panorama_replace",
            filename="forest-b.png",
            content=self.image_bytes((3000, 1000), (30, 120, 30)),
            replace=True,
            optimize_for_game=True,
            optimization_profile="travel_panorama",
            backup_dir=backup_dir,
        )
        self.assertEqual(replaced["assetResult"]["assetId"], first["assetResult"]["assetId"])
        self.assertEqual(replaced["assetResult"]["path"], first["assetResult"]["path"])
        self.assertEqual(replaced["assetResult"]["imageProcessing"]["output"]["width"], 2400)

    def test_fixed_profiles_do_not_upscale_small_sources(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        result = upload_asset(
            project,
            asset_type="image",
            category="portrait",
            asset_id="portrait_small",
            filename="small.png",
            content=self.image_bytes((320, 400), (90, 100, 110)),
            optimize_for_game=True,
            backup_dir=Path(temp.name) / "backups",
        )
        with self.webp_info((project / result["assetResult"]["path"]).read_bytes()) as image:
            self.assertEqual(image.size, (320, 400))
        self.assertTrue(any("not upscaled" in warning for warning in result["assetResult"]["imageProcessing"]["warnings"]))

    def test_combat_profile_preserves_alpha_and_caps_longest_dimension(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        result = upload_asset(
            project,
            asset_type="image",
            category="combat",
            asset_id="combat_cutout",
            filename="enemy.png",
            content=self.image_bytes((1200, 600), (20, 30, 40, 0)),
            optimize_for_game=True,
            backup_dir=Path(temp.name) / "backups",
        )
        with self.webp_info((project / result["assetResult"]["path"]).read_bytes()) as image:
            self.assertEqual(image.size, (768, 384))
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.getpixel((10, 10))[3], 0)

    def test_optimized_replacement_moves_legacy_image_to_webp_and_keeps_id(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        backup_dir = Path(temp.name) / "backups"
        first = upload_asset(
            project,
            asset_type="image",
            category="portrait",
            asset_id="portrait_replace_me",
            filename="reeve.png",
            content=self.image_bytes((480, 600), (120, 30, 30)),
            backup_dir=backup_dir,
        )
        old_path = project / first["assetResult"]["path"]
        old_bytes = old_path.read_bytes()
        replaced = upload_asset(
            project,
            asset_type="image",
            category="portrait",
            asset_id="portrait_replace_me",
            filename="new-artwork.png",
            content=self.image_bytes((1122, 1402), (30, 120, 30)),
            replace=True,
            optimize_for_game=True,
            backup_dir=backup_dir,
        )
        self.assertEqual(replaced["assetResult"]["assetId"], "portrait_replace_me")
        self.assertEqual(replaced["assetResult"]["path"], "assets/images/portrait/reeve.webp")
        self.assertFalse(old_path.exists())
        self.assertNotEqual((project / replaced["assetResult"]["path"]).read_bytes(), old_bytes)
        self.assertTrue(replaced["assetResult"]["binaryBackup"])
        self.assertEqual(load_catalog(project)["imageAssets"]["portrait_replace_me"]["path"], replaced["assetResult"]["path"])

    def test_optimization_off_keeps_raw_copy_behavior(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        source = self.image_bytes((80, 90), (10, 20, 30))
        result = upload_asset(
            project,
            asset_type="image",
            category="ui",
            asset_id="ui_raw_copy",
            filename="badge.png",
            content=source,
            optimize_for_game=False,
            backup_dir=Path(temp.name) / "backups",
        )
        self.assertEqual((project / result["assetResult"]["path"]).read_bytes(), source)
        self.assertEqual(result["assetResult"]["path"], "assets/images/ui/badge.png")

    def test_corrupt_optimized_image_does_not_mutate_catalog_or_runtime(self) -> None:
        temp, project = self.temporary_grail()
        self.addCleanup(temp.cleanup)
        source_path = project / "js" / "asset-data.js"
        before_source = source_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "Could not decode image"):
            upload_asset(
                project,
                asset_type="image",
                category="portrait",
                asset_id="portrait_corrupt",
                filename="corrupt.png",
                content=b"not-an-image",
                optimize_for_game=True,
                backup_dir=Path(temp.name) / "backups",
            )
        self.assertEqual(source_path.read_bytes(), before_source)
        self.assertFalse((project / "assets/images/portrait/corrupt.webp").exists())

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
            asset_id="portrait_pipeline_reeve",
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
            asset_id="portrait_pipeline_reeve",
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
        incoming["npcs"]["village_reeve"]["portraitAssetId"] = "portrait_pipeline_reeve"
        saved = save_catalog(project, incoming, current["sourceHashes"], backup_dir)
        self.assertEqual(saved["validation"]["errors"], [])
        self.assertEqual(load_catalog(project)["npcs"]["village_reeve"]["portraitAssetId"], "portrait_pipeline_reeve")
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
