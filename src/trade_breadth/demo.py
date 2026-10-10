"""Seeded end-to-end demo: the planted regime arc, detected."""

from __future__ import annotations

from .breadth import breadth_panel
from .regime import classify_regime
from .snapshot import snapshot
from .thrusts import detect_narrowing_warnings, detect_thrusts
from .universe import demo_universe


def run_demo(seed: int = 7) -> dict:
    """Run the full pipeline on the seeded demo universe.

    Returns a plain-data summary: panel tail, thrusts, warnings, the
    snapshot for the final date, and regime counts per phase of the
    planted arc (broadening -> narrowing -> fragile).
    """
    universe, caps = demo_universe(seed=seed)
    panel = breadth_panel(universe, weights=caps)
    regimes = classify_regime(panel, weights=caps)
    thrusts = detect_thrusts(panel)
    warnings = detect_narrowing_warnings(panel)
    snap = snapshot(universe, weights=caps)

    def counts(lo: int, hi: int) -> dict[str, int]:
        c: dict[str, int] = {}
        for r in regimes[lo:hi]:
            c[r["regime"]] = c.get(r["regime"], 0) + 1
        return c

    return {
        "seed": seed,
        "n_symbols": len(universe),
        "n_days": len(panel),
        "date_range": (panel[0]["date"], panel[-1]["date"]),
        "regime_counts_snapback_phase": counts(105, 160),  # planted V-recovery
        "regime_counts_narrow_phase": counts(320, 440),    # planted narrowing
        "regime_counts_fragile_phase": counts(480, 590),   # planted fragile
        "n_thrusts": len(thrusts),
        "thrusts": thrusts[:5],
        "n_narrowing_warnings": len(warnings),
        "final_snapshot": snap,
        "final_fragility": snap["fragility"],
    }
