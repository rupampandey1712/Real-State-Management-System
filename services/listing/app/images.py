"""Image processing: re-encode to WebP (strips EXIF incl. GPS), display + thumbnail sizes."""

import io

from PIL import Image, ImageOps

from estate_common.errors import ValidationFailed

DISPLAY_PX = 1600
THUMB_PX = 400


def process_image(raw: bytes) -> tuple[bytes, bytes]:
    try:
        image = Image.open(io.BytesIO(raw))
        image = ImageOps.exif_transpose(image).convert("RGB")
    except Exception as exc:  # Pillow raises many exception types for bad input
        raise ValidationFailed("Unsupported or corrupt image.") from exc
    return _webp(image, DISPLAY_PX), _webp(image, THUMB_PX)


def _webp(image: Image.Image, max_px: int) -> bytes:
    copy = image.copy()
    copy.thumbnail((max_px, max_px))
    buffer = io.BytesIO()
    copy.save(buffer, format="WEBP", quality=82)
    return buffer.getvalue()
