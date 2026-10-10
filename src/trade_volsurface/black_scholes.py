"""Black-Scholes pricing, Greeks, and implied-volatility solver.

Independent implementation (no dividends).  Used to back out IVs from
quoted prices and to rebuild arbitrage-free-ish call prices from a
surface for the butterfly checks.
"""

from __future__ import annotations

import math
from statistics import NormalDist

_N = NormalDist()


def _d1_d2(s0: float, K: float, T: float, r: float, sigma: float):
    d1 = (math.log(s0 / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return d1, d1 - sigma * math.sqrt(T)


def bs_price(s0: float, K: float, T: float, r: float, sigma: float,
             kind: str = "call") -> float:
    """European option price.  ``T <= 0`` returns intrinsic value."""
    if kind not in ("call", "put"):
        raise ValueError("kind must be 'call' or 'put'")
    if T <= 0:
        return max(s0 - K, 0.0) if kind == "call" else max(K - s0, 0.0)
    if sigma <= 0:
        disc = math.exp(-r * T)
        fwd = s0 - K * disc
        return max(fwd, 0.0) if kind == "call" else max(-fwd, 0.0)
    d1, d2 = _d1_d2(s0, K, T, r, sigma)
    disc = math.exp(-r * T)
    call = s0 * _N.cdf(d1) - K * disc * _N.cdf(d2)
    if kind == "call":
        return call
    return call - s0 + K * disc  # put-call parity


def bs_vega(s0: float, K: float, T: float, r: float, sigma: float) -> float:
    """dPrice/dVol per 1.0 vol point (divide by 100 for per-1%)."""
    if T <= 0 or sigma <= 0:
        return 0.0
    d1, _ = _d1_d2(s0, K, T, r, sigma)
    return s0 * _N.pdf(d1) * math.sqrt(T)


def bs_greeks(s0: float, K: float, T: float, r: float, sigma: float,
              kind: str = "call") -> dict:
    """delta, gamma, theta (per year), vega (per 1.0 vol), rho."""
    d1, d2 = _d1_d2(s0, K, T, r, sigma)
    disc = math.exp(-r * T)
    phi = _N.pdf(d1)
    sqrt_t = math.sqrt(T)
    delta = _N.cdf(d1) if kind == "call" else _N.cdf(d1) - 1.0
    gamma = phi / (s0 * sigma * sqrt_t)
    theta_common = -s0 * phi * sigma / (2 * sqrt_t)
    if kind == "call":
        theta = theta_common - r * K * disc * _N.cdf(d2)
        rho = K * T * disc * _N.cdf(d2)
    else:
        theta = theta_common + r * K * disc * _N.cdf(-d2)
        rho = -K * T * disc * _N.cdf(-d2)
    return {"delta": delta, "gamma": gamma, "theta": theta,
            "vega": s0 * phi * sqrt_t, "rho": rho}


def implied_vol(price: float, s0: float, K: float, T: float, r: float,
                kind: str = "call") -> float:
    """Back out sigma from a price: Newton, bisection fallback.

    Returns 0.0 when the price is at/below intrinsic value.
    """
    intrinsic = bs_price(s0, K, T, r, 0.0, kind)
    if price <= intrinsic * (1.0 + 1e-12):
        return 0.0

    def f(sig):
        return bs_price(s0, K, T, r, sig, kind) - price

    sig = 0.3  # Newton
    for _ in range(50):
        vega = bs_vega(s0, K, T, r, sig)
        if vega < 1e-12:
            break
        step = f(sig) / vega
        sig -= step
        if sig <= 0:
            break
        if abs(step) < 1e-10:
            return sig
    # Bisection fallback on [1e-6, 5.0]
    lo, hi = 1e-6, 5.0
    flo = f(lo)
    if flo > 0:
        return 0.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if f(mid) > 0:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-9:
            break
    return 0.5 * (lo + hi)
