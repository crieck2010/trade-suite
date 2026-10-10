"""trade-mandate CLI: the constitution on the command line."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import adapters
from .amend import MandateStore
from .demo import run_demo
from .licensing import check_license, check_update
from .mandate import new_mandate, render_markdown
from .templates import PHILOSOPHY, get_preset, preset_names
from .validate import check


def _emit(payload: dict, as_json: bool) -> int:
    print(json.dumps(payload, indent=2, default=str))
    return 0


def _table(rows: list[list[str]]) -> None:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)))


def _store(args) -> MandateStore:
    return MandateStore(args.store)


# ---------------------------------------------------------------- commands

def cmd_new(args) -> int:
    """Ratify a fresh mandate from a preset (sign-off required)."""
    store = _store(args)
    try:
        result = store.create(
            args.policy_id, approver=args.approver, rationale=args.rationale,
            effective_date=args.effective_date, **get_preset(args.preset))
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    return _emit({**result, "note": "mandate ratified; .json + .md written"},
                 args.json)


def cmd_show(args) -> int:
    """Print the current mandate (JSON or rendered markdown)."""
    store = _store(args)
    try:
        mandate = store.load(args.policy_id)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.markdown:
        print(render_markdown(mandate))
        return 0
    return _emit(mandate, args.json)


def cmd_check(args) -> int:
    """Check a proposal JSON file against the mandate.  Refusals exit 1."""
    store = _store(args)
    try:
        mandate = store.load(args.policy_id)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    with open(args.proposal) as fh:
        proposal = json.load(fh)
    result = check(mandate, proposal)
    if not args.json:
        if result["allowed"]:
            print(f"ALLOWED — mandate v{mandate['version']} "
                  f"({args.policy_id}), "
                  f"gross leverage {result['resulting_gross_leverage']:.2f}x")
        else:
            print(f"REFUSED — {len(result['violations'])} violation(s):")
            _table([["RULE", "DETAIL"]] + [
                [v["rule"], v["detail"]] for v in result["violations"]])
        for note in result["notes"]:
            print(f"note: {note}")
        return 0 if result["allowed"] else 1
    code = _emit(result, True)
    return code if result["allowed"] else 1


def cmd_amend(args) -> int:
    """Propose an amendment, or ratify a pending one with sign-off."""
    store = _store(args)
    try:
        if args.ratify:
            result = store.ratify(args.policy_id, args.ratify,
                                  approver=args.approver,
                                  rationale=args.rationale,
                                  effective_date=args.effective_date)
            return _emit({**result, "note": "amendment ratified"},
                         args.json)
        changes = json.loads(args.changes)
        amendment = store.propose_amendment(args.policy_id, changes,
                                            proposer=args.proposer)
        return _emit({**amendment,
                      "note": "staged only — nothing changes until ratified"},
                     args.json)
    except (ValueError, FileNotFoundError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1


def cmd_history(args) -> int:
    """Show the version history (every ratification)."""
    store = _store(args)
    try:
        hist = store.history(args.policy_id)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        return _emit({"policy_id": args.policy_id, "versions": hist}, True)
    _table([["VER", "ACTION", "DATE", "APPROVER", "RATIONALE"]] + [
        [str(h["version"]), h["action"], h["effective_date"],
         h["approver"], h["rationale"][:60]] for h in hist])
    return 0


def cmd_verify(args) -> int:
    """Tamper detection: recompute checksums vs the history anchor."""
    store = _store(args)
    try:
        result = store.verify(args.policy_id)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not args.json:
        status = "OK — files match the ratified version" if result["ok"] \
            else f"TAMPERED: {result['tampered_files']}"
        print(f"{args.policy_id} v{result['version']}: {status}")
        return 0 if result["ok"] else 1
    code = _emit(result, True)
    return code if result["ok"] else 1


def cmd_demo(args) -> int:
    """Run the mandate theater."""
    result = run_demo(store_dir=args.store, seed=args.seed)
    if args.json:
        return _emit(result, True)
    print("ACT 1  mandate ratified:", result["created"]["policy_id"],
          f"v{result['created']['version']}")
    print("ACT 2  valid proposal:",
          "ALLOWED" if result["valid_proposal"]["allowed"] else "REFUSED")
    print("ACT 3  violations (all refused):")
    _table([["CASE", "RULE"]] + [
        [name, ", ".join(v["rules"])]
        for name, v in result["violations"].items()])
    print("ACT 4  exit door under stand-down:",
          "OPEN" if result["exit_door_open"] else "CLOSED")
    print("ACT 5  amendment ratified:",
          f"v{result['amendment']['ratified_version']}, "
          f"max_drawdown -> {result['amended_max_drawdown']:.0%}")
    print("       verify clean:", result["verify_clean"],
          "| verify tampered:", result["verify_tampered"])
    print("ACT 6  pm_check with mandate:",
          result["pm_hook"]["with_mandate"],
          "| without mandate refused:",
          result["pm_hook"]["without_mandate_refused"])
    return 0


def cmd_presets(args) -> int:
    """List presets and their philosophies."""
    if args.json:
        return _emit({"presets": {n: PHILOSOPHY[n] for n in preset_names()}},
                     True)
    for n in preset_names():
        print(f"{n}\n  {PHILOSOPHY[n]}\n")
    return 0


def cmd_license(args) -> int:
    return _emit(check_license(args.key), args.json)


def cmd_update_check(args) -> int:
    return _emit(check_update(), args.json)


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trade-mandate",
                                description="The PM agent's written mandate.")
    p.add_argument("--store", default="./mandates",
                   help="mandate store directory (default ./mandates)")
    p.add_argument("--json", action="store_true", help="JSON output")
    sub = p.add_subparsers(dest="command", required=True)

    def _sub(name: str, **kw) -> argparse.ArgumentParser:
        # --json must be accepted after the subcommand too (argparse only
        # looks at the subparser once it has taken over)
        s = sub.add_parser(name, **kw)
        s.add_argument("--json", action="store_true", help="JSON output")
        return s

    s = _sub("new", help="ratify a fresh mandate from a preset")
    s.add_argument("policy_id")
    s.add_argument("--preset", default="balanced", choices=preset_names())
    s.add_argument("--approver", default="")
    s.add_argument("--rationale", default="")
    s.add_argument("--effective-date", default="")
    s.set_defaults(func=cmd_new)

    s = _sub("show", help="print the current mandate")
    s.add_argument("policy_id")
    s.add_argument("--markdown", action="store_true")
    s.set_defaults(func=cmd_show)

    s = _sub("check", help="check a proposal JSON file")
    s.add_argument("policy_id")
    s.add_argument("--proposal", required=True)
    s.set_defaults(func=cmd_check)

    s = _sub("amend", help="propose or ratify an amendment")
    s.add_argument("policy_id")
    s.add_argument("--changes", default="",
                   help="JSON changes to stage (propose mode)")
    s.add_argument("--proposer", default="")
    s.add_argument("--ratify", default="",
                   help="amendment id to ratify (ratify mode)")
    s.add_argument("--approver", default="")
    s.add_argument("--rationale", default="")
    s.add_argument("--effective-date", default="")
    s.set_defaults(func=cmd_amend)

    s = _sub("history", help="version history")
    s.add_argument("policy_id")
    s.set_defaults(func=cmd_history)

    s = _sub("verify", help="tamper detection")
    s.add_argument("policy_id")
    s.set_defaults(func=cmd_verify)

    s = _sub("demo", help="run the mandate theater")
    s.add_argument("--seed", type=int, default=7)
    s.set_defaults(func=cmd_demo)

    s = _sub("presets", help="list presets")
    s.set_defaults(func=cmd_presets)

    s = _sub("license", help="license-key hook")
    s.add_argument("--key", default=None)
    s.set_defaults(func=cmd_license)

    s = _sub("update-check", help="check for a newer release")
    s.set_defaults(func=cmd_update_check)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
