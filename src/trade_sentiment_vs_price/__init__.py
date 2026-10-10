"""Does sentiment lead, lag, or mirror price?  Small tools, plain data.

Built on the "many small indicators" methodology: each module is one
small, honest measurement (correlation, event study, IC, rule evaluation).
Combine their outputs downstream — in agents, backtests, or factor models —
to drive trading ideas.  Stdlib-only, deterministic.
"""

from __future__ import annotations

__version__ = "0.1.0"

from . import correlation, events, indicators, ols_lite, predict, series, signals, stats
from .adapters import (
    from_sentiment_scan,
    prices_from_dict_bars,
    sentiment_mimicking_returns,
    to_agent_report,
    to_backtest_signals,
)
from .correlation import contemporaneous, lead_lag, rolling_correlation
from .events import detect_bursts, event_study
from .indicators import (
    attention_zscore,
    composite_attention,
    divergence,
    rolling_ic_stability,
    sentiment_momentum,
    sentiment_zscore,
)
from .predict import forward_regression, information_coefficient, sign_accuracy
from .series import AlignedSeries, PriceBar, SentimentPoint, align, demo_data
from .signals import attention_rule, summarize_trades, zscore_rule

__all__ = [
    "AlignedSeries",
    "PriceBar",
    "SentimentPoint",
    "align",
    "attention_rule",
    "attention_zscore",
    "composite_attention",
    "contemporaneous",
    "correlation",
    "demo_data",
    "detect_bursts",
    "divergence",
    "event_study",
    "events",
    "forward_regression",
    "from_sentiment_scan",
    "indicators",
    "information_coefficient",
    "lead_lag",
    "ols_lite",
    "predict",
    "prices_from_dict_bars",
    "rolling_correlation",
    "rolling_ic_stability",
    "sentiment_mimicking_returns",
    "sentiment_momentum",
    "sentiment_zscore",
    "series",
    "sign_accuracy",
    "signals",
    "stats",
    "summarize_trades",
    "to_agent_report",
    "to_backtest_signals",
    "zscore_rule",
    "__version__",
]
