"""Decompression-bomb-safe image validation and thumbnailing (Pillow)."""

from __future__ import annotations

import io
import warnings

from PIL import Image, ImageOps

# Reject absurd pixel counts (decompression bombs) explicitly, and make Pillow's warning fatal.
Image.MAX_IMAGE_PIXELS = 50_000_000
warnings.simplefilter("error", Image.DecompressionBombWarning)


class InvalidImage(Exception):
    """Raised when an upload isn't a valid, fully-decodable, in-bounds image."""


def validate_and_load(data: bytes) -> Image.Image:
    """Fully decode an image before anything is stored.

    Raises ``InvalidImage`` for truncated/corrupt files and for decompression bombs (declared
    dimensions over ``MAX_IMAGE_PIXELS``). Magic-byte sniffing alone is not trusted.
    """
    try:
        image = Image.open(io.BytesIO(data))
        image.load()  # force a full decode; raises on truncation, corruption, or a bomb
        # Bake in EXIF orientation so every derived artifact (thumbnail, pHash, embedding) sees
        # the image the way a human would — a phone photo tagged "rotate 90°" must not fingerprint
        # or display sideways. exif_transpose removes the orientation tag and is a no-op when none
        # is present. The stored original bytes (and their sha256 identity) are untouched.
        oriented = ImageOps.exif_transpose(image)
    except Exception as exc:  # DecompressionBombError/Warning, UnidentifiedImageError, OSError…
        raise InvalidImage(f"invalid or unsafe image: {exc}") from exc
    return oriented


def make_thumbnail(image: Image.Image, max_px: int = 256) -> bytes:
    """A small JPEG thumbnail. Re-encoding drops EXIF (no GPS/camera metadata carried over)."""
    thumb = image.convert("RGB")
    thumb.thumbnail((max_px, max_px))
    buffer = io.BytesIO()
    thumb.save(buffer, format="JPEG")  # no exif kwarg → stripped
    return buffer.getvalue()
