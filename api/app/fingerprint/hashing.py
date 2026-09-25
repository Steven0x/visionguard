"""SHA-256 and a numpy-only perceptual hash (pHash). No scipy/imagehash dependency."""

from __future__ import annotations

import functools
import hashlib

import numpy as np
from PIL import Image

_DCT_SIZE = 32
_HASH_SIZE = 8


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@functools.lru_cache(maxsize=1)
def _dct_matrix(n: int) -> np.ndarray:
    """Orthonormal DCT-II basis matrix, so a 2D DCT is ``C @ img @ C.T``."""
    x = np.arange(n)
    u = np.arange(n)
    matrix = np.sqrt(2.0 / n) * np.cos(np.pi * (2 * x[None, :] + 1) * u[:, None] / (2 * n))
    matrix[0, :] = np.sqrt(1.0 / n)
    return matrix


def phash_hex(image: Image.Image) -> str:
    """64-bit perceptual hash as 16 hex chars (32×32 grayscale → DCT → low 8×8 → median)."""
    grayscale = image.convert("L").resize((_DCT_SIZE, _DCT_SIZE), Image.Resampling.LANCZOS)
    pixels = np.asarray(grayscale, dtype=np.float64)
    basis = _dct_matrix(_DCT_SIZE)
    dct = basis @ pixels @ basis.T
    low = dct[:_HASH_SIZE, :_HASH_SIZE]
    # Exclude the dominant DC coefficient from the median (standard pHash) for better bits.
    median = float(np.median(low.flatten()[1:]))
    bits = (low > median).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:016x}"
