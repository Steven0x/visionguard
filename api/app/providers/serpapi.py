"""SerpApi providers: Google Lens (reverse image) and Google (keyword)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from api.app.providers.base import ProviderResponse, ProviderResult

_SERPAPI_URL = "https://serpapi.com/search"
_RETRY_STATUS = {429, 500, 502, 503, 504}


def _get_json(params: dict[str, str], *, retries: int = 3, timeout: float = 20.0) -> dict[str, Any]:
    delay = 0.5
    for attempt in range(retries + 1):
        response = httpx.get(_SERPAPI_URL, params=params, timeout=timeout)
        if response.status_code in _RETRY_STATUS and attempt < retries:
            time.sleep(delay)
            delay *= 2
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError("unreachable")  # pragma: no cover


class SerpApiLensProvider:
    name = "google_lens"

    def __init__(self, api_key: str, cost_cents: int) -> None:
        self._api_key = api_key
        self._cost_cents = cost_cents

    def search(self, image_url: str) -> ProviderResponse:
        data = _get_json(
            {"engine": "google_lens", "url": image_url, "api_key": self._api_key}
        )
        results: list[ProviderResult] = []
        for match in [*data.get("visual_matches", []), *data.get("exact_matches", [])]:
            source = match.get("image") or match.get("thumbnail")
            if not source:
                continue
            results.append(
                ProviderResult(
                    source_url=source,
                    page_url=match.get("link"),
                    title=match.get("title"),
                    thumbnail_url=match.get("thumbnail"),
                    kind="image",
                )
            )
        return ProviderResponse(results=results, calls_made=1, cost_cents=self._cost_cents)


class SerpApiSearchProvider:
    name = "google_search"

    def __init__(self, api_key: str, cost_cents: int) -> None:
        self._api_key = api_key
        self._cost_cents = cost_cents

    def search(self, query: str) -> ProviderResponse:
        data = _get_json({"engine": "google", "q": query, "api_key": self._api_key})
        results = [
            ProviderResult(
                source_url=item["link"],
                page_url=item.get("link"),
                title=item.get("title"),
                kind="link",
            )
            for item in data.get("organic_results", [])
            if item.get("link")
        ]
        return ProviderResponse(results=results, calls_made=1, cost_cents=self._cost_cents)
