"""Replay: feed recorded JSONL ticks back through the bus.

Replay is how strategies get tested on "live-like" data without a network
connection: the same canonical messages, the same topic routing, the same
subscriber code paths — only the clock is compressed.

``speed`` scales wall-clock time: ``speed=2`` replays twice as fast as the
original recording. ``speed<=0`` disables sleeping entirely (as fast as
possible; the deterministic choice for tests). Timing is derived from the
messages' own ``ts`` fields, so replay preserves the original cadence
shape (bursts stay bursty).
"""

from __future__ import annotations

import json
import time


def read_ticks(path: str):
    """Yield canonical messages from a JSONL file, in order."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def topic_for(msg: dict) -> str:
    """Bus topic for a canonical message: ``<kind>s.<symbol>``."""
    return f"{msg.get('kind', 'msg')}s.{msg.get('symbol', 'UNKNOWN')}"


def replay(path: str, bus=None, speed: float = 1.0, sink=None) -> int:
    """Replay a JSONL file. Returns the number of messages delivered.

    Provide ``bus`` (a :class:`~trade_stream.bus.MessageBus`) to publish
    each message to its topic, or ``sink(topic, msg)`` to handle messages
    directly. If neither is given, messages are read and counted only.
    """
    count = 0
    t0_msg = None
    t0_wall = time.monotonic()
    for msg in read_ticks(path):
        ts = msg.get("ts")
        if speed and speed > 0 and isinstance(ts, (int, float)):
            if t0_msg is None:
                t0_msg = ts
            target = (ts - t0_msg) / speed
            elapsed = time.monotonic() - t0_wall
            if target > elapsed:
                time.sleep(target - elapsed)
        topic = topic_for(msg)
        if bus is not None:
            bus.publish(topic, msg)
        if sink is not None:
            sink(topic, msg)
        count += 1
    return count
