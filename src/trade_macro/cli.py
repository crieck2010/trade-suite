"""Command-line interface for trade-macro."""

from __future__ import annotations

import argparse
import csv
import json
import sys

from . import __version__
from .demo import demo_series, run_demo
from .indicators import list_indicators
from .licensing import check_license, check_update
from .ratio import enrich_ratios, ratio_series
from .regime import PRESETS, classify_regime, detect_transitions
from .snapshot import snapshot, snapshot_history


def _load_series(args) -> tuple[list[dict], list[dict], str]:
    if args.demo:
        s = demo_series(seed=args.seed)
        return s["copper"], s["gold"], "synthetic"
    if not (args.copper_json and args.gold_json):
        raise SystemExit("pass --demo or both --copper-json and --gold-json")
    with open(args.copper_json) as f:
        copper = json.load(f)
    with open(args.gold_json) as f:
        gold = json.load(f)
    return copper, gold, args.source


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
    if kind == "ratio":
        rows = payload["rows"]
        w.writerow(["date", "ratio", "ratio_ma50", "ratio_ma200", "roc_21", "z_252"])
        for r in rows:
            w.writerow([r["date"], r["ratio"], r["ratio_ma50"],
                        r["ratio_ma200"], r["roc_21"], r["z_252"]])
    elif kind == "regime":
        rows = payload["rows"]
        w.writerow(["date", "regime", "regime_raw", "z_252"])
        for r in rows:
            w.writerow([r["date"], r["regime"], r["regime_raw"], r["z_252"]])
    elif kind == "history":
        w.writerow(["date", "regime", "z_score", "ratio"])
        for r in payload["history"]:
            w.writerow([r["date"], r["regime"], r["z_score"], r["ratio"]])
    elif kind == "alerts":
        w.writerow(["date", "direction", "dz", "z"])
        for a in payload["alerts"]:
            w.writerow([a["date"], a["direction"], a["dz"], a["z"]])
    elif kind == "presets":
        w.writerow(["preset", "z_threshold", "persist_days",
                    "transition_dz", "transition_window"])
        for name, cfg in payload["presets"].items():
            w.writerow([name, cfg["z_threshold"], cfg["persist_days"],
                        cfg["transition_dz"], cfg["transition_window"]])
    else:  # snapshot
        s = payload["snapshot"]
        w.writerow(["field", "value"])
        for k in ("date", "indicator", "source", "preset", "regime",
                  "z_score", "ratio", "ratio_vs_200dma", "roc_21d",
                  "transition_alert"):
            w.writerow([k, s[k]])


