"""The guards: pure functions, each returning {"passed", "reasons[]"}.

Every guard fails CLOSED: missing inputs, missing siblings, malformed
reports, or stale data all refuse with a stated reason.  A guard never
passes on the absence of evidence.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from . import policy as _policy

SCHEMA_VERSION = 1

VALID_MODES = ("supervised", "autonomous")


# ------------------------------------------------------------------ utils

def config_hash(config: dict) -> str:
    """Tamper-evident binding of a strategy config to its validation report.

    Canonical JSON (sorted keys, compact separators) hashed with SHA-256.
    The same config always hashes identically; any parameter change —
    even a float rounding — produces a different hash, so a report earned
    by one parameter set cannot promote another.
    """
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"),
                           default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except (ValueError, TypeError):
        return None


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


# ------------------------------------------------------------------- gates

def gate_research_to_validated(report: dict | None, expected_config_hash: str,
                               *, allow_warns: bool = False,
                               max_age_days: int = 90,
                               now: datetime | None = None) -> dict:
    """RESEARCH -> VALIDATED: the validation gates must all pass.

    Requires a trade-swing ValidationReport (schema_version 1) with every
    gate PASS, a fresh generation timestamp, and a config hash matching
    the registered strategy config.
    """
    reasons: list[str] = []
    now = now or datetime.now(timezone.utc)

    if not isinstance(report, dict):
        return {"passed": False,
                "reasons": ["No validation report supplied. RESEARCH cannot promote "
                            "on assertion; run the strategy through trade-swing "
                            "validation and pass report= explicitly."]}
    if report.get("schema_version") != 1:
        reasons.append(f"Report schema_version is {report.get('schema_version')!r}, "
                       "expected 1 — refusing rather than misreading the format.")
    validation = report.get("validation")
    if not isinstance(validation, dict):
        reasons.append("Report has no 'validation' section.")
        return {"passed": False, "reasons": reasons}
    gates = validation.get("gates")
    if not isinstance(gates, list) or not gates:
        reasons.append("Report validation lists no gates; nothing was actually checked.")
    else:
        bad = [g.get("name", "?") for g in gates
               if g.get("verdict") not in ("PASS",) and
               not (allow_warns and g.get("verdict") == "WARN")]
        if bad:
            reasons.append("Failing gates: " + ", ".join(
                f"{g.get('name', '?')}={g.get('verdict', '?')}" for g in gates
                if g.get("name", "?") in bad) + ".")
        skipped = [g.get("name", "?") for g in gates if g.get("verdict") == "SKIPPED"]
        if skipped:
            reasons.append("SKIPPED gates (sibling missing at validation time): "
                           + ", ".join(skipped) + ". Re-run validation with "
                           "trade-overfit installed.")
    if str(validation.get("status", "")).upper() in ("FAIL", "SKIPPED"):
        reasons.append(f"Overall validation status is {validation.get('status')!r}.")

    generated = _parse_ts(report.get("generated_utc"))
    if generated is None:
        reasons.append("Report has no parseable 'generated_utc'; freshness cannot be verified.")
    else:
        age_days = (now - generated).total_seconds() / 86400.0
        if age_days < 0:
            reasons.append("Report timestamp is in the future; clock or report is untrustworthy.")
        elif age_days > max_age_days:
            reasons.append(f"Report is {age_days:.0f} days old (limit {max_age_days}); "
                           "strategies decay — re-validate on recent data.")

    rep_hash = config_hash(report.get("strategy", {}).get("config", {})) \
        if isinstance(report.get("strategy"), dict) else None
    if rep_hash != expected_config_hash:
        reasons.append("Config-hash mismatch: the report was earned by a different "
                       "parameter set than the registered strategy. Re-validate "
                       "with the registered config.")

    return {"passed": not reasons, "reasons": reasons}


def _check_approval(approval: dict | None, label: str) -> list[str]:
    reasons: list[str] = []
    if not isinstance(approval, dict):
        return [f"{label}: no human approval recorded. A named approver, "
                "timestamp, and rationale are required."]
    if _blank(approval.get("approver")):
        reasons.append(f"{label}: approver id is blank.")
    if _parse_ts(approval.get("at")) is None:
        reasons.append(f"{label}: approval timestamp missing or unparseable.")
    if _blank(approval.get("rationale")):
        reasons.append(f"{label}: rationale is blank — approvals without a "
                       "written reason do not count.")
    return reasons


def gate_validated_to_paper(approval: dict | None,
                            incubation_enrolled: bool | None) -> dict:
    """VALIDATED -> PAPER: human approval AND incubation enrollment."""
    reasons = _check_approval(approval, "Paper authorization")
    if incubation_enrolled is not True:
        reasons.append("Strategy is not enrolled in an incubation program "
                       "(trade-incubate unreachable or not enrolled). Paper "
                       "trading without the incubation harness is refused — "
                       "fail closed, never open.")
    return {"passed": not reasons, "reasons": reasons}


def gate_paper_to_live(graduated: bool | None, approval: dict | None,
                       mode: str | None, policy_id: str | None,
                       policy_dirs: list[str] | None,
                       prior_approver: str | None = None,
                       require_distinct_approver: bool = True) -> dict:
    """PAPER -> LIVE: graduation + second approval + mode + policy.

    The two-person rule: the LIVE authorization should come from a
    different human than the PAPER authorization (configurable).
    """
    reasons: list[str] = []
    if graduated is not True:
        reasons.append("Incubation has not returned a GRADUATED verdict "
                       "(trade-incubate unreachable, still running, or refused). "
                       "LIVE without graduation is refused.")
    reasons.extend(_check_approval(approval, "Live authorization"))
    if mode not in VALID_MODES:
        reasons.append(f"Mode must be one of {list(VALID_MODES)} "
                       f"(got {mode!r}); the authorized autonomy level is "
                       "part of the approval and cannot be left implicit.")
    if require_distinct_approver and isinstance(approval, dict):
        who = str(approval.get("approver", "")).strip()
        if who and prior_approver and who == prior_approver:
            reasons.append("Two-person rule: the LIVE approver must differ from "
                           f"the PAPER approver ({prior_approver!r} authorized both).")
    if _blank(policy_id):
        reasons.append("No policy_id declared; PAPER->LIVE requires a recorded "
                       "investment-policy file.")
    else:
        resolved = _policy.resolve_policy(policy_id, policy_dirs or [])
        if resolved is None:
            reasons.append(f"Policy file for {policy_id!r} not found in "
                           f"{policy_dirs or []}; cannot verify the mandate "
                           "the strategy would trade under.")
    return {"passed": not reasons, "reasons": reasons}


def gate_pause(reason: str | None) -> dict:
    reasons: list[str] = []
    if _blank(reason):
        reasons.append("A pause requires a stated reason (kill condition, "
                       "manual intervention, drift — write it down).")
    return {"passed": not reasons, "reasons": reasons}


def gate_resume(approval: dict | None) -> dict:
    reasons = _check_approval(approval, "Resume authorization")
    return {"passed": not reasons, "reasons": reasons}


def gate_retire(reason: str | None) -> dict:
    reasons: list[str] = []
    if _blank(reason):
        reasons.append("Retirement requires a reason string — the audit trail "
                       "must say why a strategy died.")
    return {"passed": not reasons, "reasons": reasons}
