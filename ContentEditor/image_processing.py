"""Small Pillow-backed image preparation helpers for the Content Editor.

The game only needs a catalog path at runtime.  This module keeps the authoring
convenience here by decoding source images, applying a purpose-specific profile,
and returning a WebP runtime copy without ever touching the selected source file.
"""

from __future__ import annotations

from base64 import b64decode, b64encode
from dataclasses import dataclass
from io import BytesIO
import json
from numbers import Real
from typing import Any

try:
    from PIL import Image, ImageChops, ImageOps
except ImportError as error:  # pragma: no cover - exercised by environment setup
    Image = None  # type: ignore[assignment]
    ImageChops = None  # type: ignore[assignment]
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
    "town": {
        "label": "Town Background 2:3",
        "target": (832, 1248),
        "quality": 85,
        "size_warning": 800 * 1024,
        "size_warning_message": "Town Background runtime file is larger than the roughly 800 KB guidance target.",
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
    "town": "town",
    "expedition": "scene",
    "travel_panorama": "travel_panorama",
    "travel": "travel_panorama",
    "encounter": "scene",
    "portrait": "portrait",
    "combat": "combat",
    "combat_scene": "scene",
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
    foreground_offset: tuple[int, int] | None = None
    foreground_canvas: tuple[int, int] | None = None

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


def _first_value(objects: list[dict[str, Any]], keys: tuple[str, ...]) -> Any:
    for obj in objects:
        for key in keys:
            if key in obj and obj[key] is not None:
                return obj[key]
    return None


def _pair(value: Any, *, names: tuple[str, str]) -> tuple[int, int] | None:
    if isinstance(value, (list, tuple)) and len(value) >= 2 and all(isinstance(item, Real) for item in value[:2]):
        return max(1, int(value[0])), max(1, int(value[1]))
    if isinstance(value, dict):
        first, second = (value.get(name) for name in names)
        if isinstance(first, Real) and isinstance(second, Real):
            return max(1, int(first)), max(1, int(second))
    return None


def _shape(value: Any) -> tuple[int, int] | None:
    if isinstance(value, (list, tuple)) and len(value) >= 2 and all(isinstance(item, Real) for item in value[:2]):
        # Array exports conventionally use numpy's [height, width] order.
        return max(1, int(value[1])), max(1, int(value[0]))
    if isinstance(value, dict):
        return _pair(value, names=("width", "height"))
    return None


def _bounds(value: Any) -> tuple[int, int, int, int] | None:
    if isinstance(value, (list, tuple)) and len(value) >= 4 and all(isinstance(item, Real) for item in value[:4]):
        x, y, width, height = (int(item) for item in value[:4])
        return x, y, max(1, width), max(1, height)
    if isinstance(value, dict):
        x = value.get("x", value.get("left", 0))
        y = value.get("y", value.get("top", 0))
        width = value.get("width")
        height = value.get("height")
        if width is None and isinstance(value.get("right"), Real) and isinstance(x, Real):
            width = value["right"] - x
        if height is None and isinstance(value.get("bottom"), Real) and isinstance(y, Real):
            height = value["bottom"] - y
        if all(isinstance(item, Real) for item in (x, y, width, height)):
            return int(x), int(y), max(1, int(width)), max(1, int(height))
    return None


def _decode_mask_values(value: Any) -> tuple[list[int], tuple[int, int] | None]:
    """Return flattened binary values and an optional (width, height)."""
    if isinstance(value, dict):
        nested = value.get("data", value.get("values", value.get("mask", value.get("segmentation"))))
        if nested is None:
            raise ValueError("SAM mask data object must contain data, values, mask, or segmentation.")
        shape = _shape(value.get("shape", value.get("size", value.get("dimensions"))))
        if shape is None and isinstance(value.get("width"), Real) and isinstance(value.get("height"), Real):
            shape = int(value["width"]), int(value["height"])
        values, nested_shape = _decode_mask_values(nested)
        return values, shape or nested_shape
    if isinstance(value, str):
        try:
            decoded = b64decode(value, validate=True)
        except Exception:
            if set(value.strip()) <= {"0", "1", " ", "\n", "\r", ","}:
                values = [int(item) for item in value.replace(",", " ").split()]
                return values, None
            raise ValueError("SAM masks string must be base64-encoded binary data or 0/1 values.")
        return list(decoded), None
    if isinstance(value, (bytes, bytearray)):
        return list(value), None
    if not isinstance(value, list) or not value:
        raise ValueError("SAM masks must contain binary data.")
    if all(isinstance(item, (bool, Real)) for item in value):
        return [1 if item else 0 for item in value], None
    if all(isinstance(item, list) for item in value):
        rows = value
        if all(all(isinstance(item, (bool, Real)) for item in row) for row in rows):
            width = max((len(row) for row in rows), default=0)
            if width <= 0:
                raise ValueError("SAM mask rows cannot be empty.")
            flattened = [1 if item else 0 for row in rows for item in row]
            return flattened, (width, len(rows))
        flattened: list[int] = []
        shape: tuple[int, int] | None = None
        for mask in rows:
            child_values, child_shape = _decode_mask_values(mask)
            flattened.extend(child_values)
            if child_shape and shape is None:
                shape = child_shape
        return flattened, shape
    raise ValueError("SAM masks must be a flat or nested binary array.")


def sam_mask_image(mask_json: str | bytes | dict[str, Any], width: int, height: int) -> Any:
    """Decode the small SAM export used by the editor into a source-sized L mask.

    The importer accepts either a full-image mask or mask data local to a
    bounding box/offset. Multiple masks are treated as one foreground union.
    """
    require_pillow()
    try:
        payload = json.loads(mask_json.decode("utf-8") if isinstance(mask_json, bytes) else mask_json) if not isinstance(mask_json, dict) else mask_json
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not parse SAM mask JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("SAM mask JSON must be an object.")

    mask_object = payload.get("masks", payload.get("mask", payload.get("segmentation")))
    if mask_object is None:
        raise ValueError("SAM mask JSON must contain masks data.")
    if isinstance(mask_object, list) and mask_object and all(isinstance(item, dict) for item in mask_object):
        combined = Image.new("L", (width, height), 0)
        for item in mask_object:
            record = dict(payload)
            record.update(item)
            record["masks"] = item.get("masks", item.get("mask", item.get("segmentation", item.get("data", item.get("values")))))
            combined = ImageChops.lighter(combined, sam_mask_image(record, width, height))
        return combined
    objects = [payload]
    if isinstance(mask_object, dict):
        objects.insert(0, mask_object)
    values, inferred_shape = _decode_mask_values(mask_object)
    shape = inferred_shape or _shape(_first_value(objects, ("shape", "size", "dimensions")))
    if shape is None:
        raw_width = _first_value(objects, ("width",))
        raw_height = _first_value(objects, ("height",))
        if isinstance(raw_width, Real) and isinstance(raw_height, Real):
            shape = max(1, int(raw_width)), max(1, int(raw_height))
    bounds = _bounds(_first_value(objects, ("bbox", "boundingBox", "bounding_box", "bounds", "cropBox", "crop_box")))
    if shape is None and bounds and len(values) == bounds[2] * bounds[3]:
        shape = bounds[2], bounds[3]
    if shape is None and len(values) == width * height:
        shape = width, height
    if shape is None:
        raise ValueError("SAM mask JSON needs mask dimensions, a bounding box, or source-sized data.")
    mask_width, mask_height = shape
    required = mask_width * mask_height
    if len(values) == required:
        decoded_values = values
    elif len(values) > required and len(values) % required == 0:
        decoded_values = [1 if any(values[offset + index] for offset in range(0, len(values), required)) else 0 for index in range(required)]
    elif len(values) * 8 >= required and all(value in range(256) for value in values):
        decoded_values = [(values[index // 8] >> (index % 8)) & 1 for index in range(required)]
    else:
        raise ValueError(f"SAM mask data has {len(values)} values but dimensions require {required}.")

    offset_value = _first_value(objects, ("offset", "origin"))
    offset = _pair(offset_value, names=("x", "y")) or (0, 0)
    if bounds and shape != (width, height):
        offset = (bounds[0], bounds[1])
    elif bounds and shape == (width, height) and offset == (0, 0):
        # A full-sized mask is already source-aligned; bbox is descriptive.
        offset = (0, 0)

    local = Image.new("L", (mask_width, mask_height), 0)
    local.putdata([255 if value else 0 for value in decoded_values])
    result = Image.new("L", (width, height), 0)
    result.paste(local, (offset[0], offset[1]))
    return result


def optimize_image(
    content: bytes,
    *,
    category: str,
    profile: str | None = None,
    crop_anchor: str = "center",
    filename: str = "source image",
    mask_json: str | bytes | dict[str, Any] | None = None,
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
            if normalized_profile == "none" and mask_json is None:
                return ProcessedImage(content, source, source, "none", "Original", anchor, ())
            oriented = ImageOps.exif_transpose(opened)
            image = _normalise_color(oriented)
            settings = IMAGE_PROFILES[normalized_profile]
            if mask_json is not None:
                alpha_mask = ImageOps.exif_transpose(sam_mask_image(mask_json, opened.width, opened.height))
                image = image.convert("RGBA")
                source_alpha = image.getchannel("A")
                image.putalpha(ImageChops.multiply(source_alpha, alpha_mask))
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

            foreground_offset = None
            foreground_canvas = None
            if mask_json is not None:
                foreground_canvas = image.size
                foreground_box = image.getchannel("A").getbbox()
                if not foreground_box:
                    raise ValueError("SAM mask does not contain any foreground pixels after image processing.")
                foreground_offset = (foreground_box[0], foreground_box[1])
                image = image.crop(foreground_box)

            output_buffer = BytesIO()
            image.save(output_buffer, format="WEBP", quality=settings.get("quality", 85), method=4)
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
        if normalized_profile in {"portrait", "scene", "town", "travel_panorama"}:
            target_width, target_height = settings["target"]
            warnings.append(f"Source is smaller than the recommended {target_width}×{target_height} {normalized_profile} size; it was not upscaled.")
    size_warning = settings.get("size_warning")
    if size_warning and len(output_content) > size_warning:
        warnings.append(settings["size_warning_message"])
    return ProcessedImage(
        output_content,
        source,
        output,
        normalized_profile,
        settings["label"],
        anchor,
        tuple(warnings),
        foreground_offset,
        foreground_canvas,
    )
