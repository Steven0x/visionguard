"""EXIF orientation is baked in on load, so thumbnails/pHash/embeddings are always upright."""

from __future__ import annotations

import io

from PIL import Image

from api.app.images import validate_and_load

_ORIENTATION_TAG = 0x0112


def _jpeg_with_orientation(orientation: int, size: tuple[int, int] = (64, 48)) -> bytes:
    image = Image.new("RGB", size, (123, 45, 67))
    exif = image.getexif()
    exif[_ORIENTATION_TAG] = orientation
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def test_exif_orientation_is_applied_on_load() -> None:
    # Orientation 6 = "rotate 90° CW to view": the stored 64x48 frame is upright at 48x64.
    data = _jpeg_with_orientation(6, size=(64, 48))
    assert Image.open(io.BytesIO(data)).size == (64, 48)  # raw bytes, pre-transpose
    assert validate_and_load(data).size == (48, 64)  # oriented for all downstream fingerprints


def test_image_without_orientation_tag_is_unchanged() -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (1, 2, 3)).save(buffer, format="JPEG")
    assert validate_and_load(buffer.getvalue()).size == (64, 48)
