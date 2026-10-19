"""Unit tests for trade_dashboard_app services, data contracts, and audit logging."""

import importlib.util
import os
from pathlib import Path

import pytest
from trade_dashboard_app.services import (
    PortfolioMetrics,
    Position,
    AssetAllocation,
    AgentNodeStatus,
    OrderRecord,
    RiskStatus,
    HardwareInferenceMetrics,
    record_audit_event,
    read_audit_log,
    get_portfolio_metrics,
    get_active_positions,
    get_asset_allocation,
    get_macro_regime_status,
    get_business_state,
    get_node_topology,
    get_debate_transcript,
    get_agent_reputation_leaderboard,
    get_hardware_metrics,
    get_risk_status,
    trigger_kill_switch,
    reset_kill_switch,
    get_pending_proposals,
    resolve_proposal,
    get_hedge_loop_status,
    get_order_blotter,
    get_validation_telemetry,
)


def test_portfolio_service_defaults():
    metrics = get_portfolio_metrics(ledger_path="nonexistent.db")
    assert isinstance(metrics, PortfolioMetrics)
    assert metrics.net_liquidity > 0
    assert metrics.vix > 0

    positions = get_active_positions(ledger_path="nonexistent.db")
    assert len(positions) > 0
    for p in positions:
        assert isinstance(p, Position)
        assert p.symbol in ["XLE", "SPY", "GLD", "CPER", "URA"]
        assert p.quantity > 0

    alloc = get_asset_allocation()
    assert isinstance(alloc, AssetAllocation)
    assert alloc.real_assets_pct + alloc.equities_pct + alloc.cash_short_term_pct == 100.0

    regime = get_macro_regime_status()
    assert "regime_label" in regime
    assert regime["regime_label"] == "EXPANSION"


def test_agent_service_contracts():
    state = get_business_state()
    assert "messages" in state
    assert "task_backlog" in state
    assert "active_assignments" in state
    assert len(state["task_backlog"]) > 0

    nodes = get_node_topology()
    assert len(nodes) == 5
    node_names = [n.name for n in nodes]
    assert any("Orchestrator" in name for name in node_names)
    assert any("Worker Pool" in name for name in node_names)

    debate = get_debate_transcript()
    assert len(debate) >= 4
    assert debate[0].role == "Bull Challenger"
    assert debate[-1].role == "Consensus"

    leaderboard = get_agent_reputation_leaderboard()
    assert len(leaderboard) >= 4
    top_agent = leaderboard[0]
    assert top_agent.realized_oos_sharpe > 1.0

    hw = get_hardware_metrics()
    assert isinstance(hw, HardwareInferenceMetrics)
    assert hw.vram_total_gb == 512.0
    assert hw.vram_free_gb >= 64.0


def test_audit_service_atomic_logging(tmp_path: Path):
    test_log = tmp_path / "test_audit.json"
    
    event = record_audit_event(
        action="TEST_ACTION",
        actor="Test Runner",
        details={"key": "value"},
        log_path=test_log,
    )
    assert event["action"] == "TEST_ACTION"
    assert test_log.exists()

    events = read_audit_log(limit=10, log_path=test_log)
    assert len(events) == 1
    assert events[0]["actor"] == "Test Runner"
    assert events[0]["details"]["key"] == "value"


def test_risk_controls_kill_switch_and_proposals(tmp_path: Path):
    # Test Kill Switch
    status_before = get_risk_status()
    assert not status_before.kill_switch_active

    trigger_kill_switch(reason="Testing emergency trigger", actor="PyTest")
    status_halted = get_risk_status()
    assert status_halted.kill_switch_active
    assert "Testing emergency trigger" in status_halted.kill_switch_reason

    reset_kill_switch(actor="PyTest")
    status_restored = get_risk_status()
    assert not status_restored.kill_switch_active

    # Test Proposals
    proposals = get_pending_proposals()
    assert len(proposals) > 0
    p_id = proposals[0].proposal_id
    success = resolve_proposal(p_id, approved=True, actor="PyTest")
    assert success
    remaining = [p for p in get_pending_proposals() if p.proposal_id == p_id]
    assert len(remaining) == 0


def test_execution_service_blotter_and_telemetry():
    blotter = get_order_blotter()
    assert len(blotter) > 0
    for order in blotter:
        assert isinstance(order, OrderRecord)
        assert order.symbol in ["SPY", "CPER", "TLT", "XLE"]
        assert len(order.rationale) > 0

    telem = get_validation_telemetry()
    assert telem["deflated_sharpe_ratio"] == 1.000
    assert telem["dsr_verdict"] == "PASS"
    assert telem["oos_median_sharpe"] == 1.385


def test_options_service_em_decay():
    from trade_dashboard_app.services import (
        EMDecayStatus,
        get_em_decay_status,
        get_iron_fly_setup,
        get_skip_day_status,
        get_vol_surface_spread,
    )
    from datetime import date

    # Test triggered decay (82.06% <= 83.0%)
    status_triggered = get_em_decay_status(opening_em=48.50, call_mid=19.80, put_mid=20.00)
    assert isinstance(status_triggered, EMDecayStatus)
    assert status_triggered.decay_pct <= 83.0
    assert status_triggered.triggered is True
    assert "TRIGGERED" in status_triggered.trigger_message

    # Test untriggered decay (90.72% > 83.0%)
    status_waiting = get_em_decay_status(opening_em=48.50, call_mid=22.00, put_mid=22.00)
    assert status_waiting.decay_pct > 83.0
    assert status_waiting.triggered is False
    assert "WAITING" in status_waiting.trigger_message

    # Test skip-day conditioning
    skip_clean = get_skip_day_status(target_date=date(2026, 10, 11))
    assert isinstance(skip_clean.reasons, list)

    # Known scheduled FOMC announcement date
    skip_fomc = get_skip_day_status(target_date=date(2026, 10, 28))
    assert skip_fomc.is_skip_day is True
    assert skip_fomc.fomc_active is True
    assert "fomc" in skip_fomc.reasons

    # Test Volatility Surface Spread & VIX Term Structure
    vol = get_vol_surface_spread()
    assert vol.iv_rv_spread > 0  # Rich IV
    assert vol.vix_ratio < 1.0   # Contango
    assert "Contango" in vol.term_structure

    # Test Iron-Fly Structure
    fly = get_iron_fly_setup(strike=5800.0)
    assert fly.atm_strike == 5800.0
    assert fly.call_long == 5850.0
    assert fly.put_long == 5750.0
    assert fly.recommended_lots % 5 == 0  # Multiples of 5 rule
    assert fly.max_risk_per_spread > 0


