"""Unit tests for trade_dashboard_app services, data contracts, and audit logging."""

import os
from pathlib import Path
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
