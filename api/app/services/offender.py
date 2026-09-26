"""Normalize a candidate URL into an offender key for grouping cases.

Heuristic, documented in docs/specs/cases.md: known social platforms → ``platform:@handle``;
parseable marketplaces → ``etsy:<shop>`` / ``ebay:<seller>``; everything else → ``domain:<host>``.
Best-effort — a wrong grouping is a UX nuisance, never a correctness/isolation issue.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

# host (sans leading www.) → platform label. The handle is the first path segment.
# Note: x.com and twitter.com both normalize to the "twitter" label on purpose, so the same
# offender groups together across the rename (the spec writes this label as "x").
_PLATFORMS = {
    "instagram.com": "instagram",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "tiktok.com": "tiktok",
    "onlyfans.com": "onlyfans",
    "facebook.com": "facebook",
    "fb.com": "facebook",
    "reddit.com": "reddit",
    "youtube.com": "youtube",
    "pornhub.com": "pornhub",
}


def _norm_host(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


def _first_segment(path: str) -> str | None:
    for seg in path.split("/"):
        if seg:
            return seg
    return None


def offender_key(url: str | None) -> str | None:
    """Return a stable grouping key, or None if the URL can't be parsed."""
    if not url:
        return None
    parts = urlsplit(url)
    host = _norm_host((parts.hostname or "").lower())
    if not host:
        return None
    path = parts.path or "/"

    platform = _PLATFORMS.get(host)
    if platform is not None:
        seg = _first_segment(path)
        if seg:
            # tiktok handles are already "@handle"; others aren't — normalize to "@handle".
            handle = seg if seg.startswith("@") else f"@{seg}"
            return f"{platform}:{handle.lower()}"
        return f"{platform}:"

    if host == "etsy.com" or host.endswith(".etsy.com"):
        segments = [s for s in path.split("/") if s]
        if len(segments) >= 2 and segments[0] == "shop":
            return f"etsy:{segments[1].lower()}"
    if host == "ebay.com" or host.endswith(".ebay.com"):
        segments = [s for s in path.split("/") if s]
        if len(segments) >= 2 and segments[0] == "usr":
            return f"ebay:{segments[1].lower()}"
        seller = parse_qs(parts.query).get("_ssn")
        if seller:
            return f"ebay:{seller[0].lower()}"

    return f"domain:{host}"
