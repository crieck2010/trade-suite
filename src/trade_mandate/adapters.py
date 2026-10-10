"""Lazy, fail-soft adapters to sibling engines.

Nothing is imported here at module top level: every sibling is probed
inside the function that needs it.  With siblings uninstalled the
adapters degrade loudly — a missing mandate or a missing sibling is a
refusal or a skip, never a silent pass.

Interop note: ``resolve_policy()`` uses the exact same SHA-256-over-raw-
bytes algorithm as ``trade_lifecycle.policy.policy_checksum``, so a
checksum recorded by trade-lifecycle's PAPER→LIVE gate verifies here
byte-for-byte.  trade-mandate writes both ``<policy_id>.md`` (the human
constitution, which trade-lifecycle discovers) and ``<policy_id>.json``
(the machine constitution, which this module enforces).
"""

from __future__ import annotations

import hashlib
import json
import os


def sibling_available(name: str) -> bool:
    """Probe for a sibling package without importing it at module scope."""
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def _sha256_bytes(data: bytes) -> str:
    # identical to trade_lifecycle.policy.policy_checksum (reimplemented
    # locally to avoid a hard dependency)
    return hashlib.sha256(data).hexdigest()


def resolve_policy(policy_id: str, search_dirs: list[str]) -> dict | None:
    """Find ``<policy_id>.md`` (preferred, trade-lifecycle compatible) or
    ``<policy_id>.json`` in the search dirs.  Returns
    ``{policy_id, path, checksum}`` or None.  Fail-closed callers treat
    None as a refusal reason, never as a pass."""
    for filename in (f"{policy_id}.md", f"{policy_id}.json"):
        for directory in search_dirs:
            path = os.path.join(directory, filename)
            if os.path.isfile(path):
                with open(path, "rb") as fh:
                    data = fh.read()
                return {"policy_id": policy_id, "path": path,
                        "checksum": _sha256_bytes(data)}
    return None


def load_mandate(policy_id: str, search_dirs: list[str]) -> dict:
    """Load the machine-readable mandate (the .json).  The .md is the
    human artifact; it is not parsed — if only the .md exists, this
    raises with instructions instead of guessing."""
    for directory in search_dirs:
        path = os.path.join(directory, f"{policy_id}.json")
        if os.path.isfile(path):
            with open(path) as fh:
                return json.load(fh)
    md = resolve_policy(policy_id, search_dirs)
    if md and md["path"].endswith(".md"):
        raise FileNotFoundError(
            f"mandate {policy_id!r}: only the human .md exists; the machine "
            f".json is required for enforcement (create it with "
            f"`trade-mandate new --preset ... --store DIR`)")
    raise FileNotFoundError(f"no mandate {policy_id!r} in {search_dirs}")


def pm_check(mandate_or_policy_id, proposal: dict,
             search_dirs: list[str] | None = None) -> dict:
    """The hook the trade-agents portfolio manager calls before any
    allocation.  Accepts a mandate dict or a policy_id (resolved lazily).

    Fail-closed: if no mandate can be resolved, the proposal is REFUSED,
    not skipped.  An agent with no constitution does not trade.
    """
    from .validate import check  # local, always available

    if isinstance(mandate_or_policy_id, dict):
        mandate = mandate_or_policy_id
    else:
        dirs = search_dirs or []
        try:
            mandate = load_mandate(mandate_or_policy_id, dirs)
        except (FileNotFoundError, OSError) as exc:
            return {
                "allowed": False,
                "violations": [{
                    "rule": "mandate.missing",
                    "detail": f"no mandate resolved for "
                              f"{mandate_or_policy_id!r}: {exc} — fail-closed",
                }],
                "notes": ["pm_check refuses without a mandate; this is "
                          "deliberate, not an error to work around"],
                "policy_id": mandate_or_policy_id,
            }
    result = check(mandate, proposal)
    result["notes"] = result.get("notes", []) + [
        f"checked against mandate v{mandate.get('version')} "
        f"({mandate.get('policy_id')})"]
    return result


def risk_limits(mandate: dict) -> dict:
    """Translate the mandate into the numbers trade-risk consumes."""
    return {
        "max_leverage": mandate["leverage_caps"]["portfolio"],
        "per_position_cap": mandate["leverage_caps"]["per_position"],
        "max_single_name_weight": mandate["concentration"]["max_single_name_weight"],
        "max_sector_weight": mandate["concentration"]["max_sector_weight"],
        "max_drawdown": mandate["max_drawdown"],
        "vol_target": mandate["vol_target"],
        "policy_id": mandate.get("policy_id"),
        "mandate_version": mandate.get("version"),
    }


def check_against_lifecycle_policy(policy_id: str, search_dirs: list[str],
                                   expected_checksum: str | None = None) -> dict:
    """Verify a trade-lifecycle-recorded policy: resolve it and, when a
    checksum was recorded at the PAPER→LIVE transition, confirm the file
    is byte-identical.  Returns {ok, ...}; ok=False means tampering or
    a replaced mandate since sign-off."""
    resolved = resolve_policy(policy_id, search_dirs)
    if resolved is None:
        return {"ok": False, "policy_id": policy_id,
                "reason": "policy file not found in search dirs"}
    if expected_checksum is not None and resolved["checksum"] != expected_checksum:
        return {"ok": False, "policy_id": policy_id,
                "reason": "checksum mismatch — mandate changed since sign-off",
                "expected": expected_checksum,
                "actual": resolved["checksum"]}
    return {"ok": True, **resolved}
