"""Command-line interface for trade-orderbook."""

from __future__ import annotations

import argparse
import json

from . import __version__
from .adapters import depth_limit_check, to_agent_features
from .analytics import estimate_slippage
from .engine import MatchingEngine
from .licensing import check_license, check_update
from .marketdata import features
from .models import Order
from .simulate import SimulatorConfig, run_session


def _demo_book() -> MatchingEngine:
    """A small two-sided book for the slippage/book demos."""
    eng = MatchingEngine()
    n = 0

    def lim(side: str, price: float, qty: float) -> None:
        nonlocal n
        n += 1
        eng.submit(Order(f"D{n}", side, qty, price))

    for i, q in enumerate([300, 200, 150, 100, 80]):
        lim("ask", 100.05 + i * 0.05, q)
        lim("bid", 99.95 - i * 0.05, q)
    return eng


def cmd_book(args: argparse.Namespace) -> int:
    eng = _demo_book()
    snap = eng.book.snapshot(levels=args.levels).to_dict()
    feats = features(eng.book)
    if args.format == "json":
        print(json.dumps({"snapshot": snap, "features": feats}, indent=2))
    else:
        print(f"best bid {feats['best_bid']:.2f} x {feats['bid_depth']:.0f}  |  "
              f"best ask {feats['best_ask']:.2f} x {feats['ask_depth']:.0f}")
        print(f"mid {feats['midprice']:.4f}  spread {feats['spread']:.2f} "
              f"({feats['spread_bps']:.1f} bps)  imbalance {feats['imbalance']:+.2f}")
        print("asks:")
        for p, q in reversed(snap["asks"]):
            print(f"  {p:>8.2f}  {q:>8.0f}")
        print("bids:")
        for p, q in snap["bids"]:
            print(f"  {p:>8.2f}  {q:>8.0f}")
    return 0


def cmd_slippage(args: argparse.Namespace) -> int:
    eng = _demo_book()
    res = estimate_slippage(eng.book, args.side, args.quantity)
    if args.format == "json":
        print(json.dumps(res, indent=2))
    else:
        print(f"{args.side} {args.quantity:.0f} vs mid {res['midprice']:.4f}: "
              f"avg fill {res['avg_price']:.4f}, "
              f"slippage {res['slippage_bps']:.1f} bps, "
              f"shortfall {res['shortfall_qty']:.0f}")
    chk = depth_limit_check(eng.book, args.side, args.quantity,
                            max_fraction=args.max_fraction)
    if args.format != "json":
        print(f"depth check: {'PASS' if chk['passes'] else 'FAIL'} — {chk['reason']}")
    return 0


def cmd_simulate(args: argparse.Namespace) -> int:
    cfg = SimulatorConfig(n_steps=args.steps, seed=args.seed,
                          snapshot_every=args.snapshot_every)
    result = run_session(cfg)
    if args.format == "json":
        print(json.dumps(result.to_dict(), indent=2))
    else:
        s = result.summary()
        print(f"session: {s['n_steps']} steps, {s['n_orders']} orders, "
              f"{s['n_trades']} trades, {s['n_cancels']} cancels")
        print(f"volume {s['total_volume']:.0f}  vwap {s['vwap']:.4f}  "
              f"avg spread {s['avg_spread_bps']:.1f} bps  "
              f"final mid {s['final_midprice']:.4f}")
    return 0


def cmd_features(args: argparse.Namespace) -> int:
    eng = _demo_book()
    print(json.dumps(to_agent_features(eng.book, symbol=args.symbol), indent=2))
    return 0


def cmd_license(_args: argparse.Namespace) -> int:
    print(json.dumps(check_license(), indent=2))
    return 0


def cmd_update_check(_args: argparse.Namespace) -> int:
    print(json.dumps(check_update(), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="trade-orderbook",
                                 description="Limit order book + matching engine")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("book", help="show a demo L2 book snapshot")
    p.add_argument("--levels", type=int, default=5)
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_book)

    p = sub.add_parser("slippage", help="estimate slippage for an order")
    p.add_argument("--side", choices=["bid", "ask"], default="bid")
    p.add_argument("--quantity", type=float, default=500.0)
    p.add_argument("--max-fraction", type=float, default=0.10)
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_slippage)

    p = sub.add_parser("simulate", help="run a synthetic market session")
    p.add_argument("--steps", type=int, default=5000)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--snapshot-every", type=int, default=100)
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("features", help="microstructure features as agent JSON")
    p.add_argument("--symbol", default="SYM")
    p.set_defaults(func=cmd_features)

    p = sub.add_parser("license", help="check the license-key hook")
    p.set_defaults(func=cmd_license)
    p = sub.add_parser("update-check", help="check for a newer release")
    p.set_defaults(func=cmd_update_check)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
