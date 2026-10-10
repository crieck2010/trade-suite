"""Command-line interface for trade-hedge."""

from __future__ import annotations

import argparse
import csv
import json
import sys

from . import __version__
from .adapters import proposals_to_paper_payloads
from .demo import demo_drift_breach, demo_stale_data, demo_vol_regime_shift
from .exposures import compute_exposures
from .hedges import propose_hedges
from .licensing import check_license, check_update
from .presets import DEFAULT_CONFIG, PRESETS, describe_presets
from .scheduler import LoopState, run_cycle

DEMOS = {
    "drift": demo_drift_breach,
    "vol": demo_vol_regime_shift,
    "stale": demo_stale_data,
}


def load_scenario(args) -> tuple[dict, dict, dict]:
    if args.demo:
        fn = DEMOS.get(args.demo)
        if fn is None:
            raise SystemExit(f"unknown demo {args.demo!r}; expected one of {sorted(DEMOS)}")
        return fn(seed=args.seed)
    if args.positions and args.prices:
        positions = [{"symbol": s, "qty": float(q)}
                     for s, q in (p.split("=") for p in args.positions)]
        prices = {s: float(p) for s, p in (p.split("=") for p in args.prices)}
        portfolio_state = {"positions": positions,
                           "equity": args.equity, "peak_equity": args.equity}
        import datetime
        market_state = {"prices": prices,
                        "as_of": datetime.datetime.now(
                            tz=datetime.timezone.utc).isoformat()}
        return portfolio_state, market_state, dict(DEFAULT_CONFIG)
    raise SystemExit("give --demo NAME or both --positions SYM=QTY... and --prices SYM=PX...")


def apply_preset(config: dict, args) -> dict:
    if args.preset:
        preset = PRESETS.get(args.preset)
        if preset is None:
            raise SystemExit(f"unknown preset {args.preset!r}; expected one of {sorted(PRESETS)}")
        config = dict(preset)
    if args.set:
        for item in args.set:
            k, _, v = item.partition("=")
            try:
                v2: object = float(v)
            except ValueError:
                v2 = v
            config[k] = v2
    return config


def _fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:,.4f}"
    return str(v)


def _emit(payload: dict, fmt: str) -> int:
    if fmt == "json":
        print(json.dumps(payload, indent=2, default=str))
    elif fmt == "csv":
        _emit_csv(payload)
    else:
        _emit_table(payload)
    return 0


def _emit_table(payload: dict) -> None:
    kind = payload.get("_kind")
    if kind == "exposures":
        e = payload["exposures"]
        print(f'{"metric":<34}{"value":>16}')
        for k in ("n_positions", "net_delta_dollars", "net_delta_dollars_beta_adj",
                  "net_delta_frac_beta_adj", "gross_dollars", "gross_frac",
                  "net_frac", "herfindahl", "top_n_share"):
            print(f"{k:<34}{_fmt(e.get(k)):>16}")
        print(f'\n{"symbol":<8}{"qty":>12}{"price":>12}{"value":>14}{"beta":>8}')
        for sym, s in e["per_symbol"].items():
            print(f'{sym:<8}{s["qty"]:>12,.2f}{s["price"]:>12,.2f}'
                  f'{s["value"]:>14,.2f}{s["beta"]:>8.2f}')
    elif kind == "cycle":
        print(f"halted: {payload['halted']}")
        for a in payload["alerts"]:
            print(f"  ! {a}")
        print(f'proposals: {len(payload["proposals"])}')
        for p in payload["proposals"]:
            print(f'  [{p["rule_id"]}] {p["action"]} {p.get("instrument") or ""} '
                  f'{_fmt(p.get("qty"))} — {p["reason"]}')
        print(f'{"rule":<14}{"evaluated":>10}{"detail":<40}')
        for rid, d in payload["diagnostics"].items():
            print(f'{rid:<14}{str(d.get("evaluated")):>10}  {d.get("reason",""):<40}')
    elif kind == "presets":
        print(f'{"preset":<14}{"differs from default"}')
        for r in payload["presets"]:
            diff = ", ".join(f"{k}={v}" for k, v in r["differs_from_default"].items())
            print(f'{r["name"]:<14}{diff}')
    else:
        print(json.dumps(payload, indent=2, default=str))


