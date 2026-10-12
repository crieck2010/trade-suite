"""Data models and enums for multi-broker strategy execution.

Supports both single-leg equity/ETF orders (RegCond-1) and multi-leg
option combo orders (0DTE European SPX/XSP cash-settled Iron-Flies).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ExecutionEnvironment(str, Enum):
    """Trading environment."""
    SIMULATE = "SIMULATE"  # Paper / simulated broker environment
    REAL = "REAL"          # Live real-money trading (strictly gated)


class OrderAction(str, Enum):
    """Order direction."""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Execution order type."""
    LIMIT = "NORMAL"   # Limit order (named NORMAL in Moomoo/Futu API)
    MARKET = "MARKET"  # Market order


class TimeInForce(str, Enum):
    """Time in force."""
    DAY = "DAY"
    GTC = "GTC"


class SecurityType(str, Enum):
    """Underlying instrument security classification."""
    STOCK = "STOCK"
    ETF = "ETF"
    OPTION = "OPTION"
    INDEX_OPTION = "INDEX_OPTION"


class ComboStrategyType(str, Enum):
    """Multi-leg option combo structure."""
    CUSTOM = "CUSTOM"
    VERTICAL = "VERTICAL"
    STRADDLE = "STRADDLE"
    STRANGLE = "STRANGLE"
    IRON_CONDOR = "IRON_CONDOR"
    IRON_FLY = "IRON_FLY"


def utcnow_str() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class OrderPayload:
    """Single-leg order payload for equities, ETFs, or single option legs."""
    symbol: str
    action: OrderAction
    quantity: int
    price: float | None = None
    order_type: OrderType = OrderType.LIMIT
    time_in_force: TimeInForce = TimeInForce.DAY
    client_tag: str = ""
    strategy: str = "regcond1"
    created_at: str = field(default_factory=utcnow_str)

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"Quantity must be positive, got {self.quantity}")
        if self.order_type == OrderType.LIMIT and (self.price is None or self.price <= 0):
            raise ValueError(f"Limit order requires positive price, got {self.price}")


@dataclass
class ComboLegPayload:
    """Individual option leg within an atomic multi-leg combo order."""
    code: str                  # Option contract symbol (e.g. US..SPXW261012C05800000)
    action: OrderAction        # BUY or SELL
    qty_ratio: int = 1         # Leg quantity ratio (e.g. 1 for standard 1:1:1:1 iron fly)
    leg_type: str = "CALL"     # CALL or PUT (informational)
    strike: float = 0.0        # Strike price (informational)

    def __post_init__(self) -> None:
        if self.qty_ratio <= 0:
            raise ValueError(f"Leg qty_ratio must be positive, got {self.qty_ratio}")


@dataclass
class ComboOrderPayload:
    """Multi-leg combo order payload (e.g. 4-leg 0DTE Iron-Fly).

    Submitted atomically to the exchange via Moomoo `place_combo_order`
    guaranteeing all legs fill simultaneously with zero leg-in risk.
    """
    legs: list[ComboLegPayload]
    quantity: int                                  # Number of combo contracts (lots)
    net_price: float                               # Net limit price (positive credit or debit)
    combo_type: ComboStrategyType = ComboStrategyType.IRON_FLY
    order_type: OrderType = OrderType.LIMIT
    time_in_force: TimeInForce = TimeInForce.DAY
    client_tag: str = ""
    strategy: str = "0dte_em_decay"
    created_at: str = field(default_factory=utcnow_str)

    def __post_init__(self) -> None:
        if not self.legs:
            raise ValueError("Combo order must have at least one leg")
        if self.quantity <= 0:
            raise ValueError(f"Combo quantity must be positive, got {self.quantity}")
        if self.order_type == OrderType.LIMIT and self.net_price is None:
            raise ValueError("Limit combo order requires net_price")


@dataclass
class ExecutionResult:
    """Result of an order placement attempt."""
    success: bool
    order_id: str
    client_tag: str
    env: ExecutionEnvironment
    status: str
    filled_qty: int = 0
    avg_price: float = 0.0
    message: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=utcnow_str)


@dataclass
class AccountState:
    """Standardized broker account snapshot."""
    account_id: str
    net_liquidity: float
    buying_power: float
    cash: float
    maintenance_margin: float
    unrealized_pnl: float
    realized_pnl: float
    currency: str = "USD"
    env: ExecutionEnvironment = ExecutionEnvironment.SIMULATE
    timestamp: str = field(default_factory=utcnow_str)


@dataclass
class PositionSnapshot:
    """Standardized portfolio position."""
    symbol: str
    quantity: float
    cost_basis: float
    market_price: float
    market_value: float
    nominal_pnl: float
    unrealized_pnl_pct: float
    sec_type: SecurityType = SecurityType.STOCK
    env: ExecutionEnvironment = ExecutionEnvironment.SIMULATE
