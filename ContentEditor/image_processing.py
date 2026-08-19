"""Small Pillow-backed image preparation helpers for the Content Editor.

The game only needs a catalog path at runtime.  This module keeps the authoring
convenience here by decoding source images, applying a purpose-specific profile,
and returning a WebP runtime copy without ever touching the selected source file.
"""

from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass
from io import BytesIO
from typing import Any

try:
    from PIL import Image, ImageOps
except ImportError as error:  # pragma: no cover - exercised by environment setup
    Image = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]
    PILLOW_IMPORT_ERROR = error
else:
    PILLOW_IMPORT_ERROR = None


IMAGE_PROFILES: dict[str, dict[str, Any]] = {
    "portrait": {
        "label": "Portrait 4:5",
        "target": (480, 600),
        "quality": 85,
        "size_warning": 200 * 1024,
        "size_warning_message": "Portrait runtime file is above the roughly 200 KB target.",
    },
    "scene": {
        "label": "Scene 16:9",
        "target": (1280, 720),
        "quality": 85,
        "size_warning": 800 * 1024,
        "size_warning_message": "Scene runtime file is larger than the roughly 800 KB guidance target.",
    },
    "travel_panorama": {
        "label": "Travel Panorama 3:1",
        "target": (2400, 800),
        "quality": 85,
        "ratio_tolerance": 0.02,
        "size_warning": 1200 * 1024,
        "size_warning_message": "Travel Panorama runtime file is larger than the roughly 1.2 MB guidance target.",
    },
    "combat": {
        "label": "Combat Cutout",
        "max_dimension": 768,
        "quality": 85,
        "size_warning": 500 * 1024,
        "size_warning_message": "Combat runtime file is unusually large for its dimensions.",
    },
    "ui": {
        "label": "UI",
        "max_dimension": 1024,
        "quality": 85,
        "size_warning": 400 * 1024,
        "size_warning_message": "UI runtime file is unusually large for its dimensions.",
    },
    "none": {
        "label": "Original",
        "quality": 85,
    },
}

PROFILE_ALIASES = {
    "location": "scene",
    "expedition": "scene",
    "travel_panorama": "travel_panorama",
    "travel": "travel_panorama",
    "encounter": "scene",
    "portrait": "portrait",
    "combat": "combat",
    "ui": "ui",
}
CROP_ANCHORS = ("center", "top", "bottom", "left", "right")


@dataclass(frozen=True)
class ImageInfo:
    width: int
    height: int
    format: str
    mode: str
    has_alpha: bool
    size: int


@dataclass(frozen=True)
class ProcessedImage:
    content: bytes
    source: ImageInfo
    output: ImageInfo
    profile: str
    profile_label: str
    crop_anchor: str
    warnings: tuple[str, ...]

    @property
    def preview_data_url(self) -> str:
        mime = {
            "JPEG": "image/jpeg",
            "JPG": "image/jpeg",
            "PNG": "image/png",
            "GIF": "image/gif",
            "WEBP": "image/webp",
            "AVIF": "image/avif",
        }.get(self.output.format, "application/octet-stream")
        return f"data:{mime};base64," + b64encode(self.content).decode("ascii")


def require_pillow() -> None:
    if Image is None:
        raise RuntimeError("Image optimization requires Pillow. Install it with: python -m pip install Pillow")


def profile_for_category(category: str, profile: str | None = None) -> str:
    selected = (profile or "").strip().lower()
    if not selected:
        selected = PROFILE_ALIASES.get(category, "none")
    if selected not in IMAGE_PROFILES:
        choices = ", ".join(key for key in IMAGE_PROFILES if key != "none")
        raise ValueError(f"Unknown image optimization profile {selected!r}; use {choices}, or none.")
    return selected


def _image_info(image: Any, content_size: int) -> ImageInfo:
    format_name = str(image.format or "unknown").upper()
    bands = image.getbands()
    has_alpha = "A" in bands or "transparency" in image.info
    return ImageInfo(image.width, image.height, format_name, image.mode, has_alpha, content_size)


