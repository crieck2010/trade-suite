"""Append-only decay event log (JSONL).

Every state transition the engine makes -- and every explicit operator
``promote`` -- lands here as one JSON object per line, mirroring the
trade-agents dissent tracker's storage discipline: human-readable,
git-diffable, never rewritten.  The log is also the state store:
``current_state(strategy)`` is the ``to_state`` of the strategy's most
recent event, defaulting to ``healthy`` when the strategy has no events
yet.

Event schema::

    {"at": "2026-10-07",            # YYYY-MM-DD (UTC)
     "strategy": "regcond1",
     "from_state": "healthy",
     "to_state": "watchlist",
     "reason": "sharpe<warn(0.5)",
     "metrics": {"trailing_sharpe": 0.42, "expected_sharpe": 1.2, ...},
     "actor": "engine" | "operator"}

``record_decay_event`` never raises: a logging failure returns
``{"ok": False, "note": ...}`` instead, because monitoring must not
crash the pipeline it watches.  (The evaluation itself is pure and
lives in :mod:`trade_decay.state_machine`.)

Default path ``~/.trade-decay/decay-events.jsonl``, override with
``$TRADE_DECAY_EVENTS``.

Stdlib only.
"""

from __future__ import annotations

import json
import os
from datetime import date

from . import state_machine

DEFAULT_EVENTS_PATH = os.path.expanduser("~/.trade-decay/decay-events.jsonl")

ACTOR_ENGINE = "engine"
ACTOR_OPERATOR = "operator"


def _default_path() -> str:
    return os.environ.get("TRADE_DECAY_EVENTS", DEFAULT_EVENTS_PATH)


def _iso_today() -> str:
    return date.today().isoformat()


def record_decay_event(strategy: str, from_state: str, to_state: str,
                       reason: str, metrics: dict | None = None,
                       actor: str = ACTOR_ENGINE,
                       path: str | None = None,
                       at: str | None = None) -> dict:
    """Append one decay event.  Never raises.

    On invalid input returns ``{"ok": False, "note": ...}`` and writes
    nothing.  On success returns ``{"ok": True, "event": ...}``.
    """
    try:
        return _record(strategy, from_state, to_state, reason,
                       metrics=metrics, actor=actor, path=path, at=at)
    except Exception as exc:  # monitoring must not crash the pipeline
        return {"ok": False,
                "note": f"decay event not recorded ({exc}); "
                        f"monitoring unaffected",
                "error": str(exc)}


def _record(strategy, from_state, to_state, reason, metrics, actor,
            path, at) -> dict:
    problems: list[str] = []
    if not strategy or not str(strategy).strip():
        problems.append("strategy is required")
    if from_state not in state_machine.STATES:
        problems.append(
            f"from_state must be one of {state_machine.STATES}, "
            f"got {from_state!r}")
    if to_state not in state_machine.STATES:
        problems.append(
            f"to_state must be one of {state_machine.STATES}, "
            f"got {to_state!r}")
    if not reason or not str(reason).strip():
        problems.append("reason is required (one short sentence)")
    if actor not in (ACTOR_ENGINE, ACTOR_OPERATOR):
        problems.append(f"actor must be engine|operator, got {actor!r}")
    if at is not None:
        try:
            date.fromisoformat(at)
        except (TypeError, ValueError):
            problems.append(f"at must be YYYY-MM-DD, got {at!r}")
    if problems:
        return {"ok": False,
                "note": "decay event NOT recorded: " + "; ".join(problems),
                "problems": problems}

    event = {
        "at": at or _iso_today(),
        "strategy": str(strategy).strip(),
        "from_state": from_state,
        "to_state": to_state,
        "reason": str(reason).strip()[:500],
        "metrics": dict(metrics or {}),
        "actor": actor,
    }
    resolved = os.path.expanduser(path or _default_path())
    os.makedirs(os.path.dirname(resolved), exist_ok=True)
    with open(resolved, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")
    return {"ok": True, "event": event}


def read_events(path: str | None = None,
                strategy: str | None = None) -> list[dict]:
    """Read the event log (oldest first).  Corrupt lines are skipped --
    one bad line must not hide the history around it."""
    resolved = os.path.expanduser(path or _default_path())
    if not os.path.isfile(resolved):
        return []
    events = []
    with open(resolved, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if strategy is not None and event.get("strategy") != strategy:
                continue
            events.append(event)
    return events


def current_state(strategy: str, path: str | None = None) -> str:
    """The strategy's current health state: ``to_state`` of its latest
    event, or ``healthy`` when it has no events yet."""
    events = read_events(path=path, strategy=strategy)
    if not events:
        return state_machine.HEALTHY
    last = events[-1].get("to_state")
    return last if last in state_machine.STATES else state_machine.HEALTHY
