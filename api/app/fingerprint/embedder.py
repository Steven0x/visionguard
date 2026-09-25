"""Whole-image embedding. Real CLIP in prod ([ml] extra); a deterministic fake in tests/CI.

NOT a face embedding — this embeds the whole image for copy-matching. See docs/specs/assets.md.
"""

from __future__ import annotations

import hashlib
import io
from functools import lru_cache
from typing import Protocol

import numpy as np

from api.app.config import get_settings


class Embedder(Protocol):
    def embed(self, image_bytes: bytes) -> list[float]:
        """Return an L2-normalized embedding for the whole image."""
        ...


class FakeEmbedder:
    """Deterministic embedding derived from the image bytes — no model, no downloads."""

    def __init__(self, dim: int) -> None:
        self._dim = dim

    def embed(self, image_bytes: bytes) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(image_bytes).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        vector = rng.standard_normal(self._dim)
        vector /= np.linalg.norm(vector) or 1.0
        return vector.astype(float).tolist()


class ClipEmbedder:
    """OpenCLIP ViT-B-32. Imports torch/open_clip lazily and loads the model once."""

    def __init__(self, model_name: str, pretrained: str) -> None:
        self._model_name = model_name
        self._pretrained = pretrained
        self._model = None
        self._preprocess = None
        self._torch = None

    def _ensure_loaded(self) -> None:
        if self._model is None:
            import open_clip  # imported lazily so the [ml] extra isn't needed to import us
            import torch

            model, _, preprocess = open_clip.create_model_and_transforms(
                self._model_name, pretrained=self._pretrained
            )
            model.eval()
            self._model = model
            self._preprocess = preprocess
            self._torch = torch

    def embed(self, image_bytes: bytes) -> list[float]:
        from PIL import Image

        self._ensure_loaded()
        if self._model is None or self._preprocess is None:  # pragma: no cover
            raise RuntimeError("embedder failed to load")
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        tensor = self._preprocess(image).unsqueeze(0)
        with self._torch.no_grad():
            features = self._model.encode_image(tensor)
            features = features / features.norm(dim=-1, keepdim=True)
        return features[0].cpu().numpy().astype(float).tolist()


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    if settings.embedder_backend == "fake":
        return FakeEmbedder(settings.embedding_dim)
    return ClipEmbedder(settings.clip_model, settings.clip_pretrained)
