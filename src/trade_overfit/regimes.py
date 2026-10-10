"""Regime-split analysis: does the edge survive calm AND stress markets?"""

from __future__ import annotations

from ._stats import median, sample_stdev
from .metrics import max_drawdown, sharpe_ratio, total_return


def trailing_vol(returns: list[float], lookback: int = 63,
                 periods: int = 252) -> list[float | None]:
    """Trailing annualized realized vol at each bar (None while warming up)."""
    import math
    out: list[float | None] = []
    for i in range(len(returns)):
        window = returns[max(0, i - lookback + 1): i + 1]
        if len(window) < 2:
            out.append(None)
        else:
            out.append(sample_stdev(window) * math.sqrt(periods))
    return out


def vol_regime_labels(returns: list[float], lookback: int = 63,
                      periods: int = 252) -> list[str]:
    """Label each bar 'calm' or 'stress' by trailing realized vol vs its median.

    Bars where trailing vol is above the sample median are 'stress',
    the rest 'calm'. Warmup bars (insufficient history) are labelled 'calm'
    so no data is discarded.
    """
    vols = trailing_vol(returns, lookback, periods)
    med = median([v for v in vols if v is not None])
    if med is None:
        return ["calm"] * len(returns)
    return ["stress" if (v is not None and v > med) else "calm" for v in vols]


def regime_report(returns: list[float], labels: list[str] | None = None,
                  lookback: int = 63, rf_annual: float = 0.0,
                  periods: int = 252) -> dict:
    """Per-regime performance. ``labels`` may be user-supplied (one per bar);
    when omitted, vol-regime labels are computed.

    Returns ``{"regimes": {label: stats}, "worst_regime": ..., "worst_regime_sharpe": ...}``.
    The stability verdict is the worst-regime Sharpe: an edge that only works
    in one regime is not an edge.
    """
    user_supplied = labels is not None
    if labels is None:
        labels = vol_regime_labels(returns, lookback, periods)
    if len(labels) != len(returns):
        raise ValueError(f"labels length {len(labels)} != returns length {len(returns)}")
    by_regime: dict[str, list[float]] = {}
    for r, lab in zip(returns, labels):
        by_regime.setdefault(lab, []).append(r)
    regimes = {}
    for lab, rs in by_regime.items():
        regimes[lab] = {
            "n_bars": len(rs),
            "sharpe": sharpe_ratio(rs, rf_annual, periods),
            "total_return": total_return(rs),
            "max_drawdown": max_drawdown(rs)["max_drawdown"],
        }
    sharpes = {lab: s["sharpe"] for lab, s in regimes.items() if s["sharpe"] is not None}
    worst = min(sharpes, key=lambda k: sharpes[k]) if sharpes else None
    return {
        "regimes": regimes,
        "worst_regime": worst,
        "worst_regime_sharpe": sharpes.get(worst) if worst else None,
        "label_source": "user" if user_supplied else "vol_regime",
    }
