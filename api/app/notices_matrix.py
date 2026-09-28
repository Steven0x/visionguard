"""Matrix-conformant channel routing (docs/legal/claims-matrix.md).

Which channel *methods* each claim type may use. The load-bearing rule (CLAUDE.md #4): only
`copyright` may go out over an **email / DMCA** channel. `trademark` and `likeness` — and
`ncii`/`impersonation` — are **platform-form only** and may NEVER be routed to DMCA/email.

This module is intentionally dependency-free (no models, no session) so the channel seed
migration and the runtime `route_for` guard can share one source of truth.
"""

from __future__ import annotations

# claim_type → allowed ChannelMethod values.
CLAIM_ALLOWED_METHODS: dict[str, frozenset[str]] = {
    "copyright": frozenset({"email", "web_form", "portal"}),
    "trademark": frozenset({"web_form", "portal"}),  # never DMCA/email
    "likeness": frozenset({"web_form", "portal"}),  # never DMCA/email
    "ncii": frozenset({"web_form", "portal"}),
    "impersonation": frozenset({"web_form", "portal"}),
}


def method_allowed_for_claim(claim_type: str, method: str) -> bool:
    return method in CLAIM_ALLOWED_METHODS.get(claim_type, frozenset())
