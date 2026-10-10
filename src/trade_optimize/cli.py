"""Command-line interface for trade-optimize."""

from __future__ import annotations

import argparse
import csv
import json
import random

from . import __version__
from . import analytics
from .adapters import dicts_to_matrix, to_agent_allocation
from .estimates import mean_returns, shrink_covariance
from .licensing import check_license, check_update
from .optimize import efficient_frontier, optimize


def _demo_returns(n_assets: int = 6, n_obs: int = 252,
                  seed: int = 7) -> tuple[list[str], list[list[float]]]:
    """Synthetic correlated returns: a market factor plus idiosyncratic noise."""
    rng = random.Random(seed)
    symbols = [f"ASSET{i+1}" for i in range(n_assets)]
    rows = []
    for _ in range(n_obs):
        mkt = rng.gauss(0.0004, 0.012)
        rows.append({s: mkt * (0.5 + 0.1 * i) + rng.gauss(0.0002, 0.008 + 0.002 * i)
                     for i, s in enumerate(symbols)})
    return dicts_to_matrix(rows)


def _load_csv(path: str) -> tuple[list[str], list[list[float]]]:
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if "date" in (reader.fieldnames or []):
            fields = [c for c in reader.fieldnames if c != "date"]
        else:
            fields = list(reader.fieldnames or [])
        rows = [{c: float(r[c]) for c in fields} for r in reader]
    return dicts_to_matrix(rows)


def _inputs(args) -> tuple[list[str], list[list[float]]]:
    if args.csv:
        return _load_csv(args.csv)
    return _demo_returns(seed=args.seed)


def cmd_optimize(args: argparse.Namespace) -> int:
    symbols, rets = _inputs(args)
    mu = mean_returns(rets)
    sigma = shrink_covariance(rets, delta=args.shrink)
    w = optimize(sigma, mu if args.method != "risk_parity" else None,
                 method=args.method, risk_free=args.risk_free,
                 max_weight=args.max_weight)
    stats = analytics.portfolio_stats(w, mu, sigma, args.risk_free)
    rc = analytics.risk_contributions(w, sigma)
    out = {
        "method": args.method,
        "symbols": symbols,
        "weights": dict(zip(symbols, (round(x, 6) for x in w))),
        "stats": stats,
        "diversification_ratio": analytics.diversification_ratio(w, sigma),
        "herfindahl": analytics.herfindahl(w),
        "risk_contributions": [
            {"symbol": s, "weight": round(c["weight"], 6),
             "risk_share": round(c["risk_share"], 6)}
            for s, c in zip(symbols, rc)
        ],
    }
    if args.format == "json":
        print(json.dumps(out, indent=2))
    else:
        print(f"{args.method} portfolio ({len(symbols)} assets):")
        for s, x in zip(symbols, w):
            print(f"  {s:>8}  {x:7.2%}")
        print(f"expected return {stats['expected_return_ann']:.2%}  "
              f"vol {stats['volatility_ann']:.2%}  "
              f"sharpe {stats['sharpe_ann']:.2f}")
    return 0


def cmd_frontier(args: argparse.Namespace) -> int:
    symbols, rets = _inputs(args)
    mu = mean_returns(rets)
    sigma = shrink_covariance(rets, delta=args.shrink)
    pts = efficient_frontier(sigma, mu, max_weight=args.max_weight,
                             n_points=args.points, risk_free=args.risk_free)
    if args.format == "json":
        print(json.dumps([
            {"expected_return_ann": p["expected_return"] * 252,
             "volatility_ann": p["volatility"] * (252 ** 0.5),
             "sharpe_ann": p["sharpe"] * (252 ** 0.5),
             "weights": dict(zip(symbols, (round(x, 4) for x in p["weights"])))}
            for p in pts], indent=2))
    else:
        print(f"{'ann_ret':>8} {'ann_vol':>8} {'sharpe':>7}  top holding")
        for p in pts:
            top = max(zip(symbols, p["weights"]), key=lambda t: t[1])
            print(f"{p['expected_return']*252:8.2%} {p['volatility']*252**0.5:8.2%} "
                  f"{p['sharpe']*252**0.5:7.2f}  {top[0]} {top[1]:.0%}")
    return 0


def cmd_allocate(args: argparse.Namespace) -> int:
    symbols, rets = _inputs(args)
    print(json.dumps(to_agent_allocation(
        symbols, rets, method=args.method, risk_free=args.risk_free,
        max_weight=args.max_weight), indent=2))
    return 0


def cmd_license(_args: argparse.Namespace) -> int:
    print(json.dumps(check_license(), indent=2))
    return 0


def cmd_update_check(_args: argparse.Namespace) -> int:
    print(json.dumps(check_update(), indent=2))
    return 0


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--csv", help="wide CSV of per-period returns (columns = symbols)")
    p.add_argument("--seed", type=int, default=7, help="demo data seed")
    p.add_argument("--shrink", type=float, default=0.2, help="covariance shrinkage delta")
    p.add_argument("--max-weight", type=float, default=1.0)
    p.add_argument("--risk-free", type=float, default=0.0, help="per-period risk-free rate")
    p.add_argument("--format", choices=["text", "json"], default="text")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="trade-optimize",
                                 description="Markowitz portfolio optimization")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("optimize", help="compute an optimal portfolio")
    p.add_argument("--method",
                   choices=["min_variance", "max_sharpe", "risk_parity", "equal_weight"],
                   default="max_sharpe")
    _add_common(p)
    p.set_defaults(func=cmd_optimize)

    p = sub.add_parser("frontier", help="trace the efficient frontier")
    p.add_argument("--points", type=int, default=12)
    _add_common(p)
    p.set_defaults(func=cmd_frontier)

    p = sub.add_parser("allocate", help="agent-ready allocation JSON")
    p.add_argument("--method",
                   choices=["min_variance", "max_sharpe", "risk_parity", "equal_weight"],
                   default="max_sharpe")
    _add_common(p)
    p.set_defaults(func=cmd_allocate)

    p = sub.add_parser("license", help="check the license-key hook")
    p.set_defaults(func=cmd_license)
    p = sub.add_parser("update-check", help="check for a newer release")
    p.set_defaults(func=cmd_update_check)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
