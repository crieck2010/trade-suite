"""trade-eda: correlation, covariance, and exploratory analysis for the trade-suite.

Stdlib-only.  Pure functions take plain data (dicts/lists of floats) in and
return plain JSON-serializable data out, so the engine plugs into the web
dashboard's research services, the desktop fallback, trade-suite workflows,
and trade-agents without a translation layer.

Modules
-------
correlation : Pearson / Spearman correlation matrices
covariance  : sample covariance and Ledoit-Wolf shrinkage
describe    : per-asset summary statistics and data-quality checks
demo        : seeded factor-model universe with known correlation blocks
adapters    : lazy, plain-data bridges to trade-optimize / trade-risk / trade-agents
"""

from __future__ import annotations

from .correlation import (
    aligned_returns,
    corr_matrix,
    max_pairwise_corr,
    mean_pairwise_corr,
    pairwise_corr,
    pearson_corr,
    spearman_corr,
)
from .covariance import ledoit_wolf, sample_cov
from .describe import data_quality, describe_returns, describe_series
from .demo import demo_bars, demo_universe

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "aligned_returns",
    "corr_matrix",
    "data_quality",
    "demo_bars",
    "demo_universe",
    "describe_returns",
    "describe_series",
    "ledoit_wolf",
    "max_pairwise_corr",
    "mean_pairwise_corr",
    "pairwise_corr",
    "pearson_corr",
    "sample_cov",
    "spearman_corr",
]


def analyze(
    bars_by_symbol: dict,
    *,
    method: str = "pearson",
    shrinkage: str = "ledoit_wolf",
    kind: str = "log",
    annualize: int = 252,
    lookback: int | None = None,
) -> dict:
    """Full correlation/EDA report as plain data.

    ``bars_by_symbol`` maps ``SYMBOL -> [bar]`` where each bar is a dict
    (or object) with at least ``close``; ``volume``/``timestamp`` are used
    for the data-quality section when present.  Series are truncated to the
    common length (oldest-first), so ragged universes still work.
    """
    from .adapters import _as_bars  # local import: keep import graph shallow

    syms = sorted({(s or "").strip().upper() for s in bars_by_symbol})
    syms = [s for s in syms if s]
    if len(syms) < 2:
        raise ValueError("need at least two symbols for correlation analysis")
    bars = {s: _as_bars(bars_by_symbol[s]) for s in syms
         if s in bars_by_symbol}
    if set(bars) != set(syms):
        raise ValueError("no bars for " + ", ".join(s for s in syms
                                                   if s not in bars))
    closes = {s: [b["close"] for b in bars[s]] for s in syms}
    if lookback is not None:
        lb = max(2, int(lookback))
        closes = {s: c[-lb:] for s, c in closes.items()}
    rets = aligned_returns(closes, kind=kind)
    n_obs = len(rets[syms[0]])
    if n_obs < 3:
        raise ValueError(f"need >= 3 return observations, have {n_obs}")

    corr = corr_matrix(rets, method=method)
    if shrinkage == "ledoit_wolf":
        lw = ledoit_wolf(rets)
        cov, delta = lw["matrix"], lw["shrinkage"]
    elif shrinkage in ("sample", "none"):
        cov, delta = sample_cov(rets)["matrix"], 0.0
    else:
        raise ValueError(f"unknown shrinkage {shrinkage!r}")
    desc = describe_returns(rets, annualize=annualize)
    quality = data_quality(bars)
    mp = mean_pairwise_corr(corr)
    hi = max_pairwise_corr(corr)
    n = len(syms)
    effective_n = n / (1.0 + (n - 1) * mp) if mp > -1.0 / max(n - 1, 1) else n
    return {
        "source": "trade-eda",
        "symbols": syms,
        "n_obs": n_obs,
        "returns_kind": kind,
        "correlation": {"method": method, "matrix": corr["matrix"]},
        "covariance": {
            "shrinkage": shrinkage,
            "shrinkage_delta": round(delta, 6),
            "matrix": cov,
            "annualized": True,
        },
        "describe": desc,
        "quality": quality,
        "diversification": {
            "mean_pairwise_corr": round(mp, 6),
            "max_pairwise_corr": {
                "a": hi[0], "b": hi[1], "value": round(hi[2], 6)},
            "effective_n_equal_weight": round(effective_n, 4),
        },
    }
