"""GARCH(1,1) and GJR-GARCH(1,1) — maximum-likelihood volatility models.

GARCH(1,1) (Bollerslev, 1986):

    σ²_t = ω + α·r²_{t-1} + β·σ²_{t-1},   ω > 0, α ≥ 0, β ≥ 0, α+β < 1

Volatility clusters: a big shock yesterday raises today's variance, and
the effect decays geometrically at rate α+β ("persistence").

GJR-GARCH (Glosten-Jagannathan-Runkle, 1993) adds the leverage effect —
bad news moves vol more than good news:

    σ²_t = ω + (α + γ·1{r_{t-1}<0})·r²_{t-1} + β·σ²_{t-1}

Estimation is Gaussian MLE via Nelder-Mead on an unconstrained
reparameterization (see _pack/_unpack): positivity and stationarity
hold by construction, so the optimizer can't wander somewhere silly.
"""

from __future__ import annotations

import math

from .optimize import nelder_mead
from .rng import RandomStream


# ------------------------------------------------------------ simulation

def simulate_garch(
    n: int,
    omega: float,
    alpha: float,
    beta: float,
    seed: int = 7,
    mu: float = 0.0,
) -> list[float]:
    """Simulate n returns from a GARCH(1,1) process (for tests/demos)."""
    rs = RandomStream(seed)
    var_inf = omega / (1.0 - alpha - beta)
    var = var_inf
    out = []
    for _ in range(n):
        var = omega + alpha * (out[-1] - mu) ** 2 + beta * var if out else var_inf
        out.append(mu + math.sqrt(var) * rs.normal())
    return out


def simulate_gjr(
    n: int,
    omega: float,
    alpha: float,
    gamma: float,
    beta: float,
    seed: int = 7,
    mu: float = 0.0,
) -> list[float]:
    """Simulate n returns from a GJR-GARCH(1,1) process."""
    rs = RandomStream(seed)
    var_inf = omega / (1.0 - alpha - beta - gamma / 2.0)
    var = var_inf
    out = []
    for _ in range(n):
        if out:
            shock = out[-1] - mu
            var = omega + (alpha + gamma * (shock < 0)) * shock**2 + beta * var
        out.append(mu + math.sqrt(var) * rs.normal())
    return out


# ------------------------------------------------------------ likelihood

def _filter_variance(returns: list[float], omega: float, alpha: float,
                     beta: float, gamma: float = 0.0) -> list[float]:
    # σ²_t may only use returns *before* t — appending before updating
    # keeps the filter honest (no look-ahead).
    var = sum(r * r for r in returns) / len(returns)  # start at sample var
    out = []
    for r in returns:
        out.append(max(var, 1e-12))
        var = omega + (alpha + gamma * (r < 0)) * r * r + beta * var
    return out


def _neg_loglik(returns: list[float], omega: float, alpha: float,
                beta: float, gamma: float = 0.0) -> float:
    nll = 0.0
    for var, r in zip(_filter_variance(returns, omega, alpha, beta, gamma), returns):
        nll += 0.5 * (math.log(var) + r * r / var)
    return nll


# ------------------------------------------------------------ fitting

def _pack_garch(omega: float, alpha: float, beta: float) -> list[float]:
    s = 1.0 - alpha - beta
    return [math.log(omega), math.log(alpha / s), math.log(beta / s)]


def _unpack_garch(x: list[float]) -> tuple[float, float, float]:
    ea, eb = math.exp(x[1]), math.exp(x[2])
    d = 1.0 + ea + eb
    return math.exp(x[0]), ea / d, eb / d


def _pack_gjr(omega: float, alpha: float, gamma: float, beta: float) -> list[float]:
    s = 1.0 - alpha - gamma - beta
    return [math.log(omega), math.log(alpha / s), math.log(gamma / s), math.log(beta / s)]


def _unpack_gjr(x: list[float]) -> tuple[float, float, float, float]:
    ea, eg, eb = math.exp(x[1]), math.exp(x[2]), math.exp(x[3])
    d = 1.0 + ea + eg + eb
    return math.exp(x[0]), ea / d, eg / d, eb / d


def _fit(returns: list[float], pack, unpack, negll, start: list[float]) -> dict:
    res = nelder_mead(lambda x: negll(unpack(x)), start)
    params = unpack(res["x"])
    n = len(returns)
    k = len(params)
    return {
        "params": params,
        "neg_loglik": res["fun"],
        "aic": 2.0 * res["fun"] + 2.0 * k,
        "bic": 2.0 * res["fun"] + k * math.log(n),
        "converged": res["converged"],
        "n_iter": res["n_iter"],
        "n": n,
    }


def fit_garch(returns: list[float]) -> dict:
    """Fit GARCH(1,1) by MLE.  Returns are demeaned internally."""
    if len(returns) < 50:
        raise ValueError("need at least 50 returns to fit GARCH")
    mu = sum(returns) / len(returns)
    r = [x - mu for x in returns]
    var = sum(x * x for x in r) / len(r)
    start = _pack_garch(var * 0.04, 0.08, 0.88)
    out = _fit(r, _pack_garch, _unpack_garch,
               lambda p: _neg_loglik(r, *p), start)
    omega, alpha, beta = out["params"]
    out.update({
        "model": "garch",
        "mu": mu,
        "omega": omega, "alpha": alpha, "beta": beta,
        "persistence": alpha + beta,
        "unconditional_variance": omega / (1.0 - alpha - beta),
        "filtered_variance": _filter_variance(r, omega, alpha, beta),
    })
    return out


def fit_gjr(returns: list[float]) -> dict:
    """Fit GJR-GARCH(1,1) by MLE (asymmetric / leverage effect)."""
    if len(returns) < 50:
        raise ValueError("need at least 50 returns to fit GJR-GARCH")
    mu = sum(returns) / len(returns)
    r = [x - mu for x in returns]
    var = sum(x * x for x in r) / len(r)
    start = _pack_gjr(var * 0.04, 0.05, 0.06, 0.85)
    out = _fit(r, _pack_gjr, _unpack_gjr,
               lambda p: _neg_loglik(r, omega=p[0], alpha=p[1], beta=p[3], gamma=p[2]),
               start)
    omega, alpha, gamma, beta = out["params"]
    out.update({
        "model": "gjr",
        "mu": mu,
        "omega": omega, "alpha": alpha, "gamma": gamma, "beta": beta,
        "persistence": alpha + beta + gamma / 2.0,
        "unconditional_variance": omega / (1.0 - alpha - beta - gamma / 2.0),
        "filtered_variance": _filter_variance(r, omega, alpha, beta, gamma=gamma),
    })
    return out


# ------------------------------------------------------------ forecasting

def garch_forecast(fit: dict, horizon: int = 10, annualize: int = 252) -> dict:
    """Multi-step variance forecast with analytic mean reversion.

    E[σ²_{t+k}] = σ²_∞ + persistence^{k-1} · (σ²_{t+1} − σ²_∞)

    Unlike EWMA's flat line, GARCH forecasts decay back toward the
    long-run variance — the term structure has a shape.
    """
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    persist = fit["persistence"]
    var_inf = fit["unconditional_variance"]
    var_next = fit["filtered_variance"][-1]
    vols = []
    for k in range(1, horizon + 1):
        var_k = var_inf + persist ** (k - 1) * (var_next - var_inf)
        vols.append(math.sqrt(max(var_k, 0.0) * annualize))
    return {
        "model": fit["model"],
        "horizon_days": horizon,
        "term_structure": vols,
        "vol_annualized": vols[0],
        "long_run_vol": math.sqrt(var_inf * annualize),
    }
