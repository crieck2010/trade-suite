"""Core data types for trade-screener.

Everything is plain data: bars are dicts (``open/high/low/close/volume``
plus ``date``), fundamentals are ``ticker -> {field: value}`` dicts, and
every public function returns JSON-serializable structures.  No third-party
dependencies, no I/O at import time.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Metric names produced by compute_metrics (documented in METHODOLOGY.md).
TECHNICAL_METRICS = (
    "price",
    "sma_20",
    "sma_50",
    "sma_200",
    "ema_20",
    "price_vs_sma_50",   # price / sma_50 - 1
    "price_vs_sma_200",  # price / sma_200 - 1
    "mom_21",            # 1-month total return
    "mom_63",            # 3-month total return
    "mom_126",           # 6-month total return
    "mom_252",           # 12-month total return
    "rsi_14",            # Wilder RSI(14)
    "vol_21",            # annualized realized vol, 21d
    "vol_63",            # annualized realized vol, 63d
    "atr_14",            # Wilder ATR(14)
    "atr_pct",           # atr_14 / price
    "dollar_vol_21",     # mean(close * volume), 21d
    "dist_52w_high",     # close / max(high, 252) - 1  (<= 0)
    "dist_52w_low",      # close / min(low, 252) - 1   (>= 0)
    "max_drawdown_252",  # worst peak-to-trough, 252d (<= 0)
    "bars",              # number of bars used
)

FUNDAMENTAL_METRICS = (
    "pe",
    "pb",
    "ps",
    "market_cap",
    "dividend_yield",
    "beta",
    "eps_growth",
    "roe",
)

#: Ops a Criterion can use.
CRITERION_OPS = ("gte", "lte", "gt", "lt", "eq", "between", "outside")


@dataclass(frozen=True)
class Criterion:
    """One filter predicate: ``metric OP value`` (or a range for between/outside).

    ``metric`` is any name from :data:`TECHNICAL_METRICS` or
    :data:`FUNDAMENTAL_METRICS` (or a caller-supplied custom metric present in
    the metrics dict).  ``value`` is a number for the comparison ops, or a
    ``(lo, hi)`` tuple for ``between``/``outside``.
    """

    metric: str
    op: str
    value: float | tuple[float, float]
    label: str = ""

    def __post_init__(self) -> None:
        if self.op not in CRITERION_OPS:
            raise ValueError(f"unknown criterion op {self.op!r}; expected one of {CRITERION_OPS}")
        if self.op in ("between", "outside"):
            lo, hi = self.value  # type: ignore[misc]
            if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo <= hi):
                raise ValueError("between/outside need a (lo, hi) tuple with lo <= hi")

    def describe(self) -> str:
        name = self.label or self.metric
        if self.op == "between":
            lo, hi = self.value  # type: ignore[misc]
            return f"{name} in [{lo}, {hi}]"
        if self.op == "outside":
            lo, hi = self.value  # type: ignore[misc]
            return f"{name} outside [{lo}, {hi}]"
        sym = {"gte": ">=", "lte": "<=", "gt": ">", "lt": "<", "eq": "=="}[self.op]
        return f"{name} {sym} {self.value}"


@dataclass(frozen=True)
class ScreenRow:
    """One symbol's screening outcome."""

    ticker: str
    passed: bool
    metrics: dict
    checks: tuple = ()  # each: {"criterion": str, "metric": str, "observed": float|None, "passed": bool}

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "passed": self.passed,
            "metrics": dict(self.metrics),
            "checks": [dict(c) for c in self.checks],
        }


@dataclass(frozen=True)
class ScreenReport:
    """Full result of :func:`trade_screener.screen.screen`."""

    universe: str
    criteria: tuple
    rows: tuple  # ScreenRow
    passed_tickers: tuple

    def to_dict(self) -> dict:
        return {
            "universe": self.universe,
            "criteria": [c.describe() for c in self.criteria],
            "n_scanned": len(self.rows),
            "n_passed": len(self.passed_tickers),
            "passed_tickers": list(self.passed_tickers),
            "rows": [r.to_dict() for r in self.rows],
        }


@dataclass(frozen=True)
class ScoredRow:
    """One symbol's composite-score ranking outcome."""

    ticker: str
    score: float
    zscores: dict  # metric -> cross-sectional z-score
    metrics: dict

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "score": self.score,
            "zscores": dict(self.zscores),
            "metrics": dict(self.metrics),
        }


@dataclass
class ScoreSpec:
    """Composite-score definition: ``weights`` maps metric -> weight.

    Positive weight rewards high metric values; negative weight rewards low
    ones (e.g. ``{"mom_126": 1.0, "vol_63": -0.5}`` favors momentum and
    penalizes volatility).  Weights are used as given (no normalization),
    so keep them comparable in magnitude.
    """

    weights: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.weights:
            raise ValueError("ScoreSpec needs at least one metric weight")
        for metric, weight in self.weights.items():
            if not isinstance(weight, (int, float)):
                raise ValueError(f"weight for {metric!r} must be numeric")
