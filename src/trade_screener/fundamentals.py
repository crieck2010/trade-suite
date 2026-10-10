"""Fundamentals loading and helpers.  Plain CSV in, plain dicts out.

Expected CSV columns (all optional except ``ticker``)::

    ticker,pe,pb,ps,market_cap,dividend_yield,beta,eps_growth,roe,name

Ratios are decimals where it matters (``dividend_yield`` 0.02 = 2%,
``eps_growth`` 0.10 = +10%/yr, ``roe`` 0.18 = 18%).
"""

from __future__ import annotations

import csv
from pathlib import Path

from .models import FUNDAMENTAL_METRICS

__all__ = ["load_fundamentals_csv", "fundamentals_from_rows", "FUNDAMENTAL_COLUMNS"]


FUNDAMENTAL_COLUMNS = ("ticker",) + FUNDAMENTAL_METRICS + ("name",)


def _to_float(raw) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    raw = str(raw).strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def fundamentals_from_rows(rows: list[dict]) -> dict[str, dict]:
    """Normalize raw row dicts into ``{TICKER: {field: value}}``."""
    out: dict[str, dict] = {}
    for row in rows:
        ticker = (row.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        entry: dict = {}
        for name in FUNDAMENTAL_METRICS:
            value = _to_float(row.get(name))
            if value is not None:
                entry[name] = value
        name = (row.get("name") or "").strip()
        if name:
            entry["name"] = name
        if ticker in out:
            out[ticker].update(entry)
        else:
            out[ticker] = entry
    return out


def load_fundamentals_csv(path: str | Path) -> dict[str, dict]:
    """Load a fundamentals CSV into ``{TICKER: {field: value}}``."""
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return fundamentals_from_rows(rows)
