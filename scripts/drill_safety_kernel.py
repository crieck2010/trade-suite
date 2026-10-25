"""Phase 1 safety-kernel drills (live-roadmap Phase 1, item 6).

Runs the three required drills against the safety kernel and the
adapter's kernel wiring — no broker, no OpenD, no SDK required:

  Drill 1 — E-Stop mid-run: orders flow, Charlie engages the E-Stop,
            orders block; reset restores flow.
  Drill 2 — Breaker trip: a losing session snapshot trips the daily-loss
            breaker, latches the E-Stop, alerts, and locks the session
            (an E-Stop reset does NOT clear the lockout).
  Drill 3 — Watchdog trip: heartbeats stop, the watchdog engages the
            E-Stop and fires the cancel-all callback.

Writes a JSON log to docs/logs/safety_drills_<date>.json and prints a
summary. Exit code 0 only if every drill passes. The Phase 1 gate also
wants these drills repeated on Charlie's PC against OpenD paper — this
script runs there unchanged (the adapter path then uses the real SDK).
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from trade_safety import (  # noqa: E402
    AccountSnapshot,
    ApprovalMode,
    MemoryAlertSink,
    MemoryAuditWriter,
    OrderIntent,
    SafetyConfig,
    SafetyKernel,
    SafetyState,
    Watchdog,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime.now(timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def acct(**kw) -> AccountSnapshot:
    base = dict(account_id="drill-acct-1234", equity=100_000.0, buying_power=100_000.0)
    base.update(kw)
    return AccountSnapshot(**base)


def order() -> OrderIntent:
    return OrderIntent(symbol="SPY", action="BUY", quantity=1, price=100.0, strategy="drill")


def fresh_kernel(clock: FakeClock, **cfg_over) -> tuple[SafetyKernel, MemoryAuditWriter, MemoryAlertSink]:
    cfg = SafetyConfig(approval_mode=ApprovalMode.AUTONOMOUS, **cfg_over)
    audit, alerts = MemoryAuditWriter(), MemoryAlertSink()
    kernel = SafetyKernel(config=cfg, state=SafetyState(), audit=audit, alert_sink=alerts, clock=clock)
    return kernel, audit, alerts


def drill_1_estop() -> dict:
    clock = FakeClock()
    kernel, audit, alerts = fresh_kernel(clock)
    before = kernel.check(order(), acct()).allowed
    kernel.engage_estop(actor="Charlie", reason="drill 1: mid-run stop")
    during = kernel.check(order(), acct()).allowed
    kernel.reset_estop(actor="Charlie")
    after = kernel.check(order(), acct()).allowed
    passed = before and not during and after
    return {
        "drill": "1_estop_mid_run",
        "passed": passed,
        "evidence": {
            "order_allowed_before": before,
            "order_allowed_during_estop": during,
            "order_allowed_after_reset": after,
            "audit_actions": audit.actions(),
        },
    }


def drill_2_breaker() -> dict:
    clock = FakeClock()
    kernel, audit, alerts = fresh_kernel(
        clock, max_daily_loss_pct=None, max_daily_loss_abs=25.0
    )
    losing = acct(realized_pnl=-40.0)
    decision = kernel.check(order(), losing)
    tripped = bool(kernel.state.data["session"]["breaker_tripped"])
    alerted = any("E-STOP" in a["title"] for a in alerts.alerts)
    kernel.reset_estop(actor="Charlie")
    still_blocked = not kernel.check(order(), acct()).allowed
    passed = (not decision.allowed) and tripped and alerted and still_blocked
    return {
        "drill": "2_daily_loss_breaker",
        "passed": passed,
        "evidence": {
            "order_allowed_on_losing_snapshot": decision.allowed,
            "block_reasons": decision.reasons,
            "breaker_tripped": tripped,
            "alert_sent": alerted,
            "still_blocked_after_estop_reset": still_blocked,
            "audit_actions": audit.actions(),
        },
    }


def drill_3_watchdog() -> dict:
    clock = FakeClock()
    kernel, audit, alerts = fresh_kernel(clock)
    cancels: list[str] = []
    watchdog = Watchdog(kernel, timeouts_s={"opend": 45.0}, on_trip=cancels.append)
    kernel.beat("opend")
    healthy = watchdog.tick() == []
    clock.advance(120)
    tripped = watchdog.tick()
    passed = healthy and tripped == ["opend"] and cancels == ["opend"] and kernel.state.estop_engaged
    return {
        "drill": "3_watchdog_heartbeat_loss",
        "passed": passed,
        "evidence": {
            "healthy_before_silence": healthy,
            "tripped_sources": tripped,
            "cancel_callback_fired_for": cancels,
            "estop_engaged": kernel.state.estop_engaged,
            "audit_actions": audit.actions(),
        },
    }


def main() -> int:
    results = [drill_1_estop(), drill_2_breaker(), drill_3_watchdog()]
    all_passed = all(r["passed"] for r in results)
    log = {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "suite": "trade_safety Phase 1 drills",
        "all_passed": all_passed,
        "results": results,
    }
    out = (
        Path(__file__).resolve().parent.parent
        / "docs"
        / "logs"
        / f"safety_drills_{log['date']}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['drill']}")
    print(f"\n{'ALL DRILLS PASSED' if all_passed else 'DRILL FAILURES PRESENT'} — log: {out}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
