"""Performance statistics from a return series. Plain lists of floats in/out."""

from __future__ import annotations

import math

from ._stats import excess_kurtosis, mean, sample_stdev, skewness

PERIODS_PER_YEAR = 252


def per_period_rf(rf_annual: float, periods: int = PERIODS_PER_YEAR) -> float:
    """Convert an annualized risk-free rate to a per-period rate."""
    return (1.0 + rf_annual) ** (1.0 / periods) - 1.0


def excess_returns(returns: list[float], rf_annual: float = 0.0,
                   periods: int = PERIODS_PER_YEAR) -> list[float]:
    """Returns minus the per-period risk-free rate."""
    rfp = per_period_rf(rf_annual, periods)
    return [r - rfp for r in returns]


def sharpe_ratio(returns: list[float], rf_annual: float = 0.0,
                 periods: int = PERIODS_PER_YEAR) -> float | None:
    """Annualized Sharpe: mean(excess) / stdev(excess) * sqrt(periods).

    Returns None when the ratio is undefined (fewer than 2 observations or
    zero volatility) — never raises, never invents a number.
    """
    xs = excess_returns(returns, rf_annual, periods)
    if len(xs) < 2:
        return None
    s = sample_stdev(xs)
    if s is None or s == 0.0:
        return None
    return (mean(xs) / s) * math.sqrt(periods)


def sortino_ratio(returns: list[float], rf_annual: float = 0.0,
                  periods: int = PERIODS_PER_YEAR, *,
                  target: float = 0.0) -> float | None:
    """Annualized Sortino: (annualized mean of excess returns − target) /
    annualized downside deviation.

    Downside deviation = sqrt(mean over ALL bars of min(0, x − tp)^2),
    annualized by sqrt(periods), where x is the excess return
    (r − per-period rf) and tp is the per-period target
    ``tp = (1 + target)^(1/periods) − 1``. Upside bars contribute zero, never
    a negative penalty — that is the whole point: Sharpe punishes a strategy
    for its upside jumps; Sortino does not.

    Returns None when the ratio is undefined — fewer than 2 observations,
    or zero downside deviation (no bar below target). None, never raises,
    never invents a number; the gates treat missing evidence as FAIL.

    For symmetric returns with target = 0, Sortino ≈ √2 × Sharpe, because the
    downside deviation uses roughly half the bars: dd ≈ σ/√2.
    """
    xs = excess_returns(returns, rf_annual, periods)
    if len(xs) < 2:
        return None
    tp = (1.0 + target) ** (1.0 / periods) - 1.0 if target != 0.0 else 0.0
    downside = [min(0.0, x - tp) for x in xs]
    dd = math.sqrt(sum(d * d for d in downside) / len(downside))
    if dd == 0.0:
        return None
    return (mean(xs) * periods - target) / (dd * math.sqrt(periods))


def equity_curve(returns: list[float]) -> list[float]:
    """Cumulative wealth index starting at 1.0."""
    curve = [1.0]
    for r in returns:
        curve.append(curve[-1] * (1.0 + r))
    return curve


def max_drawdown(returns: list[float]) -> dict:
    """Worst peak-to-trough loss.

    Returns dict with ``max_drawdown`` (<= 0), ``peak_index``, ``trough_index``
    (indices into the returns list) and ``duration_bars``.
    """
    curve = equity_curve(returns)
    peak = curve[0]
    peak_i = 0
    worst = 0.0
    worst_peak_i = 0
    worst_trough_i = 0
    for i, v in enumerate(curve[1:], start=1):
        if v > peak:
            peak = v
            peak_i = i
        dd = v / peak - 1.0
        if dd < worst:
            worst = dd
            worst_peak_i = peak_i
            worst_trough_i = i
    return {
        "max_drawdown": worst,
        "peak_index": max(0, worst_peak_i - 1),
        "trough_index": max(0, worst_trough_i - 1),
        "duration_bars": max(0, worst_trough_i - worst_peak_i),
    }


def total_return(returns: list[float]) -> float | None:
    if not returns:
        return None
    wealth = 1.0
    for r in returns:
        wealth *= 1.0 + r
    return wealth - 1.0


def annualized_return(returns: list[float],
                      periods: int = PERIODS_PER_YEAR) -> float | None:
    tr = total_return(returns)
    if tr is None or not returns:
        return None
    return (1.0 + tr) ** (periods / len(returns)) - 1.0


def calmar_ratio(returns: list[float],
                 periods: int = PERIODS_PER_YEAR) -> float | None:
    """Annualized geometric return / |max drawdown|: return per unit of pain.

    Reuses ``max_drawdown``. Returns None when undefined — empty series, or
    zero max drawdown. A zero drawdown means the strategy never lost from a
    peak in-sample; the ratio would be +∞ for any positive return, which is
    an artifact of a lucky sample, not information. None, never raises,
    never invents a number; the gates treat missing evidence as FAIL.
    """
    ann = annualized_return(returns, periods)
    dd = max_drawdown(returns)["max_drawdown"]
    if ann is None or dd == 0.0:
        return None
    return ann / abs(dd)


def profit_factor(returns: list[float]) -> float | None:
    """Gross profit / gross loss. +inf when there are no losing bars, None when empty."""
    if not returns:
        return None
    gains = sum(r for r in returns if r > 0.0)
    losses = abs(sum(r for r in returns if r < 0.0))
    if losses == 0.0:
        return math.inf if gains > 0.0 else None
    return gains / losses


def win_rate(returns: list[float]) -> float | None:
    """Fraction of positive bars. None when empty."""
    if not returns:
        return None
    return sum(1 for r in returns if r > 0.0) / len(returns)


def cost_haircut(returns: list[float], cost_bps_per_trade: float,
                 trades_per_year: float,
                 periods: int = PERIODS_PER_YEAR) -> list[float]:
    """Turnover-agnostic cost haircut: subtract a flat per-bar cost.

    Per-bar drag = (cost_bps_per_trade / 1e4) * trades_per_year / periods.
    This is deliberately turnover-agnostic — it does not model which bars
    traded. Use it as a conservative haircut, not a fill simulator.
    """
    drag = (cost_bps_per_trade / 1e4) * trades_per_year / periods
    return [r - drag for r in returns]


def performance_summary(returns: list[float], rf_annual: float = 0.0,
                        periods: int = PERIODS_PER_YEAR) -> dict:
    """Every headline stat in one plain dict. O(len(returns))."""
    dd = max_drawdown(returns)
    return {
        "n_bars": len(returns),
        "total_return": total_return(returns),
        "annualized_return": annualized_return(returns, periods),
        "sharpe": sharpe_ratio(returns, rf_annual, periods),
        "sortino": sortino_ratio(returns, rf_annual, periods),
        "max_drawdown": dd["max_drawdown"],
        "max_drawdown_duration_bars": dd["duration_bars"],
        "calmar": calmar_ratio(returns, periods),
        "profit_factor": profit_factor(returns),
        "win_rate": win_rate(returns),
        "skewness": skewness(returns),
        "excess_kurtosis": excess_kurtosis(returns),
        "volatility_ann": (sample_stdev(returns) or 0.0) * math.sqrt(periods) if len(returns) > 1 else None,
    }
