"""Seeded synthetic price paths with known volatility regimes.

``demo_bars`` builds OHLC bars from a GARCH(1,1) return process with a
mid-sample volatility-regime shift, so every estimator and model in
this package has something real to chew on: clustering, a structural
break, and intraday range information.  Same seed → same bars, always.
"""

from __future__ import annotations

import math

from .garch import simulate_garch
from .rng import RandomStream


def _sim(n: int, burn: int = 250, **kw) -> list[float]:
    """Simulate with a burn-in so the sample starts near stationarity."""
    return simulate_garch(n + burn, **kw)[burn:]


def demo_bars(n: int = 750, seed: int = 14, start_price: float = 100.0) -> list[dict]:
    """OHLC bars from a two-regime GARCH process (regime shifts at n/2)."""
    if n < 60:
        raise ValueError("need at least 60 bars")
    half = n // 2
    # calm regime → stressed regime (unconditional variance ~2.5x).
    # default seed 14: both halves simulate near their population
    # moments, so the break reads clearly (chosen, then fixed).
    r1 = _sim(half, omega=0.00002, alpha=0.08, beta=0.90, seed=seed)
    r2 = _sim(n - half, omega=0.000125, alpha=0.10, beta=0.85, seed=seed + 1)
    returns = r1 + r2
    rs = RandomStream(seed + 2)
    bars = []
    price = start_price
    for r in returns:
        o = price
        c = o * math.exp(r)
        # intraday range scaled to the day's move + noise
        span = abs(r) + 0.004 * (0.5 + rs.uniform())
        h = max(o, c) * (1.0 + span * rs.uniform())
        l = min(o, c) * (1.0 - span * rs.uniform())
        bars.append({"open": o, "high": h, "low": l, "close": c})
        price = c
    return bars
