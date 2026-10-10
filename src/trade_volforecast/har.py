"""HAR-RV: Heterogeneous Autoregressive model for Realized Volatility.

Corsi (2009).  The insight: volatility has components operating at
different horizons — daily traders, weekly funds, monthly allocators —
so tomorrow's realized variance is a linear function of yesterday's,
last week's average, and last month's average:

    RV_{t+1} = c + β_d·RV_t^{(d)} + β_w·RV_t^{(w)} + β_m·RV_t^{(m)} + ε

where RV^{(w)} and RV^{(m)} are 5- and 22-day trailing averages.  OLS
does the fitting; the model routinely beats GARCH at short horizons on
realized-volatility targets because it models long memory with three
regressors instead of one persistence parameter.
"""

from __future__ import annotations

import math

from .linalg import ols_fit


def _trailing_avg(rv: list[float], window: int) -> list[float]:
    return [sum(rv[i - window + 1 : i + 1]) / window for i in range(window - 1, len(rv))]


def har_fit(rv: list[float], weekly: int = 5, monthly: int = 22) -> dict:
    """Fit HAR-RV on a daily realized-variance series.

    ``rv`` is per-day variance (see realized.realized_var_series).
    Predicts RV_{t+1} from components known at t.
    """
    if len(rv) < monthly + 2:
        raise ValueError(f"need at least {monthly + 2} RV observations")
    # align: components use data up to t, target is RV_{t+1}
    d = rv[monthly - 1 : -1]
    w = _trailing_avg(rv, weekly)[monthly - weekly : -1]
    m = _trailing_avg(rv, monthly)[:-1]
    y = rv[monthly:]
    n = len(y)
    d, w, m = d[:n], w[:n], m[:n]
    X = [[1.0, di, wi, mi] for di, wi, mi in zip(d, w, m)]
    fit = ols_fit(X, y)
    c, b_d, b_w, b_m = fit["beta"]
    return {
        "model": "har",
        "c": c, "beta_daily": b_d, "beta_weekly": b_w, "beta_monthly": b_m,
        "r_squared": fit["r_squared"],
        "sigma2": fit["sigma2"],
        "n": fit["n"],
        # state needed for the next forecast
        "last_daily": d[-1], "last_weekly": w[-1], "last_monthly": m[-1],
    }


def har_predict(fit: dict, horizon: int = 1, annualize: int = 252) -> dict:
    """One-step-ahead RV forecast (and naive multi-step extension).

    Multi-step HAR is iterated: each forecasted day updates the
    trailing averages.  Honest about being an approximation — the
    literature usually re-estimates direct multi-step regressions.
    """
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    c, bd, bw, bm = fit["c"], fit["beta_daily"], fit["beta_weekly"], fit["beta_monthly"]
    # seed the trailing windows with the last observed values
    d_hist = [fit["last_daily"]] * 1
    w_hist = [fit["last_weekly"]] * 5
    m_hist = [fit["last_monthly"]] * 22
    vols = []
    for _ in range(horizon):
        rv_next = max(c + bd * d_hist[-1] + bw * (sum(w_hist[-5:]) / 5) + bm * (sum(m_hist[-22:]) / 22), 1e-12)
        vols.append(math.sqrt(rv_next * annualize))
        d_hist.append(rv_next); w_hist.append(rv_next); m_hist.append(rv_next)
    return {
        "model": "har",
        "horizon_days": horizon,
        "term_structure": vols,
        "vol_annualized": vols[0],
        "r_squared": fit["r_squared"],
    }
