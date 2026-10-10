"""Tick -> OHLCV bar resampling and running VWAP.

Bucketing math (derived in ``docs/METHODOLOGY.md``)::

    bucket = floor(ts / timeframe_s) * timeframe_s

Trades are grouped by ``(symbol, bucket)``; within a bucket, ordered by
timestamp:

- open  = price of the first trade
- high  = max price
- low   = min price
- close = price of the last trade
- volume = sum of sizes (0.0 when sizes are missing)
- vwap  = sum(price * size) / sum(size), None when volume is 0
- n_trades = trade count

Session handling is deliberately dumb and documented: buckets are pure
clock time (UTC epoch). There is no session calendar, no holiday logic,
no "regular trading hours" filtering — overnight buckets simply come out
empty and are omitted. If you need session-aware bars, filter the input
trades first; the resampler never invents timestamps.

Bars are canonical ``kind: "bar"`` messages (``price`` = close,
``size`` = volume) so they flow through the bus, recorder, and replay
exactly like ticks.
"""

from __future__ import annotations

import math

from .normalizer import SCHEMA_VERSION


def resample(trades: list[dict], timeframe_s: int, source: str = "resample") -> list[dict]:
    """Resample canonical trade messages into OHLCV bars, oldest first."""
    if timeframe_s <= 0:
        raise ValueError("timeframe_s must be positive")
    buckets: dict[tuple[str, int], list[dict]] = {}
    for t in trades:
        if not isinstance(t, dict) or t.get("kind") != "trade":
            continue
        ts = t.get("ts")
        price = t.get("price")
        if not isinstance(ts, (int, float)) or not isinstance(price, (int, float)):
            continue
        if not math.isfinite(ts) or not math.isfinite(price):
            continue
        bucket = math.floor(ts / timeframe_s) * timeframe_s
        buckets.setdefault((str(t.get("symbol", "UNKNOWN")), bucket), []).append(t)
    bars = []
    for (symbol, open_ts), ts_ in sorted(buckets.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        ordered = sorted(ts_, key=lambda m: m["ts"])
        prices = [m["price"] for m in ordered]
        sizes = [m["size"] if isinstance(m.get("size"), (int, float)) and math.isfinite(m["size"]) else 0.0
                 for m in ordered]
        volume = sum(sizes)
        pv = sum(p * s for p, s in zip(prices, sizes))
        bars.append({
            "kind": "bar",
            "symbol": symbol,
            "timeframe_s": timeframe_s,
            "open_ts": open_ts,
            "open": prices[0],
            "high": max(prices),
            "low": min(prices),
            "close": prices[-1],
            "price": prices[-1],
            "volume": volume,
            "size": volume,
            "vwap": (pv / volume) if volume > 0 else None,
            "n_trades": len(ordered),
            "ts": float(open_ts),
            "bid": None,
            "ask": None,
            "source": source,
            "schema_version": SCHEMA_VERSION,
        })
    return bars


class VWAPTracker:
    """Running volume-weighted average price for one symbol."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._pv = 0.0
        self._v = 0.0
        self.n = 0

    def update(self, price: float, size: float | None = None) -> float | None:
        """Add a trade; return the current VWAP (None until volume > 0)."""
        s = float(size) if isinstance(size, (int, float)) and math.isfinite(size) else 0.0
        p = float(price)
        if not math.isfinite(p):
            return self.vwap
        self._pv += p * s
        self._v += s
        self.n += 1
        return self.vwap

    @property
    def vwap(self) -> float | None:
        return (self._pv / self._v) if self._v > 0 else None

    @property
    def volume(self) -> float:
        return self._v
