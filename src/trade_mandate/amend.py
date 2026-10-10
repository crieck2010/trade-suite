"""Amendments as law: versioned, checksummed, human-signed.

Layout inside a store directory (one directory holds many mandates)::

    <policy_id>.json           # current machine mandate (includes checksum field)
    <policy_id>.md             # human rendering (what trade-lifecycle checksums)
    <policy_id>.history.jsonl  # every version: version, effective_date,
                               # approver, rationale, json_sha256, md_sha256
    <policy_id>.amendments.jsonl  # pending + ratified amendment records

``verify()`` recomputes both file checksums against the latest history
entry: any byte changed without a ratified amendment is tampering.
The history file is the trust anchor — in production keep it append-only
or mirrored off-machine; a compromised history file can bless a forgery.
(That caveat is documented, not solved, in v0.1.0.)
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date

from .mandate import (
    SCHEMA_VERSION, mandate_checksum, new_mandate, render_markdown,
    validate_mandate,
)


def _sha256_file(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class MandateStore:
    """A directory of versioned mandate files."""

    def __init__(self, directory: str):
        self.directory = directory
        os.makedirs(directory, exist_ok=True)

    # -- paths ---------------------------------------------------------
    def _p(self, name: str) -> str:
        return os.path.join(self.directory, name)

    def json_path(self, policy_id: str) -> str:
        return self._p(f"{policy_id}.json")

    def md_path(self, policy_id: str) -> str:
        return self._p(f"{policy_id}.md")

    def history_path(self, policy_id: str) -> str:
        return self._p(f"{policy_id}.history.jsonl")

    def amendments_path(self, policy_id: str) -> str:
        return self._p(f"{policy_id}.amendments.jsonl")

    # -- core ----------------------------------------------------------
    def exists(self, policy_id: str) -> bool:
        return os.path.isfile(self.json_path(policy_id))

    def _write_files(self, mandate: dict) -> dict:
        """Write .json + .md; returns {json_sha256, md_sha256}."""
        mandate = dict(mandate)
        mandate["checksum"] = mandate_checksum(mandate)
        with open(self.json_path(mandate["policy_id"]), "w") as fh:
            json.dump(mandate, fh, indent=2, sort_keys=True)
            fh.write("\n")
        md = render_markdown(mandate)
        with open(self.md_path(mandate["policy_id"]), "w") as fh:
            fh.write(md)
        return {
            "json_sha256": _sha256_file(self.json_path(mandate["policy_id"])),
            "md_sha256": _sha256_file(self.md_path(mandate["policy_id"])),
        }

    def _append_history(self, policy_id: str, entry: dict) -> None:
        with open(self.history_path(policy_id), "a") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")

    def create(self, policy_id: str, approver: str, rationale: str,
               effective_date: str, **overrides) -> dict:
        """First ratification of a mandate.  Requires sign-off like any
        amendment — there is no unsigned genesis."""
        if self.exists(policy_id):
            raise ValueError(f"mandate {policy_id!r} already exists; amend it")
        return self._ratify_new(policy_id, overrides, approver, rationale,
                                effective_date, action="create")

    def _ratify_new(self, policy_id, overrides, approver, rationale,
                    effective_date, action) -> dict:
        for field, name in ((approver, "approver"), (rationale, "rationale"),
                            (effective_date, "effective_date")):
            if not field or not str(field).strip():
                raise ValueError(f"{action} refused: {name} is required — "
                                 "unsigned or undated mandates are not law")
        mandate = new_mandate(policy_id, **overrides)
        mandate["version"] = 1
        mandate["effective_date"] = effective_date
        sums = self._write_files(mandate)
        self._append_history(policy_id, {
            "version": 1, "action": action, "effective_date": effective_date,
            "approver": approver, "rationale": rationale,
            "changes": overrides, **sums,
        })
        return {"policy_id": policy_id, "version": 1, "action": action, **sums}

    def load(self, policy_id: str) -> dict:
        path = self.json_path(policy_id)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"no mandate {policy_id!r} in {self.directory}")
        with open(path) as fh:
            return json.load(fh)

    # -- amendments ----------------------------------------------------
    def propose_amendment(self, policy_id: str, changes: dict,
                          proposer: str) -> dict:
        """Stage an amendment.  Staging changes nothing — the mandate file
        is untouched until ratify()."""
        if not self.exists(policy_id):
            raise FileNotFoundError(f"no mandate {policy_id!r}")
        if not proposer or not str(proposer).strip():
            raise ValueError("proposer is required")
        if not isinstance(changes, dict) or not changes:
            raise ValueError("changes must be a non-empty dict")
        current = self.load(policy_id)
        amendment = {
            "amendment_id": f"{policy_id}-a{current['version'] + 1}",
            "policy_id": policy_id,
            "base_version": current["version"],
            "changes": changes,
            "proposer": proposer,
            "status": "pending",
        }
        with open(self.amendments_path(policy_id), "a") as fh:
            fh.write(json.dumps(amendment, sort_keys=True) + "\n")
        return amendment

    def _read_amendments(self, policy_id: str) -> list[dict]:
        path = self.amendments_path(policy_id)
        if not os.path.isfile(path):
            return []
        with open(path) as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def pending_amendments(self, policy_id: str) -> list[dict]:
        return [a for a in self._read_amendments(policy_id)
                if a["status"] == "pending"]

    def ratify(self, policy_id: str, amendment_id: str, approver: str,
               rationale: str, effective_date: str) -> dict:
        """Apply a pending amendment: version bump, rewrite, checksums,
        history entry.  Refuses without approver, rationale, or date."""
        for field, name in ((approver, "approver"), (rationale, "rationale"),
                            (effective_date, "effective_date")):
            if not field or not str(field).strip():
                raise ValueError(f"ratify refused: {name} is required — "
                                 "unsigned or undated amendments are not law")
        pending = {a["amendment_id"]: a
                   for a in self.pending_amendments(policy_id)}
        if amendment_id not in pending:
            raise ValueError(f"no pending amendment {amendment_id!r}")
        amendment = pending[amendment_id]
        current = self.load(policy_id)
        if amendment["base_version"] != current["version"]:
            raise ValueError(
                f"amendment based on v{amendment['base_version']} but current "
                f"is v{current['version']} — re-propose on the current version")

        # apply changes onto the current mandate (one level deep, like new_mandate)
        merged = dict(current)
        for key, value in amendment["changes"].items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                sub = dict(merged[key])
                sub.update(value)
                merged[key] = sub
            else:
                merged[key] = value
        merged["version"] = current["version"] + 1
        merged["effective_date"] = effective_date
        problems = validate_mandate(merged)
        if problems:
            raise ValueError("amendment refused: " + "; ".join(problems))

        sums = self._write_files(merged)
        self._append_history(policy_id, {
            "version": merged["version"], "action": "amend",
            "effective_date": effective_date, "approver": approver,
            "rationale": rationale, "amendment_id": amendment_id,
            "changes": amendment["changes"], **sums,
        })
        # mark ratified (rewrite the amendments log)
        records = self._read_amendments(policy_id)
        with open(self.amendments_path(policy_id), "w") as fh:
            for r in records:
                if r["amendment_id"] == amendment_id:
                    r = dict(r, status="ratified", ratified_by=approver,
                             ratified_date=str(date.today()))
                fh.write(json.dumps(r, sort_keys=True) + "\n")
        return {"policy_id": policy_id, "version": merged["version"],
                "action": "amend", **sums}

    def history(self, policy_id: str) -> list[dict]:
        path = self.history_path(policy_id)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"no history for {policy_id!r}")
        with open(path) as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def verify(self, policy_id: str) -> dict:
        """Tamper detection: recompute both file checksums and compare to
        the latest history entry."""
        hist = self.history(policy_id)
        latest = hist[-1]
        actual = {
            "json_sha256": _sha256_file(self.json_path(policy_id)),
            "md_sha256": _sha256_file(self.md_path(policy_id)),
        }
        tampered = [k for k in actual if actual[k] != latest.get(k)]
        # also verify the embedded payload checksum round-trips
        mandate = self.load(policy_id)
        payload_ok = mandate.get("checksum") == mandate_checksum(mandate)
        return {
            "policy_id": policy_id,
            "version": latest["version"],
            "ok": not tampered and payload_ok,
            "tampered_files": tampered,
            "payload_checksum_ok": payload_ok,
            "expected": {k: latest.get(k) for k in actual},
            "actual": actual,
        }
