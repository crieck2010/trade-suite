"""Small statistics helpers (stdlib only).

All functions operate on plain lists of floats.  Missing values are
represented as ``None`` and are *skipped* by the windowed functions (a
window containing ``None`` yields ``None`` — we never silently fill).
"""

from __future__ import annotations

import math


def mean(values: list[float]) -> float:
    """Arithmetic mean.  Raises ValueError on an empty list."""
    if not values:
        raise ValueError("mean() of empty list")
    return sum(values) / len(values)


def stdev(values: list[float], ddof: int = 1) -> float:
    """Sample standard deviation (ddof=1 by default).

    Raises ValueError when fewer than ``ddof + 1`` observations are given.
    """
    n = len(values)
    if n - ddof <= 0:
        raise ValueError(f"stdev() needs > {ddof} observations, got {n}")
    m = mean(values)
    var = sum((v - m) ** 2 for v in values) / (n - ddof)
    return math.sqrt(var)


def moving_average(values: list[float | None], n: int) -> list[float | None]:
    """Trailing ``n``-period simple moving average.

    The window is *inclusive* of the current observation and contains only
    data at or before ``t`` — no look-ahead.  The first ``n - 1`` entries
    (and any window containing ``None``) are ``None``.
    """
    if n < 1:
        raise ValueError(f"window must be >= 1, got {n}")
    out: list[float | None] = []
    for i in range(len(values)):
        window = values[max(0, i - n + 1): i + 1]
        if len(window) < n or any(v is None for v in window):
            out.append(None)
        else:
            out.append(sum(window) / n)  # type: ignore[operator]
    return out


def rate_of_change(values: list[float | None], n: int) -> list[float | None]:
    """``n``-period rate of change in percent: ``(v_t / v_{t-n} - 1) * 100``.

    ``None`` for the first ``n`` entries, for ``None`` inputs, or when the
    base value is zero.
    """
    if n < 1:
        raise ValueError(f"window must be >= 1, got {n}")
    out: list[float | None] = []
    for i in range(len(values)):
        cur, base = values[i], values[i - n] if i >= n else None
        if cur is None or base is None or base == 0:
            out.append(None)
        else:
            out.append((cur / base - 1.0) * 100.0)
    return out


def rolling_zscore(
    values: list[float | None],
    lookback: int = 252,
    min_periods: int = 63,
) -> list[float | None]:
    """Trailing z-score: ``(v_t - mean) / stdev`` over a trailing window.

    The window holds up to ``lookback`` observations *ending at* ``t``
    (inclusive) — strictly data at or before ``t``, so there is no
    look-ahead.  Entries with fewer than ``min_periods`` valid observations,
    or a zero-variance window, yield ``None`` (the statistic abstains rather
    than inventing a value).
    """
    if lookback < 1 or min_periods < 1:
        raise ValueError("lookback and min_periods must be >= 1")
    if min_periods > lookback:
        raise ValueError("min_periods cannot exceed lookback")
    out: list[float | None] = []
    for i in range(len(values)):
        window = [v for v in values[max(0, i - lookback + 1): i + 1]
                  if v is not None]
        cur = values[i]
        if cur is None or len(window) < min_periods:
            out.append(None)
            continue
        try:
            sd = stdev(window)
        except ValueError:
            out.append(None)
            continue
        if sd == 0:
            out.append(None)
            continue
        out.append((cur - mean(window)) / sd)
    return out
