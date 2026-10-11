"""Master audit logging service for trade_dashboard_app.

Requirement: Every manual override, kill-switch activation, or trade approval
must write to an auditable master log file (audit_log.json).
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_AUDIT_LOCK = threading.Lock()
DEFAULT_AUDIT_LOG = Path(os.environ.get("TRADE_AUDIT_LOG", "audit_log.json"))


def record_audit_event(
    action: str,
    actor: str,
    details: Dict[str, Any],
    log_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Records an audit event to audit_log.json with strict thread safety."""
    path = log_path or DEFAULT_AUDIT_LOG
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "actor": actor,
        "details": details,
    }

    with _AUDIT_LOCK:
        existing: List[Dict[str, Any]] = []
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as fp:
                    content = fp.read().strip()
                    if content:
                        existing = json.loads(content)
            except Exception:
                existing = []

        existing.append(event)
        # Keep last 1,000 entries
        if len(existing) > 1000:
            existing = existing[-1000:]

        # Atomic write
        temp_path = path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as fp:
            json.dump(existing, fp, indent=2)
        temp_path.replace(path)

    return event


def read_audit_log(limit: int = 50, log_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Reads recent audit log entries, newest first."""
    path = log_path or DEFAULT_AUDIT_LOG
    if not path.exists():
        return []

    with _AUDIT_LOCK:
        try:
            with open(path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                if isinstance(data, list):
                    return list(reversed(data[-limit:]))
        except Exception:
            return []
    return []
