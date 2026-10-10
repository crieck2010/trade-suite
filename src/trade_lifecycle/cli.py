"""trade-lifecycle CLI: the investment committee on the command line."""

from __future__ import annotations

import argparse
import json
import os

from . import adapters
from .demo import run_demo
from .licensing import check_license, check_update
from .presets import PRESETS, get_preset
from .registry import StrategyRegistry

DEFAULT_REGISTRY = os.environ.get(
    "TRADE_LIFECYCLE_REGISTRY",
    os.path.expanduser("~/.trade-lifecycle/registry.jsonl"))


# ------------------------------------------------------------------ helpers

def _emit(payload: dict, as_json: bool) -> int:
    print(json.dumps(payload, indent=2, default=str))
    return 0


def _table(rows: list[list[str]]) -> None:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)))


def _registry(args) -> StrategyRegistry:
    return StrategyRegistry(args.registry)


def _load_json(path: str | None) -> dict | None:
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _approval(args) -> dict | None:
    if not args.approver and not args.rationale:
        return None
    return {"approver": args.approver or "", "at": _now_iso(),
            "rationale": args.rationale or ""}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _verdict(result: dict, as_json: bool) -> int:
    """Print a TransitionResult; refusals exit non-zero."""
    if as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        mark = "ALLOWED" if result["allowed"] else "REFUSED"
        print(f"{mark}: {result['from']} -> {result['to']} (actor: {result['actor']})")
        for reason in result["reasons"]:
            print(f"  - {reason}")
    return 0 if result["allowed"] else 2


# ------------------------------------------------------------------ commands

def cmd_register(args) -> int:
    reg = _registry(args)
    config = _load_json(args.config) or {}
    try:
        out = reg.register(args.id, args.name, args.family, config,
                           policy_id=args.policy_id, actor=args.actor)
    except ValueError as exc:
        print(f"error: {exc}")
        return 2
    return _emit(out, args.json)


def cmd_promote(args) -> int:
    reg = _registry(args)
    preset = get_preset(args.preset)
    kwargs: dict = {"preset": preset}
    if args.report:
        kwargs["report"] = _load_json(args.report)
    approval = _approval(args)
    if approval:
        kwargs["approval"] = approval
    if args.to == "PAPER":
        kwargs["incubation_enrolled"] = True if args.enrolled else (
            None if args.enrolled is None else False)
        # tri-state: --enrolled / --not-enrolled / neither (adapter decides)
    if args.to == "LIVE":
        kwargs["graduated"] = True if args.graduated else (
            None if args.graduated is None else False)
        kwargs["mode"] = args.mode
        kwargs["policy_dirs"] = args.policy_dir or []
    if args.reason:
        kwargs["reason"] = args.reason
    result = reg.promote(args.id, args.to, actor=args.actor, **kwargs)
    return _verdict(result, args.json)


def cmd_status(args) -> int:
    reg = _registry(args)
    st = reg.status(args.id)
    if st is None:
        print(f"error: unknown strategy {args.id!r}")
        return 2
    if args.json:
        return _emit(st, True)
    paused = f" (PAUSED: {st['paused_reason']})" if st["paused"] else ""
    print(f"{st['strategy_id']}: {st['state']}{paused}")
    print(f"  name: {st['name']}  family: {st['family']}")
    print(f"  config_hash: {st['config_hash'][:16]}...  policy: {st['policy_id']}")
    print(f"  approvals recorded: {st['approvals']}")
    return 0


def cmd_history(args) -> int:
    reg = _registry(args)
    evs = reg.history(args.id, refusals_only=args.refusals_only)
    if args.json:
        return _emit({"strategy_id": args.id, "events": evs}, True)
    rows = [["ts", "event", "detail"]]
    for e in evs:
        kind = e.get("event", "")
        res = e.get("result") or {}
        detail = ""
        if kind == "transition":
            detail = f"{res.get('from')}->{res.get('to')}"
        elif kind == "refusal":
            detail = f"REFUSED {res.get('from')}->{res.get('to')}"
        elif kind == "registered":
            detail = f"registered by {e.get('actor')}"
        rows.append([str(e.get("ts", ""))[:19], kind, detail])
    _table(rows)
    return 0


def cmd_pause(args) -> int:
    reg = _registry(args)
    result = reg.pause(args.id, reason=args.reason, actor=args.actor)
    return _verdict(result, args.json)


def cmd_resume(args) -> int:
    reg = _registry(args)
    approval = _approval(args)
    result = reg.resume(args.id, approval=approval, actor=args.actor)
    return _verdict(result, args.json)


def cmd_retire(args) -> int:
    reg = _registry(args)
    result = reg.retire(args.id, reason=args.reason, actor=args.actor)
    return _verdict(result, args.json)


