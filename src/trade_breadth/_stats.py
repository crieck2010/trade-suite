"""Small statistical helpers (stdlib only). Shared by the breadth engine."""

from __future__ import annotations

from statistics import mean, pstdev


def clamp01(x: float) -> float:
    """Clamp a float into [0, 1]."""
    return max(0.0, min(1.0, x))


def ema(values: list[float], n: int) -> list[float]:
    """Exponential moving average, seeded with the first value.

    alpha = 2 / (n + 1). Seeding with the first observation (rather than an
    SMA of the first n) keeps the series defined from day one; the seed's
    influence decays geometrically, so long histories are unaffected.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    if not values:
        return []
    alpha = 2.0 / (n + 1)
    out = [float(values[0])]
    for v in values[1:]:
        out.append(alpha * float(v) + (1.0 - alpha) * out[-1])
    return out


def sma(values: list[float], n: int) -> list[float | None]:
    """Simple moving average; None where fewer than n values are available."""
    if n < 1:
        raise ValueError("n must be >= 1")
    out: list[float | None] = []
    running = 0.0
    for i, v in enumerate(values):
        running += float(v)
        if i >= n:
            running -= float(values[i - n])
        out.append(running / n if i + 1 >= n else None)
    return out


def trailing_zscore(
    values: list[float | None],
    lookback: int = 252,
    min_history: int = 63,
) -> list[float | None]:
    """Trailing z-score of each point vs the *prior* `lookback` values.

    The current point is excluded from its own reference window (no lookahead).
    Returns None where fewer than `min_history` prior observations exist, and
    None where the window has zero variance — a z-score against a constant
    is undefined, so the component abstains rather than invent a number.
    """
    out: list[float | None] = []
    for i, x in enumerate(values):
        if x is None:
            out.append(None)
            continue
        window = [v for v in values[max(0, i - lookback):i] if v is not None]
        if len(window) < min_history:
            out.append(None)
            continue
        mu = mean(window)
        sd = pstdev(window)
        out.append(None if sd == 0 else (x - mu) / sd)
    return out
