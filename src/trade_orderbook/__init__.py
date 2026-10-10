"""Limit order book + matching engine for the trade-suite.

A price-time priority matching engine (limit/market orders, GTC/IOC/FOK),
market-data views (BBO, depth, imbalance, microprice), a synthetic
order-flow simulator, and execution analytics (slippage, impact).
Stdlib-only and deterministic.
"""

from __future__ import annotations

__version__ = "0.1.0"

from . import analytics, marketdata
from .adapters import (
    depth_limit_check,
    fills_for_paper_order,
    slippage_bps_for_backtest,
    to_agent_features,
)
from .book import OrderBook
from .engine import MatchingEngine
from .models import ASK, BID, BookSnapshot, Order, Trade
from .simulate import SessionResult, SimulatorConfig, run_session

__all__ = [
    "ASK",
    "BID",
    "BookSnapshot",
    "MatchingEngine",
    "Order",
    "OrderBook",
    "SessionResult",
    "SimulatorConfig",
    "Trade",
    "analytics",
    "depth_limit_check",
    "fills_for_paper_order",
    "marketdata",
    "run_session",
    "slippage_bps_for_backtest",
    "to_agent_features",
    "__version__",
]
