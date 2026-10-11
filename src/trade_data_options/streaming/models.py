"""Models for ThetaData v3 Live WebSocket streaming and 0DTE EM-decay pipeline.

Adheres to:
- Immutable dataclasses with explicit UTC timestamps.
- Zero third-party dependencies (stdlib only).
- Strict typing and mathematical validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional

from ..models import OptionRight, ensure_utc


class ConnectionState(Enum):
    """WebSocket connection lifecycle states."""
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class LiveQuote:
    """Real-time NBBO option quote received from WebSocket feed."""
    symbol: str
    expiration: date
    strike: float
    right: OptionRight
    bid: float
    ask: float
    bid_size: int = 0
    ask_size: int = 0
    volume: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def mid(self) -> float:
        """Mid-market price: (bid + ask) / 2."""
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        """Quoted bid-ask spread."""
        return max(0.0, self.ask - self.bid)


@dataclass(frozen=True, slots=True)
class LiveStraddleQuote:
    """Synchronized ATM call and put quotes forming a real-time straddle."""
    symbol: str
    expiration: date
    strike: float
    call_quote: LiveQuote
    put_quote: LiveQuote
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def straddle_bid(self) -> float:
        """Aggregate bid for the straddle."""
        return self.call_quote.bid + self.put_quote.bid

    @property
    def straddle_ask(self) -> float:
        """Aggregate ask for the straddle."""
        return self.call_quote.ask + self.put_quote.ask

    @property
    def straddle_mid(self) -> float:
        """Aggregate mid price for the straddle (total current premium)."""
        return self.call_quote.mid + self.put_quote.mid

    @property
    def total_spread(self) -> float:
        """Combined bid-ask friction for the straddle."""
        return self.straddle_ask - self.straddle_bid


@dataclass(frozen=True, slots=True)
class LiveEMDecayStreamEvent:
    """Emitted on every incoming quote tick or evaluation cycle for 0DTE EM-decay."""
    symbol: str
    expiration: date
    strike: float
    opening_em: float
    current_straddle_mid: float
    decay_ratio: float
    threshold: float = 0.83
    is_triggered: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def decay_pct_remains(self) -> float:
        """Percentage of opening premium still remaining (e.g. 82.5%)."""
        return self.decay_ratio * 100.0

    @property
    def decay_consumed_pct(self) -> float:
        """Percentage of opening premium decayed away (e.g. 17.5%)."""
        return max(0.0, 100.0 - self.decay_pct_remains)
