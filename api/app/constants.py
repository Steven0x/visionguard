"""Domain constants shared across Slice 1 services."""

from __future__ import annotations

# US state + territory 2-letter codes (uppercase). DC included; territories included so a
# valid US residence outside IL/WA clears the biometric block.
US_STATES: frozenset[str] = frozenset(
    {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI",
        "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN",
        "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
        "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
        "WV", "WI", "WY", "AS", "GU", "MP", "PR", "VI",
    }
)

# States where biometric features are blocked until counsel clears it (CLAUDE.md #9).
GEO_BLOCKED_STATES: frozenset[str] = frozenset({"IL", "WA"})

# Biometrics are permitted only for a known US state that is NOT geo-blocked. Anything else
# (null / unknown / non-US) fails closed → blocked.
BIOMETRICS_ALLOWED_STATES: frozenset[str] = US_STATES - GEO_BLOCKED_STATES

# CSV subject import limits.
SUBJECT_IMPORT_MAX_BYTES: int = 1_000_000  # ~1 MB
SUBJECT_IMPORT_MAX_ROWS: int = 1_000
