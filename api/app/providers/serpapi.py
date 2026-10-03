"""SerpApi providers: Google Lens (reverse image) and Google (keyword)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from api.app.providers.base import ProviderError, ProviderResponse, ProviderResult

_SERPAPI_URL = "https://serpapi.com/search"
_RETRY_STATUS = {429, 500, 502, 503, 504}


def _get_json(params: dict[str, str], *, retries: int = 3, timeout: float = 20.0) -> dict[str, Any]:
    # Never let the exception text carry the request URL (it contains api_key + the signed
    # asset URL) into logs or run.error — raise a sanitized ProviderError instead.
    delay = 0.5
    for attempt in range(retries + 1):
        try:
            response = httpx.get(_SERPAPI_URL, params=params, timeout=timeout)
        except httpx.RequestError as exc:
            raise ProviderError(f"serpapi request error: {type(exc).__name__}") from None
        if response.status_code in _RETRY_STATUS and attempt < retries:
            time.sleep(delay)
            delay *= 2
            continue
        if response.status_code >= 400:
            raise ProviderError(f"serpapi returned HTTP {response.status_code}") from None
        data: dict[str, Any] = response.json()
        # SerpApi signals invalid/exhausted keys with a 200 + top-level "error". Treat that as a
        # failed call, not an empty result set — otherwise a dead key looks like "no matches" and
        # staff wrongly conclude a subject is clean. Don't echo the message (may carry params).
        if "error" in data:
            raise ProviderError("serpapi returned an error response") from None
        return data
    raise ProviderError("serpapi request failed")  # pragma: no cover


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


# Result-list keys SerpApi uses across reverse-image engines; parsed defensively (order = priority).
_REVERSE_MATCH_KEYS = (
    "image_results",
    "images_results",
    "visual_matches",
    "inline_images",
    "organic_results",
)


class SerpApiReverseProvider:
    """The second reverse-image engine via SerpApi (`yandex_images`). It is face-similarity-heavy,
    so it is treated as biometric — gated on biometric consent + a per-workspace admin opt-in and
    never used for sensitive subjects (enforced in the worker). See docs/specs/discovery.md."""

    def __init__(self, engine: str, api_key: str, cost_cents: int) -> None:
        self.name = f"serpapi_{engine}"
        self._engine = engine
        self._api_key = api_key
        self._cost_cents = cost_cents

    def search(self, image_url: str) -> ProviderResponse:
        data = _get_json({"engine": self._engine, "url": image_url, "api_key": self._api_key})
        matches: list[dict[str, Any]] = []
        for key in _REVERSE_MATCH_KEYS:
            matches.extend(data.get(key, []))
        results: list[ProviderResult] = []
        for match in matches:
            source = (
                match.get("original")
                or match.get("original_image")
                or match.get("image")
                or match.get("thumbnail")
            )
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
