"""Tests for the trade_safety kernel: gates, breaker, policy, preflight, watchdog."""

from datetime import datetime, timedelta, timezone

import pytest

from trade_safety import (
    AccountSnapshot,
    ApprovalMode,
    CallbackApprover,
    MemoryAlertSink,
    MemoryAuditWriter,
    OrderIntent,
    SafetyConfig,
    SafetyKernel,
    SafetyState,
    Watchdog,
    run_preflight,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 25, 14, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def make_kernel(config: SafetyConfig | None = None, clock: FakeClock | None = None):
    clock = clock or FakeClock()
    audit = MemoryAuditWriter()
    alerts = MemoryAlertSink()
    kernel = SafetyKernel(
        config=config or SafetyConfig(approval_mode=ApprovalMode.AUTONOMOUS),
        state=SafetyState(),
        audit=audit,
        alert_sink=alerts,
        clock=clock,
    )
    return kernel, audit, alerts, clock


def account(**overrides) -> AccountSnapshot:
    base = dict(
        account_id="acc-1234",
        equity=100_000.0,
        buying_power=100_000.0,
        realized_pnl=0.0,
        unrealized_pnl=0.0,
        gross_exposure=0.0,
        maintenance_margin=0.0,
    )
    base.update(overrides)
    return AccountSnapshot(**base)


def intent(**overrides) -> OrderIntent:
    base = dict(symbol="SPY", action="BUY", quantity=1, price=100.0, strategy="test")
    base.update(overrides)
    return OrderIntent(**base)


# ---------------------------------------------------------------------------
# Basic gate behavior
# ---------------------------------------------------------------------------


def test_small_order_allowed_in_autonomous_mode():
    kernel, audit, _, _ = make_kernel()
    decision = kernel.check(intent(), account())
    assert decision.allowed
    assert "SAFETY_CHECK_PASS" in audit.actions()
    assert kernel.state.data["session"]["orders_allowed"] == 1


def test_estop_blocks_and_reset_restores():
    kernel, audit, alerts, _ = make_kernel()
    kernel.engage_estop(actor="Charlie", reason="drill")
    decision = kernel.check(intent(), account())
    assert not decision.allowed
    assert any("E-Stop" in r for r in decision.reasons)
    assert "SAFETY_ESTOP_ENGAGED" in audit.actions()
    assert alerts.alerts  # an alert was emitted

    kernel.reset_estop(actor="Charlie")
    assert kernel.check(intent(), account()).allowed


def test_anonymous_estop_reset_refused():
    kernel, _, _, _ = make_kernel()
    kernel.engage_estop(actor="Charlie", reason="drill")
    with pytest.raises(ValueError):
        kernel.reset_estop(actor="")


def test_per_trade_cap_blocks():
    kernel, _, _, _ = make_kernel()
    decision = kernel.check(intent(quantity=20, price=100.0), account())  # $2,000 > $1,000 cap
    assert not decision.allowed
    assert decision.checks["per_trade_cap"] is False


def test_market_order_notional_flagged_not_silently_passed():
    kernel, _, _, _ = make_kernel()
    decision = kernel.check(intent(price=None), account())
    assert decision.allowed
    assert any("unverifiable" in n for n in decision.notes)


def test_exposure_cap_blocks():
    kernel, _, _, _ = make_kernel()
    acct = account(gross_exposure=40_000.0)  # cap 50% of 100k = 50k
    decision = kernel.check(intent(quantity=200, price=100.0), acct)  # +20k -> 60k
    assert not decision.allowed
    assert decision.checks["exposure_cap"] is False


def test_margin_cushion_blocks():
    kernel, _, _, _ = make_kernel()
    acct = account(equity=10_000.0, maintenance_margin=8_000.0)  # cushion 20% < 25%
    decision = kernel.check(intent(), acct)
    assert not decision.allowed
    assert decision.checks["margin_cushion"] is False


def test_reduces_exposure_skips_caps_but_not_estop():
    kernel, _, _, _ = make_kernel()
    closing = intent(quantity=500, price=100.0, reduces_exposure=True)  # $50k notional
    assert kernel.check(closing, account()).allowed
    kernel.engage_estop(actor="Charlie", reason="drill")
    assert not kernel.check(closing, account()).allowed


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


def test_breaker_trips_and_locks_out_session():
    cfg = SafetyConfig(
        approval_mode=ApprovalMode.AUTONOMOUS,
        max_daily_loss_pct=None,
        max_daily_loss_abs=25.0,
    )
    kernel, audit, _, _ = make_kernel(cfg)
    losing = account(realized_pnl=-30.0)
    decision = kernel.check(intent(), losing)
    assert not decision.allowed
    assert kernel.state.data["session"]["breaker_tripped"] is True
    assert kernel.state.estop_engaged is True
    assert "SAFETY_BREAKER_TRIP" in audit.actions()

    # Resetting the E-Stop does NOT clear the session lockout.
    kernel.reset_estop(actor="Charlie")
    decision2 = kernel.check(intent(), account())
    assert not decision2.allowed
    assert any("breaker" in r for r in decision2.reasons)


def test_breaker_uses_smaller_of_pct_and_abs_limits():
    cfg = SafetyConfig(approval_mode=ApprovalMode.AUTONOMOUS)  # 2% and $25
    kernel, _, _, _ = make_kernel(cfg)
    # Session starts at $1,000 equity -> pct limit $20 binds before $25.
    assert kernel.check(intent(), account(equity=1_000.0)).allowed
    decision = kernel.check(intent(), account(equity=978.0, realized_pnl=-22.0))
    assert not decision.allowed
    assert kernel.state.data["session"]["breaker_tripped"] is True


def test_breaker_does_not_trip_below_limit():
    cfg = SafetyConfig(
        approval_mode=ApprovalMode.AUTONOMOUS,
        max_daily_loss_pct=None,
        max_daily_loss_abs=25.0,
    )
    kernel, _, _, _ = make_kernel(cfg)
    decision = kernel.check(intent(), account(realized_pnl=-10.0, unrealized_pnl=-5.0))
    assert decision.allowed
    assert kernel.state.data["session"]["breaker_tripped"] is False


# ---------------------------------------------------------------------------
# Approval policy
# ---------------------------------------------------------------------------


def test_approve_mode_without_approver_blocks():
    kernel, _, _, _ = make_kernel(SafetyConfig(approval_mode=ApprovalMode.APPROVE))
    decision = kernel.check(intent(), account())
    assert not decision.allowed
    assert any("no approver" in r for r in decision.reasons)


def test_approve_mode_callback_yes_and_no():
    yes = SafetyConfig(
        approval_mode=ApprovalMode.APPROVE,
        approver=CallbackApprover(approve_fn=lambda i: True),
    )
    kernel, _, _, _ = make_kernel(yes)
    assert kernel.check(intent(), account()).allowed

    no = SafetyConfig(
        approval_mode=ApprovalMode.APPROVE,
        approver=CallbackApprover(approve_fn=lambda i: False),
    )
    kernel2, _, _, _ = make_kernel(no)
    assert not kernel2.check(intent(), account()).allowed


def test_veto_window_veto_blocks_and_no_veto_passes():
    vetoed = SafetyConfig(
        approval_mode=ApprovalMode.VETO_WINDOW,
        approver=CallbackApprover(veto_fn=lambda i, w: True),
    )
    kernel, _, _, _ = make_kernel(vetoed)
    assert not kernel.check(intent(), account()).allowed

    quiet = SafetyConfig(
        approval_mode=ApprovalMode.VETO_WINDOW,
        approver=CallbackApprover(veto_fn=lambda i, w: False),
    )
    kernel2, _, _, _ = make_kernel(quiet)
    assert kernel2.check(intent(), account()).allowed


def test_doomed_order_never_reaches_approver():
    calls: list = []
    cfg = SafetyConfig(
        approval_mode=ApprovalMode.APPROVE,
        approver=CallbackApprover(approve_fn=lambda i: calls.append(i) or True),
    )
    kernel, _, _, _ = make_kernel(cfg)
    kernel.engage_estop(actor="Charlie", reason="drill")
    assert not kernel.check(intent(), account()).allowed
    assert calls == []  # approver not consulted for an already-blocked order


# ---------------------------------------------------------------------------
# State persistence & heartbeats
# ---------------------------------------------------------------------------


def test_state_persistence_roundtrip(tmp_path):
    path = tmp_path / "safety_state.json"
    kernel, _, _, clock = make_kernel()
    kernel.state = SafetyState(path)
    kernel.engage_estop(actor="Charlie", reason="persist me")
    reloaded = SafetyState(path)
    assert reloaded.estop_engaged is True
    assert reloaded.data["estop"]["reason"] == "persist me"


def test_heartbeat_age():
    kernel, _, _, clock = make_kernel()
    assert kernel.heartbeat_age_s("opend") is None
    kernel.beat("opend")
    assert kernel.heartbeat_age_s("opend") == pytest.approx(0.0, abs=0.01)
    clock.advance(30)
    assert kernel.heartbeat_age_s("opend") == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def test_preflight_real_offline_fails():
    kernel, _, _, _ = make_kernel()
    report = run_preflight(
        env="REAL", connected=False, account=account(), kernel=kernel, config=kernel.config
    )
    assert not report.passed
    assert ("gateway_connected", False, "OpenD must be connected for REAL") in report.checks


def test_preflight_real_simulated_fallback_account_fails():
    kernel, _, _, _ = make_kernel()
    report = run_preflight(
        env="REAL",
        connected=True,
        account=account(account_id="moomoo-simulated"),
        kernel=kernel,
        config=kernel.config,
    )
    assert not report.passed


def test_preflight_simulate_offline_passes():
    kernel, _, _, _ = make_kernel()
    report = run_preflight(
        env="SIMULATE",
        connected=False,
        account=account(account_id="moomoo-simulated", maintenance_margin=15_000.0),
        kernel=kernel,
        config=kernel.config,
    )
    assert report.passed, report.summary()


def test_preflight_account_last4_mismatch_fails():
    cfg = SafetyConfig(expected_account_last4="9999")
    kernel, _, _, _ = make_kernel(cfg)
    report = run_preflight(
        env="SIMULATE", connected=True, account=account(), kernel=kernel, config=cfg
    )
    assert not report.passed


def test_preflight_stale_data_and_insufficient_buying_power_fail():
    kernel, _, _, _ = make_kernel()
    report = run_preflight(
        env="SIMULATE",
        connected=True,
        account=account(buying_power=50.0),
        kernel=kernel,
        config=kernel.config,
        planned_notional=500.0,
        data_age_s=999.0,
    )
    assert not report.passed
    failed = {name for name, ok, _ in report.checks if not ok}
    assert {"buying_power", "data_fresh"} <= failed


# ---------------------------------------------------------------------------
# Watchdog
# ---------------------------------------------------------------------------


def test_watchdog_trips_on_stale_heartbeat_and_fires_callback():
    clock = FakeClock()
    kernel, _, _, _ = make_kernel(clock=clock)
    trips: list[str] = []
    watchdog = Watchdog(kernel, timeouts_s={"opend": 45.0}, on_trip=trips.append)
    kernel.beat("opend")
    assert watchdog.tick() == []
    clock.advance(100)
    assert watchdog.tick() == ["opend"]
    assert trips == ["opend"]
    assert kernel.state.estop_engaged is True
    # No double-trip while the source stays silent.
    assert watchdog.tick() == []


def test_watchdog_trips_on_never_received_heartbeat():
    kernel, _, _, _ = make_kernel()
    watchdog = Watchdog(kernel, timeouts_s={"opend": 45.0})
    assert watchdog.tick() == ["opend"]


def test_watchdog_recovers_when_beats_resume():
    clock = FakeClock()
    kernel, _, _, _ = make_kernel(clock=clock)
    watchdog = Watchdog(kernel, timeouts_s={"opend": 45.0})
    kernel.beat("opend")
    clock.advance(100)
    assert watchdog.tick() == ["opend"]
    kernel.beat("opend")  # gateway is back
    assert watchdog.tick() == []
