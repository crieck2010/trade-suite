"""trade-incubate CLI: the paper-quarter program on the command line."""

from __future__ import annotations

import argparse
import json

from . import adapters
from .demo import run_demo, EXPECTATIONS
from .digest import render_digest
from .drift import compare
from .ledger import IncubationLedger
from .licensing import check_license, check_update
from .presets import PRESETS, get_preset
from .program import IncubationProgram, ProgramConfig, stage_for


# ---------------------------------------------------------------- helpers

def _emit(payload: dict, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(json.dumps(payload, indent=2, default=str))
    return 0


def _table(rows: list[list[str]]) -> None:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)))


# ---------------------------------------------------------------- commands

def cmd_start(args) -> int:
    """Begin a new incubation run (prints the program card; nothing executes)."""
    cfg = get_preset(args.preset)
    prog = IncubationProgram(strategy_name=args.strategy,
                             backtest={"sharpe": args.backtest_sharpe,
                                       "max_drawdown": args.backtest_dd,
                                       "n_trades": 500},
                             config=cfg)
    return _emit({
        "strategy": prog.strategy_name,
        "preset": args.preset,
        "stages": {"WARMUP": "days 1-10 (half size)",
                   "OBSERVATION": "days 11-40",
                   "GRADUATION_REVIEW": "days 41-63"},
        "graduation": {
            "sharpe_tolerance": cfg.sharpe_tolerance,
            "dd_multiple": cfg.dd_multiple,
            "min_trades": cfg.min_trades,
        },
        "kill": {"kill_dd_multiple": cfg.kill_dd_multiple,
                 "drift_violation_pauses": True},
        "note": "Paper only. Dry-run default. Nothing here trades live.",
    }, args.json)


def cmd_status(args) -> int:
    ledger = IncubationLedger(args.ledger)
    last = ledger.last()
    if not last:
        print("no incubation days recorded yet (see `demo` or the runner)")
        return 0
    return _emit({"day": last["day"], "stage": last["stage"],
                  "equity": last["equity"], "drift": last["drift"],
                  "verdict": last["verdict"]}, args.json)


def cmd_digest(args) -> int:
    ledger = IncubationLedger(args.ledger)
    days = ledger.days()
    if not days:
        print("no incubation days recorded yet")
        return 0
    rec = days[-1] if args.date is None else next(
        (d for d in days if d["date"] == args.date), None)
    if rec is None:
        print(f"no record for date {args.date}")
        return 1
    prev_eq = days[days.index(rec) - 1]["equity"] if days.index(rec) > 0 else rec["equity"]
    from .digest import build_digest
    d = build_digest(strategy=rec.get("strategy", "?"), day=rec["day"],
                     stage=rec["stage"], equity=rec["equity"],
                     start_equity=args.start_equity,
                     day_pnl=rec["equity"] - prev_eq,
                     positions=rec.get("positions", []),
                     conviction=rec.get("regime_conviction"),
                     drift=rec.get("drift", "?"), pending_approvals=0,
                     paused=rec["verdict"].get("paused", False),
                     kill_trips=rec["verdict"].get("kill_trips_today", []))
    if args.json:
        return _emit(d, True)
    print(render_digest(d))
    return 0


def cmd_drift(args) -> int:
    ledger = IncubationLedger(args.ledger)
    if not ledger.days():
        print("no incubation days recorded yet")
        return 0
    result = compare(EXPECTATIONS, ledger.equity_curve(), ledger.closed_trades())
    if args.json:
        return _emit(result, True)
    print(f"drift verdict: {result['verdict']}  ({result['n_trades']} trades)")
    for line in result["details"]:
        print(f"  {line}")
    print(f"  note: {result['note']}")
    return 0


