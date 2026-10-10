"""Background jobs: keep the UI responsive during backtests and desk runs.

Jobs execute in a daemon thread; completion callbacks are marshalled back
onto the tkinter main thread via ``app.after`` polling.  Only the main
thread ever touches widgets.
"""

from __future__ import annotations

import queue
import threading
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class JobResult:
    ok: bool
    value: Any = None
    error: str = ""


@dataclass
class Job:
    """A unit of background work."""

    label: str
    target: Callable[..., Any]
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    on_done: Callable[[Any], None] | None = None
    on_error: Callable[[str], None] | None = None


class JobRunner:
    """Submit :class:`Job` objects; poll results on the tkinter main loop."""

    POLL_MS = 120

    def __init__(self, app) -> None:
        self._app = app
        self._results: "queue.Queue[tuple[Job, JobResult]]" = queue.Queue()
        self._polling = False
        self.running = 0

    def submit(self, job: Job) -> None:
        self.running += 1
        thread = threading.Thread(target=self._execute, args=(job,), daemon=True,
                                  name=f"job-{job.label}")
        thread.start()
        if not self._polling:
            self._polling = True
            self._app.after(self.POLL_MS, self._poll)

    def _execute(self, job: Job) -> None:
        try:
            value = job.target(*job.args, **job.kwargs)
            self._results.put((job, JobResult(True, value=value)))
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            self._results.put(
                (job, JobResult(False, error=f"{type(exc).__name__}: {exc}\n"
                                            f"{traceback.format_exc(limit=3)}"))
            )

    def _poll(self) -> None:
        drained = 0
        while drained < 8:  # bound work per tick so the UI stays fluid
            try:
                job, result = self._results.get_nowait()
            except queue.Empty:
                break
            drained += 1
            self.running = max(0, self.running - 1)
            try:
                if result.ok and job.on_done is not None:
                    job.on_done(result.value)
                elif not result.ok and job.on_error is not None:
                    job.on_error(result.error)
            except Exception:  # noqa: BLE001 - never let a callback kill polling
                pass
        if self.running or not self._results.empty():
            self._app.after(self.POLL_MS, self._poll)
        else:
            self._polling = False
