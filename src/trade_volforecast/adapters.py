"""Interop adapters: plain-data bridges to sibling suite modules.

Sibling imports are lazy (inside functions) so trade-volforecast stays
importable and testable on its own.
"""

from __future__ import annotations

from . import ewma, garch, har, realized


# ------------------------------------------------------------ trade-data-*

def realized_from_bars(bars: list[dict], estimator: str = "yang_zhang",
                       window: int = 21) -> list[dict]:
    """Rolling annualized realized vol from plain OHLC dict bars."""
    return realized.realized_vol(bars, estimator=estimator, window=window)


# ------------------------------------------------------------ trade-optimize

def vol_for_optimize(bars: list[dict], horizon: int = 21,
                     method: str = "garch") -> dict:
    """Forward vol forecast per the optimizer's plain-data contract.

    trade-optimize can annualize these into a diagonal covariance when
    no factor model is available.
    """
    rets = realized.log_returns(bars)
    if method == "garch":
        fit = garch.fit_garch(rets)
        fc = garch.garch_forecast(fit, horizon=horizon)
    elif method == "har":
        rv = realized.realized_var_series(bars)
        fc = har.har_predict(har.har_fit(rv), horizon=horizon)
    elif method == "ewma":
        fc = ewma.ewma_forecast(rets, horizon=horizon)
    else:
        raise ValueError(f"unknown method {method!r}")
    return {"source": "trade-volforecast", "method": method, **fc}


# ---------------------------------------------------------------- trade-risk

def vol_for_risk(bars: list[dict], window: int = 21) -> dict:
    """Current vol regime snapshot for risk monitoring."""
    rv = realized.realized_vol(bars, window=window)
    vols = [row["vol"] for row in rv]
    return {
        "source": "trade-volforecast",
        "current_vol": vols[-1],
        "vol_21d_avg": sum(vols) / len(vols),
        "vol_max": max(vols),
        "vol_min": min(vols),
        "n_windows": len(vols),
    }


# -------------------------------------------------------------- trade-agents

def to_agent_vol_report(bars: list[dict], horizon: int = 10) -> dict:
    """Volatility briefing for researcher agents: forecasts, not paths."""
    rets = realized.log_returns(bars)
    gfit = garch.fit_garch(rets)
    rv = realized.realized_var_series(bars)
    hfit = har.har_fit(rv)
    return {
        "source": "trade-volforecast",
        "realized_vol_21d": realized.realized_vol(bars, window=21)[-1]["vol"],
        "garch": garch.garch_forecast(gfit, horizon=horizon),
        "har": har.har_predict(hfit, horizon=horizon),
        "ewma": ewma.ewma_forecast(rets, horizon=horizon),
        "garch_persistence": gfit["persistence"],
        "har_r2": hfit["r_squared"],
    }
