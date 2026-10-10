"""Cost model: commission + slippage + spread, applied to every backtest.

Costs are applied *post-hoc* to closed trades, identically for both
backtest engines, so the engine choice never changes the cost
assumptions. The report always states the model and its parameters —
a backtest without stated costs is a fantasy.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    """Per-side costs. A round trip pays each leg twice.

    - ``commission_per_share``: e.g. 0.005 = half a cent per share.
    - ``slippage_bps``: adverse move vs the intended fill, in basis points.
    - ``spread_bps``: full bid/ask spread; crossing it costs half, per side.
    """
    commission_per_share: float = 0.005
    slippage_bps: float = 5.0
    spread_bps: float = 2.0

    def __post_init__(self) -> None:
        for name in ("commission_per_share", "slippage_bps", "spread_bps"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")

    def one_side(self, quantity: float, price: float) -> float:
        """Cost of one fill (entry OR exit)."""
        commission = quantity * self.commission_per_share
        slippage = quantity * price * self.slippage_bps / 10_000.0
        spread = quantity * price * self.spread_bps / 10_000.0 / 2.0
        return commission + slippage + spread

    def round_trip(self, quantity: float, entry_price: float,
                   exit_price: float) -> float:
        """Full cost of entering and exiting."""
        return (self.one_side(quantity, entry_price)
                + self.one_side(quantity, exit_price))

    def as_dict(self) -> dict:
        return {
            "commission_per_share": self.commission_per_share,
            "slippage_bps": self.slippage_bps,
            "spread_bps": self.spread_bps,
        }


def apply_costs(trades: list[dict], model: CostModel | None = None
                ) -> tuple[list[dict], dict]:
    """Attach ``cost`` and ``pnl_net`` to each plain-data trade.

    Trade contract in: ``{quantity, entry_price, exit_price, pnl_gross, ...}``.
    Returns ``(adjusted_trades, summary)`` where summary carries
    ``total_cost``, ``total_pnl_gross``, ``total_pnl_net`` and
    ``cost_drag`` = 1 - net/gross (None when gross <= 0).
    """
    model = model or CostModel()
    adjusted: list[dict] = []
    total_cost = 0.0
    total_gross = 0.0
    for t in trades:
        cost = model.round_trip(t["quantity"], t["entry_price"], t["exit_price"])
        pnl_net = t["pnl_gross"] - cost
        row = dict(t)
        row["cost"] = cost
        row["pnl_net"] = pnl_net
        adjusted.append(row)
        total_cost += cost
        total_gross += t["pnl_gross"]
    total_net = total_gross - total_cost
    summary = {
        "total_cost": total_cost,
        "total_pnl_gross": total_gross,
        "total_pnl_net": total_net,
        "cost_drag": (1.0 - total_net / total_gross) if total_gross > 0 else None,
        "n_trades": len(trades),
        "cost_model": model.as_dict(),
    }
    return adjusted, summary
