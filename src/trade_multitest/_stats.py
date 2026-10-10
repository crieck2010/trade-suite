"""Shared numerical primitives for trade-multitest.

Only the standard library and NumPy. No SciPy: the normal CDF / inverse
CDF are implemented here (Abramowitz-Stegun erf, Acklam inverse), and the
stationary bootstrap follows Politis & Romano (1994) in vectorised form.
"""

from __future__ import annotations

import math

import numpy as np

__all__ = [
    "norm_cdf",
    "norm_ppf",
    "stationary_bootstrap_indices",
    "newey_west_long_run_variance",
    "one_sided_t_pvalue",
]

_SQRT2 = math.sqrt(2.0)
_EULER_MASCHERONI = 0.5772156649015329


def norm_cdf(x):
    """Standard normal CDF, vectorised (Abramowitz-Stegun erf, ~1e-7)."""
    x = np.asarray(x, dtype=float)
    ax = np.abs(x)
    # A&S 7.1.26
    t = 1.0 / (1.0 + 0.3275911 * ax)
    erf = 1.0 - (
        0.254829592 * t
        - 0.284496736 * t**2
        + 1.421413741 * t**3
        - 1.453152027 * t**4
        + 1.061405429 * t**5
    ) * np.exp(-ax * ax)
    erf = np.where(x < 0.0, -erf, erf)
    return 0.5 * (1.0 + erf)


def norm_ppf(p):
    """Standard normal inverse CDF (Acklam's algorithm, ~1e-9)."""
    p = np.asarray(p, dtype=float)
    if np.any((p <= 0.0) | (p >= 1.0)):
        raise ValueError("norm_ppf requires 0 < p < 1")
    a = [-3.969683028665376e01, 2.209460984245205e02,
         -2.759285104469687e02, 1.383577518672690e02,
         -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02,
         -1.556989798598866e02, 6.680131188771972e01,
         -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e00, -2.549732539343734e00,
         4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01,
         2.445134137142996e00, 3.754408661907416e00]
    plow, phigh = 0.02425, 1.0 - 0.02425
    q = np.empty_like(p)
    lo = p < plow
    hi = p > phigh
    mid = ~(lo | hi)
    if np.any(lo):
        pl = p[lo]
        ql = np.sqrt(-2.0 * np.log(pl))
        q[lo] = (((((c[0] * ql + c[1]) * ql + c[2]) * ql + c[3]) * ql + c[4]) * ql + c[5]) / \
                ((((d[0] * ql + d[1]) * ql + d[2]) * ql + d[3]) * ql + 1.0)
    if np.any(hi):
        ph = p[hi]
        qh = np.sqrt(-2.0 * np.log(1.0 - ph))
        q[hi] = -(((((c[0] * qh + c[1]) * qh + c[2]) * qh + c[3]) * qh + c[4]) * qh + c[5]) / \
                 ((((d[0] * qh + d[1]) * qh + d[2]) * qh + d[3]) * qh + 1.0)
    if np.any(mid):
        pm = p[mid] - 0.5
        r = pm * pm
        q[mid] = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * pm / \
                 (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    return q


def stationary_bootstrap_indices(n, block_len, n_boot, seed=0):
    """Stationary-bootstrap resample indices, shape ``(n_boot, n)``.

    Politis & Romano (1994): blocks start at uniform random positions and
    have geometric lengths with mean ``block_len`` (wrapping at the end).
    Fully vectorised over bootstrap replications.
    """
    n = int(n)
    block_len = float(block_len)
    if n < 2:
        raise ValueError("stationary bootstrap needs n >= 2")
    if not block_len >= 1.0:
        raise ValueError("block_len must be >= 1")
    rng = np.random.default_rng(seed)
    p = 1.0 / block_len
    ar = np.arange(n)
    rand = rng.random((n_boot, n))
    starts = rng.integers(0, n, size=(n_boot, n))
    new_block = np.zeros((n_boot, n), dtype=bool)
    new_block[:, 0] = True
    new_block[:, 1:] = rand[:, 1:] < p
    # last block-start position at or before each t (forward fill)
    last_start = np.maximum.accumulate(np.where(new_block, ar, 0), axis=1)
    chosen_start = starts[np.arange(n_boot)[:, None], last_start]
    offsets = ar - last_start
    return (chosen_start + offsets) % n


def newey_west_long_run_variance(x, lags=None):
    """Long-run variance of a 1-D series (Newey-West, Bartlett kernel).

    Returns sigma^2 such that Var(mean(x)) ~= sigma^2 / n. Default lag is
    the Newey-West (1994) rule of thumb ``floor(4 * (n/100)^(2/9))``.
    """
    x = np.asarray(x, dtype=float).ravel()
    n = x.shape[0]
    if n < 2:
        raise ValueError("need at least 2 observations")
    if lags is None:
        lags = int(4.0 * (n / 100.0) ** (2.0 / 9.0))
    lags = max(0, int(lags))
    xc = x - x.mean()
    gamma0 = float(np.dot(xc, xc) / n)
    lr = gamma0
    for j in range(1, lags + 1):
        w = 1.0 - j / (lags + 1.0)
        lr += 2.0 * w * float(np.dot(xc[j:], xc[:-j]) / n)
    return max(lr, 0.0)


def one_sided_t_pvalue(mean, se, n=None):
    """P-value for H0: mean <= 0 vs H1: mean > 0.

    Normal approximation (valid asymptotically; the bootstrap tests in
    this package do not rely on it). ``se`` must be positive.
    """
    mean = float(mean)
    se = float(se)
    if not np.isfinite(mean) or not np.isfinite(se) or se <= 0.0:
        raise ValueError("mean and se must be finite with se > 0")
    return float(1.0 - norm_cdf(mean / se))
