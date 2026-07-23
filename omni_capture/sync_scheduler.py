"""In-process Drive batched-sync scheduler (phase-5 §1.1).

A single daemon thread runs a full `mobile_sync_agent.run_pass()` on a fixed interval. It is a
SCHEDULER only — Drive stays the sole canonical/version authority; this adds no second writer and
changes no reconcile semantics. Design points:

- **Single-flight:** a pass never overlaps itself (a slow pass spanning a tick just skips the tick).
- **Backoff:** a failing pass (quota/429/auth) widens the wait exponentially until one succeeds;
  the pass's OWN Drive-call backoff still applies inside run_pass.
- **Ring buffer:** the last 20 pass summaries are kept and exposed via `status()` for the GUI Sync
  tab; a pass that raises is recorded as an `ok:false` row (auth-missing → "Paused — sign in"), it
  never crashes the loop or the server.

The seams (`pass_fn`, `cfg_fn`, `now_fn`, `sleep`/`monotonic`, and the `stop` Event) keep it fully
unit-testable without real Drive or real time — see test_sync_scheduler.py.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime
from typing import Callable, Optional


class SyncBusy(Exception):
    """A sync pass is already in flight (single-flight). Server maps this to HTTP 409."""


# [sync] interval_minutes sentinel: "never auto-sync". Every real interval is clamped to >= 5 min
# (config.py + POST /config), so 0 is unambiguous and free to carry this meaning.
AUTO_SYNC_NEVER = 0

# How long the loop sleeps between wakes while the sentinel is set. It must still wake periodically
# and re-read cfg so that flipping [sync] back to a real interval takes effect WITHOUT restarting
# the server -- that no-restart property is real and documented at server.py:287.
_IDLE_POLL_S = 60


def auto_sync_disabled(cfg: object) -> bool:
    """True when [sync] interval_minutes = 0 -- the user hasn't chosen a real interval yet
    (or explicitly picked "never").

    Gates the two INTERVAL-driven automatic triggers: the timed loop here, and server.py's
    sync_after_capture. It deliberately does NOT gate sync_on_launch (ISS-003, 2026-07-22):
    a startup pass is a distinct trigger from "run on a timer", and the product default is
    interval-auto OFF until the user picks an interval, but on-launch ON regardless -- see
    `_loop()` below, which checks `sync_on_launch` on its own, unconditioned by this sentinel.
    Manual POST /sync/run is also NOT gated by this -- "never auto-sync" still allows an
    explicit Sync now.
    """
    return int(getattr(cfg, "interval_minutes", 60)) <= AUTO_SYNC_NEVER


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class SyncScheduler:
    def __init__(
        self,
        pass_fn: Callable[[], dict],
        cfg_fn: Callable[[], object],  # returns an object with .enabled/.interval_minutes/.sync_on_launch
        now_fn: Callable[[], str] = _now_iso,
        sleep_fn: Optional[Callable[[float], None]] = None,  # unused when stop.wait is available
        monotonic_fn: Callable[[], float] = time.monotonic,
        max_backoff: int = 8,
    ) -> None:
        self._pass_fn = pass_fn
        self._cfg_fn = cfg_fn
        self._now = now_fn
        self._monotonic = monotonic_fn
        self._max_backoff = max_backoff
        self._history: deque = deque(maxlen=20)
        self._flight = threading.Lock()      # held ONLY while a pass runs → single-flight
        self._running = False
        self._last_error: Optional[str] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ---- one guarded pass ----
    def run_now(self) -> dict:
        """Run one pass immediately. Raises SyncBusy if a pass is already running (→ 409).
        A pass that itself fails does NOT raise here — it returns an `ok:false` summary row so
        the caller (loop or POST /sync/run) can surface the error without a crash."""
        if not self._flight.acquire(blocking=False):
            raise SyncBusy("a sync pass is already running")
        self._running = True
        started = self._now()
        t0 = self._monotonic()
        try:
            summary = self._pass_fn()
            row = {"started": started, "finished": self._now(),
                   "duration_s": round(self._monotonic() - t0, 2), "ok": True}
            row.update(summary or {})
            self._last_error = None
        except Exception as exc:  # auth missing, quota, network — record, never crash the loop
            row = {"started": started, "finished": self._now(),
                   "duration_s": round(self._monotonic() - t0, 2), "ok": False, "error": str(exc)}
            self._last_error = str(exc)
        finally:
            self._running = False
            self._flight.release()
        self._history.append(row)
        return row

    def _safe_pass(self) -> Optional[dict]:
        try:
            return self.run_now()
        except SyncBusy:
            return None  # already running (shouldn't happen from the single loop, but harmless)

    def status(self) -> dict:
        cfg = self._cfg_fn()
        return {
            "enabled": bool(getattr(cfg, "enabled", False)),
            "interval_minutes": int(getattr(cfg, "interval_minutes", 60)),
            "running": self._running,
            "last_pass": self._history[-1] if self._history else None,
            "last_error": self._last_error,
            "history": list(self._history),
        }

    # ---- the loop ----
    def _loop(self) -> None:
        cfg = self._cfg_fn()
        # ISS-003: on-launch is independent of the interval sentinel -- it must fire on the
        # product default (interval_minutes=0 / no interval chosen yet, sync_on_launch=True)
        # as long as the system-wide master switch (`enabled`) is on.
        if getattr(cfg, "enabled", False) and getattr(cfg, "sync_on_launch", True):
            self._safe_pass()
        backoff = 1
        while not self._stop.is_set():
            cfg = self._cfg_fn()
            if auto_sync_disabled(cfg):
                # Sentinel: run no pass, but keep waking on a fixed poll so a config flip back to
                # a real interval needs no restart. Backoff is meaningless with no passes running.
                if self._stop.wait(_IDLE_POLL_S):
                    break  # stop() signalled
                backoff = 1
                continue
            interval_s = max(5, int(getattr(cfg, "interval_minutes", 60))) * 60
            if self._stop.wait(interval_s * backoff):
                break  # stop() signalled
            # Re-read: the wait above can span hours, and the config may have changed inside it.
            # A pass fired against the pre-wait cfg would ignore a "never"/off set during the wait.
            cfg = self._cfg_fn()
            if not getattr(cfg, "enabled", False) or auto_sync_disabled(cfg):
                backoff = 1
                continue
            row = self._safe_pass()
            if row is None:
                continue
            backoff = 1 if row.get("ok") else min(backoff * 2, self._max_backoff)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="sync-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


# Module-level singleton the server wires at startup and the endpoints read. None until started.
_scheduler: Optional[SyncScheduler] = None

# SYNC-28: the check-then-set below was unguarded, so two concurrent callers could each construct
# a SyncScheduler and start() a thread — two loops, two passes, single-flight defeated.
_scheduler_lock = threading.Lock()


def get_scheduler() -> Optional[SyncScheduler]:
    return _scheduler


def start_scheduler(pass_fn: Callable[[], dict], cfg_fn: Callable[[], object]) -> SyncScheduler:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = SyncScheduler(pass_fn, cfg_fn)
        # SYNC-28: always start(). After stop() the singleton is non-None but its _loop has
        # exited, so the old early return handed back a DEAD scheduler that never ran another
        # pass — sync silently stopped until a server restart. start() is already idempotent
        # (it returns immediately while the thread is_alive), so calling it unconditionally is
        # safe and is what makes a stop()/start() cycle actually restart the loop.
        _scheduler.start()
        return _scheduler
