"""Data models: orders, trades, and book snapshots.

Plain dataclasses with JSON-friendly ``to_dict`` so results cross process
and agent boundaries without the engine leaking in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

BID = "bid"
ASK = "ask"


@dataclass
class Order:
    """A single order.  ``price=None`` means market order."""

    order_id: str
    side: str  # "bid" (buy) | "ask" (sell)
    quantity: float
    price: float | None = None
    order_type: str = "limit"  # "limit" | "market"
    tif: str = "GTC"  # "GTC" | "IOC" | "FOK"
    timestamp: int = 0  # engine-assigned sequence number (time priority)
    leaves: float = 0.0  # remaining quantity; set on submit
    status: str = "new"  # new|partially_filled|filled|cancelled|rejected

    def __post_init__(self) -> None:
        if self.leaves == 0.0:
            self.leaves = self.quantity

    @property
    def is_market(self) -> bool:
        return self.order_type == "market" or self.price is None

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "order_type": self.order_type,
            "tif": self.tif,
            "timestamp": self.timestamp,
            "leaves": self.leaves,
            "status": self.status,
        }


@dataclass
class Trade:
    """One match between an aggressor and a resting order.

    Trade price is always the *resting* order's price (standard exchange
    semantics): the aggressor pays the quoted price, never better or worse.
    """

    trade_id: int
    price: float
    quantity: float
    aggressor_side: str  # side of the incoming order: "bid" | "ask"
    resting_order_id: str
    aggressor_order_id: str
    timestamp: int

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "price": self.price,
            "quantity": self.quantity,
            "aggressor_side": self.aggressor_side,
            "resting_order_id": self.resting_order_id,
            "aggressor_order_id": self.aggressor_order_id,
            "timestamp": self.timestamp,
        }


@dataclass
class BookSnapshot:
    """A point-in-time L2 view of the book."""

    timestamp: int
    bids: list[tuple[float, float]] = field(default_factory=list)  # (price, qty)
    asks: list[tuple[float, float]] = field(default_factory=list)

    @property
    def best_bid(self) -> float | None:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0][0] if self.asks else None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "bids": [[p, q] for p, q in self.bids],
            "asks": [[p, q] for p, q in self.asks],
        }
