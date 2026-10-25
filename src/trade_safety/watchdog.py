"""Heartbeat watchdog (live-roadmap Phase 1, item 3).

The watchdog owns no thread and no clock loop: the host process (the
adapter's session loop, a scheduler, a drill) calls :meth:`tick`
periodically. If any required heartbeat source is stale — or never
beat at all — the watchdog engages the kernel E-Stop, fires the alert,
and invokes ``on_trip`` (the adapter wires this to cancel-all-open-
orders). Each source trips at most once until it beats again.
"""

from __future__ import annotations

import logging
from typing import Callable

from .kernel import SafetyKernel

logger = logging.getLogger(__name__)


class Watchdog:
    def __init__(
        self,
        kernel: SafetyKernel,
        timeouts_s: dict[str, float] | None = None,
        on_trip: Callable[[str], None] | None = None,
    ) -> None:
        self.kernel = kernel
        self.timeouts = timeouts_s if timeouts_s is not None else dict(kernel.config.heartbeat_timeout_s)
        self.on_trip = on_trip
        self._tripped: set[str] = set()

    def tick(self) -> list[str]:
        """Check all sources once. Returns the sources that tripped now."""
        tripped_now: list[str] = []
        for source, timeout in self.timeouts.items():
            age = self.kernel.heartbeat_age_s(source)
            fresh = age is not None and age <= timeout
            if fresh:
                self._tripped.discard(source)
                continue
            if source in self._tripped:
                continue
            self._tripped.add(source)
            reason = (
                f"watchdog: heartbeat '{source}' never received"
                if age is None
                else f"watchdog: heartbeat '{source}' stale ({age:.0f}s > {timeout:.0f}s)"
            )
            logger.error("Watchdog trip: %s", reason)
            self.kernel.engage_estop(actor="watchdog", reason=reason)
            if self.on_trip is not None:
                try:
                    self.on_trip(source)
                except Exception as exc:  # cancel-all failing must not mask the trip
                    logger.error("Watchdog on_trip callback failed for %s: %s", source, exc)
            tripped_now.append(source)
        return tripped_now
