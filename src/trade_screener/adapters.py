"""Lazy adapters to sibling trade-suite engines.

Every adapter imports its sibling inside the function body, so
``import trade_screener`` never requires another suite package.  A missing
sibling raises a clear ``RuntimeError`` naming the package to install.
"""

from __future__ import annotations

from .models import ScoreSpec, ScreenReport

__all__ = [
    "bars_from_trade_data",
    "tickers_from_universe",
    "to_backtest_universe",
    "to_agent_ideas",
    "metrics_for_optimize",
]


def _need(package: str):
    try:
        return __import__(package)
    except ImportError as exc:
        raise RuntimeError(
            f"this adapter needs the '{package}' package "
            f"(pip install git+https://github.com/crieck2010/{package.replace('_', '-')}.git)"
        ) from exc


def bars_from_trade_data(tickers: list[str], source: str = "demo", days: int = 300) -> dict[str, list[dict]]:
    """Fetch ``{TICKER: [bars]}`` via trade-data-equities (preferred) or the
    trade-suite data service (fallback).  Bars keep the suite's plain-dict
    OHLCV contract."""
    clean = [t.strip().upper() for t in tickers if t and t.strip()]
    if not clean:
        raise ValueError("at least one ticker is required")
    try:
        tde = _need("trade_data_equities")
        fetch = tde.get_bars_many if hasattr(tde, "get_bars_many") else None
    except RuntimeError:
        fetch = None
    if fetch is None:
        suite = _need("trade_suite")
        return suite.data.get_bars_many(clean, source=source, days=days)
    return {t.upper(): fetch(t, source=source, days=days) for t in clean}


def tickers_from_universe(name_or_path: str) -> tuple[str, list[str]]:
    """Load tickers from a trade-data-equities ``Universe`` CSV file.

    Returns ``(universe_name, tickers)``.  Falls back to a plain text file
    (one ticker per line) when trade-data-equities is not installed.
    """
    import csv
    from pathlib import Path

    path = Path(name_or_path)
    if not path.exists():
        raise FileNotFoundError(f"universe file not found: {name_or_path}")
    try:
        tde = _need("trade_data_equities")
        universe = tde.Universe.from_csv(path.stem, path)
        return universe.name, universe.tickers
    except RuntimeError:
        tickers: list[str] = []
        with open(path, newline="", encoding="utf-8") as fh:
            first = fh.read(1024)
            fh.seek(0)
            if "ticker" in first.splitlines()[0].lower():
                for row in csv.DictReader(fh):
                    if row.get("ticker"):
                        tickers.append(row["ticker"].strip().upper())
            else:
                tickers = [line.strip().upper() for line in fh if line.strip()]
        return path.stem, tickers


def to_backtest_universe(report: ScreenReport) -> dict:
    """Shape a screen result as a trade-backtest universe payload."""
    return {
        "universe": report.universe,
        "tickers": list(report.passed_tickers),
        "n_scanned": len(report.rows),
        "n_passed": len(report.passed_tickers),
        "criteria": [c.describe() for c in report.criteria],
    }


def to_agent_ideas(report: ScreenReport, scored: list | None = None) -> list[dict]:
    """Shape screen (+ optional score) output as trade-agents research ideas.

    Each idea is a plain dict with a thesis string the desk agents can quote.
    """
    ideas: list[dict] = []
    rank = {r.ticker: i + 1 for i, r in enumerate(scored)} if scored else {}
    for row in report.rows:
        if not row.passed:
            continue
        metrics = row.metrics
        thesis_bits = []
        mom = metrics.get("mom_126")
        if mom is not None:
            thesis_bits.append(f"6m momentum {mom:+.1%}")
        rsi = metrics.get("rsi_14")
        if rsi is not None:
            thesis_bits.append(f"RSI(14) {rsi:.0f}")
        dv = metrics.get("dollar_vol_21")
        if dv is not None:
            thesis_bits.append(f"21d dollar volume ${dv:,.0f}")
        ideas.append({
            "ticker": row.ticker,
            "kind": "screen_pass",
            "universe": report.universe,
            "rank": rank.get(row.ticker),
            "thesis": "; ".join(thesis_bits) or "passed all screen criteria",
            "metrics": {k: v for k, v in metrics.items() if v is not None},
        })
    ideas.sort(key=lambda d: (d["rank"] is None, d["rank"] or 0, d["ticker"]))
    return ideas


def metrics_for_optimize(rows: list, metrics: tuple[str, ...] = ("vol_63", "mom_126")) -> dict:
    """Pull per-ticker metrics into the ``{ticker: {metric: value}}`` shape
    trade-optimize's covariance / expected-return builders accept."""
    out: dict = {}
    for row in rows:
        entry = {m: row.metrics.get(m) for m in metrics if row.metrics.get(m) is not None}
        if entry:
            out[row.ticker] = entry
    return out
