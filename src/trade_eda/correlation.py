"""Correlation matrices: Pearson and Spearman, stdlib-only.

All functions take ``{symbol: [returns]}`` with aligned series (see
:func:`aligned_returns`) and return plain data.  Missing values are not
guessed at: series are truncated to their common length first, so every
pairwise statistic is computed on the same observations.
"""

from __future__ import annotations

import math


def _closes(bars_or_closes) -> list[float]:
    out = []
    for b in bars_or_closes:
        if isinstance(b, dict):
            out.append(float(b["close"]))
        elif hasattr(b, "close"):
            out.append(float(b.close))
        else:
            out.append(float(b))
    return out


def aligned_returns(
    closes_by_symbol: dict[str, list],
    kind: str = "log",
) -> dict[str, list[float]]:
    """``{symbol: closes}`` -> ``{symbol: returns}``, common length.

    Truncates every series to the shortest length (oldest-first) and drops
    the first observation per series (no return exists for it).  ``kind``
    is ``"log"`` (default) or ``"simple"``.  Non-positive closes are
    skipped for log returns rather than raising.
    """
    if kind not in ("log", "simple"):
        raise ValueError("kind must be 'log' or 'simple'")
    closes = {s: _closes(c) for s, c in closes_by_symbol.items()}
    if not closes:
        raise ValueError("no series provided")
    m = min(len(c) for c in closes.values())
    if m < 2:
        raise ValueError("need >= 2 closes per symbol")
    out: dict[str, list[float]] = {}
    for s, c in closes.items():
        c = c[-m:]
        if kind == "log":
            out[s] = [math.log(c[i] / c[i - 1]) for i in range(1, m)
                      if c[i] > 0 and c[i - 1] > 0]
        else:
            out[s] = [c[i] / c[i - 1] - 1.0 for i in range(1, m)
                      if c[i - 1] != 0]
    return out


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def _std(xs: list[float], ddof: int = 1) -> float:
    n = len(xs)
    if n <= ddof:
        return 0.0
    mu = _mean(xs)
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - ddof))


def pearson_corr(x: list[float], y: list[float]) -> float:
    """Pearson product-moment correlation in [-1, 1]."""
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("need two aligned series of length >= 2")
    sx, sy = _std(x), _std(y)
    if sx == 0.0 or sy == 0.0:
        return 0.0  # constant series carries no linear signal
    mx, my = _mean(x), _mean(y)
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y)) / (len(x) - 1)
    return max(-1.0, min(1.0, cov / (sx * sy)))


def _ranks(xs: list[float]) -> list[float]:
    """Average ranks for ties (1-based)."""
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


def spearman_corr(x: list[float], y: list[float]) -> float:
    """Spearman rank correlation: Pearson on average ranks."""
    return pearson_corr(_ranks(x), _ranks(y))


def pairwise_corr(
    returns: dict[str, list[float]],
    method: str = "pearson",
) -> dict[tuple[str, str], float]:
    """``{(a, b): corr}`` for every unordered pair, ``a < b``."""
    if method == "pearson":
        fn = pearson_corr
    elif method == "spearman":
        fn = spearman_corr
    else:
        raise ValueError(f"unknown method {method!r}")
    syms = sorted(returns)
    out: dict[tuple[str, str], float] = {}
    for i, a in enumerate(syms):
        for b in syms[i + 1:]:
            out[(a, b)] = fn(returns[a], returns[b])
    return out


def corr_matrix(
    returns: dict[str, list[float]],
    method: str = "pearson",
) -> dict:
    """Full correlation matrix as plain data.

    Returns ``{"symbols": [...], "matrix": [[...]]}`` with 1.0 on the
    diagonal, symmetric off-diagonals, rounded to 6 dp.
    """
    syms = sorted(returns)
    if len(syms) < 2:
        raise ValueError("need at least two series")
    pw = pairwise_corr(returns, method=method)
    idx = {s: i for i, s in enumerate(syms)}
    n = len(syms)
    mat = [[0.0] * n for _ in range(n)]
    for i in range(n):
        mat[i][i] = 1.0
    for (a, b), v in pw.items():
        i, j = idx[a], idx[b]
        mat[i][j] = mat[j][i] = round(v, 6)
    return {"symbols": syms, "matrix": mat}


def mean_pairwise_corr(corr: dict) -> float:
    """Average off-diagonal correlation (diversification at a glance)."""
    mat, n = corr["matrix"], len(corr["symbols"])
    if n < 2:
        return 0.0
    total = sum(mat[i][j] for i in range(n) for j in range(i + 1, n))
    return total / (n * (n - 1) / 2)


def max_pairwise_corr(corr: dict) -> tuple[str, str, float]:
    """The most-correlated pair: ``(symbol_a, symbol_b, value)``."""
    syms, mat, n = corr["symbols"], corr["matrix"], len(corr["symbols"])
    best = (syms[0], syms[1], mat[0][1])
    for i in range(n):
        for j in range(i + 1, n):
            if abs(mat[i][j]) > abs(best[2]):
                best = (syms[i], syms[j], mat[i][j])
    return best
