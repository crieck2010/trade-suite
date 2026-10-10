"""A comprehensive, dependency-free library of trading strategies.

Strategies are pure decision logic: bars in, signals out. They never
import ``trade-backtest``; see :mod:`trade_strategies.adapters` for the
lazy bridge that runs them in the backtester. Agents enumerate the
library through :mod:`trade_strategies.registry`.
"""

from .adapters import run_backtest, to_backtest_strategy
from .base import (
    Signal,
    SignalAction,
    SingleAssetStrategy,
    Strategy,
    closes,
    field,
    highs,
    lows,
    volumes,
)
from .mean_reversion import (
    BollingerReversion,
    RSI2MeanReversion,
    StochasticReversion,
    ZScoreReversion,
)
from .meta import EnsembleVote, RegimeFilter, TrailingStop
from .momentum import (
    BollingerSqueezeBreakout,
    KeltnerBreakout,
    OBVTrend,
    TimeSeriesMomentum,
    VWAPDeviation,
)
from .multi_asset import CrossSectionalMomentum, PairsTrading
from .registry import (
    STRATEGY_REGISTRY,
    describe_strategies,
    get_strategy,
    list_families,
    list_strategies,
)
from .regcond_1 import WEIGHTS as REGCOND_1_WEIGHTS
from .regcond_1 import RegCond1, SYMBOLS as REGCOND_1_SYMBOLS
from .trend import DonchianBreakout, EMACrossover, MACDTrend, SMACrossover, Supertrend

__version__ = "0.4.0"

__all__ = [
    "BollingerReversion",
    "BollingerSqueezeBreakout",
    "CrossSectionalMomentum",
    "DonchianBreakout",
    "EMACrossover",
    "EnsembleVote",
    "KeltnerBreakout",
    "MACDTrend",
    "OBVTrend",
    "PairsTrading",
    "REGCOND_1_SYMBOLS",
    "REGCOND_1_WEIGHTS",
    "RSI2MeanReversion",
    "RegCond1",
    "RegimeFilter",
    "SMACrossover",
    "STRATEGY_REGISTRY",
    "Signal",
    "SignalAction",
    "SingleAssetStrategy",
    "StochasticReversion",
    "Strategy",
    "Supertrend",
    "TimeSeriesMomentum",
    "TrailingStop",
    "VWAPDeviation",
    "ZScoreReversion",
    "closes",
    "describe_strategies",
    "field",
    "get_strategy",
    "highs",
    "list_families",
    "list_strategies",
    "lows",
    "run_backtest",
    "to_backtest_strategy",
    "volumes",
]
