"""Pure performance metrics on plain equity curves / trade lists.

Stdlib-only reimplementation of the headline stats (mirrors
``trade-backtest.performance`` semantics: simple returns, 252-day
annualization) so the reference backtest never depends on the sibling
being installed. When trade-backtest IS installed, the adapter still
routes through it — these functions are only the *reporting* layer.
"""

from __future__ import annotations

import math
import statistics


def total_return(equity: list[float]) -> float:
    if len(equity) < 2 or equity[0] <= 0:
        return 0.0
    return equity[-1] / equity[0] - 1.0


def cagr(equity: list[float], periods_per_year: float = 252.0) -> float:
    if len(equity) < 2 or equity[0] <= 0 or equity[-1] <= 0:
        return 0.0
    years = (len(equity) - 1) / periods_per_year
    if years <= 0:
        return 0.0
    return (equity[-1] / equity[0]) ** (1.0 / years) - 1.0


def simple_returns(equity: list[float]) -> list[float]:
    out = []
    for prev, cur in zip(equity, equity[1:]):
        out.append(cur / prev - 1.0 if prev else 0.0)
    return out


def sharpe_ratio(equity: list[float], periods_per_year: float = 252.0,
                 risk_free: float = 0.0) -> float | None:
    rets = simple_returns(equity)
    if len(rets) < 2:
        return None
    vol = statistics.pstdev(rets)
    if vol == 0:
        return None
    rf_per = (1.0 + risk_free) ** (1.0 / periods_per_year) - 1.0
    excess = [r - rf_per for r in rets]
    mean_excess = sum(excess) / len(excess)
    return mean_excess / statistics.pstdev(excess) * math.sqrt(periods_per_year)


def max_drawdown(equity: list[float]) -> dict:
    """Returns {max_drawdown (negative fraction), peak_idx, trough_idx}."""
    peak = equity[0] if equity else 0.0
    worst = 0.0
    peak_idx = trough_idx = 0
    cur_peak_idx = 0
    for i, v in enumerate(equity):
        if v > peak:
            peak, cur_peak_idx = v, i
        dd = (v - peak) / peak if peak else 0.0
        if dd < worst:
            worst, peak_idx, trough_idx = dd, cur_peak_idx, i
    return {"max_drawdown": worst, "peak_idx": peak_idx, "trough_idx": trough_idx}


def win_rate(trades: list[dict], pnl_key: str = "pnl_net") -> float | None:
    if not trades:
        return None
    return sum(1 for t in trades if t[pnl_key] > 0) / len(trades)


def profit_factor(trades: list[dict], pnl_key: str = "pnl_net") -> float | None:
    gross_win = sum(t[pnl_key] for t in trades if t[pnl_key] > 0)
    gross_loss = -sum(t[pnl_key] for t in trades if t[pnl_key] < 0)
    if gross_loss == 0:
        return None if gross_win == 0 else float("inf")
    return gross_win / gross_loss


def expectancy(trades: list[dict], pnl_key: str = "pnl_net") -> float | None:
    if not trades:
        return None
    return sum(t[pnl_key] for t in trades) / len(trades)


def summarize(equity: list[float], trades: list[dict],
              periods_per_year: float = 252.0) -> dict:
    """Headline stats on the (cost-adjusted) equity curve + net trades."""
    dd = max_drawdown(equity)
    return {
        "total_return": total_return(equity),
        "cagr": cagr(equity, periods_per_year),
        "sharpe_ratio": sharpe_ratio(equity, periods_per_year),
        "max_drawdown": dd["max_drawdown"],
        "num_trades": float(len(trades)),
        "win_rate": win_rate(trades),
        "profit_factor": profit_factor(trades),
        "expectancy": expectancy(trades),
    }
