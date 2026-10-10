"""Reconnect policy: exponential backoff with jitter + staleness detection.

The delay formula::

    delay = min(cap, base * 2**attempt) + uniform(0, jitter)

Why this shape (see ``docs/METHODOLOGY.md`` for the derivation):

- *Exponential* growth keeps a flapping connection from hammering the
  server (or burning API quota) while still retrying quickly at first,
  when most blips resolve.
- *Jitter* decorrelates retries. Without it, every client that drops at
  the same moment (exchange restart, network flap) retries in lockstep —
  the "thundering herd" — and the retry storm becomes a second outage.
  Adding ``uniform(0, jitter)`` spreads the herd over the jitter window.
- *Cap* bounds the worst case so a long outage doesn't schedule a retry
  hours out.

Deterministic under a seed (``random.Random`` instance), so tests can
assert exact sequences.

Staleness is detected by the runner: "no frame AND no pong within
``stale_after`` seconds" means the socket is dead even though it looks
open (half-open TCP connections are the classic case). See
:meth:`ReconnectPolicy.is_stale`.
"""

from __future__ import annotations

import random


class ReconnectPolicy:
    """Backoff + staleness policy for stream sessions."""

    def __init__(
        self,
        base: float = 1.0,
        cap: float = 60.0,
        jitter: float = 1.0,
        max_attempts: int | None = None,
        stale_after: float = 30.0,
        seed: int | None = None,
    ) -> None:
        if base <= 0 or cap <= 0 or jitter < 0:
            raise ValueError("base/cap must be positive, jitter non-negative")
        if stale_after <= 0:
            raise ValueError("stale_after must be positive")
        self.base = base
        self.cap = cap
        self.jitter = jitter
        self.max_attempts = max_attempts
        self.stale_after = stale_after
        self._rng = random.Random(seed)

    def delay_for(self, attempt: int) -> float:
        """Seconds to wait before retry number ``attempt`` (0-based)."""
        if attempt < 0:
            raise ValueError("attempt must be >= 0")
        grown = min(self.cap, self.base * (2.0**attempt))
        return grown + self._rng.uniform(0.0, self.jitter)

    def should_retry(self, attempt: int) -> bool:
        """Whether another retry is allowed after ``attempt`` failures."""
        if self.max_attempts is None:
            return True
        return attempt < self.max_attempts

    def is_stale(self, now: float, last_activity_ts: float) -> bool:
        """True when nothing (frame or pong) arrived within ``stale_after``."""
        return (now - last_activity_ts) > self.stale_after


# Suite-wide presets: name -> constructor kwargs (documented in CLI `presets`).
PRESETS: dict[str, dict] = {
    "conservative": {
        "base": 2.0,
        "cap": 120.0,
        "jitter": 2.0,
        "max_attempts": None,
        "stale_after": 60.0,
        "note": "patient: slow exchanges, avoids hammering, tolerates gaps",
    },
    "balanced": {
        "base": 1.0,
        "cap": 60.0,
        "jitter": 1.0,
        "max_attempts": None,
        "stale_after": 30.0,
        "note": "default: quick recovery, jittered herd protection",
    },
    "aggressive": {
        "base": 0.25,
        "cap": 10.0,
        "jitter": 0.5,
        "max_attempts": None,
        "stale_after": 10.0,
        "note": "low-latency LAN / colocated: reconnect fast, detect staleness fast",
    },
}


def preset(name: str, **overrides) -> ReconnectPolicy:
    """Build a :class:`ReconnectPolicy` from a named preset."""
    if name not in PRESETS:
        raise KeyError(f"unknown preset {name!r}; choose from {sorted(PRESETS)}")
    kw = {k: v for k, v in PRESETS[name].items() if k != "note"}
    kw.update(overrides)
    return ReconnectPolicy(**kw)
