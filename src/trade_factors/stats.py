"""Small-sample statistics: moments, Student-t and F distributions.

t and F CDFs run through the regularized incomplete beta function
(continued-fraction evaluation, Numerical Recipes style) — no SciPy.
"""

from __future__ import annotations

import math


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def var(xs: list[float], ddof: int = 1) -> float:
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - ddof)


def std(xs: list[float]) -> float:
    return math.sqrt(var(xs))


def cov(xs: list[float], ys: list[float]) -> float:
    mx, my = mean(xs), mean(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (len(xs) - 1)


def corr(xs: list[float], ys: list[float]) -> float:
    return cov(xs, ys) / (std(xs) * std(ys))


def _betacf(a: float, b: float, x: float) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < 1e-300:
        d = 1e-300
    d = 1.0 / d
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        delt = c * d
        h *= delt
        if abs(delt - 1.0) < 3e-12:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
             + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(lbeta) * _betacf(a, b, x) / a
    return 1.0 - math.exp(lbeta) * _betacf(b, a, 1.0 - x) / b


def t_cdf(t: float, df: float) -> float:
    """P(T <= t) for Student-t with df degrees of freedom."""
    if t == 0.0:
        return 0.5
    x = df / (df + t * t)
    ib = betainc(df / 2.0, 0.5, x)
    return 1.0 - 0.5 * ib if t > 0 else 0.5 * ib


def t_pvalue(t: float, df: float) -> float:
    """Two-sided p-value for a t-statistic."""
    return 2.0 * (1.0 - t_cdf(abs(t), df))


def f_cdf(f: float, d1: float, d2: float) -> float:
    """P(F <= f) for F(d1, d2)."""
    if f <= 0.0:
        return 0.0
    return betainc(d1 / 2.0, d2 / 2.0, d1 * f / (d1 * f + d2))


def f_pvalue(f: float, d1: float, d2: float) -> float:
    """Right-tail p-value for an F-statistic."""
    return 1.0 - f_cdf(f, d1, d2)
