"""trade-macro: copper:gold macro regime engine.

Expansion / contraction / neutral classification from the copper:gold
ratio — the market's growth-expectations proxy — with transition alerts,
a stable snapshot() interop contract, and an indicator registry so future
macro indicators slot in without touching existing code.

Pure-Python, stdlib-only engine. Plain data in/out (dicts, lists of floats).
Research/backtesting/paper-trading only — never live trading.
"""

from __future__ import annotations

from .adapters import (
    factor_series_input,
    flow_context_input,
    hedge_tilt_input,
    market_context_provider,
    risk_regime_input,
    series_from_trade_data_equities,
    series_from_trade_data_futures,
    weather_input,
)
from .demo import demo_series, run_demo
from .flow_context import (
    BuybackContext,
    FlowContext,
    ForcedSellingContext,
    buyback_blackout,
    flow_context,
    forced_selling_risk,
)
from .indicators import (
    INDICATORS,
    get_indicator,
    list_indicators,
    register_indicator,
)
from .ratio import enrich_ratios, ratio_series
from .regime import (
    CONTRACTION,
    EXPANSION,
    NEUTRAL,
    PRESETS,
    REGIMES,
    classify_regime,
    detect_transitions,
)
from .series import SOURCE_NOTES, align_series, validate_series
from .skip_days import (
    SkipCalendar,
    SkipDay,
    default_skip_calendar,
    is_skip_day,
)
from .snapshot import SCHEMA_VERSION, snapshot, snapshot_history
from .weather import WEATHER_RULES, WeatherReport, trading_weather

__version__ = "0.2.0"

__all__ = [
    "__version__",
    "SCHEMA_VERSION",
    "WEATHER_RULES",
    "BuybackContext",
    "CONTRACTION",
    "EXPANSION",
    "FlowContext",
    "ForcedSellingContext",
    "INDICATORS",
    "NEUTRAL",
    "PRESETS",
    "REGIMES",
    "SOURCE_NOTES",
    "SkipCalendar",
    "SkipDay",
    "WeatherReport",
    "align_series",
    "buyback_blackout",
    "classify_regime",
    "default_skip_calendar",
    "demo_series",
    "detect_transitions",
    "enrich_ratios",
    "factor_series_input",
    "flow_context",
    "flow_context_input",
    "forced_selling_risk",
    "get_indicator",
    "hedge_tilt_input",
    "is_skip_day",
    "list_indicators",
    "market_context_provider",
    "ratio_series",
    "register_indicator",
    "risk_regime_input",
    "run_demo",
    "series_from_trade_data_equities",
    "series_from_trade_data_futures",
    "snapshot",
    "snapshot_history",
    "trading_weather",
    "validate_series",
    "weather_input",
]
