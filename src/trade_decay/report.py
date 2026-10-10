"""Decay reporting: per-strategy health as plain data.

``decay_report()`` is the JSON interchange surface other engines
consume (trade-allocate, trade-agents): one dict per strategy with its
state, metrics, and recommendation.  Schema is frozen in
docs/INTEROP.md -- add fields, never rename or remove.

This module only *computes*.  State transitions and their events are
written by :func:`trade_decay.evaluate.evaluate_all` (used by the
``trade-decay evaluate`` CLI); ``decay_report`` itself is read-only so
dashboards can call it freely.
"""

from __future__ import annotations

import math
from datetime import date

from . import events as decay_events
from . import ledger as ledger_mod
from . import metrics
from . import state_machine
from .registry import StrategySpec


def _round(value, ndigits: int = 4):
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return round(v, ndigits)


def strategy_health(spec: StrategySpec,
                    thresholds: state_machine.Thresholds) -> dict:
    """Compute decay metrics + current state for one strategy.

    Never raises for ledger problems: the result carries
    ``"error"`` and state ``"unknown"`` so one broken ledger cannot
    take down a multi-strategy report.
    """
    try:
        reader = ledger_mod.LedgerReader(spec.ledger_path)
        series = reader.equity_series()
    except ledger_mod.LedgerError as exc:
        return {"strategy": spec.strategy_id, "state": "unknown",
                "error": str(exc), "recommendation": "ledger unreadable"}

    daily = metrics.resample_daily(series)
    n_points = len(daily)
    trailing = metrics.trailing_sharpe(
        daily, window_days=thresholds.trailing_window_days)
    ratio = (trailing / spec.expected_sharpe
             if math.isfinite(trailing) and spec.expected_sharpe else None)
    z = metrics.divergence_zscore(trailing, spec.expected_sharpe,
                                  spec.expected_sharpe_std)
    dd = metrics.max_drawdown(daily)
    dd_ratio = (dd["max_dd"] / spec.validation_maxdd
                if spec.validation_maxdd and math.isfinite(dd["max_dd"])
                else None)
    rolling = metrics.rolling_sharpe(daily, window_days=30)
    half_life = metrics.fit_half_life(rolling)

    state = decay_events.current_state(spec.strategy_id)

    last_snapshot = daily[-1][0].date().isoformat() if daily else None
    return {
        "strategy": spec.strategy_id,
        "state": state,
        "n_daily_points": n_points,
        "last_snapshot": last_snapshot,
        "trailing_sharpe": _round(trailing),
        "expected_sharpe": _round(spec.expected_sharpe),
        "sharpe_ratio": _round(ratio),
        "z_score": _round(z),
        "half_life_days": _round(half_life["half_life_days"]),
        "half_life_r2": _round(half_life["r_squared"]),
        "half_life_decaying": half_life["decaying"],
        "max_drawdown": _round(dd["max_dd"]),
        "validation_maxdd": _round(spec.validation_maxdd),
        "dd_ratio": _round(dd_ratio),
        "half_life_class": spec.half_life_class,
        "recommendation": _recommendation_for(state),
    }


def _recommendation_for(state: str) -> str:
    return {
        state_machine.HEALTHY: "no action",
        state_machine.WATCHLIST: "review at next desk session",
        state_machine.DEMOTED: "retirement recommended; operator promote "
                               "to revisit",
    }.get(state, "no action")


def decay_report(specs: list[StrategySpec],
                 thresholds: state_machine.Thresholds) -> dict:
    """Full health report across strategies (plain data, JSON-ready)."""
    rows = [strategy_health(spec, thresholds) for spec in specs]
    by_state: dict[str, list[str]] = {s: [] for s in state_machine.STATES}
    by_state["unknown"] = []
    for row in rows:
        by_state.setdefault(row["state"], []).append(row["strategy"])
    return {
        "as_of": date.today().isoformat(),
        "n_strategies": len(rows),
        "states": {k: sorted(v) for k, v in by_state.items() if v},
        "strategies": rows,
    }
