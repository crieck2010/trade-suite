"""CLI: trade-decay report | evaluate | promote | register.

Recommendations only -- no subcommand touches a broker, an allocator,
or a position.  ``evaluate`` is the one that writes (append-only
JSONL events, and only on state changes); ``report`` is read-only.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import events as decay_events
from . import state_machine
from .config import load_config
from .evaluate import evaluate_all, promote
from .registry import (RegistryError, StrategySpec, find_spec,
                       load_registry, save_registry)
from .report import decay_report


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def _fmt_report(rep: dict) -> str:
    lines = [f"decay report ({rep['as_of']})",
             f"  strategies: {rep['n_strategies']}"]
    for state in ("healthy", "watchlist", "demoted", "unknown"):
        names = (rep["states"] or {}).get(state)
        if names:
            lines.append(f"  {state}: {', '.join(names)}")
    for row in rep["strategies"]:
        lines.append(f"  [{row['strategy']}] state={row['state']}")
        if row.get("error"):
            lines.append(f"    error: {row['error']}")
            continue
        lines.append(
            f"    trailing_sharpe={row['trailing_sharpe']} "
            f"(expected {row['expected_sharpe']}, "
            f"ratio {row['sharpe_ratio']}, z {row['z_score']})")
        lines.append(
            f"    half_life={row['half_life_days']}d "
            f"(r2 {row['half_life_r2']}, decaying "
            f"{row['half_life_decaying']})  "
            f"max_dd={row['max_drawdown']} (validation "
            f"{row['validation_maxdd']}, ratio {row['dd_ratio']})")
        lines.append(f"    n_daily={row['n_daily_points']} "
                     f"last={row['last_snapshot']}")
        lines.append(f"    -> {row['recommendation']}")
    return "\n".join(lines)


def _cmd_report(args) -> int:
    specs = load_registry(args.registry)
    if args.strategy:
        specs = [find_spec(specs, args.strategy)]
    thresholds = load_config(args.config)
    rep = decay_report(specs, thresholds)
    if args.format == "json":
        print(json.dumps(rep, indent=2))
    else:
        print(_fmt_report(rep))
    return 0


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------

def _cmd_evaluate(args) -> int:
    specs = load_registry(args.registry)
    thresholds = load_config(args.config)
    summary = evaluate_all(specs, thresholds, events_path=args.events,
                           config_path=args.config)
    for res in summary["results"]:
        name = res["strategy"]
        if not res.get("evaluated"):
            print(f"  [{name}] skipped: {res['reason']}")
        elif res.get("changed"):
            print(f"  [{name}] {res['previous_state']} -> {res['state']}: "
                  f"{res['recommendation']}")
        else:
            print(f"  [{name}] {res['state']} (no change): "
                  f"{res['recommendation']}")
    print(f"evaluated {summary['n_strategies']}, "
          f"{summary['n_changed']} state change(s)")
    return 0


# ---------------------------------------------------------------------------
# promote
# ---------------------------------------------------------------------------

def _cmd_promote(args) -> int:
    res = promote(args.strategy, args.reason, events_path=args.events)
    if res.get("ok"):
        print(f"{args.strategy}: demoted -> watchlist (recorded)")
        return 0
    print(f"not promoted: {res.get('note')}")
    return 1


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------

def _cmd_register(args) -> int:
    specs = load_registry(args.registry)
    if any(s.strategy_id == args.id for s in specs):
        print(f"error: {args.id} already registered", file=sys.stderr)
        return 1
    spec = StrategySpec(
        strategy_id=args.id,
        ledger_path=args.ledger,
        inception=args.inception,
        expected_sharpe=args.expected_sharpe,
        expected_sharpe_std=args.expected_sharpe_std,
        validation_maxdd=args.validation_maxdd,
        half_life_class=args.half_life_class,
        notes=args.notes or "")
    specs.append(spec)
    path = save_registry(specs, args.registry)
    print(f"registered {args.id} -> {path}")
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--registry",
                        help="registry file (default: $TRADE_DECAY_REGISTRY "
                             "or ~/.trade-decay/strategies.json)")
    parser.add_argument("--config",
                        help="config file (default: $TRADE_DECAY_CONFIG or "
                             "~/.trade-decay/config.json)")
    parser.add_argument("--events",
                        help="decay event log (default: $TRADE_DECAY_EVENTS "
                             "or ~/.trade-decay/decay-events.jsonl)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trade-decay",
        description="Live-strategy decay monitor: trailing performance vs "
                    "validation expectations.  Recommendations only -- "
                    "never touches a broker.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("report",
                       help="strategy health report (read-only)")
    _common(p)
    p.add_argument("--strategy", default=None,
                   help="report on one strategy id")
    p.add_argument("--format", default="text", choices=("text", "json"))
    p.set_defaults(func=_cmd_report)

    p = sub.add_parser("evaluate",
                       help="run the state machine; log events on changes")
    _common(p)
    p.set_defaults(func=_cmd_evaluate)

    p = sub.add_parser("promote",
                       help="operator: move a demoted strategy to watchlist")
    _common(p)
    p.add_argument("strategy", help="strategy id")
    p.add_argument("--reason", required=True,
                   help="why it deserves a second look (recorded)")
    p.set_defaults(func=_cmd_promote)

    p = sub.add_parser("register", help="add a strategy to the registry")
    _common(p)
    p.add_argument("--id", required=True)
    p.add_argument("--ledger", required=True,
                   help="trade-paper ledger path for this strategy")
    p.add_argument("--inception", required=True,
                   help="live/paper start date YYYY-MM-DD")
    p.add_argument("--expected-sharpe", type=float, required=True,
                   help="Tier-1 validation Sharpe (the expectation)")
    p.add_argument("--expected-sharpe-std", type=float, default=None,
                   help="dispersion of the validation Sharpe (for z-scores)")
    p.add_argument("--validation-maxdd", type=float, default=None,
                   help="validation max drawdown as a fraction (e.g. 0.08)")
    p.add_argument("--half-life-class", default="data-dependent",
                   choices=("market-structure", "data-dependent",
                            "timeless"))
    p.add_argument("--notes", default="")
    p.set_defaults(func=_cmd_register)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
