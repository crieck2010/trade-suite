"""Command-line interface for trade-stream."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time

from . import __version__
from .bus import MessageBus
from .demo import run_demo
from .licensing import check_license, check_update
from .recorder import TickRecorder
from .reconnect import PRESETS
from .replay import read_ticks, replay
from .runner import StreamSession
from .sources import live_source_names, source_names


def _symbols(s: str) -> list[str]:
    return [p.strip() for p in s.split(",") if p.strip()]


def _cmd_stream(args) -> int:
    if args.source not in live_source_names():
        print(f"error: source {args.source!r} is not streamable "
              f"(live: {live_source_names()})", file=sys.stderr)
        return 2
    if args.source != "demo":
        print(f"warning: connecting to live {args.source} feed over the network",
              file=sys.stderr)
    symbols = _symbols(args.symbols)
    bus = MessageBus()
    seen: list[dict] = []
    recorder = TickRecorder(args.record) if args.record else None

    def _on_msg(topic, msg):
        seen.append(msg)
        if recorder is not None and msg.get("kind") in ("trade", "quote", "bar"):
            recorder.record(msg)

    sub_trades = bus.subscribe("trades.*", _on_msg)
    sub_quotes = bus.subscribe("quotes.*", _on_msg)
    session = StreamSession(args.source, symbols, bus=bus, policy=args.preset)
    session.start()
    try:
        if args.duration:
            time.sleep(args.duration)
        else:
            while session._thread is not None and session._thread.is_alive():
                time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        stats = session.stop()
        # The bus dispatches asynchronously: wait until subscribers have
        # seen everything the session published before reporting.
        deadline = time.time() + 10.0
        while (sub_trades.stats()["received"] + sub_quotes.stats()["received"]
               < stats["published"] and time.time() < deadline):
            time.sleep(0.01)
        bus.close()
    payload = {"command": "stream", "stats": stats,
               "n_seen": len(seen), "recorded_to": args.record,
               "last": seen[-1] if seen else None}
    return _emit(payload, args.format)


def _cmd_record(args) -> int:
    args.record = args.dir
    args.duration = args.duration or 5.0
    return _cmd_stream(args)


def _cmd_replay(args) -> int:
    if args.format == "json":
        def sink(topic, msg):
            print(json.dumps({"topic": topic, "msg": msg}, default=str))
        n = replay(args.file, sink=sink, speed=args.speed)
    else:
        n = 0
        for msg in read_ticks(args.file):
            n += 1
            print(f"{msg.get('ts', '?')} {msg.get('kind', '?'):>6} "
                  f"{msg.get('symbol', '?'):<10} {msg.get('price', '-')}")
    if args.format == "json":
        pass
    else:
        print(f"replayed {n} messages from {args.file}", file=sys.stderr)
    return 0


def _cmd_topics(_args) -> int:
    print("topic patterns: <kind>s.<symbol>  e.g. trades.BTC-USD, quotes.AAPL")
    print("wildcards via fnmatch:  trades.*   quotes.*   *   alerts.*")
    print("alerts publish on:      alerts.<symbol>")
    return 0


def _cmd_presets(_args) -> int:
    for name in ("conservative", "balanced", "aggressive"):
        p = PRESETS[name]
        print(f"{name:>13}: base={p['base']} cap={p['cap']} jitter={p['jitter']} "
              f"stale_after={p['stale_after']}  # {p['note']}")
    return 0


def _cmd_demo(args) -> int:
    summary = run_demo(seed=args.seed)
    return _emit({"command": "demo", **summary}, args.format)


def _emit(payload: dict, fmt: str) -> int:
    if fmt == "json":
        print(json.dumps(payload, indent=2, default=str))
    else:
        _emit_table(payload)
    return 0


def _emit_table(payload: dict) -> None:
    cmd = payload.get("command")
    if cmd == "stream":
        s = payload["stats"]
        print(f"source={s['source']} symbols={','.join(s['symbols'])}")
        print(f"received={s['received']} published={s['published']} "
              f"restarts={s['restarts']}")
        if payload.get("recorded_to"):
            print(f"recorded to {payload['recorded_to']}")
        last = payload.get("last")
        if last:
            print(f"last: {last['kind']} {last['symbol']} @ {last['price']}")
    elif cmd == "demo":
        print(f"demo seed={payload['seed']} ticks={payload['n_ticks']} "
              f"alerts={payload['n_alerts']} bars={payload['n_bars']}")
        for a in payload["alerts"]:
            print(f"  ALERT {a['symbol']} {a['move_pct']:+.2f}% "
                  f"(window {a['window_s']:.0f}s)")
        for sym, lp in sorted(payload["latest"].items()):
            print(f"  {sym:<6} last {lp['price']:.4f}")
    else:
        print(json.dumps(payload, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trade-stream",
                                description="Real-time market-data streaming engine")
    p.add_argument("--format", choices=["table", "json"], default="table")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("stream", help="run a live (or demo) stream")
    s.add_argument("--source", default="demo",
                   help=f"one of {source_names()}")
    s.add_argument("--symbols", default="AAA,BBB",
                   help="comma-separated symbols (demo) or product ids (coinbase)")
    s.add_argument("--record", default=None, metavar="DIR",
                   help="record ticks to DIR as JSONL")
    s.add_argument("--duration", type=float, default=None,
                   help="run for N seconds then stop")
    s.add_argument("--preset", default="balanced",
                   choices=["conservative", "balanced", "aggressive"])
    s.set_defaults(func=_cmd_stream)

    r = sub.add_parser("record", help="record a stream to JSONL")
    r.add_argument("--source", default="demo")
    r.add_argument("--symbols", default="AAA,BBB")
    r.add_argument("--dir", required=True, metavar="DIR")
    r.add_argument("--duration", type=float, default=5.0)
    r.add_argument("--preset", default="balanced",
                   choices=["conservative", "balanced", "aggressive"])
    r.set_defaults(func=_cmd_record)

    rp = sub.add_parser("replay", help="replay a recorded JSONL file")
    rp.add_argument("file")
    rp.add_argument("--speed", type=float, default=0.0,
                    help="time compression; 0 = as fast as possible")
    rp.set_defaults(func=_cmd_replay)

    d = sub.add_parser("demo", help="run the seeded end-to-end demo")
    d.add_argument("--seed", type=int, default=7)
    d.set_defaults(func=_cmd_demo)

    t = sub.add_parser("topics", help="document bus topic patterns")
    t.set_defaults(func=_cmd_topics)

    pr = sub.add_parser("presets", help="show reconnect presets")
    pr.set_defaults(func=_cmd_presets)

    lic = sub.add_parser("license", help="license-key hook (stub)")
    lic.set_defaults(func=lambda a: (print(json.dumps(check_license(), indent=2)), 0)[1])

    up = sub.add_parser("update-check", help="check for a newer release")
    up.set_defaults(func=lambda a: (print(json.dumps(check_update(), indent=2)), 0)[1])

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
