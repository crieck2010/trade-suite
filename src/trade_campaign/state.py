"""Campaign state: the small JSON file that survives between runs.

Holds the incubation program's counters, the strategy feed watermark,
and per-symbol cost basis (for realized-P&L / closed-trade accounting).
The strategy object itself is *not* persisted — it is deterministic, so
each run rebuilds it by replaying the close history, and the watermark
says which of those days the campaign has already lived through.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class CampaignState:
    program_day: int = 0
    program_state: str = "WARMUP"
    kill_trips: list = field(default_factory=list)
    drift_worst: str = "OK"
    #: Last bar date fed to the strategy *as a live session*.
    fed_through: str | None = None
    #: Date of the newest rebalance signal set already acted on.
    last_acted: str | None = None
    #: {symbol: {"qty": float, "avg_cost": float}} — campaign's own
    #: accounting view; the broker's positions remain the truth for qty.
    cost_basis: dict = field(default_factory=dict)
    #: Closed (flattened) trades: {symbol, pnl, date}.
    closed_trades: list = field(default_factory=list)
    started_on: str | None = None

    # -- persistence ----------------------------------------------------
    @classmethod
    def load(cls, path: Path) -> "CampaignState":
        if Path(path).exists():
            return cls(**json.loads(Path(path).read_text(encoding="utf-8")))
        return cls()

    def save(self, path: Path) -> None:
        path = Path(path)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.__dict__, indent=1, default=str),
                       encoding="utf-8")
        os.replace(tmp, path)

    # -- fill accounting --------------------------------------------------
    def apply_fill(self, symbol: str, action: str, qty: float,
                   price: float, day: date) -> dict | None:
        """Fold one fill into cost basis.

        Returns a closed-trade record when a SELL flattens the position,
        else ``None``.  Realized P&L on partial exits accrues into the
        position's stored ``realized`` until it flattens.
        """
        pos = self.cost_basis.setdefault(
            symbol, {"qty": 0.0, "avg_cost": 0.0, "realized": 0.0})
        if action == "BUY":
            total_cost = pos["avg_cost"] * pos["qty"] + price * qty
            pos["qty"] += qty
            pos["avg_cost"] = total_cost / pos["qty"] if pos["qty"] else 0.0
            return None
        # SELL
        closed_qty = min(qty, pos["qty"])
        pos["realized"] = pos.get("realized", 0.0) + (
            price - pos["avg_cost"]) * closed_qty
        pos["qty"] -= closed_qty
        if pos["qty"] <= 1e-9:
            record = {"symbol": symbol, "pnl": round(pos["realized"], 2),
                      "date": day.isoformat()}
            self.closed_trades.append(record)
            self.cost_basis[symbol] = {"qty": 0.0, "avg_cost": 0.0,
                                       "realized": 0.0}
            return record
        return None
