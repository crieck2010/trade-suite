"""Small statistical helpers (stdlib only). Internal use."""

from __future__ import annotations

import math

_SQRT2 = math.sqrt(2.0)


def normal_cdf(x: float) -> float:
    """Standard normal CDF via math.erf."""
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def norm_ppf(p: float) -> float:
    """Inverse standard normal CDF (Acklam's approximation, ~1e-9 accuracy).

    Raises ValueError for p outside (0, 1).
    """
    if not 0.0 < p < 1.0:
        raise ValueError(f"p must be in (0, 1), got {p!r}")
    # Coefficients for Acklam's rational approximation.
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01,
         2.445134137142996e00, 3.754408661907416e00]
    plow, phigh = 0.02425, 1.0 - 0.02425
    if p < plow:  # lower tail
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p > phigh:  # upper tail
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)


def mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def sample_variance(xs: list[float]) -> float | None:
    """Unbiased (n-1) sample variance; None when n < 2."""
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    return sum((x - m) ** 2 for x in xs) / (n - 1)


def sample_stdev(xs: list[float]) -> float | None:
    v = sample_variance(xs)
    return math.sqrt(v) if v is not None else None


def skewness(xs: list[float]) -> float | None:
    """Sample skewness (Fisher, bias-corrected); None when n < 3 or stdev == 0."""
    n = len(xs)
    if n < 3:
        return None
    m = sum(xs) / n
    s = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    if s == 0.0:
        return None
    return (n / ((n - 1) * (n - 2))) * sum(((x - m) / s) ** 3 for x in xs)


def excess_kurtosis(xs: list[float]) -> float | None:
    """Sample excess kurtosis (Fisher, bias-corrected); None when n < 4 or stdev == 0."""
    n = len(xs)
    if n < 4:
        return None
    m = sum(xs) / n
    s = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    if s == 0.0:
        return None
    m4 = sum(((x - m) / s) ** 4 for x in xs)
    return (n * (n + 1) / ((n - 1) * (n - 2) * (n - 3))) * m4 - 3.0 * (n - 1) ** 2 / ((n - 2) * (n - 3))


def median(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0