def _emit_table(payload: dict) -> None:
    kind = payload.get("_kind", "snapshot")
    if kind == "ratio":
        print("  ".join(f"{c:>14}" for c in
                         ("date", "ratio", "ma50", "ma200", "roc_21", "z_252")))
        for r in payload["rows"]:
            print(f"{r['date']:>14}  {_fmt(r['ratio']):>14}  "
                  f"{_fmt(r['ratio_ma50']):>14}  {_fmt(r['ratio_ma200']):>14}  "
                  f"{_fmt(r['roc_21']):>14}  {_fmt(r['z_252']):>14}")
    elif kind == "regime":
        print("  ".join(f"{c:>14}" for c in ("date", "regime", "raw", "z_252")))
        for r in payload["rows"]:
            print(f"{r['date']:>14}  {r['regime']:>14}  "
                  f"{r['regime_raw']:>14}  {_fmt(r['z_252']):>14}")
    elif kind == "history":
        print("  ".join(f"{c:>14}" for c in ("date", "regime", "z", "ratio")))
        for r in payload["history"]:
            print(f"{r['date']:>14}  {r['regime']:>14}  "
                  f"{_fmt(r['z_score']):>14}  {_fmt(r['ratio']):>14}")
    elif kind == "alerts":
        if not payload["alerts"]:
            print("no transition alerts")
        for a in payload["alerts"]:
            print(f"{a['date']}  {a['direction']:<15} dz={a['dz']:+.2f} z={a['z']:+.2f}")
    elif kind == "presets":
        for name, cfg in payload["presets"].items():
            print(f"{name:<10} z>{cfg['z_threshold']}  persist={cfg['persist_days']}d  "
                  f"alert_dz>{cfg['transition_dz']}  window={cfg['transition_window']}d")
    else:  # snapshot
        s = payload["snapshot"]
        for k in ("date", "indicator", "source", "preset", "regime", "z_score",
                  "ratio", "ratio_vs_200dma", "roc_21d", "transition_alert"):
            print(f"{k:<18} {_fmt(s[k])}")
        if s["transition"]:
            t = s["transition"]
            print(f"{'transition':<18} {t['direction']} (dz={t['dz']:+.2f})")


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--demo", action="store_true", help="use seeded demo series")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--copper-json", help="JSON file with copper series")
    p.add_argument("--gold-json", help="JSON file with gold series")
    p.add_argument("--preset", default="standard", choices=sorted(PRESETS))
    p.add_argument("--source", default="futures")
    p.add_argument("--format", default="table", choices=("table", "json", "csv"))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trade-macro",
                                description="Copper:gold macro regime engine")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("snapshot", help="latest (or dated) regime snapshot")
    _add_common(s)
    s.add_argument("--date", help="historical snapshot date YYYY-MM-DD")

    s = sub.add_parser("ratio", help="ratio panel with trailing statistics")
    _add_common(s)
    s.add_argument("--start", help="first date YYYY-MM-DD")
    s.add_argument("--limit", type=int, default=5)

    s = sub.add_parser("regime", help="regime panel + transition alerts")
    _add_common(s)
    s.add_argument("--start", help="first date YYYY-MM-DD")
    s.add_argument("--limit", type=int, default=5)

    s = sub.add_parser("history", help="per-date regime history")
    _add_common(s)
    s.add_argument("--limit", type=int, default=5)

    s = sub.add_parser("presets", help="show threshold presets")

    s = sub.add_parser("license", help="license-key hook status")
    s = sub.add_parser("update-check", help="check GitHub for a newer release")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fmt = getattr(args, "format", "table")

    if args.cmd == "presets":
        return _emit({"_kind": "presets", "presets": PRESETS}, fmt)
    if args.cmd == "license":
        info = check_license()
        if fmt == "json":
            print(json.dumps(info, indent=2))
        else:
            for k, v in info.items():
                print(f"{k:<12} {v}")
        return 0
    if args.cmd == "update-check":
        print(json.dumps(check_update(), indent=2))
        return 0

    copper, gold, source = _load_series(args)
    src = source if args.demo else args.source

    if args.cmd == "snapshot":
        snap = snapshot(copper, gold, date=args.date, preset=args.preset,
                        source=src)
        return _emit({"_kind": "snapshot", "snapshot": snap}, fmt)

    rows = enrich_ratios(ratio_series(copper, gold))
    if args.cmd == "ratio":
        rows = [r for r in rows
                if args.start is None or r["date"] >= args.start][-args.limit:]
        return _emit({"_kind": "ratio", "rows": rows}, fmt)

    if args.cmd == "regime":
        rows = classify_regime(rows, preset=args.preset)
        alerts = detect_transitions(rows, preset=args.preset)
        rows = [r for r in rows
                if args.start is None or r["date"] >= args.start][-args.limit:]
        payload = {"_kind": "regime", "rows": rows}
        if fmt == "json":
            payload["alerts"] = alerts
        elif fmt == "table":
            print("--- transition alerts ---")
            for a in alerts:
                print(f"{a['date']}  {a['direction']:<15} "
                      f"dz={a['dz']:+.2f} z={a['z']:+.2f}")
            if not alerts:
                print("none")
            print("--- regime panel ---")
        return _emit(payload, fmt)

    if args.cmd == "history":
        hist = snapshot_history(copper, gold, preset=args.preset, source=src,
                                limit=args.limit)
        hist["_kind"] = "history"
        return _emit(hist, fmt)

    raise AssertionError(f"unhandled command {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
