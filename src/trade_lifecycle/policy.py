"""Machine-readable mandate hooks (minimal but real).

A strategy may declare a ``policy_id`` at registration.  PAPER -> LIVE
requires the policy file to exist and its checksum to be recorded in the
transition event — the seed of the future investment-policy module.
Policy files are Markdown mandates named ``<policy_id>.md``.
"""

from __future__ import annotations

import hashlib
import os

SCHEMA_VERSION = 1


def policy_checksum(content: bytes) -> str:
    """SHA-256 over the raw file bytes."""
    return hashlib.sha256(content).hexdigest()


def write_policy(directory: str, policy_id: str, text: str) -> dict:
    """Write a policy file; returns {policy_id, path, checksum}."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{policy_id}.md")
    data = text.encode("utf-8")
    with open(path, "wb") as fh:
        fh.write(data)
    return {"policy_id": policy_id, "path": path,
            "checksum": policy_checksum(data)}


def resolve_policy(policy_id: str, search_dirs: list[str]) -> dict | None:
    """Find ``<policy_id>.md`` in the search dirs; None when absent.

    Returns {policy_id, path, checksum}.  Fail-closed callers treat None
    as a refusal reason, never as a pass.
    """
    filename = f"{policy_id}.md"
    for directory in search_dirs:
        path = os.path.join(directory, filename)
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                data = fh.read()
            return {"policy_id": policy_id, "path": path,
                    "checksum": policy_checksum(data)}
    return None
