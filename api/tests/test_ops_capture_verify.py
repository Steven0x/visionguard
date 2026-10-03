"""The day-1 ops evidence tool (`ops/capture/capture.py`) — RFC 3161 verify path.

`capture.py` is a standalone script, not part of the `api` package, so we load it by path.
A committed capture-folder fixture (`ops/capture/tests/fixtures/sample_capture`) carries a real
freetsa.org RFC 3161 token over its exact `manifest.json` bytes; `verify_token` / `cmd_verify`
must accept it and reject any tampering. Regenerate the fixture by POSTing a request built over
the manifest bytes to https://freetsa.org/tsr (see capture.py).
"""

from __future__ import annotations

import importlib.util
from argparse import Namespace
from pathlib import Path

import pytest

pytest.importorskip("rfc3161_client", reason="ops capture verify needs rfc3161-client")

_REPO = Path(__file__).resolve().parents[2]
_FIXTURE = _REPO / "ops" / "capture" / "tests" / "fixtures" / "sample_capture"


def _load_capture():
    path = _REPO / "ops/capture/capture.py"
    spec = importlib.util.spec_from_file_location("vg_ops_capture", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verify_token_accepts_recorded_real_token() -> None:
    cap = _load_capture()
    manifest_bytes = (_FIXTURE / "manifest.json").read_bytes()
    token = (_FIXTURE / "manifest.tsr").read_bytes()
    ok, detail = cap.verify_token(token, manifest_bytes)
    assert ok is True, detail


def test_verify_token_rejects_tampered_manifest() -> None:
    cap = _load_capture()
    token = (_FIXTURE / "manifest.tsr").read_bytes()
    ok, _ = cap.verify_token(token, (_FIXTURE / "manifest.json").read_bytes() + b"x")
    assert ok is False


def test_cmd_verify_passes_on_the_fixture_capture(capsys) -> None:
    cap = _load_capture()
    rc = cap.cmd_verify(Namespace(folder=str(_FIXTURE)))
    out = capsys.readouterr().out
    assert rc == 0
    assert "VERIFIED" in out
    assert "OK   timestamp" in out