def cmd_demo(args) -> int:
    summary = run_demo(seed=args.seed)
    if args.json:
        return _emit(summary, True)
    for line in summary["theater"]:
        print(line)
    print()
    for sid, st in summary["final_states"].items():
        paused = " (PAUSED)" if st["paused"] else ""
        print(f"{sid}: {st['state']}{paused}")
    print(f"\nRefusals logged: {summary['n_refusals']}")
    return 0


def cmd_presets(args) -> int:
    if args.json:
        return _emit({n: p for n, p in PRESETS.items()}, True)
    rows = [["preset", "allow_warns", "max_age_days", "distinct_approver", "description"]]
    for name, p in PRESETS.items():
        rows.append([name, str(p["allow_warns"]), str(p["max_age_days"]),
                     str(p["require_distinct_approver"]), p["description"]])
    _table(rows)
    return 0


def cmd_license(args) -> int:
    return _emit(check_license(args.key), args.json)


def cmd_update_check(args) -> int:
    return _emit(check_update(), args.json)


# ------------------------------------------------------------------ parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trade-lifecycle",
                                description="The investment committee in code: "
                                            "strategy lifecycle + promotion gates.")
    p.add_argument("--registry", default=DEFAULT_REGISTRY,
                   help="Path to the JSONL registry (default: %(default)s).")
    p.add_argument("--actor", default="human", help="Actor recorded in the audit log.")
    p.add_argument("--json", action="store_true", help="JSON output.")
    sub = p.add_subparsers(dest="command", required=True)

    def _sp(*a, **k):
        s = sub.add_parser(*a, **k)
        s.add_argument("--json", action="store_true", help="JSON output.")
        return s

    r = _sp("register", help="Register a strategy in RESEARCH.")
    r.add_argument("--id", required=True)
    r.add_argument("--name", default="")
    r.add_argument("--family", default="")
    r.add_argument("--config", help="Path to a JSON config file.")
    r.add_argument("--policy-id", default=None)
    r.set_defaults(func=cmd_register)

    pr = _sp("promote", help="Attempt a lifecycle transition.")
    pr.add_argument("id")
    pr.add_argument("--to", required=True,
                    help="Target: VALIDATED, PAPER, LIVE, PAUSED, RESUME, RETIRED.")
    pr.add_argument("--preset", default="strict", choices=sorted(PRESETS))
    pr.add_argument("--report", help="Path to a ValidationReport JSON.")
    pr.add_argument("--approver", default="")
    pr.add_argument("--rationale", default="")
    pr.add_argument("--enrolled", dest="enrolled", action="store_true", default=None)
    pr.add_argument("--not-enrolled", dest="enrolled", action="store_false")
    pr.add_argument("--graduated", dest="graduated", action="store_true", default=None)
    pr.add_argument("--not-graduated", dest="graduated", action="store_false")
    pr.add_argument("--mode", default=None, choices=["supervised", "autonomous"])
    pr.add_argument("--policy-dir", action="append", default=[])
    pr.add_argument("--reason", default="",
                    help="Reason (for PAUSED / RETIRED targets).")
    pr.set_defaults(func=cmd_promote)

    s = _sp("status", help="Show a strategy's lifecycle state.")
    s.add_argument("id")
    s.set_defaults(func=cmd_status)

    h = _sp("history", help="Show the audit trail for a strategy.")
    h.add_argument("id")
    h.add_argument("--refusals-only", action="store_true")
    h.set_defaults(func=cmd_history)

    pa = _sp("pause", help="Pause a strategy (overlay).")
    pa.add_argument("id")
    pa.add_argument("--reason", default="")
    pa.set_defaults(func=cmd_pause)

    re = _sp("resume", help="Resume a paused strategy (re-approval required).")
    re.add_argument("id")
    re.add_argument("--approver", default="")
    re.add_argument("--rationale", default="")
    re.set_defaults(func=cmd_resume)

    rt = _sp("retire", help="Retire a strategy (terminal).")
    rt.add_argument("id")
    rt.add_argument("--reason", default="")
    rt.set_defaults(func=cmd_retire)

    d = _sp("demo", help="Run the seeded lifecycle theater.")
    d.add_argument("--seed", type=int, default=7)
    d.set_defaults(func=cmd_demo)

    prs = _sp("presets", help="List gate strictness profiles.")
    prs.set_defaults(func=cmd_presets)

    lic = _sp("license", help="Check the license-key hook.")
    lic.add_argument("--key", default=None)
    lic.set_defaults(func=cmd_license)

    up = _sp("update-check", help="Check for a newer release.")
    up.set_defaults(func=cmd_update_check)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
