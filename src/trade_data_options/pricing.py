"""European option pricing: Black-Scholes-Merton with dividends.

All functions are pure and dependency-free (``math`` only). Rates and
volatilities are decimals (0.05 = 5%), time in years (Actual/365).

Conventions
-----------
* ``theta`` is per **year** (divide by 365 for per-day).
* ``vega`` is per 1.00 of volatility (divide by 100 for per vol point).
* ``rho`` is per 1.00 of rate (divide by 100 for per percentage point).
* Degenerate inputs (``T <= 0`` or ``sigma <= 0``) return discounted
  intrinsic value with intrinsic-only greeks (delta in {0, 1}, rest 0).
"""

from __future__ import annotations

import math

from .exceptions import ConvergenceError
from .models import Greeks, OptionRight

_SQRT_2PI = math.sqrt(2.0 * math.pi)
_IV_LO, _IV_HI = 1e-4, 5.0


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _validate(s: float, k: float, t: float, r: float, sigma: float, q: float) -> None:
    for name, value in (("S", s), ("K", k)):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be a positive finite number, got {value!r}")
    for name, value in (("T", t), ("r", r), ("sigma", sigma), ("q", q)):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite, got {value!r}")
    if t < 0:
        raise ValueError(f"T must be non-negative, got {t!r}")
    if sigma < 0:
        raise ValueError(f"sigma must be non-negative, got {sigma!r}")


def _d1_d2(s: float, k: float, t: float, r: float, sigma: float, q: float) -> tuple[float, float]:
    vol_t = sigma * math.sqrt(t)
    d1 = (math.log(s / k) + (r - q + 0.5 * sigma * sigma) * t) / vol_t
    return d1, d1 - vol_t


def bs_price(
    right: OptionRight,
    s: float,
    k: float,
    t: float,
    r: float,
    sigma: float,
    q: float = 0.0,
) -> float:
    """Black-Scholes price of a European option."""
    _validate(s, k, t, r, sigma, q)
    disc_r, disc_q = math.exp(-r * t), math.exp(-q * t)
    if t <= 0 or sigma <= 0:
        intrinsic = s * disc_q - k * disc_r
        return max(intrinsic, 0.0) if right is OptionRight.CALL else max(-intrinsic, 0.0)
    d1, d2 = _d1_d2(s, k, t, r, sigma, q)
    if right is OptionRight.CALL:
        return s * disc_q * _ncdf(d1) - k * disc_r * _ncdf(d2)
    return k * disc_r * _ncdf(-d2) - s * disc_q * _ncdf(-d1)


def bs_greeks(
    right: OptionRight,
    s: float,
    k: float,
    t: float,
    r: float,
    sigma: float,
    q: float = 0.0,
) -> Greeks:
    """Black-Scholes greeks (annualized; see module docstring)."""
    _validate(s, k, t, r, sigma, q)
    if t <= 0 or sigma <= 0:
        disc_q = math.exp(-q * t)
        itm = (s * disc_q > k * math.exp(-r * t)) if right is OptionRight.CALL else (s * disc_q < k * math.exp(-r * t))
        delta = (1.0 if itm else 0.0) * disc_q
        if right is OptionRight.PUT:
            delta -= disc_q
        return Greeks(delta=delta, gamma=0.0, theta=0.0, vega=0.0, rho=0.0)

    d1, d2 = _d1_d2(s, k, t, r, sigma, q)
    disc_r, disc_q = math.exp(-r * t), math.exp(-q * t)
    nd1, nd2 = _ncdf(d1), _ncdf(d2)
    pdf_d1 = _npdf(d1)
    sqrt_t = math.sqrt(t)

    gamma = disc_q * pdf_d1 / (s * sigma * sqrt_t)
    vega = s * disc_q * pdf_d1 * sqrt_t
    if right is OptionRight.CALL:
        delta = disc_q * nd1
        theta = (
            -s * sigma * disc_q * pdf_d1 / (2.0 * sqrt_t)
            - r * k * disc_r * nd2
            + q * s * disc_q * nd1
        )
        rho = k * t * disc_r * nd2
    else:
        delta = disc_q * (nd1 - 1.0)
        theta = (
            -s * sigma * disc_q * pdf_d1 / (2.0 * sqrt_t)
            + r * k * disc_r * _ncdf(-d2)
            - q * s * disc_q * _ncdf(-d1)
        )
        rho = -k * t * disc_r * _ncdf(-d2)
    return Greeks(delta=delta, gamma=gamma, theta=theta, vega=vega, rho=rho)


def intrinsic_value(right: OptionRight, s: float, k: float) -> float:
    """Undiscounted intrinsic value (for T = 0)."""
    if right is OptionRight.CALL:
        return max(s - k, 0.0)
    return max(k - s, 0.0)


def _arbitrage_bounds(right: OptionRight, s: float, k: float, t: float, r: float, q: float) -> tuple[float, float]:
    disc_r, disc_q = math.exp(-r * t), math.exp(-q * t)
    if right is OptionRight.CALL:
        return max(s * disc_q - k * disc_r, 0.0), s * disc_q
    return max(k * disc_r - s * disc_q, 0.0), k * disc_r


def implied_volatility(
    price: float,
    right: OptionRight,
    s: float,
    k: float,
    t: float,
    r: float,
    q: float = 0.0,
    tol: float = 1e-8,
    max_iter: int = 100,
) -> float:
    """Implied volatility via Newton-Raphson with bisection fallback.

    Raises :class:`ConvergenceError` when ``price`` violates arbitrage
    bounds or the solver fails to converge.
    """
    _validate(s, k, t, r, 0.2, q)  # validates everything but sigma
    if not math.isfinite(price) or price < 0:
        raise ValueError(f"price must be a non-negative number, got {price!r}")
    if t <= 0:
        raise ConvergenceError("implied volatility is undefined at expiry (T <= 0)")
    lo_bound, hi_bound = _arbitrage_bounds(right, s, k, t, r, q)
    if not (lo_bound - 1e-12 <= price <= hi_bound + 1e-12):
        raise ConvergenceError(
            f"price {price} violates arbitrage bounds [{lo_bound:.6f}, {hi_bound:.6f}]"
        )

    def f(sigma: float) -> tuple[float, float]:
        return bs_price(right, s, k, t, r, sigma, q) - price, bs_greeks(right, s, k, t, r, sigma, q).vega

    # Newton-Raphson from a sensible seed, guarded to the bracket.
    sigma = 0.3
    for _ in range(max_iter):
        diff, vega = f(sigma)
        if abs(diff) < tol:
            return sigma
        if vega < 1e-12:
            break
        step = diff / vega
        sigma -= step
        if not (_IV_LO <= sigma <= _IV_HI):
            break
    else:
        return sigma

    # Bisection fallback: price is monotone increasing in sigma.
    lo, hi = _IV_LO, _IV_HI
    f_lo = bs_price(right, s, k, t, r, lo, q) - price
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        diff = bs_price(right, s, k, t, r, mid, q) - price
        if abs(diff) < tol:
            return mid
        if (f_lo < 0) == (diff < 0):
            lo, f_lo = mid, diff
        else:
            hi = mid
    raise ConvergenceError(f"implied volatility did not converge for price {price}")
