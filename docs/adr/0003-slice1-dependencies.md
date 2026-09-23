# ADR 0003: Slice 1 dependency

- **Status:** Accepted
- **Date:** 2026-09-23
- **Context:** Slice 1 adds CSV subject import via a multipart file upload. CLAUDE.md requires
  an ADR for any dependency beyond the named stack.

## Decision

Add **`python-multipart`** — required by FastAPI/Starlette to parse `multipart/form-data`
(the `UploadFile` used by the subject-import endpoints). It is the standard, FastAPI-endorsed
parser; no runtime code of our own depends on it directly.

No other backend or frontend dependency is added for Slice 1. Contact-email is validated as a
plain string (no `email-validator`), and the frontend uses state-based navigation (no router
library) to avoid new dependencies for this slice.

## Consequences

- CSV parsing itself uses the Python standard library (`csv`, `io`); no CSV dependency added.
