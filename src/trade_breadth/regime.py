"""Composite breadth regime classification and the fragility gauge.

Regime is a *description* of participation: BROADENING (the average stock
is healthy and keeping up), NARROWING (a shrinking set of names carries
the market), or NEUTRAL.  Fragility is a 0-1 gauge of how dangerous a
narrow market is: narrowing participation *times* index concentration.
"""

from __future__ import annotations

from ._stats import clamp01, trailing_zscore

BROADENING = "BROADENING"
NARROWING = "NARROWING"
NEUTRAL = "NEUTRAL"

PRESETS = {
    # score thresholds are in z-score units of the composite
    "standard": {"up": 0.5, "down": -0.5, "z_lookback": 252, "min_history": 63},
    "strict": {"up": 1.0, "down": -1.0, "z_lookback": 252, "min_history": 63},
    "loose": {"up": 0.25, "down": -0.25, "z_lookback": 252, "min_history": 63},
}

# fragility = W_NARROW * narrowness + W_CONC * concentration (documented weights)
W_NARROW = 0.6
W_CONC = 0.4


def concentration(weights: dict[str, float] | None) -> float | None:
    """Normalized Herfindahl index of index weights, in [0, 1].

    H = sum(w^2) normalized: (H - 1/N) / (1 - 1/N), so 0 = perfectly
    equal-weighted and 1 = a single name.  Returns None when no weights
    are supplied — concentration is then unknown, never invented.
    """
    if not weights:
        return None
    total = sum(weights.values())
    if total <= 0:
        return None
    w = [v / total for v in weights.values() if v > 0]
    n = len(w)
    if n < 2:
        return 1.0
    h = sum(x * x for x in w)
    return clamp01((h - 1.0 / n) / (1.0 - 1.0 / n))


def top_n_share(weights: dict[str, float] | None, n: int = 10) -> float | None:
    """Share of total weight held by the top-n names (None without weights)."""
    if not weights:
        return None
    total = sum(weights.values())
    if total <= 0:
        return None
    ranked = sorted((v / total for v in weights.values() if v > 0), reverse=True)
    return sum(ranked[:n])


def fragility(
    pct_above_50dma: float | None,
    weights: dict[str, float] | None,
) -> float | None:
    """Fragility gauge in [0, 1]: narrowing participation x concentration.

    narrowness = clamp01((50 - pct_above_50dma) / 50): 0 when at least half
    the market sits above its 50-day MA, 1 when nothing does.
    fragility = 0.6 * narrowness + 0.4 * concentration.  Without weights,
    concentration is unknown and fragility falls back to narrowness alone
    (documented: this *understates* concentration risk — supply weights
    for the real read).
    """
    if pct_above_50dma is None:
        return None
    narrowness = clamp01((50.0 - pct_above_50dma) / 50.0)
    conc = concentration(weights)
    if conc is None:
        return narrowness
    return clamp01(W_NARROW * narrowness + W_CONC * conc)


def classify_regime(
    panel: list[dict],
    weights: dict[str, float] | None = None,
    preset: str = "standard",
) -> list[dict]:
    """Classify each day of a breadth panel.

    Composite score = mean of trailing z-scores of three components:

    - ``ew_cw_ratio_vs_63dma`` — is the average stock beating the mega-caps?
    - ``pct_above_50dma`` — how broad is participation right now?
    - ``mcclellan_summation`` — the accumulated momentum of breadth itself.

    Each z is trailing-only (no lookahead), 252-day lookback, 63-day minimum
    history; a component with no computable z abstains (it is excluded from
    the mean, never zero-filled).  Score > ``up`` -> BROADENING,
    < ``down`` -> NARROWING, else NEUTRAL.  Days without enough history for
    any component score None -> NEUTRAL (documented, not invented).
    """
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}; choose from {sorted(PRESETS)}")
    cfg = PRESETS[preset]
    n = len(panel)
    z_ewcw = trailing_zscore(
        [r.get("ew_cw_ratio_vs_63dma") for r in panel],
        lookback=cfg["z_lookback"], min_history=cfg["min_history"])
    z_pct = trailing_zscore(
        [r.get("pct_above_50dma") for r in panel],
        lookback=cfg["z_lookback"], min_history=cfg["min_history"])
    z_mcc = trailing_zscore(
        [r.get("mcclellan_summation") for r in panel],
        lookback=cfg["z_lookback"], min_history=cfg["min_history"])

    out: list[dict] = []
    for i, row in enumerate(panel):
        zs = [z for z in (z_ewcw[i], z_pct[i], z_mcc[i]) if z is not None]
        score = sum(zs) / len(zs) if zs else None
        if score is None:
            regime = NEUTRAL
        elif score > cfg["up"]:
            regime = BROADENING
        elif score < cfg["down"]:
            regime = NARROWING
        else:
            regime = NEUTRAL
        out.append({
            "date": row["date"],
            "regime": regime,
            "regime_score": score,
            "fragility": fragility(row.get("pct_above_50dma"), weights),
            "components": {
                "z_ew_cw_trend": z_ewcw[i],
                "z_pct_above_50dma": z_pct[i],
                "z_mcclellan_summation": z_mcc[i],
            },
            "preset": preset,
        })
    return out
