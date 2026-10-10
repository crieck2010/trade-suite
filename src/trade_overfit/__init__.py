"""trade-overfit: the overfitting desk — strategy validation that kills fake alpha.

Pure-Python, stdlib-only engine. Plain data in/out (lists of floats, dicts).
Research/backtesting/paper-trading only — never live trading.
"""

from __future__ import annotations

from .adapters import (
    gate_research_idea,
    promotion_payload,
    returns_from_backtest,
)
from .demo import demo_noise_strategies, demo_selection_bias, demo_true_edge
from .dsr import deflated_sharpe_ratio, expected_sharpe_under_null, psr
from .gates import DEFAULT_GATES, PRESETS, Gate, evaluate_gates, validate
from .metrics import (
    calmar_ratio,
    cost_haircut,
    max_drawdown,
    performance_summary,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    win_rate,
)
from .regimes import regime_report, vol_regime_labels
from .walkforward import walk_forward

__version__ = "0.2.0"

__all__ = [
    "__version__",
    "calmar_ratio",
    "cost_haircut",
    "deflated_sharpe_ratio",
    "demo_noise_strategies",
    "demo_selection_bias",
    "demo_true_edge",
    "evaluate_gates",
    "expected_sharpe_under_null",
    "gate_research_idea",
    "max_drawdown",
    "performance_summary",
    "promotion_payload",
    "profit_factor",
    "psr",
    "regime_report",
    "returns_from_backtest",
    "sharpe_ratio",
    "sortino_ratio",
    "validate",
    "vol_regime_labels",
    "walk_forward",
    "DEFAULT_GATES",
    "PRESETS",
    "Gate",
]
