"""Tiny image-bytes helpers for asset tests."""

from __future__ import annotations

import io

from PIL import Image


def _encode(fmt: str, color: tuple[int, int, int], size: tuple[int, int]) -> bytes:
    image = Image.new("RGB", size, color)
    buffer = io.BytesIO()
    image.save(buffer, fmt)
    return buffer.getvalue()


Color = tuple[int, int, int]
Size = tuple[int, int]


def png_bytes(color: Color = (10, 20, 30), size: Size = (64, 48)) -> bytes:
    return _encode("PNG", color, size)


def jpeg_bytes(color: Color = (200, 50, 50), size: Size = (64, 48)) -> bytes:
    return _encode("JPEG", color, size)


def webp_bytes(color: Color = (30, 120, 90), size: Size = (64, 48)) -> bytes:
    return _encode("WEBP", color, size)
