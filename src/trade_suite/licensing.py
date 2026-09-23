"""License-key check hook (monetization readiness).

v0.1.0 ships community mode: no key is required and every feature works.
The hook is in place so a future release can gate premium features behind a
key validated against a merchant of record (Gumroad / Lemon Squeezy).

Key format: ``TS-XXXX-XXXX-XXXX`` (uppercase alphanumerics).  Keys are stored
in ``~/.trade_suite/license.key`` and never leave the machine in v0.1.0
(offline format check only).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

KEY_PATTERN = re.compile(r"^TS-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")
CONFIG_DIR = Path(os.path.expanduser("~")) / ".trade_suite"
KEY_FILE = CONFIG_DIR / "license.key"


@dataclass(frozen=True)
class LicenseStatus:
    valid: bool
    tier: str  # "community" | "pro"
    detail: str


def format_valid(key: str) -> bool:
    """Offline format check for a license key."""
    return bool(KEY_PATTERN.match((key or "").strip().upper()))


def save_key(key: str) -> LicenseStatus:
    """Persist ``key`` after a format check; return the resulting status."""
    status = check_key(key)
    if not status.valid:
        return status
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(key.strip().upper() + "\n", encoding="utf-8")
    return status


def load_key() -> str | None:
    try:
        text = KEY_FILE.read_text(encoding="utf-8").strip().upper()
    except OSError:
        return None
    return text or None


def check_key(key: str | None) -> LicenseStatus:
    if not key:
        return LicenseStatus(False, "community", "no key on file")
    if format_valid(key):
        return LicenseStatus(True, "pro", "key format accepted (offline check)")
    return LicenseStatus(False, "community", "key format invalid")


def current_status() -> LicenseStatus:
    """Status of the locally stored key; community tier when absent."""
    key = load_key()
    if key is None:
        return LicenseStatus(False, "community", "community mode (no key required)")
    return check_key(key)


def clear_key() -> None:
    try:
        KEY_FILE.unlink()
    except OSError:
        pass