def cmd_graduate(args) -> int:
    ledger = IncubationLedger(args.ledger)
    if not ledger.days():
        print("no incubation days recorded yet")
        return 0
    from .drift import paper_stats
    prog = IncubationProgram(strategy_name=args.strategy,
                             backtest={"sharpe": args.backtest_sharpe,
                                       "max_drawdown": args.backtest_dd,
                                       "n_trades": 500},
                             config=get_preset(args.preset))
    prog.day = len(ledger.days())
    stats = paper_stats(ledger.equity_curve(), ledger.closed_trades())
    result = prog.graduate(stats)
    if args.json:
        return _emit(result, True)
    for name, c in result["criteria"].items():
        mark = "PASS" if c["pass"] else "FAIL"
        print(f"  [{mark}] {name}: {c['detail']}")
    print(f"graduated: {result['graduated']}")
    return 0


def cmd_demo(args) -> int:
    arc = run_demo(seed=args.seed)
    if args.json:
        return _emit({k: v for k, v in arc.items() if k != "digest_text"}, True)
    print(f"seed {arc['seed']}: {arc['days_run']} days, "
          f"paused={arc['paused']} (day {arc['paused_day']}), "
          f"final equity ${arc['final_equity']:,.2f}, {arc['n_trades']} trades")
    tail = arc["drift_history"][38:]
    # compress consecutive duplicates for readability
    comp = []
    for v in tail:
        if not comp or comp[-1] != v:
            comp.append(v)
    print("drift arc from day 39: " + " -> ".join(comp))
    for k in arc["kill_trips"]:
        print(f"  kill: day {k['day']} {k['condition']} — {k['detail']}")
    print()
    print(arc["digest_text"])
    return 0


def cmd_presets(args) -> int:
    if args.json:
        return _emit({k: {"description": v["description"]} for k, v in PRESETS.items()}, True)
    _table([["preset", "description"]] +
           [[k, v["description"]] for k, v in PRESETS.items()])
    return 0


# ---------------------------------------------------------------- main

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trade-incubate",
                                description="Paper-trading incubation program.")
    json_parent = argparse.ArgumentParser(add_help=False)
    json_parent.add_argument("--json", action="store_true", help="JSON output")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start", parents=[json_parent], help="Begin a new incubation program")
    s.add_argument("--strategy", default="swing-trend")
    s.add_argument("--preset", default="balanced", choices=sorted(PRESETS))
    s.add_argument("--backtest-sharpe", type=float, default=1.2)
    s.add_argument("--backtest-dd", type=float, default=0.06)
    s.set_defaults(func=cmd_start)

    s = sub.add_parser("status", parents=[json_parent], help="Latest incubation status from the ledger")
    s.add_argument("--ledger", default="incubation.jsonl")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("digest", parents=[json_parent], help="Render the daily digest")
    s.add_argument("--ledger", default="incubation.jsonl")
    s.add_argument("--date", default=None)
    s.add_argument("--start-equity", type=float, default=100_000.0)
    s.set_defaults(func=cmd_digest)

    s = sub.add_parser("drift", parents=[json_parent], help="Drift check on the recorded track record")
    s.add_argument("--ledger", default="incubation.jsonl")
    s.set_defaults(func=cmd_drift)

    s = sub.add_parser("graduate", parents=[json_parent], help="Evaluate graduation criteria")
    s.add_argument("--ledger", default="incubation.jsonl")
    s.add_argument("--strategy", default="swing-trend")
    s.add_argument("--preset", default="balanced", choices=sorted(PRESETS))
    s.add_argument("--backtest-sharpe", type=float, default=1.2)
    s.add_argument("--backtest-dd", type=float, default=0.06)
    s.set_defaults(func=cmd_graduate)

    s = sub.add_parser("demo", parents=[json_parent], help="Seeded 63-day incubation arc")
    s.add_argument("--seed", type=int, default=7)
    s.set_defaults(func=cmd_demo)

    s = sub.add_parser("presets", parents=[json_parent], help="List incubation presets")
    s.set_defaults(func=cmd_presets)

    s = sub.add_parser("license", parents=[json_parent], help="License status")
    s.set_defaults(func=lambda a: _emit(check_license(), a.json))
    s = sub.add_parser("update-check", parents=[json_parent], help="Check for a newer release")
    s.set_defaults(func=lambda a: _emit(check_update(), a.json))
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