def inspect_image(content: bytes, filename: str = "source image") -> ImageInfo:
    """Decode an image and return its dimensions/format without writing it."""
    require_pillow()
    try:
        with Image.open(BytesIO(content)) as opened:
            opened.load()
            return _image_info(opened, len(content))
    except Exception as error:
        raise ValueError(f"Could not decode image {filename!r}: {error}") from error


def _anchor_offset(available: int, crop: int, anchor: str) -> int:
    if available <= crop:
        return 0
    if anchor in {"left", "top"}:
        return 0
    if anchor in {"right", "bottom"}:
        return available - crop
    return (available - crop) // 2


def _crop_to_ratio(image: Any, target_ratio: float, anchor: str, tolerance: float = 0.0001) -> Any:
    source_ratio = image.width / image.height
    if abs(source_ratio - target_ratio) < tolerance:
        return image
    if source_ratio > target_ratio:
        crop_width = max(1, min(image.width, round(image.height * target_ratio)))
        left = _anchor_offset(image.width, crop_width, anchor)
        return image.crop((left, 0, left + crop_width, image.height))
    crop_height = max(1, min(image.height, round(image.width / target_ratio)))
    top = _anchor_offset(image.height, crop_height, anchor)
    return image.crop((0, top, image.width, top + crop_height))


def _resize_to_fit(image: Any, max_width: int, max_height: int) -> Any:
    scale = min(max_width / image.width, max_height / image.height, 1.0)
    if scale >= 1.0:
        return image
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    return image.resize(size, resampling)


def _normalise_color(image: Any) -> Any:
    has_alpha = "A" in image.getbands() or "transparency" in image.info
    if has_alpha:
        return image.convert("RGBA")
    return image.convert("RGB")


def optimize_image(
    content: bytes,
    *,
    category: str,
    profile: str | None = None,
    crop_anchor: str = "center",
    filename: str = "source image",
) -> ProcessedImage:
    """Decode, orient, resize/crop, and encode an image as game-ready WebP."""
    require_pillow()
    normalized_profile = profile_for_category(category, profile)
    anchor = (crop_anchor or "center").strip().lower()
    if anchor not in CROP_ANCHORS:
        raise ValueError(f"Unknown crop anchor {crop_anchor!r}; use {', '.join(CROP_ANCHORS)}.")
    try:
        with Image.open(BytesIO(content)) as opened:
            opened.load()
            source = _image_info(opened, len(content))
            if normalized_profile == "none":
                return ProcessedImage(content, source, source, "none", "Original", anchor, ())
            oriented = ImageOps.exif_transpose(opened)
            image = _normalise_color(oriented)
            settings = IMAGE_PROFILES[normalized_profile]
            if "target" in settings:
                target_width, target_height = settings["target"]
                image = _crop_to_ratio(
                    image,
                    target_width / target_height,
                    anchor,
                    float(settings.get("ratio_tolerance", 0.0001)),
                )
                image = _resize_to_fit(image, target_width, target_height)
            elif "max_dimension" in settings:
                image = _resize_to_fit(image, settings["max_dimension"], settings["max_dimension"])

            output_buffer = BytesIO()
            image.save(output_buffer, format="WEBP", quality=settings["quality"], method=4)
            output_content = output_buffer.getvalue()
            with Image.open(BytesIO(output_content)) as encoded:
                encoded.load()
                output = _image_info(encoded, len(output_content))
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f"Could not decode image {filename!r}: {error}") from error

    warnings: list[str] = []
    if source.width < settings.get("target", (0, 0))[0] or source.height < settings.get("target", (0, 0))[1]:
        if normalized_profile in {"portrait", "scene", "travel_panorama"}:
            target_width, target_height = settings["target"]
            warnings.append(f"Source is smaller than the recommended {target_width}×{target_height} {normalized_profile} size; it was not upscaled.")
    size_warning = settings.get("size_warning")
    if size_warning and len(output_content) > size_warning:
        warnings.append(settings["size_warning_message"])
    return ProcessedImage(output_content, source, output, normalized_profile, settings["label"], anchor, tuple(warnings))
