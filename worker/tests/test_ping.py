from worker.tasks import ping


def test_ping_runs_eagerly() -> None:
    # task_always_eager is on when APP_ENV=test, so this executes inline.
    assert ping.delay().get(timeout=5) == "pong"
