"""Price-spike alerts: |move| over a trailing window exceeds a threshold.

The rule is intentionally simple and fully specified::

    ref   = oldest trade price still inside [now - window_s, now]
    move  = (price_now - ref) / ref
    alert when |move| >= threshold

After firing, the detector rearms on the *post-spike* window (the window
is cleared) so one spike produces one alert instead of a staccato of
repeats while the elevated price sits inside the window.

Alerts are canonical-ish event dicts (not bus ``kind`` messages — they
are *derived* events)::

    {"kind": "alert", "alert": "price_spike", "symbol": ...,
     "move_pct": ..., "window_s": ..., "threshold": ...,
     "ref_price": ..., "price": ..., "ts": ..., "source": ...,
     "schema_version": 1}

These are what :mod:`trade_stream.adapters` forwards to ``trade-hedge``
(defensive tilt) and ``trade-risk`` (limit review): a spike is context
for risk, not a trade signal.
"""

from __future__ import annotations

import collections
import math

from .normalizer import SCHEMA_VERSION


class SpikeDetector:
    """Trailing-window spike detector for one symbol."""

    def __init__(self, window_s: float = 300.0, threshold: float = 0.05) -> None:
        if window_s <= 0:
            raise ValueError("window_s must be positive")
        if threshold <= 0:
            raise ValueError("threshold must be positive")
        self.window_s = window_s
        self.threshold = threshold
        self._trades: collections.deque[tuple[float, float]] = collections.deque()
        self.fired = 0

    def update(self, ts: float, price: float, symbol: str = "",
               source: str = "") -> dict | None:
        """Feed a trade; return an alert dict when the rule fires, else None."""
        if not (isinstance(ts, (int, float)) and isinstance(price, (int, float))):
            return None
        if not (math.isfinite(ts) and math.isfinite(price)) or price <= 0:
            return None
        cutoff = ts - self.window_s
        while self._trades and self._trades[0][0] < cutoff:
            self._trades.popleft()
        self._trades.append((ts, price))
        if len(self._trades) < 2:
            return None
        ref = self._trades[0][1]
        if ref <= 0:
            return None
        move = (price - ref) / ref
        if abs(move) >= self.threshold:
            self.fired += 1
            alert = {
                "kind": "alert",
                "alert": "price_spike",
                "symbol": symbol,
                "move_pct": move * 100.0,
                "window_s": self.window_s,
                "threshold": self.threshold,
                "ref_price": ref,
                "price": price,
                "ts": float(ts),
                "source": source,
                "schema_version": SCHEMA_VERSION,
            }
            self._trades.clear()  # rearm on the post-spike window
            return alert
        return None


class MultiSpikeDetector:
    """One :class:`SpikeDetector` per symbol, created on first sight."""

    def __init__(self, window_s: float = 300.0, threshold: float = 0.05) -> None:
        self.window_s = window_s
        self.threshold = threshold
        self._detectors: dict[str, SpikeDetector] = {}

    def update(self, msg: dict) -> dict | None:
        if not isinstance(msg, dict) or msg.get("kind") != "trade":
            return None
        symbol = str(msg.get("symbol", ""))
        det = self._detectors.get(symbol)
        if det is None:
            det = SpikeDetector(self.window_s, self.threshold)
            self._detectors[symbol] = det
        return det.update(msg.get("ts"), msg.get("price"),
                          symbol=symbol, source=str(msg.get("source", "")))

    @property
    def symbols(self) -> list[str]:
        return sorted(self._detectors)
