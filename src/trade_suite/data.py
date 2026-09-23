"""Market-data access for suite workflows.

Delegates to the dashboard engines' ``DataService`` (demo + delayed
equities), preferring the web dashboard's engine and falling back to the
desktop's — the same services both UIs use, so scripted workflows and the
dashboards always agree.
"""

from __future__ import annotations


def _data_service():
    """Return a dashboard ``DataService`` instance (lazy import)."""
    for package in ("trade_dashboard_web", "trade_dashboard_desktop"):
        try:
            mod = __import__(f"{package}.engine", fromlist=["DataService"])
        except ImportError:
            continue
        return mod.DataService()
    raise RuntimeError(
        "no dashboard package installed; install one of:\n"
        "  pip install git+https://github.com/crieck2010/trade-dashboard-web.git\n"
        "  pip install git+https://github.com/crieck2010/trade-dashboard-desktop.git"
    )


def sources() -> list[dict]:
    """Available data sources with availability flags."""
    return _data_service().sources()


def get_bars(symbol: str, source: str = "demo", days: int = 250) -> list[dict]:
    """Fetch ``days`` of daily bars as plain dicts (OHLCV + timestamp)."""
    return _data_service().get_bars(symbol, source=source, days=days)


def get_bars_many(symbols: list[str], source: str = "demo",
                  days: int = 250) -> dict[str, list[dict]]:
    """Fetch bars for several symbols; keys are upper-cased symbols."""
    service = _data_service()
    out = {}
    for symbol in symbols:
        key = (symbol or "").strip().upper()
        if key:
            out[key] = service.get_bars(key, source=source, days=days)
    if not out:
        raise ValueError("at least one symbol is required")
    return out
