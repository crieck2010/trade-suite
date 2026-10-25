"""Audit writers for the safety kernel.

``JsonAuditWriter`` appends events to the same ``audit_log.json`` the
execution adapters use (a JSON list, written atomically via a temp file
+ replace — the adapter's established pattern), tagged
``component="SafetyKernel"`` so one file tells the whole story.
``MemoryAuditWriter`` collects events in-process for tests and drills.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JsonAuditWriter:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def write(self, action: str, details: dict[str, Any]) -> None:
        event = {
            "timestamp": _now_iso(),
            "action": action,
            "component": "SafetyKernel",
            "details": details,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            entries: list[Any] = []
            if self.path.exists():
                try:
                    with open(self.path, "r", encoding="utf-8") as f:
                        entries = json.load(f)
                        if not isinstance(entries, list):
                            entries = [entries]
                except Exception:
                    entries = []
            entries.append(event)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2)
            tmp.replace(self.path)
        except Exception as exc:  # audit failure must never crash trading code paths that report it
            logger.error("SafetyKernel audit write failed (%s): %s", self.path, exc)


class MemoryAuditWriter:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def write(self, action: str, details: dict[str, Any]) -> None:
        self.events.append(
            {"timestamp": _now_iso(), "action": action, "component": "SafetyKernel", "details": details}
        )

    def actions(self) -> list[str]:
        return [e["action"] for e in self.events]
