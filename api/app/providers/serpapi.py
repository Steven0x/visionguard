"""SerpApi providers: Google Lens (reverse image) and Google (keyword)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from api.app.config import get_settings
from api.app.providers.base import ProviderError, ProviderResponse, ProviderResult

_SERPAPI_URL = "https://serpapi.com/search"
_RETRY_STATUS = {429, 500, 502, 503, 504}
# SerpApi returns a 200 + top-level "error" for a plain EMPTY result set (e.g. a `site:` name
# sweep that matches nothing). That is not a failure and SerpApi does not bill it — so it must be
# treated as zero results, not as a dead run. Any OTHER "error" (bad key, quota, rate limit) is a
# real failure whose message we surface (it is SerpApi's own text — never our request URL/key).
_NO_RESULTS_MARKERS = ("hasn't returned any results", "has not returned any results")


def _sanitize_message(message: str) -> str:
    """Collapse whitespace and cap length. SerpApi's error text is server-authored and never
    contains our api_key or the signed asset URL (those live only in the request URL, which we
    never put in an exception)."""
    return " ".join(message.split())[:200]


def _is_no_results(message: str) -> bool:
    low = message.lower()
    return any(marker in low for marker in _NO_RESULTS_MARKERS)


def _get_json(
    params: dict[str, str], *, retries: int | None = None, timeout: float | None = None
) -> tuple[dict[str, Any], bool]:
    """Return (data, billed). `billed` is False for an empty-result-set response (not charged by
    SerpApi); True for a normal successful search. Raises a sanitized ProviderError on a real
    failure — the message is safe to show in the UI / store on run.error.

    Transient failures (network/timeout errors, 429, 5xx) are retried with exponential backoff up
    to `retries` times before failing, so a single slow response doesn't kill a whole run."""
    settings = get_settings()
    retries = settings.serpapi_max_retries if retries is None else retries
    timeout = settings.serpapi_timeout_seconds if timeout is None else timeout
    delay = 0.5
    for attempt in range(retries + 1):
        try:
            response = httpx.get(_SERPAPI_URL, params=params, timeout=timeout)
        except httpx.RequestError as exc:
            # Timeouts and other transient transport errors — retry, then fail with the reason.
            if attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise ProviderError(
                f"SerpApi request error ({type(exc).__name__}) after {attempt + 1} attempts"
            ) from None
        if response.status_code in _RETRY_STATUS and attempt < retries:
            time.sleep(delay)
            delay *= 2
            continue
        if response.status_code >= 400:
            raise ProviderError(f"SerpApi returned HTTP {response.status_code}") from None
        data: dict[str, Any] = response.json()
        error = data.get("error")
        if error:
            message = str(error)
            if _is_no_results(message):
                return data, False  # empty result set — not a failure, not billed
            raise ProviderError(f"SerpApi: {_sanitize_message(message)}") from None
        return data, True
    raise ProviderError("SerpApi request failed")  # pragma: no cover


class SerpApiLensProvider:
    name = "google_lens"

    def __init__(self, api_key: str, cost_cents: int) -> None:
        self._api_key = api_key
        self._cost_cents = cost_cents

    def search(self, image_url: str) -> ProviderResponse:
        data, billed = _get_json(
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
        return _response(results, billed, self._cost_cents)


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
        data, billed = _get_json(
            {"engine": self._engine, "url": image_url, "api_key": self._api_key}
        )
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
        return _response(results, billed, self._cost_cents)


class SerpApiSearchProvider:
    name = "google_search"

    def __init__(self, api_key: str, cost_cents: int) -> None:
        self._api_key = api_key
        self._cost_cents = cost_cents

    def search(self, query: str) -> ProviderResponse:
        data, billed = _get_json({"engine": "google", "q": query, "api_key": self._api_key})
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
        return _response(results, billed, self._cost_cents)


def _response(
    results: list[ProviderResult], billed: bool, cost_cents: int
) -> ProviderResponse:
    """A billed search counts 1 call + its cost; an empty-result-set response (not billed by
    SerpApi) counts 0 calls / 0 cost so it never consumes the workspace budget."""
    return ProviderResponse(
        results=results,
        calls_made=1 if billed else 0,
        cost_cents=cost_cents if billed else 0,
    )
