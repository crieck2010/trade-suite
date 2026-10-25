"""Persistent safety state: E-Stop latch, session record, heartbeats.

Stored as one JSON document, written atomically (temp file + replace),
so a crashed process never leaves a half-written latch. With no path,
state is in-memory only (tests, drills).
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT: dict[str, Any] = {
    "estop": {"engaged": False, "reason": "", "actor": "", "at": ""},
    "session": {
        "date": "",
        "start_equity": 0.0,
        "breaker_tripped": False,
        "orders_allowed": 0,
        "orders_blocked": 0,
    },
    "heartbeats": {},  # source -> ISO timestamp of last beat
}


class SafetyState:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._lock = threading.Lock()
        self.data: dict[str, Any] = json.loads(json.dumps(_DEFAULT))
        if self.path is not None and self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    for key in _DEFAULT:
                        if key in loaded:
                            self.data[key] = loaded[key]
            except Exception as exc:
                logger.error("Safety state unreadable (%s): %s — starting clean", self.path, exc)

    def save(self) -> None:
        if self.path is None:
            return
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, indent=2)
                tmp.replace(self.path)
            except Exception as exc:
                logger.error("Safety state save failed (%s): %s", self.path, exc)

    # -- E-Stop latch ------------------------------------------------------
    @property
    def estop_engaged(self) -> bool:
        return bool(self.data["estop"]["engaged"])

    def engage_estop(self, actor: str, reason: str, at_iso: str) -> None:
        self.data["estop"] = {
            "engaged": True,
            "reason": reason,
            "actor": actor,
            "at": at_iso,
        }
        self.save()

    def reset_estop(self, at_iso: str) -> None:
        # NOTE: resetting the E-Stop never clears the session breaker
        # lockout (session.breaker_tripped) — that ends with the session.
        self.data["estop"] = {"engaged": False, "reason": "", "actor": "", "at": at_iso}
        self.save()

    # -- Heartbeats ----------------------------------------------------------
    def beat(self, source: str, at_iso: str) -> None:
        self.data["heartbeats"][source] = at_iso
        self.save()

    def last_beat(self, source: str) -> str | None:
        return self.data["heartbeats"].get(source)
