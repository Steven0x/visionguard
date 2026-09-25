"""TinEye reverse-image provider (used only when a workspace enables it)."""

from __future__ import annotations

import httpx

from api.app.providers.base import ProviderError, ProviderResponse, ProviderResult

_TINEYE_URL = "https://api.tineye.com/rest/search/"


class TinEyeProvider:
    name = "tineye"

    def __init__(self, api_key: str, cost_cents: int) -> None:
        self._api_key = api_key
        self._cost_cents = cost_cents

    def search(self, image_url: str) -> ProviderResponse:
        try:
            response = httpx.get(
                _TINEYE_URL,
                params={"image_url": image_url, "api_key": self._api_key},
                timeout=20.0,
            )
        except httpx.RequestError as exc:
            raise ProviderError(f"tineye request error: {type(exc).__name__}") from None
        if response.status_code >= 400:
            raise ProviderError(f"tineye returned HTTP {response.status_code}") from None
        data = response.json()
        results = [
            ProviderResult(
                source_url=match.get("image_url", ""),
                page_url=(match.get("backlinks") or [{}])[0].get("url"),
                kind="image",
            )
            for match in data.get("results", {}).get("matches", [])
            if match.get("image_url")
        ]
        return ProviderResponse(results=results, calls_made=1, cost_cents=self._cost_cents)
