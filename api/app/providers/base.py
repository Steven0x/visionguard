"""Discovery provider interfaces. Real clients call SerpApi/TinEye; tests use fakes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ProviderResult:
    source_url: str  # the found image/content URL
    page_url: str | None = None  # the page it appears on
    title: str | None = None
    thumbnail_url: str | None = None
    kind: str = "link"  # "image" | "link"


@dataclass
class ProviderResponse:
    results: list[ProviderResult]
    calls_made: int
    cost_cents: int


class ReverseImageProvider(Protocol):
    name: str

    def search(self, image_url: str) -> ProviderResponse:
        """Reverse-image search for a (public/signed) image URL."""
        ...


class KeywordProvider(Protocol):
    name: str

    def search(self, query: str) -> ProviderResponse:
        ...
