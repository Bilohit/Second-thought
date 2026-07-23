"""Unit tests for the Drive batched-sync scheduler (phase-5 §1.1). No real Drive, no real time —
the pass_fn and clock are injected. Covers single-flight, error capture, and the ring buffer; the
daemon loop is thin orchestration over these primitives and is not thread-tested (would be flaky).

E6 addendum: the loop IS now covered, but still without a thread — `_FakeStop` stands in for the
`stop` Event so `_loop()` runs on the main thread and every sleep becomes an assertable number."""
from dataclasses import dataclass

import pytest

import sync_scheduler
from sync_scheduler import SyncScheduler, SyncBusy, auto_sync_disabled


@dataclass
class FakeCfg:
    enabled: bool = True
    interval_minutes: int = 60
    sync_on_launch: bool = True


def _mk(pass_fn, cfg=None):
    ticks = iter(range(10_000))
    return SyncScheduler(
        pass_fn=pass_fn,
        cfg_fn=lambda: cfg or FakeCfg(),
        now_fn=lambda: "T",
        monotonic_fn=lambda: next(ticks),
    )


def test_run_now_returns_summary_and_records_history():
    s = _mk(lambda: {"uploaded": 3, "pulled": 1, "errors": 0})
    row = s.run_now()
    assert row["ok"] is True
    assert row["uploaded"] == 3 and row["pulled"] == 1
    assert s.status()["last_pass"]["uploaded"] == 3
    assert len(s.status()["history"]) == 1


def test_single_flight_raises_busy_when_locked():
    s = _mk(lambda: {})
    assert s._flight.acquire(blocking=False)  # simulate a pass already running
    try:
        import pytest
        with pytest.raises(SyncBusy):
            s.run_now()
    finally:
        s._flight.release()


def test_failing_pass_records_ok_false_never_raises():
    def boom():
        raise RuntimeError("no auth")
    s = _mk(boom)
    row = s.run_now()  # must NOT raise
    assert row["ok"] is False
    assert "no auth" in row["error"]
    assert s.status()["last_error"] == "no auth"


def test_ring_buffer_caps_at_20():
    s = _mk(lambda: {"n": 1})
    for _ in range(25):
        s.run_now()
    assert len(s.status()["history"]) == 20


def test_status_reflects_config():
    s = _mk(lambda: {}, cfg=FakeCfg(enabled=False, interval_minutes=15))
    st = s.status()
    assert st["enabled"] is False and st["interval_minutes"] == 15
    assert st["running"] is False


# ---------------------------------------------------------------------------
# E6: interval_minutes = 0 -> "never auto-sync"
#
# The sentinel gates the ONE interval-driven automatic trigger that lives here (the timed
# loop); server.py's sync_after_capture is covered in test_server.py. Manual run_now() is
# deliberately NOT gated -- that is the whole difference between "Never" and master-off.
#
# ISS-003 (2026-07-22): sync_on_launch is a DIFFERENT trigger and is deliberately NOT gated
# by this sentinel -- the product default is interval-auto OFF until the user picks an
# interval, but on-launch ON regardless of that choice. See test_sync_on_launch_fires_*
# below (replaces the old test_sentinel_blocks_sync_on_launch, which asserted the opposite).
# ---------------------------------------------------------------------------


class _FakeStop:
    """Stands in for the scheduler's threading.Event so `_loop()` can be driven on the main thread:
    every wait() records its timeout and the Nth wait returns True (= stop() signalled) to end the
    loop. Turns "how long does it sleep, and does it pass?" into plain assertions, no real time."""

    def __init__(self, stop_after: int = 1):
        self.waits: list[float] = []
        self._stop_after = stop_after

    def is_set(self) -> bool:
        return False

    def wait(self, timeout=None) -> bool:
        self.waits.append(timeout)
        return len(self.waits) >= self._stop_after


def _counting_pass(passes: list):
    return lambda: passes.append(1) or {"uploaded": 0}


def _run_loop(s: SyncScheduler, stop_after: int = 1) -> list:
    stop = _FakeStop(stop_after)
    s._stop = stop
    s._loop()
    return stop.waits


def test_auto_sync_disabled_only_for_the_zero_sentinel():
    assert auto_sync_disabled(FakeCfg(interval_minutes=0)) is True
    assert auto_sync_disabled(FakeCfg(interval_minutes=5)) is False
    assert auto_sync_disabled(FakeCfg(interval_minutes=60)) is False


def test_sentinel_blocks_the_timed_loop():
    """Trigger 1. Before the sentinel, `max(5, 0) * 60` turned "never" into a pass every 5 MINUTES
    — the exact opposite of what the user asked for."""
    passes: list = []
    s = _mk(_counting_pass(passes), cfg=FakeCfg(interval_minutes=0, sync_on_launch=False))
    waits = _run_loop(s, stop_after=3)
    assert passes == [], "the never-auto-sync sentinel still ran an automatic pass"
    assert waits == [sync_scheduler._IDLE_POLL_S] * 3, "sentinel must idle-poll, not sleep an interval"


def test_sync_on_launch_fires_on_the_product_default_even_with_no_interval_chosen():
    """ISS-003: the shipping default is interval_minutes=0 (no interval chosen yet) with
    sync_on_launch=True and enabled=True. On-launch must still fire -- it is not gated by
    the interval sentinel. (This replaces the old test_sentinel_blocks_sync_on_launch,
    which asserted the pre-ISS-003 behavior this change deliberately reverses.)"""
    passes: list = []
    s = _mk(_counting_pass(passes), cfg=FakeCfg(interval_minutes=0, sync_on_launch=True))
    _run_loop(s, stop_after=1)
    assert passes == [1], "sync_on_launch did not fire on the interval-unset default"


