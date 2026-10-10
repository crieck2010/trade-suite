"""Market-data access for the dashboard.

Sources:
  ``demo``     -- deterministic synthetic bars (always available, offline).
  ``equities`` -- real delayed data via the ``trade-data-equities`` engine
                  (lazy import; needs that package + ``yfinance`` installed).

Bars are normalized to plain dicts so the JSON API never leaks engine types.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone


def bar_to_dict(bar) -> dict:
    """Normalize a dict-like or engine ``Bar`` to a JSON-safe dict."""
    if isinstance(bar, dict):
        ts = bar.get("timestamp")
        return {
            "symbol": bar.get("symbol", ""),
            "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            "open": float(bar.get("open", 0.0)),
            "high": float(bar.get("high", 0.0)),
            "low": float(bar.get("low", 0.0)),
            "close": float(bar.get("close", 0.0)),
            "volume": float(bar.get("volume", 0.0)),
        }
    ts = getattr(bar, "timestamp", None)
    return {
        "symbol": getattr(bar, "symbol", "") or "",
        "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
        "open": float(bar.open),
        "high": float(bar.high),
        "low": float(bar.low),
        "close": float(bar.close),
        "volume": float(getattr(bar, "volume", 0.0) or 0.0),
    }


def synth_bars(symbol: str, n: int = 250, start: float = 100.0, seed: int = 7) -> list[dict]:
    """Deterministic demo bars with three regimes (up / chop / down)."""
    rng = random.Random(seed + abs(hash(symbol)) % 997)
    bars, price = [], start
    t = datetime(2024, 1, 2, tzinfo=timezone.utc)
    for i in range(n):
        drift = 0.003 if i < n * 0.4 else (-0.001 if i < n * 0.7 else -0.003)
        o = price
        c = o * (1 + drift + rng.uniform(-0.02, 0.02))
        bars.append(
            {
                "symbol": symbol,
                "timestamp": t.isoformat(),
                "open": o,
                "high": max(o, c) * 1.005,
                "low": min(o, c) * 0.995,
                "close": c,
                "volume": 2_000_000.0,
            }
        )
        price, t = c, t + timedelta(days=1)
    return bars


class DataService:
    """Fetch bars from the configured sources."""

    SOURCES = ("demo", "equities")

    def sources(self) -> list[dict]:
        out = [{"id": "demo", "label": "Demo (synthetic, offline)", "available": True}]
        try:
            import trade_data_equities  # noqa: F401

            available, note = True, "Delayed data via trade-data-equities (yfinance)"
        except ImportError:
            available, note = False, "Install trade-data-equities for real data"
        out.append({"id": "equities", "label": "Equities (delayed)", "available": available, "note": note})
        return out

    def get_bars(
        self, symbol: str, source: str = "demo", days: int = 365
    ) -> list[dict]:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            raise ValueError("symbol is required")
        if source == "demo":
            return synth_bars(symbol, n=max(60, min(days, 750)))
        if source == "equities":
            return self._equities_bars(symbol, days)
        raise ValueError(f"unknown source {source!r}; choose from demo, equities")

    def _equities_bars(self, symbol: str, days: int) -> list[dict]:
        try:
            from trade_data_equities import EquitiesDataClient, Timeframe
            from trade_data_equities.providers.yfinance import YFinanceProvider
        except ImportError as exc:
            raise RuntimeError(
                "the equities source needs the trade-data-equities package "
                "(and yfinance) installed"
            ) from exc
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=max(30, days))
        client = EquitiesDataClient(YFinanceProvider())
        bars = client.get_bars(symbol, Timeframe.DAILY, start, end, use_cache=True)
        out = [bar_to_dict(b) for b in bars]
        for b in out:
            b["symbol"] = symbol
        if not out:
            raise RuntimeError(f"no bars returned for {symbol}")
        return out
