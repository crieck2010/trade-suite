"""Trade Execution Layer: Multi-broker strategy order execution.

Provides unified adapters for executing equity rebalancing (RegCond-1)
and cash-settled European index options (0DTE SPX/XSP Iron-Flies).

Exports:
- ExecutionAdapter (Abstract base class)
- ExecutionEnvironment, OrderAction, OrderType, SecurityType, ComboStrategyType
- OrderPayload, ComboLegPayload, ComboOrderPayload, ExecutionResult, AccountState, PositionSnapshot
- MoomooExecutionAdapter, MoomooAdapterConfig
- Exceptions: ExecutionError, LiveSafetyError, TradeUnlockError, OpenDConnectionError, OrderRejectionError
"""

from __future__ import annotations

from .base import ExecutionAdapter
from .exceptions import (
    ExecutionError,
    LiveSafetyError,
    OpenDConnectionError,
    OrderRejectionError,
    TradeUnlockError,
)
from .models import (
    AccountState,
    ComboLegPayload,
    ComboOrderPayload,
    ComboStrategyType,
    ExecutionEnvironment,
    ExecutionResult,
    OrderAction,
    OrderPayload,
    OrderType,
    PositionSnapshot,
    SecurityType,
    TimeInForce,
)
from .moomoo_adapter import MoomooAdapterConfig, MoomooExecutionAdapter

__version__ = "0.1.0"

__all__ = [
    "ExecutionAdapter",
    "ExecutionEnvironment",
    "OrderAction",
    "OrderType",
    "TimeInForce",
    "SecurityType",
    "ComboStrategyType",
    "OrderPayload",
    "ComboLegPayload",
    "ComboOrderPayload",
    "ExecutionResult",
    "AccountState",
    "PositionSnapshot",
    "MoomooExecutionAdapter",
    "MoomooAdapterConfig",
    "ExecutionError",
    "LiveSafetyError",
    "TradeUnlockError",
    "OpenDConnectionError",
    "OrderRejectionError",
]
