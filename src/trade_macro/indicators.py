"""Indicator registry — the extension slot.

Indicator #1 is ``copper_gold``.  Indicator #2+ (credit spreads, yield-curve
slope, …) slots in by calling :func:`register_indicator` — no changes to
``regime.py`` or ``snapshot.py`` are needed.

Registry entry interface::

    {
        "name": "copper_gold",            # registry key, snake_case
        "description": "…",               # one-line human description
        "required_series": ["copper", "gold"],  # keys of the series map
        "compute": callable,             # (series_map, preset) -> result
        "version": 1,                    # entry schema version
    }

``compute(series_map, preset="standard")`` receives
``{"copper": [...], "gold": [...]}`` (each a validated price series) and
must return ``{"panel": [...], "alerts": [...], "latest": {...}}`` where
``panel`` rows carry at least ``date`` and ``regime`` (see
:mod:`trade_macro.regime` for the generic classifier future indicators
should reuse).
"""

from __future__ import annotations

from .ratio import enrich_ratios, ratio_series
from .regime import classify_regime, detect_transitions

REQUIRED_SPEC_KEYS = ("name", "description", "required_series", "compute", "version")


def _copper_gold_compute(series_map: dict, preset: str = "standard") -> dict:
    missing = [k for k in ("copper", "gold") if k not in series_map]
    if missing:
        raise ValueError(f"copper_gold needs series {missing}")
    rows = enrich_ratios(ratio_series(series_map["copper"], series_map["gold"]))
    rows = classify_regime(rows, preset=preset)
    alerts = detect_transitions(rows, preset=preset)
    return {"panel": rows, "alerts": alerts, "latest": rows[-1] if rows else None}


INDICATORS: dict[str, dict] = {
    "copper_gold": {
        "name": "copper_gold",
        "description": (
            "Copper:gold ratio macro regime — the market's growth-expectations "
            "proxy. Rising ratio = pricing expansion; falling = contraction."
        ),
        "required_series": ["copper", "gold"],
        "compute": _copper_gold_compute,
        "version": 1,
    },
}


def list_indicators() -> list[str]:
    """Registered indicator names, sorted."""
    return sorted(INDICATORS)


def get_indicator(name: str) -> dict:
    """Return the registry spec for ``name`` (ValueError if unknown)."""
    if name not in INDICATORS:
        raise ValueError(
            f"unknown indicator {name!r}; registered: {list_indicators()}")
    return INDICATORS[name]


def register_indicator(name: str, spec: dict) -> None:
    """Register a new indicator.  Raises ValueError on duplicates or a spec
    missing any of ``name``/``description``/``required_series``/
    ``compute``/``version``."""
    if name in INDICATORS:
        raise ValueError(f"indicator {name!r} is already registered")
    missing = [k for k in REQUIRED_SPEC_KEYS if k not in spec]
    if missing:
        raise ValueError(f"indicator spec missing keys: {missing}")
    if not callable(spec["compute"]):
        raise ValueError("indicator spec 'compute' must be callable")
    INDICATORS[name] = dict(spec)