def test_sync_on_launch_still_fires_for_a_real_interval():
    """The positive control — on-launch fires whether or not a real interval is chosen."""
    passes: list = []
    s = _mk(_counting_pass(passes), cfg=FakeCfg(interval_minutes=60, sync_on_launch=True))
    _run_loop(s, stop_after=1)
    assert passes == [1]


def test_sync_on_launch_still_gated_by_the_master_switch():
    """`enabled=False` (the system-wide master) must still block on-launch even though the
    interval sentinel no longer does."""
    passes: list = []
    s = _mk(_counting_pass(passes), cfg=FakeCfg(enabled=False, interval_minutes=0, sync_on_launch=True))
    _run_loop(s, stop_after=1)
    assert passes == [], "on-launch fired despite the master switch being off"


def test_sync_on_launch_off_still_skips_the_launch_pass():
    """`sync_on_launch=False` must still suppress the launch pass regardless of interval."""
    passes: list = []
    s = _mk(_counting_pass(passes), cfg=FakeCfg(interval_minutes=60, sync_on_launch=False))
    _run_loop(s, stop_after=1)
    assert passes == [], "on-launch fired despite sync_on_launch=False"


@pytest.mark.parametrize("mins,expected_s", [(1, 300), (4, 300), (5, 300), (15, 900), (60, 3600)])
def test_interval_above_zero_still_clamps_to_5_minutes(mins, expected_s):
    """The pre-existing min-5-minute rule survives the sentinel: only 0 means never; 1-4 clamp."""
    s = _mk(lambda: {}, cfg=FakeCfg(interval_minutes=mins, sync_on_launch=False))
    assert _run_loop(s, stop_after=1) == [expected_s]


def test_flipping_the_sentinel_at_runtime_needs_no_restart():
    """The load-bearing property (server.py:287): the loop re-reads cfg on every wake, so choosing
    a real interval in Settings starts passes again with no server restart. This is why the sentinel
    idle-polls instead of parking forever — a `wait()` with no timeout would strand the loop."""
    cfg = FakeCfg(interval_minutes=0, sync_on_launch=False)
    passes: list = []
    s = SyncScheduler(
        pass_fn=_counting_pass(passes),
        cfg_fn=lambda: cfg,          # a live object, exactly like reload_config().sync
        now_fn=lambda: "T",
        monotonic_fn=lambda: 0,
    )
    stop = _FakeStop(stop_after=3)
    real_wait = stop.wait

    def _wait_and_flip(timeout=None):
        stopped = real_wait(timeout)
        if len(stop.waits) == 1:     # user picks "every 15 min" while the loop idles on its poll
            cfg.interval_minutes = 15
        return stopped

    stop.wait = _wait_and_flip
    s._stop = stop
    s._loop()

    assert passes == [1], "loop did not pick up the interval change without a restart"
    assert stop.waits == [sync_scheduler._IDLE_POLL_S, 900, 900]


def test_flipping_to_the_sentinel_mid_wait_cancels_the_due_pass():
    """The reverse flip. The wait can span hours, so cfg is re-read after it: a pass fired against
    the pre-wait config would sync minutes after the user asked for "never"."""
    cfg = FakeCfg(interval_minutes=60, sync_on_launch=False)
    passes: list = []
    s = SyncScheduler(
        pass_fn=_counting_pass(passes),
        cfg_fn=lambda: cfg,
        now_fn=lambda: "T",
        monotonic_fn=lambda: 0,
    )
    stop = _FakeStop(stop_after=2)
    real_wait = stop.wait

    def _wait_and_flip(timeout=None):
        stopped = real_wait(timeout)
        cfg.interval_minutes = 0     # user picks "Never" during the 60-minute sleep
        return stopped

    stop.wait = _wait_and_flip
    s._stop = stop
    s._loop()

    assert passes == [], "a pass fired against the pre-wait config after the user chose Never"


def test_run_now_ignores_the_sentinel():
    """Manual Sync now must still work under "never" — it gates AUTOMATIC passes only."""
    passes: list = []
    s = _mk(_counting_pass(passes), cfg=FakeCfg(interval_minutes=0))
    assert s.run_now()["ok"] is True
    assert passes == [1]


if __name__ == "__main__":
    test_run_now_returns_summary_and_records_history()
    test_single_flight_raises_busy_when_locked()
    test_failing_pass_records_ok_false_never_raises()
    test_ring_buffer_caps_at_20()
    test_status_reflects_config()
    test_auto_sync_disabled_only_for_the_zero_sentinel()
    test_sentinel_blocks_the_timed_loop()
    test_sync_on_launch_fires_on_the_product_default_even_with_no_interval_chosen()
    test_sync_on_launch_still_fires_for_a_real_interval()
    test_sync_on_launch_still_gated_by_the_master_switch()
    test_sync_on_launch_off_still_skips_the_launch_pass()
    test_interval_above_zero_still_clamps_to_5_minutes(1, 300)
    test_interval_above_zero_still_clamps_to_5_minutes(60, 3600)
    test_flipping_the_sentinel_at_runtime_needs_no_restart()
    test_flipping_to_the_sentinel_mid_wait_cancels_the_due_pass()
    test_run_now_ignores_the_sentinel()
    print("ok")
