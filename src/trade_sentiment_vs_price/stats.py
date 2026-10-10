"""Small-sample stats: moments, rank correlation, t-test for correlation.

Self-contained (no sibling imports): the t CDF runs through the
regularized incomplete beta function so correlation p-values are exact,
not normal approximations.
"""

from __future__ import annotations

import math


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def var(xs: list[float], ddof: int = 1) -> float:
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - ddof)


def std(xs: list[float]) -> float:
    return math.sqrt(max(var(xs), 0.0))


def pearson(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation; 0.0 when either series is constant."""
    n = len(xs)
    mx, my = mean(xs), mean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return 0.0
    return sxy / math.sqrt(sxx * syy)


def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman rank correlation (ties get average ranks)."""
    return pearson(_ranks(xs), _ranks(ys))


def _betacf(a: float, b: float, x: float) -> float:
    c, d = 1.0, 1.0 - (a + b) * x / (a + 1.0)
    if abs(d) < 1e-300:
        d = 1e-300
    d = 1.0 / d
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        aa = m * (b - m) * x / ((a + m2 - 1.0) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (a + b + m) * x / ((a + m2) * (a + m2 + 1.0))
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
    if t == 0.0:
        return 0.5
    ib = betainc(df / 2.0, 0.5, df / (df + t * t))
    return 1.0 - 0.5 * ib if t > 0 else 0.5 * ib


def corr_pvalue(r: float, n: int) -> float:
    """Two-sided p-value for a correlation from n observations."""
    if n < 3 or abs(r) >= 1.0:
        return 0.0 if abs(r) >= 1.0 and n >= 3 else 1.0
    t = r * math.sqrt((n - 2) / (1 - r * r))
    return 2.0 * (1.0 - t_cdf(abs(t), n - 2))


def zscore(xs: list[float]) -> list[float]:
    m, s = mean(xs), std(xs)
    if s == 0:
        return [0.0] * len(xs)
    return [(x - m) / s for x in xs]


def trailing_zscore(xs: list[float], window: int) -> list[float]:
    """Causal z-score: each point vs the trailing window before it."""
    out = []
    for i in range(len(xs)):
        hist = xs[max(0, i - window):i]
        if len(hist) < 2:
            out.append(0.0)
            continue
        m, s = mean(hist), std(hist)
        out.append((xs[i] - m) / s if s > 0 else 0.0)
    return out
