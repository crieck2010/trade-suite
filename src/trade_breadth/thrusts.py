"""Breadth-thrust event detection and narrowing/exhaustion warnings.

A thrust is a *regime-change* signal: participation snaps from washed-out
to broad in a handful of sessions.  Warnings flag the opposite —
an index making highs while participation diverges.  Both are context,
not predictions; see METHODOLOGY.md.
"""

from __future__ import annotations


def detect_thrusts(
    panel: list[dict],
    low: float = 40.0,
    high: float = 60.0,
    window: int = 10,
) -> list[dict]:
    """Zweig-style breadth thrusts on % of stocks above the 50-day MA.

    An event fires on the first day ``t`` where ``pct_t > high`` while some
    day in ``[t - window, t)`` printed below ``low``.  While participation
    stays above ``high`` no new event fires (one event per episode).
    ``magnitude`` = ``pct_t - min(pct over the window)``.
    """
    events: list[dict] = []
    in_episode = False
    for i, row in enumerate(panel):
        pct = row.get("pct_above_50dma")
        if pct is None:
            in_episode = False
            continue
        if pct > high:
            if not in_episode:
                lookback = [r.get("pct_above_50dma") for r in panel[max(0, i - window):i]]
                lookback = [v for v in lookback if v is not None]
                if lookback and min(lookback) < low:
                    events.append({
                        "date": row["date"],
                        "type": "breadth_thrust",
                        "pct_above_50dma": pct,
                        "window_min": min(lookback),
                        "magnitude": pct - min(lookback),
                        "window": window,
                    })
            in_episode = True
        elif pct <= high:
            in_episode = False
    return events


def detect_narrowing_warnings(
    panel: list[dict],
    lookback: int = 63,
) -> list[dict]:
    """Flag days where the cap-weight index makes a new high on weak breadth.

    Warning condition on day ``t``: ``cw_index`` at a ``lookback``-day high
    while ``pct_above_50dma`` is *below its own* ``lookback``-day median —
    the classic "fewer and fewer names carrying the market" divergence.
    Documented as a warning, not a prediction.
    """
    warnings: list[dict] = []
    for i, row in enumerate(panel):
        cw = row.get("cw_index")
        pct = row.get("pct_above_50dma")
        if cw is None or pct is None or i < lookback:
            continue
        hist_cw = [r.get("cw_index") for r in panel[i - lookback:i]]
        hist_pct = [r.get("pct_above_50dma") for r in panel[i - lookback:i]]
        if any(v is None for v in hist_cw) or any(v is None for v in hist_pct):
            continue
        if cw >= max(hist_cw):
            med = sorted(hist_pct)[len(hist_pct) // 2]
            if pct < med:
                warnings.append({
                    "date": row["date"],
                    "type": "narrowing_divergence",
                    "cw_index": cw,
                    "pct_above_50dma": pct,
                    "pct_63d_median": med,
                    "detail": (
                        f"cap-weight index at {lookback}d high ({cw:.1f}) while "
                        f"only {pct:.1f}% of stocks sit above their 50-day MA "
                        f"(63d median {med:.1f}%)"
                    ),
                })
    return warnings
