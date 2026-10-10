"""trade-decay: live-strategy decay monitoring with retirement triggers.

The research desk (trade-agents) validates ideas and the paper trader
(trade-paper) runs them; this engine watches what happens *after*
adoption.  For each registered live strategy it compares trailing
performance against the Tier-1 validation expectations, fits the
rolling edge's half-life, and moves a health state machine
(healthy -> watchlist -> demoted).  Demotion emits a *recommendation
to retire* -- the engine never touches a broker, an allocator, or a
position.

Language standard: strategies are validated / invalidated / discarded
/ demoted.  Never "kill" -- in code, docs, or comments.
"""

from .config import load_config
from .evaluate import evaluate_all, evaluate_strategy, promote
from .events import current_state, read_events, record_decay_event
from .ledger import LedgerError, LedgerReader
from .metrics import (divergence_zscore, fit_half_life, max_drawdown,
                      resample_daily, rolling_sharpe, sharpe_ratio,
                      trailing_sharpe)
from .registry import (RegistryError, StrategySpec, find_spec,
                       load_registry, save_registry)
from .report import decay_report, strategy_health
from .state_machine import (DEMOTED, HEALTHY, INSUFFICIENT_DATA,
                            WATCHLIST, Thresholds, evaluate)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "DEMOTED", "HEALTHY", "INSUFFICIENT_DATA", "WATCHLIST",
    "LedgerError", "LedgerReader",
    "RegistryError", "StrategySpec",
    "Thresholds",
    "current_state", "decay_report", "divergence_zscore",
    "evaluate", "evaluate_all", "evaluate_strategy", "find_spec",
    "fit_half_life", "load_config", "load_registry", "max_drawdown",
    "promote", "read_events", "record_decay_event", "resample_daily",
    "rolling_sharpe", "save_registry", "sharpe_ratio", "strategy_health",
    "trailing_sharpe",
]
