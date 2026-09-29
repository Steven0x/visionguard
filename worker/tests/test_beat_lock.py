"""The per-job beat lock lets one runner in and turns a concurrent second run into a no-op;
it fails open when Redis is unreachable so a single-beat deployment (and eager tests) still run."""

from __future__ import annotations

import pytest

from worker import locks
from worker.locks import beat_lock, single_run


class _FakeRedis:
    """SET NX / GET / DELETE with no real expiry (enough for the lock semantics)."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = value.encode()
        return True

    def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(locks, "_redis", lambda: fake)
    return fake


def test_second_acquisition_while_held_is_refused(fake_redis: _FakeRedis) -> None:
    with beat_lock("job") as outer:
        assert outer is True
        with beat_lock("job") as inner:
            assert inner is False  # already held
    # Released on exit → can acquire again.
    with beat_lock("job") as again:
        assert again is True


def test_single_run_skips_when_lock_held(fake_redis: _FakeRedis) -> None:
    calls = {"n": 0}

    @single_run("job")
    def task() -> int:
        calls["n"] += 1
        return 42

    # Hold the lock, then invoke the wrapped task: it must be skipped (returns None, no body run).
    fake_redis.set("vg:beatlock:job", "someoneelse", nx=True)
    assert task() is None
    assert calls["n"] == 0


def test_single_run_executes_when_free(fake_redis: _FakeRedis) -> None:
    @single_run("job")
    def task() -> int:
        return 42

    assert task() == 42


def test_fails_open_when_redis_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> object:
        raise ConnectionError("no redis")

    monkeypatch.setattr(locks, "_redis", _boom)

    @single_run("job")
    def task() -> int:
        return 7

    assert task() == 7  # runs despite Redis being down
