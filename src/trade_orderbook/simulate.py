"""Synthetic market simulator: generate plausible order flow, run it through
the matching engine, and report what happened.

The simulator is for research and strategy testing — not a market model of
any particular venue.  Midprice follows a random walk; limit orders arrive
around it, market orders consume liquidity, and resting orders get
cancelled.  Everything is seeded and deterministic.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import marketdata
from .engine import MatchingEngine
from .models import ASK, BID, Order, Trade


@dataclass
class SimulatorConfig:
    n_steps: int = 5_000
    seed: int = 7
    start_price: float = 100.0
    tick: float = 0.01
    mid_vol: float = 0.02  # midprice random-walk stdev per step (in ticks^2-ish)
    p_limit: float = 0.55  # per-step probability of a limit order
    p_market: float = 0.12  # per-step probability of a market order
    p_cancel: float = 0.10  # per-step probability of cancelling a resting order
    qty_min: float = 1.0
    qty_max: float = 10.0
    max_depth_ticks: int = 10  # limit orders land within ±N ticks of mid
    snapshot_every: int = 100


@dataclass
class SessionResult:
    config: SimulatorConfig
    trades: list[Trade] = field(default_factory=list)
    snapshots: list[dict] = field(default_factory=list)
    n_orders: int = 0
    n_cancels: int = 0

    def summary(self) -> dict:
        vols = [t.quantity for t in self.trades]
        notionals = [t.quantity * t.price for t in self.trades]
        vwap = sum(notionals) / sum(vols) if vols else 0.0
        spreads = [s["spread_bps"] for s in self.snapshots
                   if s.get("spread_bps") is not None]
        return {
            "n_steps": self.config.n_steps,
            "n_orders": self.n_orders,
            "n_trades": len(self.trades),
            "n_cancels": self.n_cancels,
            "total_volume": sum(vols),
            "vwap": vwap,
            "avg_spread_bps": sum(spreads) / len(spreads) if spreads else None,
            "final_midprice": self.snapshots[-1]["midprice"] if self.snapshots else None,
        }

    def to_dict(self) -> dict:
        return {
            "summary": self.summary(),
            "trades": [t.to_dict() for t in self.trades],
            "snapshots": self.snapshots,
        }


def run_session(config: SimulatorConfig | None = None) -> SessionResult:
    """Run one synthetic trading session through the matching engine."""
    cfg = config or SimulatorConfig()
    rng = random.Random(cfg.seed)
    engine = MatchingEngine()
    result = SessionResult(config=cfg)
    mid = cfg.start_price
    oid = 0

    def next_id(prefix: str) -> str:
        nonlocal oid
        oid += 1
        return f"{prefix}-{oid}"

    def book_mid() -> float:
        m = marketdata.midprice(engine.book)
        return m if m is not None else mid

    for step in range(cfg.n_steps):
        # midprice random walk (in price units, scaled by tick)
        mid = max(mid + rng.gauss(0, cfg.mid_vol) * cfg.tick * 10, cfg.tick)
        r = rng.random()
        if r < cfg.p_limit:
            side = BID if rng.random() < 0.5 else ASK
            ticks = rng.randint(1, cfg.max_depth_ticks)
            m = book_mid()
            # bids below mid / asks above mid: they rest, never cross
            price = round(m - ticks * cfg.tick if side == BID
                          else m + ticks * cfg.tick, 10)
            qty = round(rng.uniform(cfg.qty_min, cfg.qty_max), 4)
            engine.submit(Order(next_id("L"), side, qty, price))
            result.n_orders += 1
        elif r < cfg.p_limit + cfg.p_market:
            side = BID if rng.random() < 0.5 else ASK
            qty = round(rng.uniform(cfg.qty_min, cfg.qty_max), 4)
            engine.submit(Order(next_id("M"), side, qty, order_type="market"))
            result.n_orders += 1
        elif r < cfg.p_limit + cfg.p_market + cfg.p_cancel and len(engine.book):
            victim = rng.choice(list(engine.book._orders.keys()))
            if engine.cancel(victim):
                result.n_cancels += 1

        if step % cfg.snapshot_every == 0:
            snap = marketdata.features(engine.book, timestamp=step)
            result.snapshots.append(snap)

    result.trades = engine.trades
    return result
