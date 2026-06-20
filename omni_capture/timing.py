"""
timing.py
---------
Lightweight, dependency-free per-stage timing for the capture pipeline.

One StageTimer is created per pipeline run (CLI or HTTP). Each pipeline stage
is wrapped in `with timer.stage("name"): ...`. At the end of the run,
`timer.log_summary()` emits ONE machine-parseable line:

    [timing] {"run_id":"abc","stages":{"enrich":47712.3,"llm":812.0},"total_ms":48530.1}

co-located with the run id so log lines can be correlated. The same design is
used identically by main.py (CLI) and server.py (HTTP/SSE) -- no duplicated
timing logic.
"""
from __future__ import annotations

import json
import sys
import time
from contextlib import contextmanager
from typing import Dict, Iterator, Optional, TextIO


class StageTimer:
    def __init__(self, run_id: Optional[str] = None) -> None:
        self.run_id = run_id
        self._stages: Dict[str, float] = {}
        self._t0 = time.perf_counter()

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self._stages[name] = round(self._stages.get(name, 0.0) + elapsed_ms, 1)

    def add(self, name: str, elapsed_ms: float) -> None:
        """Manually record a stage measured outside a `with` block."""
        self._stages[name] = round(self._stages.get(name, 0.0) + elapsed_ms, 1)

    def total_ms(self) -> float:
        return round((time.perf_counter() - self._t0) * 1000.0, 1)

    def summary(self) -> dict:
        return {"run_id": self.run_id, "stages": dict(self._stages), "total_ms": self.total_ms()}

    def summary_json(self) -> str:
        return json.dumps(self.summary(), separators=(",", ":"))

    def log_summary(self, stream: Optional[TextIO] = None) -> None:
        out = stream or sys.stderr
        out.write("[timing] " + self.summary_json() + "\n")
        out.flush()
