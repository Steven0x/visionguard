"""Provider factories, selected by PROVIDER_BACKEND."""

from __future__ import annotations

from api.app.config import get_settings
from api.app.providers.base import (
    KeywordProvider,
    ProviderResponse,
    ProviderResult,
    ReverseImageProvider,
)

__all__ = [
    "KeywordProvider",
    "ProviderResponse",
    "ProviderResult",
    "ReverseImageProvider",
    "get_keyword_provider",
    "get_reverse_image_providers",
]


def get_reverse_image_providers(*, tineye_enabled: bool) -> list[ReverseImageProvider]:
    settings = get_settings()
    if settings.provider_backend == "fake":
        from api.app.providers.fakes import FakeReverseImageProvider

        return [FakeReverseImageProvider()]

    from api.app.providers.serpapi import SerpApiLensProvider

    providers: list[ReverseImageProvider] = [
        SerpApiLensProvider(settings.serpapi_key, settings.serpapi_cost_cents_per_call)
    ]
    if tineye_enabled:
        from api.app.providers.tineye import TinEyeProvider

        providers.append(
            TinEyeProvider(settings.tineye_api_key, settings.tineye_cost_cents_per_call)
        )
    return providers


def get_keyword_provider() -> KeywordProvider:
    settings = get_settings()
    if settings.provider_backend == "fake":
        from api.app.providers.fakes import FakeKeywordProvider

        return FakeKeywordProvider()

    from api.app.providers.serpapi import SerpApiSearchProvider

    return SerpApiSearchProvider(settings.serpapi_key, settings.serpapi_cost_cents_per_call)
