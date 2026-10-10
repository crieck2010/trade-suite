"""Tick recorder: canonical messages -> local JSONL files.

Layout::

    <root>/<SYMBOL>/<YYYY-MM-DD>.jsonl

One file per symbol per UTC day (documented rotation). Each line is one
canonical message as JSON. Appends are atomic enough for our purposes
(single writer per file; the recorder holds a lock per open file).

Recording is the bridge between streaming and research: record the live
feed, then :mod:`trade_stream.replay` feeds it back through the bus for
strategy testing on "live-like" data without a network connection.
"""

from __future__ import annotations

import datetime
import json
import os
import threading


def _day_str(ts: float) -> str:
    return datetime.datetime.fromtimestamp(
        ts, tz=datetime.timezone.utc
    ).strftime("%Y-%m-%d")


def _safe_symbol(symbol: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in symbol)


class TickRecorder:
    """Append canonical messages to per-symbol, per-day JSONL files."""

    def __init__(self, root_dir: str) -> None:
        self.root_dir = root_dir
        os.makedirs(root_dir, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()
        self.recorded = 0

    def _lock_for(self, path: str) -> threading.Lock:
        with self._locks_lock:
            lock = self._locks.get(path)
            if lock is None:
                lock = threading.Lock()
                self._locks[path] = lock
            return lock

    def path_for(self, symbol: str, ts: float) -> str:
        day = _day_str(ts)
        return os.path.join(self.root_dir, _safe_symbol(symbol), f"{day}.jsonl")

    def record(self, msg: dict) -> str:
        """Append one canonical message. Returns the file path written."""
        symbol = str(msg.get("symbol", "UNKNOWN"))
        ts = float(msg.get("ts", 0.0))
        path = self.path_for(symbol, ts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        line = json.dumps(msg, default=str) + "\n"
        with self._lock_for(path):
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
        self.recorded += 1
        return path

    def files(self) -> list[str]:
        """All recorded JSONL files, sorted."""
        out = []
        for dirpath, _dirs, files in os.walk(self.root_dir):
            for fn in files:
                if fn.endswith(".jsonl"):
                    out.append(os.path.join(dirpath, fn))
        return sorted(out)
