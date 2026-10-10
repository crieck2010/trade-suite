"""Screening: metric computation, criterion filtering, composite scoring.

The pipeline for one symbol is::

    bars + fundamentals --compute_metrics--> metrics dict
                       --apply_criteria--> pass/fail + per-check detail
                       --score----------> composite z-score (ranking)

Cross-sectional work (z-scores) is always done over the scanned set only —
never peeks outside it.
"""

from __future__ import annotations

from . import indicators as ind
from .models import (
    CRITERION_OPS,
    FUNDAMENTAL_METRICS,
    Criterion,
    ScoredRow,
    ScoreSpec,
    ScreenReport,
    ScreenRow,
)

__all__ = [
    "compute_metrics",
    "apply_criteria",
    "screen",
    "score",
    "zscores",
    "PRESETS",
    "preset_criteria",
]


def compute_metrics(bars: list[dict], fundamentals: dict | None = None) -> dict:
    """Compute every technical metric plus any supplied fundamentals.

    Missing data yields ``None`` for that metric (never raises).  ``fundamentals``
    is a plain ``{field: value}`` dict; only recognized
    :data:`~trade_screener.models.FUNDAMENTAL_METRICS` fields are copied in.
    """
    metrics: dict = {"bars": len(bars)}
    cl = ind.closes(bars)
    if cl:
        price = cl[-1]
        metrics["price"] = price
        for n in (20, 50, 200):
            metrics[f"sma_{n}"] = ind.sma(cl, n)
        metrics["ema_20"] = ind.ema(cl, 20)
        sma50, sma200 = metrics["sma_50"], metrics["sma_200"]
        metrics["price_vs_sma_50"] = price / sma50 - 1.0 if sma50 else None
        metrics["price_vs_sma_200"] = price / sma200 - 1.0 if sma200 else None
        for n, name in ((21, "mom_21"), (63, "mom_63"), (126, "mom_126"), (252, "mom_252")):
            metrics[name] = ind.momentum(cl, n)
        metrics["rsi_14"] = ind.rsi_wilder(bars, 14)
        metrics["vol_21"] = ind.realized_vol(cl, 21)
        metrics["vol_63"] = ind.realized_vol(cl, 63)
        atr = ind.atr_wilder(bars, 14) if all(b.get("high") is not None and b.get("low") is not None for b in bars) else None
        metrics["atr_14"] = atr
        metrics["atr_pct"] = atr / price if atr else None
        metrics["dollar_vol_21"] = ind.mean_dollar_volume(bars, 21)
        metrics["dist_52w_high"] = ind.distance_to_high(bars, 252)
        metrics["dist_52w_low"] = ind.distance_to_low(bars, 252)
        metrics["max_drawdown_252"] = ind.max_drawdown(cl, 252)
    if fundamentals:
        for name in FUNDAMENTAL_METRICS:
            if name in fundamentals and fundamentals[name] is not None:
                metrics[name] = float(fundamentals[name])
    return metrics


def _check_one(metrics: dict, criterion: Criterion) -> dict:
    observed = metrics.get(criterion.metric)
    check = {
        "criterion": criterion.describe(),
        "metric": criterion.metric,
        "observed": observed,
        "passed": False,
    }
    if observed is None:
        return check  # missing data never passes a filter
    op, value = criterion.op, criterion.value
    if op == "gte":
        ok = observed >= value
    elif op == "lte":
        ok = observed <= value
    elif op == "gt":
        ok = observed > value
    elif op == "lt":
        ok = observed < value
    elif op == "eq":
        ok = observed == value
    elif op == "between":
        lo, hi = value  # type: ignore[misc]
        ok = lo <= observed <= hi
    elif op == "outside":
        lo, hi = value  # type: ignore[misc]
        ok = observed < lo or observed > hi
    else:  # pragma: no cover - guarded by Criterion.__post_init__
        raise ValueError(f"unknown op {op!r}")
    check["passed"] = bool(ok)
    return check


def apply_criteria(metrics: dict, criteria: list[Criterion]) -> tuple[bool, list[dict]]:
    """Apply every criterion (AND semantics); returns (passed, checks)."""
    checks = [_check_one(metrics, c) for c in criteria]
    return all(c["passed"] for c in checks), checks


def screen(
    universe_data: dict[str, list[dict]],
    criteria: list[Criterion],
    fundamentals: dict[str, dict] | None = None,
    universe: str = "universe",
) -> ScreenReport:
    """Filter a universe through ``criteria``.

    ``universe_data`` maps ticker -> bars (each bar a dict with at least
    ``close``; ``high``/``low``/``volume`` unlock the liquidity/range
    metrics).  ``fundamentals`` maps ticker -> ``{field: value}``.
    """
    fundamentals = fundamentals or {}
    rows: list[ScreenRow] = []
    passed: list[str] = []
    for ticker in sorted(universe_data):
        metrics = compute_metrics(universe_data[ticker], fundamentals.get(ticker.upper()))
        ok, checks = apply_criteria(metrics, criteria)
        rows.append(ScreenRow(ticker=ticker, passed=ok, metrics=metrics,
                             checks=tuple(checks)))
        if ok:
            passed.append(ticker)
    return ScreenReport(universe=universe, criteria=tuple(criteria),
                       rows=tuple(rows), passed_tickers=tuple(passed))


