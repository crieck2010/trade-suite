"""Kill-switch logic. Pure functions, plain data.

The loop mirrors trade-paper's paper-only guard philosophy: when anything is
wrong with the inputs, the safe action is NO action. A halted cycle emits
alerts and ZERO proposals — hedging on stale prices or into a drawdown is
how paper portfolios become real losses.

Halt conditions (all configurable):
- portfolio drawdown exceeds config["max_drawdown"] (needs equity + peak_equity)
- any market price older than config["max_stale_minutes"]
- any position missing a price
"""

from __future__ import annotations

import datetime as _dt


def _parse_ts(value) -> _dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return _dt.datetime.fromtimestamp(value, tz=_dt.timezone.utc)
    if isinstance(value, str):
        try:
            s = value.replace("Z", "+00:00")
            ts = _dt.datetime.fromisoformat(s)
            return ts if ts.tzinfo else ts.replace(tzinfo=_dt.timezone.utc)
        except ValueError:
            return None
    return None


def safety_check(
    portfolio_state: dict,
    market_state: dict,
    config: dict | None = None,
    now: _dt.datetime | None = None,
) -> dict:
    """Return {"halted": bool, "alerts": [str], "drawdown": float|None,
    "stale_minutes": float|None}."""
    config = config or {}
    alerts: list[str] = []
    halted = False

    # 1. Drawdown kill-switch.
    equity = portfolio_state.get("equity")
    peak = portfolio_state.get("peak_equity")
    max_dd = float(config.get("max_drawdown", 0.10))
    drawdown = None
    if equity is not None and peak not in (None, 0):
        drawdown = 1.0 - float(equity) / float(peak)
        if drawdown > max_dd:
            halted = True
            alerts.append(
                f"KILL-SWITCH: drawdown {drawdown:.2%} exceeds limit {max_dd:.2%} — halting")

    # 2. Stale market data.
    now = now or _dt.datetime.now(tz=_dt.timezone.utc)
    as_of = _parse_ts(market_state.get("as_of"))
    max_stale = float(config.get("max_stale_minutes", 60))
    stale_minutes = None
    if as_of is None:
        halted = True
        alerts.append("KILL-SWITCH: market data has no usable timestamp — halting")
    else:
        stale_minutes = (now - as_of).total_seconds() / 60.0
        if stale_minutes > max_stale:
            halted = True
            alerts.append(
                f"KILL-SWITCH: market data {stale_minutes:.1f} min old "
                f"(limit {max_stale:.0f}) — halting")

    # 3. Missing prices.
    prices = market_state.get("prices") or {}
    missing = [p["symbol"] for p in portfolio_state.get("positions", [])
               if p.get("symbol") not in prices]
    if missing:
        halted = True
        alerts.append(
            f"KILL-SWITCH: missing prices for {', '.join(sorted(missing))} — halting")

    return {"halted": halted, "alerts": alerts, "drawdown": drawdown,
            "stale_minutes": stale_minutes}
