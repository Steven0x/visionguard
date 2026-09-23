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
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
