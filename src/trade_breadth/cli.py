"""Command-line interface for trade-breadth."""

from __future__ import annotations

import argparse
import csv
import json
import sys

from . import __version__
from .breadth import breadth_panel
from .demo import run_demo
from .licensing import check_license, check_update
from .regime import PRESETS
from .snapshot import snapshot, snapshot_history
from .thrusts import detect_narrowing_warnings, detect_thrusts
from .universe import demo_universe


def _load_universe(args) -> tuple[dict, dict | None]:
    if args.demo:
        return demo_universe(seed=args.seed)
    with open(args.universe_json) as f:
        data = json.load(f)
    if isinstance(data, dict) and "universe" in data:
        return data["universe"], data.get("weights")
    return data, None


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


def _emit_csv(payload: dict) -> None:
    kind = payload.get("_kind", "snapshot")
    w = csv.writer(sys.stdout)
    if kind == "panel":
        rows = payload["rows"]
        w.writerow(list(rows[0].keys()))
        for r in rows:
            w.writerow([r[k] for k in rows[0].keys()])
    elif kind == "history":
        w.writerow(["date", "regime", "regime_score", "fragility"])
        for r in payload["history"]:
            w.writerow([r["date"], r["regime"], r["regime_score"], r["fragility"]])
    elif kind == "thrusts":
        w.writerow(["date", "type", "pct_above_50dma", "magnitude"])
        for t in payload["thrusts"]:
            w.writerow([t["date"], t["type"], t.get("pct_above_50dma"), t.get("magnitude")])
    else:  # snapshot
        s = payload["snapshot"]
        w.writerow(["field", "value"])
        for k in ("date", "regime", "regime_score", "fragility"):
            w.writerow([k, s[k]])
        for k, v in s["indicators"].items():
            w.writerow([f"indicator:{k}", v])


def _emit_table(payload: dict) -> None:
    kind = payload.get("_kind", "snapshot")
    if kind == "panel":
        rows = payload["rows"]
        cols = ["date", "advancers", "decliners", "pct_above_50dma",
                "highs_minus_lows", "mcclellan_oscillator", "ew_cw_ratio"]
        print("  ".join(f"{c:>18}" for c in cols))
        for r in rows:
            print("  ".join(f"{_fmt(r.get(c)):>18}" for c in cols))
    elif kind == "history":
        print(f'{"date":<12}{"regime":<12}{"score":>10}{"fragility":>10}')
        for r in payload["history"]:
            print(f'{r["date"]:<12}{r["regime"]:<12}'
                  f'{_fmt(r["regime_score"]):>10}{_fmt(r["fragility"]):>10}')
    elif kind == "thrusts":
        if not payload["thrusts"]:
            print("no breadth thrusts detected")
        for t in payload["thrusts"]:
            print(f'{t["date"]}  {t["type"]}  magnitude={_fmt(t.get("magnitude"))}')
        if payload["warnings"]:
            print("warnings:")
            for x in payload["warnings"]:
                print(f'  {x["date"]}  {x["type"]}: {x["detail"]}')
    else:  # snapshot
        s = payload["snapshot"]
        print(f'date:      {s["date"]}')
        print(f'regime:    {s["regime"]}  (score {_fmt(s["regime_score"])})')
        print(f'fragility: {_fmt(s["fragility"])}')
        for k, v in s["indicators"].items():
            print(f'  {k:<24}{_fmt(v)}')
        if s["thrusts_recent"]:
            print("recent thrusts:")
            for t in s["thrusts_recent"]:
                print(f'  {t["date"]}  magnitude={_fmt(t.get("magnitude"))}')
        for x in s["warnings"]:
            print(f'warning: {x["type"]}: {x["detail"]}')


def _add_source(p: argparse.ArgumentParser) -> None:
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--demo", action="store_true",
                     help="seeded 60-symbol demo universe (no network)")
    src.add_argument("--universe-json",
                     help="JSON file: {symbol: [bars]} or {universe:..., weights:...}")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--preset", choices=sorted(PRESETS), default="standard")
    p.add_argument("--format", choices=["table", "json", "csv"], default="table")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trade-breadth",
                                 description="US equity market-breadth engine")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("snapshot", help="dated regime snapshot (the interop contract)")
    _add_source(s)
    s.add_argument("--date", help="historical snapshot date (YYYY-MM-DD)")

    s = sub.add_parser("panel", help="daily breadth panel")
    _add_source(s)
    s.add_argument("--days", type=int, default=20, help="trailing days to show")

    s = sub.add_parser("thrusts", help="breadth thrusts + narrowing warnings")
    _add_source(s)

    s = sub.add_parser("history", help="regime/fragility history")
    _add_source(s)
    s.add_argument("--days", type=int, default=60, help="trailing days to show")

    s = sub.add_parser("presets", help="list regime-threshold presets")

    sub.add_parser("license", help="license-key hook (stub)")
    sub.add_parser("update-check", help="check for a newer release")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "license":
        print(json.dumps(check_license(), indent=2))
        return 0
    if args.cmd == "update-check":
        print(json.dumps(check_update(), indent=2))
        return 0
    if args.cmd == "presets":
        for name, cfg in PRESETS.items():
            print(f"{name:<10} up={cfg['up']:+.2f} down={cfg['down']:+.2f} "
                  f"z_lookback={cfg['z_lookback']} min_history={cfg['min_history']}")
        return 0

    universe, weights = _load_universe(args)
    fmt = args.format
    if args.cmd == "snapshot":
        snap = snapshot(universe, weights=weights, date=args.date, preset=args.preset)
        return _emit({"_kind": "snapshot", "snapshot": snap}, fmt)
    if args.cmd == "panel":
        panel = breadth_panel(universe, weights=weights)
        return _emit({"_kind": "panel", "rows": panel[-args.days:]}, fmt)
    if args.cmd == "thrusts":
        panel = breadth_panel(universe, weights=weights)
        return _emit({"_kind": "thrusts",
                      "thrusts": detect_thrusts(panel),
                      "warnings": detect_narrowing_warnings(panel)}, fmt)
    if args.cmd == "history":
        hist = snapshot_history(universe, weights=weights, preset=args.preset)
        return _emit({"_kind": "history", "history": hist[-args.days:]}, fmt)
    raise AssertionError("unreachable")
