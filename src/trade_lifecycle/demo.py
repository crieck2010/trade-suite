"""Seeded lifecycle theater (deterministic): the committee in action.

Four strategies walk the lifecycle under a fixed clock:

- A ``trend-7``: clean validation report -> VALIDATED -> PAPER (human
  approval + incubation) -> graduates -> LIVE with autonomous mode
  authorized and the policy checksum recorded.
- B ``chop-9``: failing gates -> ``promote`` REFUSES with enumerated
  reasons.  The refusal is logged.
- C ``fade-3``: reaches PAPER, then a drift kill-condition pauses it.
- D ``old-1``: retired with a reason; a later promotion attempt out of
  RETIRED is refused loudly — terminal means terminal.

Nothing here touches a broker.  All sibling reads are injected fakes so
the demo runs with zero siblings installed.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone

from . import adapters, policy as _policy
from .registry import StrategyRegistry

SEED = 7
# Fixed clock: the demo is deterministic and never goes stale.
DEMO_NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


def _clock():
    return DEMO_NOW.isoformat()


def make_report(config: dict, gate_verdicts: list[tuple[str, str]],
                generated_utc: str, status: str | None = None) -> dict:
    """Build a trade-swing-shaped ValidationReport (schema_version 1)."""
    gates = [{"name": name, "verdict": verdict, "value": 1.0 if verdict == "PASS" else -1.0,
              "threshold": 0.0, "margin": 1.0 if verdict == "PASS" else -1.0}
             for name, verdict in gate_verdicts]
    if status is None:
        status = ("FAIL" if any(v == "FAIL" for _, v in gate_verdicts)
                  else "WARN" if any(v == "WARN" for _, v in gate_verdicts)
                  else "PASS")
    return {
        "schema_version": 1,
        "generated_utc": generated_utc,
        "strategy": {"name": "demo", "family": "demo",
                     "config": config},
        "data_provenance": {"source": "demo"},
        "backtest": {"engine": "demo", "metrics": {}},
        "costs": {},
        "validation": {"status": status, "gates": gates},
        "limitations": ["demo report"],
    }


def _approval(who: str, rationale: str, days_ago: int = 1) -> dict:
    return {"approver": who,
            "at": (DEMO_NOW - timedelta(days=days_ago)).isoformat(),
            "rationale": rationale}


def run_demo(seed: int = SEED) -> dict:
    """Run the theater; returns a plain-data summary (deterministic)."""
    _ = seed  # the theater is scripted; the seed documents determinism
    tmp = tempfile.mkdtemp(prefix="trade_lifecycle_demo_")
    policy_dir = os.path.join(tmp, "policies")
    fund_policy = _policy.write_policy(
        policy_dir, "fund-ips-v1",
        "# Investment Policy Statement (demo)\n\n"
        "Max drawdown 15%. Vol target 10%. No leverage. "
        "Kill switch: human only.\n")

    adapters.clear_backends()
    adapters.use_backends(
        incubation_status_fn=lambda sid: {
            "trend-7": {"enrolled": True, "graduated": True},
            "fade-3": {"enrolled": True, "graduated": False},
        }.get(sid, {"enrolled": False, "graduated": False}),
    )

    reg = StrategyRegistry(os.path.join(tmp, "registry.jsonl"), clock=_clock)
    log: list[str] = []

    def say(msg: str) -> None:
        log.append(msg)

    def show(result: dict) -> None:
        mark = "ALLOW " if result["allowed"] else "REFUSE"
        say(f"  [{mark}] {result['from']} -> {result['to']}")
        for reason in result["reasons"]:
            say(f"         - {reason}")

    fresh = (DEMO_NOW - timedelta(days=20)).isoformat()
    cfg_a = {"fast": 20, "slow": 50, "atr_period": 14}

    # ------------------------------------------------ strategy A: the full path
    say("A trend-7 — the full path to LIVE:")
    reg.register("trend-7", "Trend Seven", "ma-cross", cfg_a,
                 policy_id="fund-ips-v1", actor="demo")
    report_a = make_report(cfg_a, [
        ("deflated_sharpe", "PASS"), ("walk_forward", "PASS"),
        ("max_drawdown", "PASS"), ("worst_regime", "PASS"),
        ("net_excess", "PASS")], fresh)
    show(reg.promote("trend-7", "VALIDATED", actor="demo", report=report_a))
    show(reg.promote("trend-7", "PAPER", actor="alice",
                     approval=_approval("alice", "Validation clean; enroll in Q4 incubation.")))
    show(reg.promote("trend-7", "LIVE", actor="bob",
                     approval=_approval("bob", "Graduated; authorizing autonomous mode."),
                     graduated=True, mode="autonomous",
                     policy_dirs=[policy_dir]))

    # ------------------------------------------------ strategy B: refused at the gate
    say("B chop-9 — refused at validation:")
    cfg_b = {"fast": 5, "slow": 10, "atr_period": 14}
    reg.register("chop-9", "Chop Nine", "ma-cross", cfg_b, actor="demo")
    report_b = make_report(cfg_b, [
        ("deflated_sharpe", "FAIL"), ("walk_forward", "FAIL"),
        ("max_drawdown", "PASS"), ("worst_regime", "FAIL"),
        ("net_excess", "WARN")], fresh)
    show(reg.promote("chop-9", "VALIDATED", actor="demo", report=report_b))
    # ...and it cannot skip ahead either:
    show(reg.promote("chop-9", "PAPER", actor="demo",
                     approval=_approval("mallory", "Trust me.")))

    # ------------------------------------------------ strategy C: paused in paper
    say("C fade-3 — paused by a kill condition in PAPER:")
    cfg_c = {"fast": 20, "slow": 50, "atr_period": 14}
    reg.register("fade-3", "Fade Three", "ma-cross", cfg_c, actor="demo")
    report_c = make_report(cfg_c, [
        ("deflated_sharpe", "PASS"), ("walk_forward", "PASS"),
        ("max_drawdown", "PASS"), ("worst_regime", "PASS"),
        ("net_excess", "PASS")], fresh)
    show(reg.promote("fade-3", "VALIDATED", actor="demo", report=report_c))
    show(reg.promote("fade-3", "PAPER", actor="alice",
                     approval=_approval("alice", "Enrolling for observation.")))
    show(reg.pause("fade-3", actor="risk-desk",
                   reason="Kill condition: drift VIOLATION — win rate collapsed in week 7."))
    # paused strategies cannot promote until resumed:
    show(reg.promote("fade-3", "LIVE", actor="bob",
                     approval=_approval("bob", "Trying to skip the pause."),
                     graduated=True, mode="supervised", policy_dirs=[policy_dir]))

    # ------------------------------------------------ strategy D: retired is terminal
    say("D old-1 — retired; terminal means terminal:")
    reg.register("old-1", "Old One", "ma-cross", cfg_a, actor="demo")
    show(reg.retire("old-1", actor="alice",
                    reason="Superseded by trend-7; edge decayed after 2024."))
    show(reg.promote("old-1", "VALIDATED", actor="mallory", report=report_a))

    refusals = reg.refusals()
    say(f"Refusal log: {len(refusals)} refused attempts recorded.")
    adapters.clear_backends()
    return {
        "seed": seed,
        "theater": log,
        "final_states": {sid: reg.status(sid) for sid in
                         ("trend-7", "chop-9", "fade-3", "old-1")},
        "n_refusals": len(refusals),
        "policy_checksum": fund_policy["checksum"],
    }


def main() -> int:
    summary = run_demo()
    for line in summary["theater"]:
        print(line)
    print()
    for sid, st in summary["final_states"].items():
        paused = " (PAUSED)" if st["paused"] else ""
        print(f"{sid}: {st['state']}{paused}")
    print(f"\nRefusals logged: {summary['n_refusals']}")
    return 0
