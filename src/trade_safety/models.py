"""Data models for the safety kernel (live-roadmap Phase 1).

Plain dataclasses, stdlib only. The kernel never imports broker code;
adapters translate their own payloads into these shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OrderIntent:
    """A proposed order, as the safety kernel sees it."""

    symbol: str
    action: str  # "BUY" / "SELL"
    quantity: float
    price: float | None  # None for market orders (notional unverifiable)
    strategy: str = ""
    multiplier: float = 1.0  # 100 for option combos priced per-share
    reduces_exposure: bool = False  # closing orders skip cap/cushion checks

    @property
    def notional(self) -> float | None:
        """Dollar size of the order, or None when it cannot be known."""
        if self.price is None:
            return None
        return abs(self.quantity * self.price * self.multiplier)


@dataclass(frozen=True)
class AccountSnapshot:
    """The account facts the kernel decides on."""

    account_id: str
    equity: float
    buying_power: float
    realized_pnl: float = 0.0  # session/day, broker-reported
    unrealized_pnl: float = 0.0
    gross_exposure: float = 0.0  # sum of |position market values|
    maintenance_margin: float = 0.0

    @property
    def session_loss(self) -> float:
        """Positive number when the session is down, else 0."""
        return max(0.0, -(self.realized_pnl + self.unrealized_pnl))

    @property
    def margin_cushion(self) -> float:
        """Equity minus maintenance-margin requirement (IML proxy).

        Mirrors Moomoo's Intraday Margin Level concept
        (ELV - SRO maintenance margin requirement). Approximate: the
        broker's ELV excludes option market value, which this snapshot
        cannot reproduce exactly.
        """
        return self.equity - self.maintenance_margin


@dataclass
class Decision:
    """Outcome of a kernel check. ``checks`` records each gate by name."""

    allowed: bool
    reasons: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
