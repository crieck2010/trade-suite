"""trade_incubate: the paper-trading incubation program.

Step 3 of the path to live trading: run a validated strategy through a
disciplined 63-trading-day (~one quarter) paper incubation and continuously
answer one question — "is the strategy behaving like its backtest?"

Nothing here trades live.  Execution routes exclusively through
trade-paper's paper-only guard (FakeBroker in dry-run).
"""

from __future__ import annotations

from .program import IncubationProgram, Stage, DEFAULT_CRITERIA
from .drift import compare, drift_verdict
from .ledger import IncubationLedger
from .digest import build_digest, render_digest
from .runner import run_day, DayConfig

__version__ = "0.1.0"
__all__ = [
    "IncubationProgram",
    "Stage",
    "DEFAULT_CRITERIA",
    "compare",
    "drift_verdict",
    "IncubationLedger",
    "build_digest",
    "render_digest",
    "run_day",
    "DayConfig",
    "__version__",
]
