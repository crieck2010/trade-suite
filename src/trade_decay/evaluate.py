"""Evaluation loop: compute health, move the state machine, log events.

:func:`evaluate_all` is what the ``trade-decay evaluate`` cron/CLI
calls.  For each registered strategy it:

1. reads the ledger and computes decay metrics (via
   :mod:`trade_decay.report`),
2. loads the current state from the event log,
3. runs one :mod:`trade_decay.state_machine` step,
4. appends a JSONL event **only when the state changes**
   (plus an operator ``promote`` moves demoted -> watchlist).

The engine is recommendations-only: it never touches a broker,
never edits an allocator, never closes a position.  Demotion means
"the data says retire this"; a human or a consuming system decides.

Stdlib + numpy (via metrics).  No network, no credentials.
"""

from __future__ import annotations

import math

from . import events as decay_events
from . import ledger as ledger_mod
from . import metrics
from . import state_machine
from .config import load_config
from .registry import StrategySpec, load_registry
from .report import strategy_health


def evaluate_strategy(spec: StrategySpec,
                      thresholds: state_machine.Thresholds,
                      events_path: str | None = None) -> dict:
    """Evaluate one strategy; append an event iff the state changed."""
    health = strategy_health(spec, thresholds)
    if health.get("state") == "unknown":
        return {"strategy": spec.strategy_id, "evaluated": False,
                "reason": health.get("error", "ledger unreadable"),
                "event": None}

    current = decay_events.current_state(spec.strategy_id,
                                         path=events_path)
    ratio = health.get("sharpe_ratio")
    outcome = state_machine.evaluate(
        current_state=current,
        n_daily_points=health.get("n_daily_points", 0),
        sharpe_ratio=ratio,
        z_score=health.get("z_score"),
        dd_ratio=health.get("dd_ratio"),
        thresholds=thresholds)

    new_state = outcome["state"]
    if new_state == state_machine.INSUFFICIENT_DATA:
        return {"strategy": spec.strategy_id, "evaluated": True,
                "state": current, "changed": False,
                "reason": outcome["recommendation"], "event": None}

    changed = new_state != current
    event = None
    if changed:
        metrics_snapshot = {
            k: health.get(k) for k in (
                "trailing_sharpe", "expected_sharpe", "sharpe_ratio",
                "z_score", "half_life_days", "max_drawdown", "dd_ratio",
                "n_daily_points", "last_snapshot") if health.get(k) is not None
        }
        res = decay_events.record_decay_event(
            spec.strategy_id, current, new_state,
            reason="; ".join(outcome["fired"]) or outcome["recommendation"],
            metrics=metrics_snapshot,
            actor=decay_events.ACTOR_ENGINE,
            path=events_path)
        event = res.get("event")

    return {"strategy": spec.strategy_id, "evaluated": True,
            "state": new_state, "previous_state": current,
            "changed": changed, "level": outcome["level"],
            "fired": outcome["fired"],
            "recommendation": outcome["recommendation"], "event": event}


def evaluate_all(specs: list[StrategySpec] | None = None,
                 thresholds: state_machine.Thresholds | None = None,
                 events_path: str | None = None,
                 config_path: str | None = None) -> dict:
    """Evaluate every registered strategy.  Returns a summary dict."""
    t = thresholds or load_config(config_path)
    watched = specs if specs is not None else load_registry()
    results = [evaluate_strategy(spec, t, events_path=events_path)
               for spec in watched]
    changed = [r for r in results if r.get("changed")]
    return {"n_strategies": len(results),
            "n_changed": len(changed),
            "changed": [r["strategy"] for r in changed],
            "results": results}


def promote(strategy_id: str, reason: str,
            events_path: str | None = None) -> dict:
    """Operator move: demoted -> watchlist (one step; recorded).

    Demotion is sticky by design -- only an explicit, reasoned operator
    action revisits it, and the action itself is an event so the
    revisit is auditable.  Promoting a non-demoted strategy is a
    no-op reported as such.
    """
    current = decay_events.current_state(strategy_id, path=events_path)
    if current != state_machine.DEMOTED:
        return {"ok": False,
                "note": f"{strategy_id} is {current}, not demoted; "
                        f"nothing to promote"}
    return decay_events.record_decay_event(
        strategy_id, state_machine.DEMOTED, state_machine.WATCHLIST,
        reason=reason, actor=decay_events.ACTOR_OPERATOR,
        path=events_path)
