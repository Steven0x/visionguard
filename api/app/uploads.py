"""Shared upload helpers: capped chunked reads and content-type sniffing."""

from __future__ import annotations

from fastapi import UploadFile

_CHUNK = 64 * 1024

# Magic-byte signatures for the only document types we accept.
_SIGNATURES: list[tuple[bytes, str]] = [
    (b"%PDF-", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
]


class UploadTooLarge(Exception):
    """Raised when an upload exceeds the byte cap."""


class UnsupportedFileType(Exception):
    """Raised when a file's sniffed type is not PDF/JPEG/PNG."""


async def read_capped_upload(file: UploadFile, max_bytes: int) -> bytes:
    """Read an upload in chunks, aborting past ``max_bytes`` so a huge body can't be
    buffered whole into memory before the size check."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise UploadTooLarge(f"file too large (limit {max_bytes} bytes)")
        chunks.append(chunk)
    return b"".join(chunks)


def sniff_content_type(data: bytes) -> str | None:
    """Return the content type from magic bytes, or None if not an accepted type."""
    for signature, content_type in _SIGNATURES:
        if data.startswith(signature):
            return content_type
    return None


def require_document_type(data: bytes) -> str:
    """Validate an uploaded document by sniffing; return its content type or raise.

    Ignores the client-declared type and the extension — only the bytes decide.
    """
    content_type = sniff_content_type(data[:16])
    if content_type is None:
        raise UnsupportedFileType("only PDF, JPEG, or PNG files are accepted")
    return content_type
