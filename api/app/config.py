"""Application settings, loaded from the environment via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# APP_ENV values where the Clerk-bypassing test auth (and other fakes) are permitted.
_TEST_AUTH_ALLOWED_ENVS = {"dev", "test"}
# APP_ENV values that are real, network-connected deployments. They get the strict backend
# guard (see Settings._guard_deployed_env): no fake/none backends, real Clerk, exact CORS.
_DEPLOYED_ENVS = {"staging", "production"}
# Real CSAM scanner backends. EMPTY until a PhotoDNA/Safer backend is implemented behind the
# csam.py interface — so a deployed env (which requires a real backend) cannot boot yet. That
# is intentional (CLAUDE.md #7): production must not run with imagery flowing and no scanner.
_REAL_CSAM_BACKENDS: set[str] = set()
# Minimum object-lock retention for production evidence (7 years), unless an explicit,
# documented override is set. Matches the claims-matrix retention open question (pending counsel).
_MIN_PRODUCTION_RETENTION_DAYS = 2555


def _is_exact_origin(origin: str) -> bool:
    """True only for a bare ``scheme://host[:port]`` origin (no path/query/fragment/wildcard).

    Rejects wildcards, whitespace/control characters (incl. interior NUL and a bare trailing
    ``#``/``?``), non-ASCII, and userinfo. The final round-trip check (``urlunsplit`` back to the
    same string) is the real guard: anything urlsplit dropped or normalised won't match.
    """
    if not origin.isascii() or not origin.isprintable():
        return False
    if any(c in origin for c in "*#?") or origin != origin.strip():
        return False
    parts = urlsplit(origin)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username:
        return False
    # Exact means path/query/fragment are empty AND the string re-serialises to itself.
    if parts.path or parts.query or parts.fragment:
        return False
    return urlunsplit((parts.scheme, parts.netloc, "", "", "")) == origin


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
    # Require MFA (Clerk `fva` second-factor claim) on every staff token. Off in dev/test
    # (test tokens carry no `fva`); the deployed-env guard requires it True in staging/production.
    clerk_require_mfa: bool = False

    # Observability & operability (Slice 11)
    log_level: str = "INFO"
    log_json: bool = False  # structured JSON logs; the deployed-env guard REQUIRES this on
    sentry_dsn: str = ""  # error tracking is off unless a DSN is set
    sentry_traces_sample_rate: float = 0.0

    # Security controls (Slice 11). Off by default so dev/test behave as before; the deployed-env
    # guard REQUIRES them on (refuses to boot otherwise). Rate limit is keyed on the VERIFIED
    # staff id.
    security_headers_enabled: bool = False
    rate_limit_enabled: bool = False
    rate_limit_writes_per_min: int = 60
    max_request_bytes: int = 30_000_000  # hard cap on any request body (413 past this)

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
    # Slice 12: cap URL tips per agency user per day (on top of the per-minute write rate limit),
    # since each tip can trigger a fetch + provider cost. Over the cap → 429.
    portal_tip_daily_cap: int = 50
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
    # Discovery queries containing any of these are suppressed while no REAL CSAM scanner is
    # connected (safe mode) — they tend to surface the riskiest imagery. See services/discovery.
    discovery_risky_terms: str = "leaked,leak,onlyfans,nude,nudes,mega,telegram,stolen,xxx,free"

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
    # Non-empty reason lets production run below the 7-year floor (documented, deliberate).
    evidence_retention_override_reason: str = ""
    evidence_freshness_days: int = 7  # a Filed case needs a sealed capture newer than this
    capture_nav_timeout_ms: int = 45_000
    capture_max_page_px: int = 20_000  # cap full-page screenshot height
    capture_tool_version: str = "vg-capture/1.0.0"
    # TSAs tried in order; first answer wins. Real backend only. Both roots are pinned in
    # evidence_roots/ and both responses parse under rfc3161-client's strict DER parser (DigiCert,
    # Sectigo and Apple do not — their certificate SET is not DER-sorted — so they are not listed).
    # Adding a TSA here means pinning its root in evidence_roots/tsa_pinned_roots.pem. See
    # evidence_ts.py.
    tsa_urls: str = (
        "https://freetsa.org/tsr,https://timestamp.sigstore.dev/api/v1/timestamp"
    )

    # Email & notices (Slice 8). `outbox` captures messages and never touches the network, so
    # dev/test can NEVER send real mail; `sendgrid` sends via SendGrid and is refused outside
    # production (guarded below), mirroring the CSAM/auth-bypass guards.
    email_backend: str = "outbox"  # "outbox" (dev/test/default) | "sendgrid" (prod)
    sendgrid_api_key: str = ""
    email_from: str = "notices@visionguard.example"
    email_reply_to: str = ""
    email_rate_limit_per_min: int = 30

    # Billing (Slice 13). `fake` records calls in-memory (dev/test, never the network); `stripe`
    # talks to Stripe and is required in deployments (guarded below). All PRICING lives on Stripe
    # Price objects referenced by these IDs — our code only sets a quantity and attaches coupons.
    billing_backend: str = "fake"  # "fake" (dev/test) | "stripe" (deployments)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_core_monthly: str = ""
    stripe_price_core_annual: str = ""
    stripe_price_priority_monthly: str = ""
    stripe_price_priority_annual: str = ""
    stripe_price_onboarding_audit: str = ""
    stripe_coupon_design_partner: str = ""
    # The Billing-Portal configuration that DISABLES subscription quantity/plan edits (set via the
    # Stripe API). Quantity is ours to derive; plan changes go through staff.
    stripe_portal_configuration_id: str = ""
    # Pass `automatic_tax` to Checkout. Off until sales-tax nexus/registration is confirmed.
    stripe_automatic_tax: bool = False
    billing_min_quantity: int = 5  # subscription quantity floor (per-subject plans)
    billing_grace_days: int = 14  # past_due grace before suspension

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
    def discovery_risky_term_list(self) -> list[str]:
        return [t.strip().lower() for t in self.discovery_risky_terms.split(",") if t.strip()]

    @property
    def csam_scanner_is_real(self) -> bool:
        """A real CSAM scanner is connected (not `none`/`fake`). While false, discovery runs in
        'safe mode': risky-term queries are suppressed and staff see a banner (CLAUDE.md #7)."""
        return self.csam_scanner_backend in _REAL_CSAM_BACKENDS

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_deployed(self) -> bool:
        """A real, network-connected deployment (staging or production) — gets the strict guard."""
        return self.app_env in _DEPLOYED_ENVS

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
        # Allowed values: none/fake plus any implemented real backend (empty set today).
        if self.csam_scanner_backend not in ({"none", "fake"} | _REAL_CSAM_BACKENDS):
            allowed = ", ".join(sorted({"none", "fake"} | _REAL_CSAM_BACKENDS))
            raise ValueError(
                f"CSAM_SCANNER_BACKEND must be one of: {allowed} (got "
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

        # Billing: the fake backend never talks to Stripe, so it's dev/test only. And a LIVE
        # Stripe secret key must never be used outside production — a misconfigured staging/dev
        # must not charge real cards. (Production is required to use live keys; see the deployed
        # guard.) Webhook secrets (`whsec_`) are mode-agnostic, so only the secret key is checked.
        if self.billing_backend not in ("fake", "stripe"):
            raise ValueError("BILLING_BACKEND must be 'fake' or 'stripe'.")
        if self.billing_backend == "fake" and self.app_env not in _TEST_AUTH_ALLOWED_ENVS:
            raise ValueError(
                "BILLING_BACKEND=fake is only allowed when APP_ENV is 'dev' or 'test' "
                f"(got APP_ENV={self.app_env!r}). Refusing to start."
            )
        if self.stripe_secret_key.startswith("sk_live_") and not self.is_production:
            raise ValueError(
                "A live Stripe secret key (sk_live_…) is only allowed in production "
                f"(got APP_ENV={self.app_env!r}). Refusing to start."
            )
        return self

    @model_validator(mode="after")
    def _guard_deployed_env(self) -> Settings:
        """Refuse to boot a staging/production deployment that isn't fully production-safe.

        Every pluggable backend must be its REAL implementation (no fake/none), Clerk must be
        configured, CORS must be an exact origin allowlist, and MFA must be required. Because no
        real CSAM scanner exists yet (_REAL_CSAM_BACKENDS is empty), a deployed env cannot boot
        until one is connected — intentional (CLAUDE.md #7). All problems are reported at once.
        """
        if not self.is_deployed:
            return self

        problems: list[str] = []
        # Every backend must be real. (name, current, required)
        for name, current, required in (
            ("EMBEDDER_BACKEND", self.embedder_backend, "clip"),
            ("FETCHER_BACKEND", self.fetcher_backend, "safe"),
            ("PROVIDER_BACKEND", self.provider_backend, "serpapi"),
            ("CAPTURE_BACKEND", self.capture_backend, "playwright"),
            ("TSA_BACKEND", self.tsa_backend, "rfc3161"),
            ("STORAGE_BACKEND", self.storage_backend, "s3"),
        ):
            if current != required:
                problems.append(f"{name} must be {required!r} in a deployment (got {current!r}).")

        # CSAM: a real scanner is mandatory — none/fake never store imagery in a deployment.
        if self.csam_scanner_backend not in _REAL_CSAM_BACKENDS:
            problems.append(
                "CSAM_SCANNER_BACKEND must be a real scanner backend in a deployment (got "
                f"{self.csam_scanner_backend!r}). No real backend is connected yet, so a "
                "deployment cannot start until one is — intentional (CLAUDE.md #7)."
            )

        # Clerk must be configured (the test-auth bypass is already forbidden here).
        if not self.clerk_jwt_issuer:
            problems.append("CLERK_JWT_ISSUER is required in a deployment.")
        if not self.clerk_jwks_url:
            problems.append("CLERK_JWKS_URL is required in a deployment.")
        if not self.clerk_require_mfa:
            problems.append("CLERK_REQUIRE_MFA must be true in a deployment (staff MFA required).")

        # The hardening controls must actually be ON — a deployment must not boot degraded just
        # because a toml env block was copied/edited. The guard enforces them, not the toml alone.
        if not self.log_json:
            problems.append("LOG_JSON must be true in a deployment (structured, scrubbed logs).")
        if not self.security_headers_enabled:
            problems.append("SECURITY_HEADERS_ENABLED must be true in a deployment.")
        if not self.rate_limit_enabled:
            problems.append("RATE_LIMIT_ENABLED must be true in a deployment.")

        # CORS must be a non-empty list of exact origins (no wildcard, no path).
        origins = self.allowed_origin_list
        if not origins:
            problems.append("ALLOWED_ORIGINS must be a non-empty exact-origin list.")
        else:
            bad = [o for o in origins if not _is_exact_origin(o)]
            if bad:
                problems.append(f"ALLOWED_ORIGINS entries are not exact origins: {bad}.")

        # Email: production sends via SendGrid; staging must never send real mail (outbox only).
        if self.is_production and self.email_backend != "sendgrid":
            problems.append("EMAIL_BACKEND must be 'sendgrid' in production.")
        if self.app_env == "staging" and self.email_backend != "outbox":
            problems.append("EMAIL_BACKEND must be 'outbox' in staging (fake email only).")

        # Billing must be the real Stripe backend with all credentials + plan prices configured.
        # Production uses LIVE keys; staging uses TEST keys (staging must never charge real cards).
        if self.billing_backend != "stripe":
            problems.append(
                f"BILLING_BACKEND must be 'stripe' in a deployment (got {self.billing_backend!r})."
            )
        if not self.stripe_secret_key:
            problems.append("STRIPE_SECRET_KEY is required in a deployment.")
        if not self.stripe_webhook_secret:
            problems.append("STRIPE_WEBHOOK_SECRET is required in a deployment.")
        # The restricted Customer-Portal configuration (disables self-serve quantity/plan edits) is
        # mandatory — without it Stripe falls back to the account default, which would let a billing
        # contact change quantity/plan themselves (quantity is ours to derive; plan goes via staff).
        if not self.stripe_portal_configuration_id:
            problems.append(
                "STRIPE_PORTAL_CONFIGURATION_ID is required in a deployment (the restricted "
                "Customer-Portal config that disables self-serve quantity/plan changes)."
            )
        missing_prices = [
            name
            for name, value in (
                ("STRIPE_PRICE_CORE_MONTHLY", self.stripe_price_core_monthly),
                ("STRIPE_PRICE_CORE_ANNUAL", self.stripe_price_core_annual),
                ("STRIPE_PRICE_PRIORITY_MONTHLY", self.stripe_price_priority_monthly),
                ("STRIPE_PRICE_PRIORITY_ANNUAL", self.stripe_price_priority_annual),
            )
            if not value
        ]
        if missing_prices:
            problems.append(
                f"Stripe plan price IDs are required in a deployment: {missing_prices}."
            )
        if self.is_production and not self.stripe_secret_key.startswith("sk_live_"):
            problems.append("STRIPE_SECRET_KEY must be a live key (sk_live_…) in production.")
        if self.app_env == "staging" and not self.stripe_secret_key.startswith("sk_test_"):
            problems.append(
                "STRIPE_SECRET_KEY must be a test key (sk_test_…) in staging (no real cards)."
            )

        # Production evidence retention floor (7 years) unless a documented override is set.
        if (
            self.is_production
            and self.evidence_retention_days < _MIN_PRODUCTION_RETENTION_DAYS
            and not self.evidence_retention_override_reason.strip()
        ):
            problems.append(
                f"EVIDENCE_RETENTION_DAYS must be >= {_MIN_PRODUCTION_RETENTION_DAYS} in "
                "production unless EVIDENCE_RETENTION_OVERRIDE_REASON is set (got "
                f"{self.evidence_retention_days})."
            )

        if problems:
            joined = "\n  - ".join(problems)
            raise ValueError(
                f"APP_ENV={self.app_env!r} is a deployment but its config is not "
                f"production-safe. Refusing to start:\n  - {joined}"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
