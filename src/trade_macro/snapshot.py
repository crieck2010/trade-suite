"""The ``snapshot()`` interop contract.

This is the single stable object the rest of the suite consumes:

- **trade-agents** merges it into ``market_context`` on every idea/debate
  (macro regime conditions idea generation and the risk desk)
- **trade-risk** reads ``regime`` for regime-conditional limits
- **trade-factors** can use the ratio series as a macro factor
- **trade-hedge** reads ``regime == "CONTRACTION"`` as a defensive-tilt input

Schema is versioned (``schema_version``); v1 is documented in
``docs/ARCHITECTURE.md``.  The dict is JSON-serializable by construction
(missing values are ``None``, never NaN).
"""

from __future__ import annotations

from .indicators import get_indicator
from .regime import PRESETS

SCHEMA_VERSION = 1

INDICATOR = "copper_gold"


def _compute(copper: list[dict], gold: list[dict], preset: str) -> dict:
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}; choose from {sorted(PRESETS)}")
    spec = get_indicator(INDICATOR)
    return spec["compute"]({"copper": copper, "gold": gold}, preset=preset)


def snapshot(
    copper: list[dict],
    gold: list[dict],
    date: str | None = None,
    preset: str = "standard",
    source: str = "futures",
) -> dict:
    """Build the dated, JSON-serializable macro regime snapshot.

    ``date`` selects a historical snapshot (default: the last panel date).
    Raises ValueError for an unknown date or preset.  ``source`` records
    where the legs came from (``"futures"`` / ``"etf"`` / ``"synthetic"``…);
    it is provenance metadata, not a code path.
    """
    data = _compute(copper, gold, preset)
    panel = data["panel"]
    if not panel:
        raise ValueError("no overlapping copper/gold dates")
    alerts = {a["date"]: a for a in data["alerts"]}
    if date is None:
        row = panel[-1]
    else:
        matches = [r for r in panel if r["date"] == date]
        if not matches:
            raise ValueError(
                f"date {date!r} not in panel ({panel[0]['date']}..{panel[-1]['date']})")
        row = matches[0]
    ma200 = row.get("ratio_ma200")
    ratio = row.get("ratio")
    return {
        "schema_version": SCHEMA_VERSION,
        "indicator": INDICATOR,
        "source": source,
        "preset": preset,
        "date": row["date"],
        "regime": row["regime"],
        "z_score": row.get("z_252"),
        "ratio": ratio,
        "ratio_vs_200dma": (ratio / ma200 - 1.0)
        if ratio is not None and ma200 else None,
        "roc_21d": row.get("roc_21"),
        "transition_alert": row["date"] in alerts,
        "transition": alerts.get(row["date"]),
    }


def snapshot_history(
    copper: list[dict],
    gold: list[dict],
    preset: str = "standard",
    source: str = "futures",
    limit: int | None = None,
) -> dict:
    """Per-date regime history (ascending), optionally truncated to the
    last ``limit`` rows."""
    data = _compute(copper, gold, preset)
    history = [
        {"date": r["date"], "regime": r["regime"],
         "z_score": r.get("z_252"), "ratio": r.get("ratio")}
        for r in data["panel"]
    ]
    if limit is not None:
        history = history[-limit:]
    return {
        "schema_version": SCHEMA_VERSION,
        "indicator": INDICATOR,
        "source": source,
        "preset": preset,
        "history": history,
    }
