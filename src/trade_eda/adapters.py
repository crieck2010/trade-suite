"""Lazy, plain-data adapters to the rest of the trade-suite.

Each adapter imports its target engine only when called, so trade-eda
stays dependency-free and every suite engine stays independently
importable.  All inputs/outputs are plain dicts/lists of floats —
no engine objects cross the boundary.
"""

from __future__ import annotations


def _as_bars(bars) -> list[dict]:
    out = []
    for b in bars:
        if isinstance(b, dict):
            out.append(b)
        else:
            out.append({
                "symbol": getattr(b, "symbol", ""),
                "timestamp": getattr(b, "timestamp", None),
                "open": getattr(b, "open", None),
                "high": getattr(b, "high", None),
                "low": getattr(b, "low", None),
                "close": b.close,
                "volume": getattr(b, "volume", None),
            })
    return out


def _require(dist: str, package: str):
    try:
        return __import__(package, fromlist=["*"])
    except ImportError as exc:
        raise RuntimeError(
            f"{dist} is not installed; install it with "
            f"`pip install git+https://github.com/crieck2010/{dist}.git`"
        ) from exc


def corr_for_optimize(
    bars_by_symbol: dict,
    shrinkage: str = "ledoit_wolf",
) -> dict:
    """Annualized covariance matrix ready for ``trade-optimize``.

    Returns ``{"source", "symbols", "cov_annualized"}`` — the exact shape
    an optimizer consumes, with Ledoit-Wolf shrinkage applied by default
    so the matrix is well-conditioned even for wide universes.
    """
    from . import analyze

    rep = analyze(bars_by_symbol, shrinkage=shrinkage)
    return {
        "source": "trade-eda",
        "symbols": rep["symbols"],
        "cov_annualized": rep["covariance"]["matrix"],
        "shrinkage_delta": rep["covariance"]["shrinkage_delta"],
        "n_obs": rep["n_obs"],
    }


def corr_for_risk(bars_by_symbol: dict) -> dict:
    """Concentration/diversification report for ``trade-risk``.

    Flags the most-correlated pair and the equal-weight effective number
    of bets — a portfolio of 8 names with mean pairwise correlation 0.6
    behaves like ~2 independent bets, not 8.
    """
    from . import analyze

    rep = analyze(bars_by_symbol)
    div = rep["diversification"]
    hi = div["max_pairwise_corr"]
    return {
        "source": "trade-eda",
        "symbols": rep["symbols"],
        "n_obs": rep["n_obs"],
        "mean_pairwise_corr": div["mean_pairwise_corr"],
        "max_pairwise_corr": hi,
        "effective_n_equal_weight": div["effective_n_equal_weight"],
        "concentrated": hi["value"] > 0.9,
        "notes": (
            f"Most correlated pair {hi['a']}/{hi['b']} at {hi['value']:.2f}; "
            f"{len(rep['symbols'])} names behave like "
            f"{div['effective_n_equal_weight']:.1f} independent bets."
        ),
    }


def to_agent_eda_report(bars_by_symbol: dict) -> dict:
    """Compact JSON EDA brief for ``trade-agents`` researchers."""
    from . import analyze

    rep = analyze(bars_by_symbol)
    return {
        "source": "trade-eda",
        "symbols": rep["symbols"],
        "n_obs": rep["n_obs"],
        "mean_pairwise_corr": rep["diversification"]["mean_pairwise_corr"],
        "max_pairwise_corr": rep["diversification"]["max_pairwise_corr"],
        "effective_n_equal_weight":
            rep["diversification"]["effective_n_equal_weight"],
        "vol_annualized": {s: d["vol_annualized"]
                           for s, d in rep["describe"].items()},
        "nonnormal": [s for s, d in rep["describe"].items()
                      if d["jarque_bera"] > 9.21],  # chi2(2) 1% critical value
        "quality_flags": {s: {k: v for k, v in q.items() if k != "clean"}
                          for s, q in rep["quality"].items()
                          if not q["clean"]},
    }


def eda_forecast_inputs(
    bars_by_symbol: dict,
    horizon: int = 21,
) -> dict:
    """Volatility/correlation inputs for ``trade-volforecast``.

    Annualized per-asset vols plus the correlation matrix — everything a
    risk model needs to turn single-asset vol forecasts into a portfolio
    vol forecast via ``w'Σw``.
    """
    from . import analyze

    rep = analyze(bars_by_symbol)
    return {
        "source": "trade-eda",
        "symbols": rep["symbols"],
        "n_obs": rep["n_obs"],
        "horizon_days": horizon,
        "vol_annualized": {s: d["vol_annualized"]
                           for s, d in rep["describe"].items()},
        "correlation": rep["correlation"],
        "cov_annualized": rep["covariance"]["matrix"],
    }
