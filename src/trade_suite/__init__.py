"""trade-suite: one install for the whole algorithmic/agentic trading system.

This is the meta-package: it declares every suite module as a dependency,
introspects the environment (:mod:`trade_suite.env`), and offers end-to-end
research workflows (:mod:`trade_suite.pipeline`) plus a unified CLI
(``trade-suite``).

Research/backtesting/paper-trading tooling only — no live trading.
"""

from . import env

__version__ = "0.4.0"
__all__ = ["env", "__version__"]
