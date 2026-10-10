"""Command-line interface for trade-volsurface."""

from __future__ import annotations

import argparse
import csv
import json
import math

from . import __version__
from .adapters import from_option_chain, to_agent_surface
from .analytics import skew_quotes
from .arbitrage import check_surface
from .black_scholes import bs_greeks, bs_price, implied_vol
from .licensing import check_license, check_update
from .surface import VolSurface
from .svi import fit_svi_surface, raw_svi_w


def demo_quotes() -> list[dict]:
    """Synthetic SVI surface: negative skew, term-structure contango."""
    rows = []
    for T in (0.25, 0.5, 1.0, 2.0):
        a, b, rho, m, s = 0.02, 0.18, -0.45, 0.03, 0.28
        atm_w = raw_svi_w(0.0, a, b, rho, m, s)
        for i in range(-6, 7):
            k = 0.10 * i
            w = raw_svi_w(k, a, b, rho, m, s)
            rows.append({"T": T, "k": k,
                         "iv": math.sqrt(w / T) * (1 + 0.06 * math.sqrt(T))})
    return rows


def _rows_with_strikes(rows: list[dict], s0: float, r: float) -> list[dict]:
    return [{"T": q["T"], "K": s0 * math.exp(r * q["T"] + q["k"]), "iv": q["iv"]}
            for q in rows]


def load_surface(args: argparse.Namespace) -> VolSurface:
    if args.demo:
        rows = _rows_with_strikes(demo_quotes(), args.s0, args.r)
    else:
        with open(args.csv, newline="") as fh:
            rows = [{k: (float(v) if k in ("T", "K", "iv", "price") else v)
                     for k, v in row.items()} for row in csv.DictReader(fh)]
    return from_option_chain(rows, args.s0, args.r)


def cmd_iv(args: argparse.Namespace) -> int:
    iv = implied_vol(args.price, args.s0, args.K, args.T, args.r, args.kind)
    check = bs_price(args.s0, args.K, args.T, args.r, iv, args.kind)
    print(f"implied vol: {iv:.4%}  (reprices to {check:.4f})")
    return 0


def cmd_greeks(args: argparse.Namespace) -> int:
    g = bs_greeks(args.s0, args.K, args.T, args.r, args.sigma, args.kind)
    px = bs_price(args.s0, args.K, args.T, args.r, args.sigma, args.kind)
    print(f"price {px:.4f}")
    for k, v in g.items():
        print(f"{k:>6}: {v:+.4f}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    surface = load_surface(args)
    summary = to_agent_surface(surface)
    if args.format == "json":
        print(json.dumps(summary, indent=2))
        return 0
    print(f"s0={args.s0} r={args.r:.2%} expiries={surface.expiries}")
    print("ATM term structure:")
    for T, iv in surface.atm_term_structure():
        print(f"  T={T:<5} iv={iv:.2%}")
    print("Skew (25-delta):")
    for T in surface.expiries:
        q = skew_quotes(surface, T)
        print(f"  T={T:<5} RR={q['rr_25d']:+.2%}  butterfly={q['bfly_25d']:+.2%}")
    arb = summary["arbitrage"]
    print(f"arbitrage-free: {arb['arbitrage_free']} "
          f"(calendar={arb['n_calendar']}, butterfly={arb['n_butterfly']})")
    if args.fit_svi:
        fits = fit_svi_surface(surface)
        print("SVI fits:")
        for T, f in fits.items():
            print(f"  T={T:<5} rmse_iv={f.rmse_iv:.6f} rho={f.rho:+.3f}")
    return 0


def cmd_smile(args: argparse.Namespace) -> int:
    surface = load_surface(args)
    T = args.T if args.T else surface.expiries[0]
    for row in surface.smile(T):
        print(f"K={row['K']:>10.2f}  k={row['k']:+.3f}  iv={row['iv']:.2%}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    surface = load_surface(args)
    print(json.dumps(check_surface(surface), indent=2))
    return 0


def cmd_license(_args: argparse.Namespace) -> int:
    print(json.dumps(check_license(), indent=2))
    return 0


def cmd_update_check(_args: argparse.Namespace) -> int:
    print(json.dumps(check_update(), indent=2))
    return 0


def _surface_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--csv", help="chains CSV (T,K,iv | T,K,price,kind)")
    p.add_argument("--demo", action="store_true", help="synthetic SVI surface")
    p.add_argument("--s0", type=float, default=100.0)
    p.add_argument("--r", type=float, default=0.03)
    p.add_argument("--format", choices=["text", "json"], default="text")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="trade-volsurface",
                                 description="Volatility surface toolkit")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("iv", help="back out implied vol from a price")
    p.add_argument("--price", type=float, required=True)
    p.add_argument("--s0", type=float, default=100.0)
    p.add_argument("--K", type=float, default=100.0)
    p.add_argument("--T", type=float, default=1.0)
    p.add_argument("--r", type=float, default=0.03)
    p.add_argument("--kind", choices=["call", "put"], default="call")
    p.set_defaults(func=cmd_iv)

    p = sub.add_parser("greeks", help="Black-Scholes price and Greeks")
    p.add_argument("--s0", type=float, default=100.0)
    p.add_argument("--K", type=float, default=100.0)
    p.add_argument("--T", type=float, default=1.0)
    p.add_argument("--r", type=float, default=0.03)
    p.add_argument("--sigma", type=float, default=0.20)
    p.add_argument("--kind", choices=["call", "put"], default="call")
    p.set_defaults(func=cmd_greeks)

    p = sub.add_parser("build", help="build a surface and summarize it")
    _surface_args(p)
    p.add_argument("--fit-svi", action="store_true")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("smile", help="print an IV smile")
    _surface_args(p)
    p.add_argument("--T", type=float, default=0.0)
    p.set_defaults(func=cmd_smile)

    p = sub.add_parser("check", help="no-arbitrage diagnostics")
    _surface_args(p)
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("license", help="check the license-key hook")
    p.set_defaults(func=cmd_license)
    p = sub.add_parser("update-check", help="check for a newer release")
    p.set_defaults(func=cmd_update_check)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
