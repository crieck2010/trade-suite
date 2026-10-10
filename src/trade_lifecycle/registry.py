"""The strategy registry: append-only JSONL event log, replayed to state.

Every registration, every allowed transition, and — as a first-class
feature — every REFUSED transition attempt is appended with timestamp,
actor, and reasons.  Auditors read refusals: a strategy that was never
refused was never really gated.

Current state is derived by folding the event log, so the log is the
single source of truth and history can never be rewritten.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from . import gates, lifecycle
from .lifecycle import STATES

SCHEMA_VERSION = 1


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class StrategyRegistry:
    """Append-only registry.  ``clock`` is injectable for deterministic tests."""

    def __init__(self, path: str, clock=None):
        self.path = path
        self._clock = clock or _utcnow
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("")

    # ------------------------------------------------------------- events

    def _append(self, event: dict) -> dict:
        event = {"schema_version": SCHEMA_VERSION, "ts": self._clock(), **event}
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, default=str) + "\n")
        return event

    def _events(self) -> list[dict]:
        out = []
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def _fold(self) -> dict:
        """Replay the log into {strategy_id: record}."""
        records: dict[str, dict] = {}
        for ev in self._events():
            sid = ev.get("strategy_id")
            kind = ev.get("event")
            if kind == "registered" and sid:
                records[sid] = {
                    "strategy_id": sid,
                    "name": ev.get("name", ""),
                    "family": ev.get("family", ""),
                    "created_at": ev.get("ts"),
                    "config": ev.get("config", {}),
                    "config_hash": ev.get("config_hash", ""),
                    "policy_id": ev.get("policy_id"),
                    "state": "RESEARCH",
                    "paused": False,
                    "paused_reason": None,
                    "approvals": [],
                }
            elif sid in records:
                rec = records[sid]
                if kind == "transition":
                    to = (ev.get("result") or {}).get("to")
                    if to == "PAUSED":
                        rec["paused"] = True
                        rec["paused_reason"] = ev.get("reason")
                    elif to == "RESUME":
                        rec["paused"] = False
                        rec["paused_reason"] = None
                    elif to in STATES:
                        rec["state"] = to
                        rec["paused"] = False
                        rec["paused_reason"] = None
                    for ap in ev.get("approvals", []):
                        rec["approvals"].append(ap)
        return records

    # ------------------------------------------------------------ actions

    def register(self, strategy_id: str, name: str, family: str,
                 config: dict, policy_id: str | None = None,
                 actor: str = "system") -> dict:
        records = self._fold()
        if strategy_id in records:
            raise ValueError(f"Strategy {strategy_id!r} is already registered.")
        if not strategy_id or not str(strategy_id).strip():
            raise ValueError("strategy_id is required.")
        if not isinstance(config, dict):
            raise ValueError("config must be a dict.")
        event = self._append({
            "event": "registered",
            "strategy_id": strategy_id,
            "name": name,
            "family": family,
            "config": config,
            "config_hash": gates.config_hash(config),
            "policy_id": policy_id,
            "actor": actor,
        })
        return {"registered": True, "strategy_id": strategy_id,
                "config_hash": event["config_hash"], "state": "RESEARCH"}

    def status(self, strategy_id: str) -> dict | None:
        rec = self._fold().get(strategy_id)
        if rec is None:
            return None
        return {k: v for k, v in rec.items() if k != "approvals"} | \
               {"approvals": len(rec["approvals"])}

    def history(self, strategy_id: str, refusals_only: bool = False) -> list[dict]:
        evs = [e for e in self._events() if e.get("strategy_id") == strategy_id]
        if refusals_only:
            evs = [e for e in evs if e.get("event") == "refusal"]
        return evs

    def refusals(self, strategy_id: str | None = None) -> list[dict]:
        evs = [e for e in self._events() if e.get("event") == "refusal"]
        if strategy_id is not None:
            evs = [e for e in evs if e.get("strategy_id") == strategy_id]
        return evs

    # ------------------------------------------------------- the committee

    def attempt(self, strategy_id: str, to: str, actor: str = "human",
                preset: dict | None = None, **inputs) -> dict:
        """Try a transition.  Returns a TransitionResult; refusals are logged.

        ``inputs`` carries the guard evidence: report=, approval=,
        graduated=, incubation_enrolled=, mode=, policy_dirs=, reason=.
        """
        from .presets import get_preset  # local import: no cycles
        preset = preset or get_preset("strict")
        rec = self._fold().get(strategy_id)
        at = self._clock()
        if rec is None:
            result = lifecycle.transition_result(
                allowed=False, reasons=[f"Unknown strategy {strategy_id!r}."],
                frm="?", to=to, at=at, actor=actor)
            self._append({"event": "refusal", "strategy_id": strategy_id,
                          "actor": actor, "result": result})
            return result

        state, paused = rec["state"], rec["paused"]
        table = lifecycle.classify(to, state, paused)
        if not table["legal"]:
            result = lifecycle.transition_result(
                allowed=False, reasons=[table["note"]],
                frm=state, to=to, at=at, actor=actor, paused=paused)
            self._append({"event": "refusal", "strategy_id": strategy_id,
                          "actor": actor, "result": result})
            return result

        guard_reasons, extra = self._run_guard(
            table["kind"], state, to, rec, preset, inputs, at)
        if guard_reasons:
            result = lifecycle.transition_result(
                allowed=False, reasons=[table["note"]] + guard_reasons,
                frm=state, to=to, at=at, actor=actor, paused=paused)
            self._append({"event": "refusal", "strategy_id": strategy_id,
                          "actor": actor, "result": result})
            return result

        result = lifecycle.transition_result(
            allowed=True, reasons=[table["note"]], frm=state, to=to,
            at=at, actor=actor, paused=(to == "PAUSED"))
        event = {"event": "transition", "strategy_id": strategy_id,
                 "actor": actor, "result": result, "approvals": extra.get("approvals", [])}
        if extra.get("reason"):
            event["reason"] = extra["reason"]
        if extra.get("policy_checksum"):
            event["policy_checksum"] = extra["policy_checksum"]
        if extra.get("mode"):
            event["mode"] = extra["mode"]
        self._append(event)
        return result

    # -------------------------------------------------------------- guards

    def _run_guard(self, kind: str, state: str, to: str, rec: dict,
                   preset: dict, inputs: dict, at: str):
        """Dispatch to the guard for this transition kind.

        Returns (reasons: list[str], extra: dict).  Empty reasons = pass.
        """
        from . import policy as _policy
        now = datetime.fromisoformat(at)
        extra: dict = {}

        if kind == "forward" and state == "RESEARCH" and to == "VALIDATED":
            report = inputs.get("report")
            if report is None:
                from . import adapters
                report = adapters.get_validation_report(rec["strategy_id"])
            g = gates.gate_research_to_validated(
                report, rec["config_hash"],
                allow_warns=bool(preset.get("allow_warns", False)),
                max_age_days=int(preset.get("max_age_days", 90)), now=now)
            return g["reasons"], extra

        if kind == "forward" and state == "VALIDATED" and to == "PAPER":
            approval = inputs.get("approval")
            enrolled = inputs.get("incubation_enrolled")
            if enrolled is None:
                from . import adapters
                st = adapters.get_incubation_status(rec["strategy_id"])
                enrolled = bool(st and st.get("enrolled"))
            g = gates.gate_validated_to_paper(approval, enrolled)
            if not g["reasons"] and isinstance(approval, dict):
                extra["approvals"] = [{"kind": "paper", **approval}]
            return g["reasons"], extra

        if kind == "forward" and state == "PAPER" and to == "LIVE":
            approval = inputs.get("approval")
            graduated = inputs.get("graduated")
            if graduated is None:
                from . import adapters
                st = adapters.get_incubation_status(rec["strategy_id"])
                graduated = bool(st and st.get("graduated"))
            mode = inputs.get("mode")
            policy_dirs = inputs.get("policy_dirs") or []
            prior = rec["approvals"][-1].get("approver") if rec["approvals"] else None
            g = gates.gate_paper_to_live(
                graduated, approval, mode, rec.get("policy_id"), policy_dirs,
                prior_approver=prior,
                require_distinct_approver=bool(preset.get("require_distinct_approver", True)))
            if not g["reasons"]:
                if isinstance(approval, dict):
                    extra["approvals"] = [{"kind": "live", **approval}]
                extra["mode"] = mode
                resolved = _policy.resolve_policy(rec["policy_id"], policy_dirs)
                if resolved:
                    extra["policy_checksum"] = resolved["checksum"]
            return g["reasons"], extra

        if kind == "pause":
            g = gates.gate_pause(inputs.get("reason"))
            if not g["reasons"]:
                extra["reason"] = inputs.get("reason")
            return g["reasons"], extra

        if kind == "resume":
            g = gates.gate_resume(inputs.get("approval"))
            if not g["reasons"] and isinstance(inputs.get("approval"), dict):
                extra["approvals"] = [{"kind": "resume", **inputs["approval"]}]
            return g["reasons"], extra

        if kind == "retire":
            g = gates.gate_retire(inputs.get("reason"))
            if not g["reasons"]:
                extra["reason"] = inputs.get("reason")
            return g["reasons"], extra

        return [f"No guard implemented for {kind} {state}>{to}; failing closed."], extra

    # ------------------------------------------------------- conveniences

    def pause(self, strategy_id: str, reason: str, actor: str = "human",
              **kw) -> dict:
        return self.attempt(strategy_id, "PAUSED", actor=actor, reason=reason, **kw)

    def resume(self, strategy_id: str, approval: dict, actor: str = "human",
               **kw) -> dict:
        return self.attempt(strategy_id, "RESUME", actor=actor, approval=approval, **kw)

    def retire(self, strategy_id: str, reason: str, actor: str = "human",
               **kw) -> dict:
        return self.attempt(strategy_id, "RETIRED", actor=actor, reason=reason, **kw)

    def promote(self, strategy_id: str, to: str, actor: str = "human",
                **kw) -> dict:
        return self.attempt(strategy_id, to, actor=actor, **kw)