def zscores(values: dict[str, float | None]) -> dict[str, float]:
    """Cross-sectional z-scores over the non-None values.

    Uses the population stdev; a zero-variance column yields 0.0 for every
    symbol; symbols with missing values are omitted.
    """
    present = {t: v for t, v in values.items() if v is not None}
    out = {t: 0.0 for t in present}
    if len(present) < 2:
        return out
    mean = sum(present.values()) / len(present)
    var = sum((v - mean) ** 2 for v in present.values()) / len(present)
    if var <= 0:
        return out
    sd = var ** 0.5
    return {t: (v - mean) / sd for t, v in present.items()}


def score(
    universe_data: dict[str, list[dict]],
    spec: ScoreSpec,
    fundamentals: dict[str, dict] | None = None,
) -> list[ScoredRow]:
    """Rank a universe by a weighted sum of cross-sectional z-scores.

    ``score = sum(weight[m] * zscore[m])``.  Rows are returned sorted by
    descending score (ties broken by ticker for determinism).
    """
    fundamentals = fundamentals or {}
    metrics = {t: compute_metrics(bars, fundamentals.get(t.upper()))
               for t, bars in universe_data.items()}
    zcols = {m: zscores({t: met.get(m) for t, met in metrics.items()})
             for m in spec.weights}
    ranked = []
    for ticker in sorted(metrics):
        zs = {m: zcols[m].get(ticker, 0.0) for m in spec.weights}
        total = sum(spec.weights[m] * zs[m] for m in spec.weights)
        ranked.append(ScoredRow(ticker=ticker, score=total, zscores=zs,
                               metrics=metrics[ticker]))
    ranked.sort(key=lambda r: (-r.score, r.ticker))
    return ranked


#: Named filter packs.  Each preset is a list of (metric, op, value) triples;
#: thresholds assume daily bars and plain-ratio metrics (e.g. dividend_yield
#: as a decimal).
PRESETS: dict[str, list[tuple]] = {
    "momentum": [
        ("mom_126", "gte", 0.10),
        ("price_vs_sma_50", "gte", 0.0),
        ("rsi_14", "between", (30.0, 80.0)),
        ("dollar_vol_21", "gte", 1_000_000.0),
    ],
    "value": [
        ("pe", "between", (0.0, 20.0)),
        ("pb", "lte", 3.0),
        ("dividend_yield", "gte", 0.015),
        ("price_vs_sma_200", "gte", -0.20),
    ],
    "quality": [
        ("roe", "gte", 0.15),
        ("eps_growth", "gte", 0.05),
        ("max_drawdown_252", "gte", -0.30),
        ("vol_63", "lte", 0.40),
    ],
    "low-vol": [
        ("vol_63", "lte", 0.20),
        ("beta", "lte", 1.0),
        ("max_drawdown_252", "gte", -0.25),
        ("dollar_vol_21", "gte", 1_000_000.0),
    ],
    "breakout": [
        ("dist_52w_high", "gte", -0.03),
        ("price_vs_sma_50", "gte", 0.02),
        ("rsi_14", "between", (50.0, 85.0)),
        ("dollar_vol_21", "gte", 2_000_000.0),
    ],
    "oversold-bounce": [
        ("rsi_14", "lte", 30.0),
        ("dist_52w_low", "lte", 0.15),
        ("price_vs_sma_200", "gte", -0.35),
    ],
}

#: Named composite-score packs (metric -> weight).
SCORE_PRESETS: dict[str, dict] = {
    "momentum-score": {"mom_126": 1.0, "mom_63": 0.5, "vol_63": -0.5, "rsi_14": 0.25},
    "value-score": {"pe": -1.0, "pb": -0.5, "dividend_yield": 0.75, "roe": 0.5},
    "quality-score": {"roe": 1.0, "eps_growth": 0.75, "vol_63": -0.5, "max_drawdown_252": 0.5},
}


def preset_criteria(name: str) -> list[Criterion]:
    """Build the :class:`Criterion` list for a named preset."""
    try:
        triples = PRESETS[name]
    except KeyError:
        raise ValueError(f"unknown preset {name!r}; choose from {sorted(PRESETS)}")
    return [Criterion(metric=m, op=o, value=v, label=f"{name}:{m}") for m, o, v in triples]


def preset_score_spec(name: str) -> ScoreSpec:
    """Build the :class:`ScoreSpec` for a named score preset."""
    try:
        weights = SCORE_PRESETS[name]
    except KeyError:
        raise ValueError(f"unknown score preset {name!r}; choose from {sorted(SCORE_PRESETS)}")
    return ScoreSpec(weights=dict(weights))
