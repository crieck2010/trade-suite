"""Seeded demo universes: trend (should PASS), chop (should FAIL), crash.

Deterministic via ``random.Random(seed)``. Business days from 2023-01-02.
These bars are illustrative — a PASS here proves the validation loop
works, NOT that the strategy makes money (see docs/VALIDATION.md).

Baskets:
- "trend": TREND_A, TREND_B, CRASH_A — persistent drift plus one crash.
  The trend system should ride the drift and dodge most of the crash,
  beating buy-and-hold net of costs.
- "chop": CHOP_A, CHOP_B — range-bound sine + noise. The trend system
  whipsaws; the gates should FAIL (or WARN) it.
- "all": everything.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta


def _business_days(start: date, n: int) -> list[str]:
    out: list[str] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _randn(rng: random.Random) -> float:
    """Box-Muller standard normal from a seeded RNG."""
    u1 = max(rng.random(), 1e-12)
    u2 = rng.random()
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def _ohlc(dates: list[str], closes: list[float], rng: random.Random,
          wiggle: float = 0.0015, base_volume: int = 1_000_000) -> list[dict]:
    bars = []
    prev = closes[0]
    for d, c in zip(dates, closes):
        o = prev
        hi = max(o, c) * (1.0 + wiggle * abs(_randn(rng)))
        lo = min(o, c) * (1.0 - wiggle * abs(_randn(rng)))
        bars.append({
            "date": d, "open": o, "high": hi, "low": lo, "close": c,
            "volume": int(base_volume * (1.0 + 0.5 * abs(_randn(rng)))),
        })
        prev = c
    return bars


def _trendy(n: int, drift: float, vol: float, start: float,
            rng: random.Random,
            corrections: list[tuple[int, int, float]] | None = None
            ) -> list[float]:
    """GBM with injected corrections: (start_idx, days, log_total_drop).

    Corrections are the left-tail events buy-and-hold eats in full and a
    trailing stop mostly dodges — the economic rationale for trend
    following, planted on purpose so the demo exercises the benchmark
    gate honestly.
    """
    corrections = corrections or []
    closes = [start]
    for t in range(1, n):
        r = drift + vol * _randn(rng)
        for (s, d, l) in corrections:
            if s <= t < s + d:
                r = l / d + 0.02 * _randn(rng)
                break
        closes.append(closes[-1] * math.exp(r))
    return closes


def demo_bars(seed: int = 7, n_days: int = 750) -> dict[str, list[dict]]:
    """Full demo universe: 2 trend + 2 chop + 1 crash symbol."""
    rng = random.Random(seed)
    dates = _business_days(date(2023, 1, 2), n_days)
    out: dict[str, list[dict]] = {}

    # persistent drifters
    out["TREND_A"] = _ohlc(dates, _trendy(n_days, 0.0016, 0.011, 100.0, rng,
                                        [(200, 15, math.log(0.75)), (520, 12, math.log(0.82))]), rng)
    out["TREND_B"] = _ohlc(dates, _trendy(n_days, 0.0014, 0.012, 80.0, rng,
                                        [(330, 15, math.log(0.75)), (610, 12, math.log(0.82))]), rng)

    # range-bound whipsaws: sine + noise around a flat level
    for name, level, amp, period in (("CHOP_A", 100.0, 7.0, 55),
                                     ("CHOP_B", 60.0, 5.0, 70)):
        closes = []
        for t in range(n_days):
            wave = amp * math.sin(2.0 * math.pi * t / period)
            closes.append(level + wave + _randn(rng) * level * 0.008)
        out[name] = _ohlc(dates, closes, rng)

    # drift, then a -60% crash over 30 days, partial recovery, then a
    # second -35% crash: the left-tail regime where trend-following earns
    # its keep versus buy-and-hold.
    closes = _trendy(400, 0.0016, 0.011, 100.0, rng)
    crash_ret = math.log(0.35) / 30
    for _ in range(30):
        closes.append(closes[-1] * math.exp(crash_ret + 0.02 * _randn(rng)))
    closes.extend(_trendy(150, 0.0012, 0.011, closes[-1], rng))
    crash_ret2 = math.log(0.65) / 20
    for _ in range(20):
        closes.append(closes[-1] * math.exp(crash_ret2 + 0.02 * _randn(rng)))
    closes.extend(_trendy(n_days - 600, 0.0008, 0.012, closes[-1], rng))
    out["CRASH_A"] = _ohlc(dates, closes, rng)

    return out


BASKETS = {
    "trend": ["TREND_A", "TREND_B", "CRASH_A"],
    "chop": ["CHOP_A", "CHOP_B"],
    "all": ["TREND_A", "TREND_B", "CHOP_A", "CHOP_B", "CRASH_A"],
}


def demo_benchmark(bars_by_symbol: dict[str, list[dict]],
                   symbols: list[str]) -> list[float]:
    """Equal-weight buy-and-hold daily returns for a basket (the benchmark
    the beats_benchmark_net gate compares against, net of costs)."""
    series = []
    for s in symbols:
        closes = [b["close"] for b in bars_by_symbol[s]]
        series.append([closes[i] / closes[i - 1] - 1.0
                       for i in range(1, len(closes))])
    n = min(len(x) for x in series)
    return [sum(x[i] for x in series) / len(series) for i in range(n)]


def run_demo(seed: int = 7):
    """End-to-end demo: backtest + validate the trend and chop baskets.

    Returns ``{"trend": report, "chop": report}``. The pipeline is
    working iff trend PASSES and chop FAILs (or WARNs).
    """
    from .backtest import run_backtest
    from .report import build_report
    from .strategy import SwingConfig
    from .validate import run_validation

    bars = demo_bars(seed=seed)
    out = {}
    for basket in ("trend", "chop"):
        symbols = BASKETS[basket]
        sub = {s: bars[s] for s in symbols}
        provenance = {
            "source": "demo", "basket": basket, "symbols": symbols,
            "n_bars": len(next(iter(sub.values()))),
            "delay": "n/a (synthetic)",
            "seed": seed,
            "note": "Seeded synthetic bars: proves the pipeline, not the strategy.",
        }
        bt = run_backtest(sub, config=SwingConfig(), provenance=provenance)
        bench = demo_benchmark(sub, symbols)
        # benchmark returns align to equity-curve returns (both per-bar)
        val = run_validation(bt, benchmark_returns=bench)
        out[basket] = build_report(bt, val, provenance)
    return out
