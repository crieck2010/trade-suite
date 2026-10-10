"""Seeded demo universe: a two-factor model with known correlation blocks.

Eight assets in two blocks of four.  Assets in the same block share a
strong common factor (within-block correlation ~0.6); the two factors are
weakly correlated (~0.15), so cross-block correlation is low (~0.1).
Every run with the same seed produces the same bars, so demos, docs, and
tests are reproducible.

This is synthetic data for demos and tests — not market data.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta


def _gauss(rng: random.Random) -> float:
    # Box-Muller, avoids caching issues of random.gauss across versions.
    u1 = max(rng.random(), 1e-12)
    u2 = rng.random()
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def demo_universe(
    n_days: int = 500,
    seed: int = 7,
    start: str = "2024-01-02",
) -> dict[str, list[float]]:
    """``{symbol: [daily closes]}`` with a known two-block structure."""
    rng = random.Random(seed)
    names = [f"BLK1_{i}" for i in range(1, 5)] + \
            [f"BLK2_{i}" for i in range(1, 5)]
    # Factor loadings: block 1 loads on factor A, block 2 on factor B.
    load_a = [0.75, 0.70, 0.80, 0.65]
    load_b = [0.72, 0.78, 0.68, 0.74]
    factor_corr = 0.15
    vols = [0.012, 0.015, 0.011, 0.018, 0.013, 0.016, 0.012, 0.017]
    closes: dict[str, list[float]] = {s: [100.0 + 5.0 * i]
                                      for i, s in enumerate(names)}
    day0 = date.fromisoformat(start)
    d = day0
    while d.weekday() >= 5:  # start on a weekday
        d += timedelta(days=1)
    for _ in range(n_days):
        fa = _gauss(rng)
        fb = factor_corr * fa + math.sqrt(1 - factor_corr ** 2) * _gauss(rng)
        for i, s in enumerate(names):
            load = load_a[i] if i < 4 else load_b[i - 4]
            f = fa if i < 4 else fb
            idio = _gauss(rng) * math.sqrt(max(1 - load ** 2, 1e-6))
            r = vols[i] * (load * f + idio)
            closes[s].append(closes[s][-1] * math.exp(r))
        d += timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
    return closes


def demo_bars(
    n_days: int = 500,
    seed: int = 7,
    start: str = "2024-01-02",
) -> dict[str, list[dict]]:
    """Demo universe as OHLCV bars (dicts) for engine/dashboard input."""
    rng = random.Random(seed + 1_000)
    closes = demo_universe(n_days=n_days, seed=seed, start=start)
    day0 = date.fromisoformat(start)
    d = day0
    while d.weekday() >= 5:
        d += timedelta(days=1)
    out: dict[str, list[dict]] = {}
    for s, cs in closes.items():
        bars = []
        dd = d
        prev = cs[0]
        for c in cs[1:]:
            drift = (c - prev) / prev
            o = prev * (1 + _gauss(rng) * 0.002)
            h = max(o, c) * (1 + abs(_gauss(rng)) * 0.003)
            l = min(o, c) * (1 - abs(_gauss(rng)) * 0.003)
            bars.append({
                "symbol": s,
                "timestamp": dd.isoformat() + "T00:00:00+00:00",
                "open": round(o, 4), "high": round(h, 4),
                "low": round(l, 4), "close": round(c, 4),
                "volume": int(1_000_000 * (1 + abs(drift) * 50)
                              * (0.7 + 0.6 * rng.random())),
            })
            prev = c
            dd += timedelta(days=1)
            while dd.weekday() >= 5:
                dd += timedelta(days=1)
        out[s] = bars
    return out
