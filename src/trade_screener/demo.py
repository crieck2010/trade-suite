"""Deterministic synthetic universe for demos, tests, and offline work.

Generates ``n`` tickers with seeded regime archetypes so every demo is
reproducible: steady uptrend, downtrend, mean-reverting, high-volatility
churn, and flat drift.  Bars are plain dicts (date/open/high/low/close/
volume) matching the suite's bar contract.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

from .fundamentals import fundamentals_from_rows

__all__ = ["demo_universe", "demo_fundamentals", "ARCHETYPES"]

ARCHETYPES = ("uptrend", "downtrend", "mean-revert", "high-vol", "flat")


def _gen_bars(rng: random.Random, archetype: str, days: int, start: date, start_price: float) -> list[dict]:
    params = {
        "uptrend": (0.0009, 0.012),
        "downtrend": (-0.0009, 0.013),
        "mean-revert": (0.0, 0.018),
        "high-vol": (0.0002, 0.035),
        "flat": (0.0001, 0.006),
    }[archetype]
    drift, vol = params
    bars: list[dict] = []
    price = start_price
    anchor = start_price  # mean-reversion anchor
    for i in range(days):
        shock = rng.gauss(0.0, vol)
        if archetype == "mean-revert":
            shock += -0.06 * (price / anchor - 1.0)
        ret = drift + shock
        open_ = price
        close = price * math.exp(ret)
        high = max(open_, close) * (1.0 + abs(rng.gauss(0, vol * 0.3)))
        low = min(open_, close) * (1.0 - abs(rng.gauss(0, vol * 0.3)))
        volume = int(rng.lognormvariate(math.log(2_000_000), 0.6))
        bars.append({
            "date": (start + timedelta(days=i)).isoformat(),
            "open": round(open_, 4),
            "high": round(high, 4),
            "low": round(low, 4),
            "close": round(close, 4),
            "volume": volume,
        })
        price = close
    return bars


def demo_universe(n: int = 12, days: int = 300, seed: int = 7) -> dict[str, list[dict]]:
    """Build a seeded synthetic universe: ``{TICKER: [bars]}``.

    Tickers are ``DEMO01..`` and archetypes cycle in order, so the first five
    tickers are always uptrend / downtrend / mean-revert / high-vol / flat.
    """
    rng = random.Random(seed)
    start = date(2025, 1, 2)
    out: dict[str, list[dict]] = {}
    for i in range(n):
        ticker = f"DEMO{i + 1:02d}"
        archetype = ARCHETYPES[i % len(ARCHETYPES)]
        start_price = 20.0 + 15.0 * ((i * 37) % 11)
        out[ticker] = _gen_bars(rng, archetype, days, start, start_price)
    return out


def demo_fundamentals(tickers: list[str], seed: int = 7) -> dict[str, dict]:
    """Seeded synthetic fundamentals aligned with the demo archetypes."""
    rng = random.Random(seed + 1)
    profiles = {
        "uptrend": {"pe": 28.0, "pb": 4.5, "dividend_yield": 0.008, "beta": 1.15, "eps_growth": 0.18, "roe": 0.22},
        "downtrend": {"pe": 9.0, "pb": 0.8, "dividend_yield": 0.045, "beta": 1.3, "eps_growth": -0.12, "roe": 0.04},
        "mean-revert": {"pe": 16.0, "pb": 1.9, "dividend_yield": 0.022, "beta": 0.95, "eps_growth": 0.06, "roe": 0.13},
        "high-vol": {"pe": 45.0, "pb": 7.0, "dividend_yield": 0.0, "beta": 1.8, "eps_growth": 0.30, "roe": 0.10},
        "flat": {"pe": 14.0, "pb": 1.2, "dividend_yield": 0.035, "beta": 0.6, "eps_growth": 0.02, "roe": 0.11},
    }
    rows = []
    for i, ticker in enumerate(tickers):
        archetype = ARCHETYPES[i % len(ARCHETYPES)]
        base = profiles[archetype]
        row = {"ticker": ticker}
        for k, v in base.items():
            jitter = 1.0 + rng.uniform(-0.15, 0.15)
            row[k] = round(v * jitter, 4) if k != "dividend_yield" else round(max(0.0, v * jitter), 4)
        row["market_cap"] = int(rng.uniform(1e9, 5e11))
        row["ps"] = round(base["pe"] * rng.uniform(0.15, 0.35), 2)
        rows.append(row)
    return fundamentals_from_rows(rows)
