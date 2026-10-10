"""Markowitz portfolio optimization for the trade-suite.

Mean-variance optimizers (minimum variance, maximum Sharpe, efficient
frontier, risk parity) over pure-Python linear algebra — no third-party
dependencies.  Long-only with per-asset weight caps, shrinkage covariance
estimation, portfolio analytics, and rebalancing into concrete orders.
"""

from __future__ import annotations

__version__ = "0.1.0"

from . import analytics, estimates, linalg
from .adapters import (
    dicts_to_matrix,
    portfolio_vol_for_risk,
    returns_from_dict_bars,
    to_agent_allocation,
    to_backtest_weights,
    to_paper_orders,
)
from .optimize import (
    efficient_frontier,
    equal_weight,
    max_sharpe,
    min_variance,
    optimize,
    risk_parity,
)
from .rebalance import trades_to_target

__all__ = [
    "analytics",
    "dicts_to_matrix",
    "efficient_frontier",
    "equal_weight",
    "estimates",
    "linalg",
    "max_sharpe",
    "min_variance",
    "optimize",
    "portfolio_vol_for_risk",
    "returns_from_dict_bars",
    "risk_parity",
    "to_agent_allocation",
    "to_backtest_weights",
    "to_paper_orders",
    "trades_to_target",
    "__version__",
]
