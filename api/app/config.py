"""Application settings, loaded from the environment via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# APP_ENV values where the Clerk-bypassing test auth is permitted.
_TEST_AUTH_ALLOWED_ENVS = {"dev", "test"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    app_env: str = "dev"
    auth_test_mode: bool = False
    allowed_origins: str = "http://localhost:5173"

    # Database
    database_url: str = (
        "postgresql+psycopg://visionguard:visionguard@localhost:5432/visionguard"
    )

    # Clerk
    clerk_jwt_issuer: str = ""
    clerk_jwks_url: str = ""
    clerk_audience: str = ""

    # Redis (worker)
    redis_url: str = "redis://localhost:6379/0"

    # Object storage. "s3" = MinIO (dev) / R2 (prod); "fake" = in-memory (tests/CI).
    storage_backend: str = "s3"
    storage_endpoint_url: str = "http://localhost:9000"
    storage_access_key_id: str = "minioadmin"
    storage_secret_access_key: str = "minioadmin"  # noqa: S105 - local dev default
    storage_bucket: str = "vg-assets"
    storage_region: str = "us-east-1"
    storage_signed_url_ttl_seconds: int = 300
    storage_max_upload_bytes: int = 15_000_000

    # Assets & fingerprinting (Slice 3)
    asset_max_upload_bytes: int = 25_000_000
    embedder_backend: str = "clip"  # "clip" (prod) | "fake" (tests/CI)
    clip_model: str = "ViT-B-32"
    clip_pretrained: str = "laion2b_s34b_b79k"
    embedding_dim: int = 512
    thumbnail_max_px: int = 256
    asset_max_fingerprint_attempts: int = 5

    # Discovery (Slice 4)
    fetcher_backend: str = "safe"  # "safe" (prod) | "fake" (tests/CI)
    provider_backend: str = "serpapi"  # "serpapi" (prod) | "fake" (tests/CI)
    fetcher_timeout_seconds: float = 10.0
    fetcher_max_bytes: int = 10_000_000
    fetcher_max_redirects: int = 3
    fetcher_user_agent: str = "VisionGuard/1.0 (+https://visionguard.example)"
    discovery_default_monthly_budget: int = 500
    discovery_intake_max_urls: int = 200
    serpapi_key: str = ""
    tineye_api_key: str = ""
    serpapi_cost_cents_per_call: int = 1
    tineye_cost_cents_per_call: int = 20

    @property
    def allowed_origin_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env not in _TEST_AUTH_ALLOWED_ENVS

    @model_validator(mode="after")
    def _guard_test_mode(self) -> Settings:
        # A misconfigured deploy must never ship the auth bypass. Fail fast at load.
        if self.auth_test_mode and self.app_env not in _TEST_AUTH_ALLOWED_ENVS:
            raise ValueError(
                "AUTH_TEST_MODE=1 is only allowed when APP_ENV is 'dev' or 'test' "
                f"(got APP_ENV={self.app_env!r}). Refusing to start."
            )
        # A wildcard origin with credentialed CORS is unsafe; forbid it outside dev/test.
        # (It would also disable the azp origin check, which keys off this same list.)
        if "*" in self.allowed_origin_list and self.app_env not in _TEST_AUTH_ALLOWED_ENVS:
            raise ValueError(
                "ALLOWED_ORIGINS must not be '*' when APP_ENV is not 'dev'/'test'."
            )
        # Presigned document URLs must be short-lived; cap at 15 minutes.
        if not 0 < self.storage_signed_url_ttl_seconds <= 900:
            raise ValueError("STORAGE_SIGNED_URL_TTL_SECONDS must be between 1 and 900.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