def test_stress_service_evaluations():
    from trade_dashboard_app.services import (
        HISTORICAL_PRESETS,
        ShockResult,
        evaluate_portfolio_shock,
        generate_gamma_curve_points,
    )

    assert len(HISTORICAL_PRESETS) >= 4
    preset_names = [p.name for p in HISTORICAL_PRESETS]
    assert any("COVID" in p for p in preset_names)
    assert any("2022" in p for p in preset_names)

    # Moderate bear shock: SPX -3%, VIX +10, Yield +25 bps
    res = evaluate_portfolio_shock(
        delta_spx_pct=-3.0,
        delta_vix_pts=10.0,
        delta_yield_bps=25.0,
    )
    assert isinstance(res, ShockResult)
    assert res.projected_nlv < res.initial_nlv
    assert res.total_dollar_pnl < 0
    assert res.equity_legs_pnl < 0
    assert res.duration_leg_pnl < 0  # Yield spike hurts TLT
    assert res.options_legs_pnl < 0   # Vega + Gamma loss
    assert res.post_shock_gamma > 142.50  # Gamma surges
    assert res.proposed_hedge_action in ["SELL (TRIM)", "NONE"]
    assert res.proposed_hedge_instrument == "SPY"

    # Severe crash shock: SPX -10%, VIX +30, Yield -30 bps -> should trigger kill threshold
    crash_res = evaluate_portfolio_shock(
        delta_spx_pct=-10.0,
        delta_vix_pts=30.0,
        delta_yield_bps=-30.0,
    )
    assert crash_res.breach_kill_threshold is True
    assert crash_res.total_pct_pnl < -3.0

    # Gamma curve generation
    curve = generate_gamma_curve_points(delta_vix=10.0, delta_yield=25.0)
    assert len(curve) == 11
    assert curve[0]["SPX Move (%)"] == -5.0
    assert curve[-1]["SPX Move (%)"] == 5.0


# streamlit is an optional dependency (pyproject 'dashboard' extra).
# The tab modules import it at module level, so this test — the only one
# that renders a tab — skips cleanly on machines without it.
requires_streamlit = pytest.mark.skipif(
    importlib.util.find_spec("streamlit") is None,
    reason="streamlit not installed (optional 'dashboard' extra)",
)


@requires_streamlit
def test_field_service_and_telemetry():
    from trade_dashboard_app.services import (
        FieldTelemetry,
        execute_field_emergency_action,
        get_field_telemetry,
        get_risk_status,
        read_audit_log,
        reset_kill_switch,
    )
    from trade_dashboard_app.tabs import render_tab8

    # Ensure clean starting state
    reset_kill_switch(actor="Test Runner")

    telemetry = get_field_telemetry()
    assert isinstance(telemetry, FieldTelemetry)
    assert telemetry.net_liquidity > 0
    assert telemetry.vix > 0
    assert telemetry.tailscale_ip == "100.82.140.22"
    assert telemetry.tailscale_latency_ms == 24
    assert telemetry.system_health in ["NOMINAL", "ELEVATED_RISK", "CRITICAL_BREACH"]
    assert isinstance(telemetry.alerts, list)

    # Test 1-Tap Emergency E-Stop
    res_estop = execute_field_emergency_action("FULL_E_STOP", actor="Test Operator")
    assert res_estop["status"] == "SUCCESS"
    assert get_risk_status().kill_switch_active is True

    # Telemetry should now report critical breach with kill switch alert
    telemetry_breach = get_field_telemetry()
    assert telemetry_breach.system_health == "CRITICAL_BREACH"
    assert any("KILL SWITCH" in a.title for a in telemetry_breach.alerts)

    # Test Reset E-Stop
    res_reset = execute_field_emergency_action("RESET_E_STOP", actor="Test Operator")
    assert res_reset["status"] == "SUCCESS"
    assert get_risk_status().kill_switch_active is False

    # Test 1-Tap Flatten 0DTE Wings
    res_flatten = execute_field_emergency_action("FLATTEN_0DTE_WINGS", actor="Test Operator")
    assert res_flatten["status"] == "SUCCESS"

    # Test 1-Tap Hedge Delta Neutral
    res_hedge = execute_field_emergency_action("HEDGE_DELTA_NEUTRAL", actor="Test Operator")
    assert res_hedge["status"] == "SUCCESS"

    # Verify audit log recorded events
    recent_audits = read_audit_log(limit=10)
    audit_actions = [e.get("action") for e in recent_audits]
    assert "KILL_SWITCH_ACTIVATED" in audit_actions
    assert "KILL_SWITCH_RESET" in audit_actions
    assert "FIELD_FLATTEN_0DTE_WINGS" in audit_actions
    assert "FIELD_HEDGE_DELTA_NEUTRAL" in audit_actions

    # Verify tab8 callable
    assert callable(render_tab8)



