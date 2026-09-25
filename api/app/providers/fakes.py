"""Deterministic offline providers for tests/CI (no network)."""

from __future__ import annotations

import hashlib

from api.app.providers.base import ProviderResponse, ProviderResult


class FakeReverseImageProvider:
    name = "fake_reverse_image"

    def search(self, image_url: str) -> ProviderResponse:
        digest = hashlib.sha256(image_url.encode()).hexdigest()[:10]
        results = [
            ProviderResult(
                source_url=f"https://found.example/img/{digest}.png",
                page_url=f"https://found.example/page/{digest}",
                kind="image",
            )
        ]
        return ProviderResponse(results=results, calls_made=1, cost_cents=1)


class FakeKeywordProvider:
    name = "fake_keyword"

    def search(self, query: str) -> ProviderResponse:
        slug = hashlib.sha256(query.encode()).hexdigest()[:10]
        results = [
            ProviderResult(
                source_url=f"https://found.example/result/{slug}",
                page_url=f"https://found.example/result/{slug}",
                title=f"result for {query}",
                kind="link",
            )
        ]
        return ProviderResponse(results=results, calls_made=1, cost_cents=1)
