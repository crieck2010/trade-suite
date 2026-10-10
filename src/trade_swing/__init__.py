"""trade_swing — reference swing-trend strategy + full validation loop.

A strategy proves nothing by itself. This package proves the *pipeline*:
strategy -> backtest with costs -> overfit gates -> verdict report.

Public entry points:
    SwingTrendStrategy / generate_signals  (strategy.py)
    atr_position_size                       (sizing.py)
    CostModel / apply_costs                 (costs.py)
    run_backtest                            (backtest.py)
    run_validation                          (validate.py)
    build_report                            (report.py)
    demo_bars / run_demo                    (demo.py)
"""

from __future__ import annotations

__version__ = "0.1.0"

from .strategy import SwingConfig, SwingTrendStrategy, generate_signals  # noqa: F401
from .sizing import atr_position_size  # noqa: F401
from .costs import CostModel, apply_costs  # noqa: F401
from .backtest import run_backtest  # noqa: F401
from .validate import run_validation  # noqa: F401
from .report import build_report  # noqa: F401
from .demo import demo_bars, run_demo  # noqa: F401
