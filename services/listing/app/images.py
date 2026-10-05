"""Image processing: re-encode to WebP (strips EXIF incl. GPS), display + thumbnail sizes.

Accepted inputs (FR-1.2): JPEG, PNG, WebP and HEIC/HEIF (iPhone photos, via pillow-heif)."""

import io

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

from estate_common.errors import ValidationFailed

register_heif_opener()

DISPLAY_PX = 1600
THUMB_PX = 400
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF"}


def process_image(raw: bytes) -> tuple[bytes, bytes]:
    try:
        image = Image.open(io.BytesIO(raw))
        image_format = image.format
        image = ImageOps.exif_transpose(image).convert("RGB")
    except Exception as exc:  # Pillow raises many exception types for bad input
        raise ValidationFailed("Unsupported or corrupt image.") from exc
    if image_format not in ALLOWED_FORMATS:
        raise ValidationFailed("Photos must be JPEG, PNG, WebP or HEIC.")
    return _webp(image, DISPLAY_PX), _webp(image, THUMB_PX)


def _webp(image: Image.Image, max_px: int) -> bytes:
    copy = image.copy()
    copy.thumbnail((max_px, max_px))
    buffer = io.BytesIO()
    copy.save(buffer, format="WEBP", quality=82)
    return buffer.getvalue()
