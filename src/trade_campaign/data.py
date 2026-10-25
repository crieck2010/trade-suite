"""Daily-close fetching for campaigns.

Two sources:

- ``yfinance`` — real delayed daily closes via trade-data-equities
  (the standing free data source).  Lazy import; needs the ``live``
  extra.  This is what a real campaign runs on.
- ``demo`` — the dashboard's deterministic synthetic bars (crc32-seeded).
  Plumbing tests and offline proofs only; a demo-fed campaign would be
  measuring synthetic data, and the digest says so.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def fetch_closes(symbols, days: int, source: str = "yfinance"
                 ) -> dict[str, list[tuple[date, float]]]:
    """``{symbol: [(date, close), ...]}`` ascending by date."""
    if source == "demo":
        return _demo_closes(symbols, days)
    if source == "yfinance":
        return _yfinance_closes(symbols, days)
    raise ValueError(f"unknown bars source {source!r}")


def _demo_closes(symbols, days: int) -> dict[str, list[tuple[date, float]]]:
    from trade_dashboard_web.engine.data_service import synth_bars

    out: dict[str, list[tuple[date, float]]] = {}
    for sym in symbols:
        bars = synth_bars(sym, n=min(max(days, 60), 750))
        out[sym] = [
            (datetime.fromisoformat(b["timestamp"]).date(),
             float(b["close"]))
            for b in bars
        ]
    return out


def _yfinance_closes(symbols, days: int) -> dict[str, list[tuple[date, float]]]:
    try:
        from trade_data_equities import EquitiesDataClient, Timeframe
        from trade_data_equities.providers.yfinance import YFinanceProvider
    except ImportError as exc:
        raise RuntimeError(
            "the yfinance source needs the trade-data-equities package "
            "with yfinance (pip install -e \".[live]\")"
        ) from exc
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=max(30, days))
    client = EquitiesDataClient(YFinanceProvider())
    out: dict[str, list[tuple[date, float]]] = {}
    for sym in symbols:
        bars = client.get_bars(sym, Timeframe.DAILY, start, end)
        series = [(b.timestamp.date(), float(b.close)) for b in bars]
        if len(series) < 30:
            raise RuntimeError(
                f"only {len(series)} daily bars for {sym}; need >= 30 "
                "(and >= 260 for the strategy warmup)")
        out[sym] = series
    return out
