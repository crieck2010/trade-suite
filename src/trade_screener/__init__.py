"""Multi-symbol equity screener for the trade-suite.

Filter a universe through technical / liquidity / fundamental criteria,
or rank it by a composite cross-sectional z-score.  Stdlib-only,
deterministic, plain-data in and out.
"""

from __future__ import annotations

__version__ = "0.1.0"

from . import demo, fundamentals, indicators, models, screen
from .adapters import (
    bars_from_trade_data,
    metrics_for_optimize,
    tickers_from_universe,
    to_agent_ideas,
    to_backtest_universe,
)
from .demo import demo_fundamentals, demo_universe
from .fundamentals import load_fundamentals_csv
from .models import (
    CRITERION_OPS,
    FUNDAMENTAL_METRICS,
    TECHNICAL_METRICS,
    Criterion,
    ScoredRow,
    ScoreSpec,
    ScreenReport,
    ScreenRow,
)
from .screen import (
    PRESETS,
    SCORE_PRESETS,
    apply_criteria,
    compute_metrics,
    preset_criteria,
    preset_score_spec,
    score,
    screen,
    zscores,
)

__all__ = [
    "CRITERION_OPS",
    "FUNDAMENTAL_METRICS",
    "PRESETS",
    "SCORE_PRESETS",
    "TECHNICAL_METRICS",
    "__version__",
    "Criterion",
    "ScoredRow",
    "ScoreSpec",
    "ScreenReport",
    "ScreenRow",
    "apply_criteria",
    "bars_from_trade_data",
    "compute_metrics",
    "demo",
    "demo_fundamentals",
    "demo_universe",
    "fundamentals",
    "indicators",
    "load_fundamentals_csv",
    "metrics_for_optimize",
    "models",
    "preset_criteria",
    "preset_score_spec",
    "score",
    "screen",
    "tickers_from_universe",
    "to_agent_ideas",
    "to_backtest_universe",
    "zscores",
]
