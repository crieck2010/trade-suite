"""Lazy sibling adapters — import cleanly with no siblings installed.

Data-source adapters (``series_from_*``) take an optional ``fetch``
callable so callers are never coupled to a sibling's client API; when
``fetch`` is omitted we attempt a best-effort wiring of the sibling's
default provider and raise a clear RuntimeError if that fails.

Consumer adapters (``market_context_provider``, ``risk_regime_input``,
``factor_series_input``, ``hedge_tilt_input``) are pure functions of plain
data — they work with zero siblings present.
"""

from __future__ import annotations

import importlib
from datetime import date as _date

from .series import validate_series
from .snapshot import snapshot


def _optional_import(name: str):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def _to_series_dicts(dates, prices) -> list[dict]:
    return [{"date": str(d), "price": float(p)} for d, p in zip(dates, prices)]


def _futures_fetch(mod, root: str, start, end) -> list[dict]:
    """Best-effort: continuous front-month daily closes via yfinance provider."""
    provider = mod.providers.yfinance.YFinanceFuturesProvider()
    client = mod.client.FuturesDataClient(provider)
    contracts = client.get_contracts(root, n=12)
    series = []
    for c in contracts:
        bars = client.get_bars(c, mod.models.Timeframe.DAILY, start, end)
        series.append(mod.continuous.ContractSeries(contract=c, bars=bars))
    cont = mod.continuous.build_continuous(series, roll="volume", adjust="ratio")
    out = []
    for b in cont:
        ts = b.timestamp.date() if hasattr(b.timestamp, "date") else b.timestamp
        if start is not None and ts < start:
            continue
        if end is not None and ts >= end:
            continue
        out.append({"date": ts.isoformat(), "price": float(b.close)})
    return out


def series_from_trade_data_futures(
    copper_root: str = "HG",
    gold_root: str = "GC",
    start: _date | None = None,
    end: _date | None = None,
    fetch=None,
) -> dict:
    """Fetch copper/gold continuous-contract series via trade-data-futures.

    ``fetch(root, start, end)`` may be supplied to bypass the sibling's
    client API entirely.  Without it we lazy-import trade-data-futures and
    build volume-rolled, ratio-adjusted continuous daily closes; a clear
    RuntimeError is raised if the sibling is missing or the wiring fails.
    """
    if fetch is None:
        mod = _optional_import("trade_data_futures")
        if mod is None:
            raise RuntimeError(
                "trade_data_futures is not installed: "
                "`pip install trade-data-futures` or pass fetch=..."
            )
        try:
            fetch = lambda root, s, e: _futures_fetch(mod, root, s, e)  # noqa: E731
        except Exception as exc:
            raise RuntimeError(
                f"could not auto-wire trade_data_futures ({exc}); pass fetch=..."
            ) from exc
    copper = validate_series(fetch(copper_root, start, end), "copper")
    gold = validate_series(fetch(gold_root, start, end), "gold")
    return {"copper": copper, "gold": gold}


def series_from_trade_data_equities(
    copper_etf: str = "CPER",
    gold_etf: str = "GLD",
    start: _date | None = None,
    end: _date | None = None,
    fetch=None,
) -> dict:
    """Fetch copper/gold ETF-proxy series via trade-data-equities.

    Same ``fetch(symbol, start, end)`` contract as above; raises a clear
    RuntimeError when the sibling is missing and no fetch is supplied.
    """
    if fetch is None:
        mod = _optional_import("trade_data_equities")
        if mod is None:
            raise RuntimeError(
                "trade_data_equities is not installed: "
                "`pip install trade-data-equities` or pass fetch=..."
            )

        def _eq_fetch(symbol, s, e):
            provider = mod.YFinanceProvider()
            client = mod.EquitiesDataClient(provider)
            bars = client.get_bars(symbol, mod.Timeframe.DAILY, s, e)
            return _to_series_dicts(
                [b.timestamp.date().isoformat() for b in bars],
                [b.close for b in bars],
            )

        fetch = _eq_fetch
    copper = validate_series(fetch(copper_etf, start, end), "copper")
    gold = validate_series(fetch(gold_etf, start, end), "gold")
    return {"copper": copper, "gold": gold}


def market_context_provider(
    copper: list[dict],
    gold: list[dict],
    preset: str = "standard",
    source: str = "futures",
) -> dict:
    """Snapshot shaped for trade-agents' ``market_context`` merge."""
    return {"macro": snapshot(copper, gold, preset=preset, source=source)}


def risk_regime_input(snap: dict) -> dict:
    """Regime digest for trade-risk's regime-conditional limits."""
    regime = snap.get("regime")
    return {
        "regime": regime,
        "contraction": regime == "CONTRACTION",
        "expansion": regime == "EXPANSION",
        "defensive": regime in ("CONTRACTION",),
        "z_score": snap.get("z_score"),
        "date": snap.get("date"),
    }


def factor_series_input(copper: list[dict], gold: list[dict]) -> list[dict]:
    """Ratio time series for trade-factors' macro-factor regressions."""
    from .ratio import ratio_series
    return [
        {"date": r["date"], "copper_gold_ratio": r["ratio"]}
        for r in ratio_series(copper, gold)
    ]


def hedge_tilt_input(snap: dict) -> dict:
    """Defensive-tilt signal for trade-hedge: -1 contraction, 0 neutral,
    +1 expansion."""
    regime = snap.get("regime")
    tilt = {"CONTRACTION": -1, "NEUTRAL": 0, "EXPANSION": 1}.get(regime, 0)
    return {
        "tilt": tilt,
        "regime": regime,
        "date": snap.get("date"),
        "reason": f"copper:gold regime is {regime}",
    }


def flow_context_input(
    series: list[dict],
    as_of=None,
    blackout_ranges=None,
) -> dict:
    """Flow-context digest for trade-agents' ``market_context`` merge.

    Pure function of plain data (the repo-standard ``[{"date", "price"}]``
    series, e.g. SPY daily closes).  Returns ``{"flow_context": {...}}``
    with the buyback-blackout and forced-selling reads from
    :mod:`trade_macro.flow_context` — regime *context* (the "when"), not a
    strategy signal.  The graded-conviction decision layer consumes it
    alongside the copper:gold regime.
    """
    from .flow_context import flow_context
    return {"flow_context": flow_context(series, as_of=as_of,
                                         blackout_ranges=blackout_ranges
                                         ).to_dict()}