def _emit_csv(payload: dict) -> None:
    w = csv.writer(sys.stdout)
    kind = payload.get("_kind")
    if kind == "exposures":
        w.writerow(["symbol", "qty", "price", "value", "beta", "beta_adj_delta"])
        for sym, s in payload["exposures"]["per_symbol"].items():
            w.writerow([sym, s["qty"], s["price"], s["value"], s["beta"],
                        s["beta_adj_delta"]])
    elif kind == "cycle":
        w.writerow(["rule_id", "action", "instrument", "qty", "reason"])
        for p in payload["proposals"]:
            w.writerow([p["rule_id"], p["action"], p.get("instrument"),
                        p.get("qty"), p["reason"]])
    elif kind == "presets":
        w.writerow(["preset", "key", "value"])
        for r in payload["presets"]:
            for k, v in r["differs_from_default"].items():
                w.writerow([r["name"], k, v])
    else:
        w.writerow(["field", "value"])
        for k, v in payload.items():
            if k != "_kind":
                w.writerow([k, v])


def cmd_exposures(args) -> int:
    portfolio_state, market_state, config = load_scenario(args)
    config = apply_preset(config, args)
    exposures = compute_exposures(portfolio_state["positions"],
                                  market_state["prices"], config)
    return _emit({"_kind": "exposures", "exposures": exposures}, args.format)


def cmd_propose(args) -> int:
    portfolio_state, market_state, config = load_scenario(args)
    config = apply_preset(config, args)
    result = run_cycle(portfolio_state, market_state, config, LoopState())
    if args.submit:
        payloads = proposals_to_paper_payloads(result["proposals"])
        print("# SUBMIT MODE: the payloads below are shaped for trade-paper's")
        print("# approval queue. Nothing is sent anywhere — the user approves")
        print("# each proposal in trade-paper. Paper-trading only.")
        print(json.dumps(payloads, indent=2, default=str))
        return 0
    print("# DRY RUN (default): proposals are computed, nothing is emitted anywhere.")
    print("# Re-run with --submit to see the trade-paper approval-queue payloads.")
    return _emit({"_kind": "cycle", **result}, args.format)


def cmd_presets(args) -> int:
    return _emit({"_kind": "presets", "presets": describe_presets()}, args.format)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="trade-hedge",
                                 description="Auto-hedging loop: keep the portfolio inside its risk limits.")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--demo", choices=sorted(DEMOS),
                       help="seeded demo scenario: drift|vol|stale")
        p.add_argument("--positions", nargs="*", metavar="SYM=QTY")
        p.add_argument("--prices", nargs="*", metavar="SYM=PX")
        p.add_argument("--equity", type=float, default=100_000.0)
        p.add_argument("--preset", choices=sorted(PRESETS),
                       help="hedge config preset")
        p.add_argument("--set", nargs="*", metavar="KEY=VALUE",
                       help="override individual config keys")
        p.add_argument("--seed", type=int, default=7)
        p.add_argument("--format", choices=["table", "json", "csv"], default="table")

    p = sub.add_parser("exposures", help="measure portfolio exposures")
    common(p); p.set_defaults(fn=cmd_exposures)

    p = sub.add_parser("propose", help="run one hedge-loop cycle (dry-run by default)")
    common(p)
    p.add_argument("--submit", action="store_true",
                   help="print the trade-paper approval-queue payloads instead of the dry-run report")
    p.set_defaults(fn=cmd_propose)

    p = sub.add_parser("presets", help="list hedge config presets")
    p.add_argument("--format", choices=["table", "json", "csv"], default="table")
    p.set_defaults(fn=cmd_presets)

    p = sub.add_parser("license", help="license-key hook (stubbed)")
    p.set_defaults(fn=lambda a: (print(json.dumps(check_license(), indent=2)), 0)[1])

    p = sub.add_parser("update-check", help="check for a newer release")
    p.set_defaults(fn=lambda a: (print(json.dumps(check_update(), indent=2)), 0)[1])
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
