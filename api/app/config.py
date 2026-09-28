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
    # CSAM scanning gate (CLAUDE.md #7) — see api/app/csam.py. Every open-web/uploaded image
    # must pass a `clean` scan before any bytes are stored/sealed. "none" (default) fails closed;
    # "fake" is dev/test-only (refused otherwise below). csam_fake_result drives the fake.
    csam_scanner_backend: str = "none"  # none | fake (real PhotoDNA/Safer added later)
    csam_fake_result: str = "clean"  # clean | match | error (fake backend only)

    # Review & matching (Slice 5). Thresholds, weights and the leak/tube domain + risky-keyword
    # lists are config (env), never hard-coded, so ops can tune them without a deploy.
    review_phash_exact_max: int = 6  # Hamming distance ≤ this = near-exact copy
    review_phash_near_max: int = 16  # ≤ this still counts as a pHash match
    review_embedding_match_threshold: float = 0.80  # cosine similarity ≥ this = visual match
    review_score_visual_exact: int = 60
    review_score_visual_near: int = 40
    review_score_embedding_max: int = 40
    review_score_leak_domain: int = 25
    review_score_risky_keyword: int = 8  # per keyword
    review_score_risky_keyword_cap: int = 24
    # Seed placeholders — ops maintains the real list via env. Comma-separated hostnames.
    review_leak_domains: str = "leak-tube.example,leaks.example"
    review_risky_keywords: str = "leaked,leak,free,onlyfans,nude,nudes,stolen,xxx"
    review_bulk_dismiss_max: int = 500

    # Cases (Slice 6). Follow-up timer per state: "state:days,..." (config, not hard-coded).
    # A transition sets due_at = now + days[new_state]; terminal states clear it.
    case_due_days: str = "confirmed:2,filed:3,removed:1,countered:5,escalated:7,monitoring:14"

    # Outcomes & re-upload watch (Slice 9). A removal is proposed only when two consecutive
    # `gone` rechecks are at least this many hours apart (a single 404 can be a geo-block / login
    # wall / rate limit). The monitoring watch window reuses case_due_days["monitoring"].
    recheck_min_gap_hours: int = 24

    # Evidence capture (Slice 7).
    capture_backend: str = "playwright"  # "playwright" (prod) | "fake" (tests/CI)
    tsa_backend: str = "rfc3161"  # "rfc3161" (prod) | "fake" (tests/CI)
    storage_evidence_bucket: str = "vg-evidence"  # write-once, object-locked; separate bucket
    evidence_object_lock_mode: str = "GOVERNANCE"  # GOVERNANCE | COMPLIANCE
    evidence_retention_days: int = 365  # object-lock retention (dev overrides to ~1 in .env)
    evidence_freshness_days: int = 7  # a Filed case needs a sealed capture newer than this
    capture_nav_timeout_ms: int = 45_000
    capture_max_page_px: int = 20_000  # cap full-page screenshot height
    capture_tool_version: str = "vg-capture/1.0.0"
    # TSAs tried in order; first answer wins. Real backend only.
    tsa_urls: str = (
        "https://freetsa.org/tsr,http://timestamp.digicert.com,http://timestamp.sectigo.com"
    )

    # Email & notices (Slice 8). `outbox` captures messages and never touches the network, so
    # dev/test can NEVER send real mail; `sendgrid` sends via SendGrid and is refused outside
    # production (guarded below), mirroring the CSAM/auth-bypass guards.
    email_backend: str = "outbox"  # "outbox" (dev/test/default) | "sendgrid" (prod)
    sendgrid_api_key: str = ""
    email_from: str = "notices@visionguard.example"
    email_reply_to: str = ""
    email_rate_limit_per_min: int = 30

    @property
    def allowed_origin_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def case_due_days_map(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for pair in self.case_due_days.split(","):
            pair = pair.strip()
            if not pair or ":" not in pair:
                continue
            state, _, days = pair.partition(":")
            try:
                result[state.strip()] = int(days)
            except ValueError:
                continue
        return result

    @property
    def tsa_url_list(self) -> list[str]:
        return [u.strip() for u in self.tsa_urls.split(",") if u.strip()]

    @property
    def review_leak_domain_set(self) -> set[str]:
        return {d.strip().lower() for d in self.review_leak_domains.split(",") if d.strip()}

    @property
    def review_risky_keyword_list(self) -> list[str]:
        return [k.strip().lower() for k in self.review_risky_keywords.split(",") if k.strip()]

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
        # Fail loud on a misconfigured CSAM gate rather than silently degrading to fail-closed.
        if self.csam_scanner_backend not in ("none", "fake"):
            raise ValueError(
                f"CSAM_SCANNER_BACKEND must be 'none' or 'fake' (got "
                f"{self.csam_scanner_backend!r})."
            )
        if self.csam_fake_result not in ("clean", "match", "error"):
            raise ValueError("CSAM_FAKE_RESULT must be 'clean', 'match', or 'error'.")
        # The fake CSAM scanner must never run in production — it does not actually scan.
        if self.csam_scanner_backend == "fake" and self.app_env not in _TEST_AUTH_ALLOWED_ENVS:
            raise ValueError(
                "CSAM_SCANNER_BACKEND=fake is only allowed when APP_ENV is 'dev' or 'test' "
                f"(got APP_ENV={self.app_env!r}). Refusing to start."
            )
        # Email: dev/test must never send real mail. `sendgrid` is production-only and needs
        # its credentials; anything else falls back to the capture-only outbox.
        if self.email_backend not in ("outbox", "sendgrid"):
            raise ValueError("EMAIL_BACKEND must be 'outbox' or 'sendgrid'.")
        if self.email_backend == "sendgrid":
            if not self.is_production:
                raise ValueError(
                    "EMAIL_BACKEND=sendgrid is only allowed in production (APP_ENV not in "
                    f"{sorted(_TEST_AUTH_ALLOWED_ENVS)}); dev/test can never send real mail. "
                    f"Got APP_ENV={self.app_env!r}. Refusing to start."
                )
            if not (self.sendgrid_api_key and self.email_from):
                raise ValueError(
                    "EMAIL_BACKEND=sendgrid requires SENDGRID_API_KEY and EMAIL_FROM."
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
