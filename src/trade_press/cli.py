"""CLI: trade-press scan/rollup/state/themes/policy."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone

from . import __version__, licensing
from .archive import DEFAULT_ARCHIVE_PATH, PressArchive
from .context import narrative_input
from .pipeline import rollup, scan
from .themes import THEME_PACKS, get_theme


def cmd_scan(args) -> int:
    theme = get_theme(args.theme)
    archive = PressArchive(args.archive)
    try:
        scored = scan(theme, archive=archive, limit_per_query=args.limit)
        cov = archive.coverage(theme.theme_id)
    finally:
        archive.close()
    first = cov["first_recorded"] if cov else "n/a"
    print(f"theme={theme.theme_id} matched={len(scored)} "
          f"archive_total={cov['n_items'] if cov else 0} "
          f"first_recorded={first}")
    for s in scored[: args.show]:
        pol = f"{s.polarity:+.2f}"
        print(f"  {s.item.published_at or s.item.observed_at} "
              f"polarity={pol} {s.item.publisher}: {s.item.title[:90]}")
    if len(scored) > args.show:
        print(f"  ... and {len(scored) - args.show} more")
    return 0


def cmd_rollup(args) -> int:
    theme = get_theme(args.theme)
    day = (date.fromisoformat(args.date) if args.date
           else datetime.now(timezone.utc).date())
    archive = PressArchive(args.archive)
    try:
        state = rollup(archive, theme, day)
    finally:
        archive.close()
    print(json.dumps(state.to_dict(), indent=2))
    return 0


def cmd_state(args) -> int:
    archive = PressArchive(args.archive)
    try:
        payload = narrative_input(args.as_of, archive, theme_id=args.theme)
    except ValueError as exc:
        print(f"no narrative state: {exc}", file=sys.stderr)
        return 2
    finally:
        archive.close()
    print(json.dumps(payload, indent=2))
    return 0


def cmd_themes(args) -> int:
    for theme in THEME_PACKS.values():
        print(f"{theme.theme_id}: {theme.title} "
              f"(pack v{theme.version}, {len(theme.queries)} queries, "
              f"min_hits={theme.min_hits})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="trade-press",
        description="Press listener: narrative momentum by theme "
                    "(research context, not a signal)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser(
        "scan", help="fetch, classify, score, and archive one theme's press")
    s.add_argument("--theme", default="ai_infrastructure_capex",
                   help="registered theme id (default: %(default)s)")
    s.add_argument("--archive", default=str(DEFAULT_ARCHIVE_PATH),
                   metavar="DB", help="point-in-time archive (SQLite)")
    s.add_argument("--limit", type=int, default=50,
                   help="items per theme query (default 50)")
    s.add_argument("--show", type=int, default=10,
                   help="matched headlines to print (default 10)")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser(
        "rollup", help="compute + store one day's narrative state")
    s.add_argument("--theme", default="ai_infrastructure_capex",
                   help="registered theme id (default: %(default)s)")
    s.add_argument("--archive", default=str(DEFAULT_ARCHIVE_PATH),
                   metavar="DB", help="point-in-time archive (SQLite)")
    s.add_argument("--date", default=None, metavar="YYYY-MM-DD",
                   help="day to roll up (default: today, UTC)")
    s.set_defaults(func=cmd_rollup)

    s = sub.add_parser(
        "state", help="print the stored press.narrative_state.v1 payload")
    s.add_argument("--theme", default="ai_infrastructure_capex",
                   help="registered theme id (default: %(default)s)")
    s.add_argument("--archive", default=str(DEFAULT_ARCHIVE_PATH),
                   metavar="DB", help="point-in-time archive (SQLite)")
    s.add_argument("--as-of", required=True, metavar="YYYY-MM-DD",
                   help="date the read applies to (strict: no stale reads)")
    s.set_defaults(func=cmd_state)

    s = sub.add_parser("themes", help="list registered theme packs")
    s.set_defaults(func=cmd_themes)

    s = sub.add_parser("policy", help="press storage/licensing policy")
    s.set_defaults(func=lambda a: (print(json.dumps(
        licensing.storage_policy(), indent=2)), 0)[1])

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
