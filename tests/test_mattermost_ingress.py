"""Unit tests for Mattermost & Tailscale Ingress Gateway and LangGraph State DAG."""

import pytest

from trade_agents.orchestrator import (
    IngressMessage,
    IngressResponse,
    LangGraphCyclicStateDAG,
    MattermostEgressNotifier,
    MattermostIngressGateway,
    MessageSource,
    is_tailscale_ip,
)
from trade_dashboard_app.services import (
    dispatch_mobile_mattermost_command,
    get_mattermost_gateway_status,
    get_risk_status,
    reset_kill_switch,
)


def test_tailscale_ip_validation():
    # Tailscale CGNAT subnet (100.64.0.0/10)
    assert is_tailscale_ip("100.82.140.22") is True
    assert is_tailscale_ip("100.64.0.1") is True
    assert is_tailscale_ip("100.127.255.254") is True
    # Localhost
    assert is_tailscale_ip("127.0.0.1") is True
    assert is_tailscale_ip("localhost") is True
    # Non-Tailscale IP addresses
    assert is_tailscale_ip("192.168.1.50") is False
    assert is_tailscale_ip("10.0.0.1") is False
    assert is_tailscale_ip("8.8.8.8") is False
    assert is_tailscale_ip("invalid-ip") is False


def test_langgraph_cyclic_state_dag():
    dag = LangGraphCyclicStateDAG()
    dag.append_message(role="user", content="Test objective", name="Charlie")
    dag.route_task("T-999", "Calculate 0DTE delta wings", "High")

    state = dag.get_state()
    assert len(state["messages"]) == 1
    assert state["messages"][0]["name"] == "Charlie"
    assert len(state["task_backlog"]) == 1
    assert state["task_backlog"][0]["id"] == "T-999"

    # Advance cycle
    new_state = dag.advance_cycle()
    assert len(new_state["active_assignments"]) >= 1
    assert any(a["task_id"] == "T-999" for a in new_state["active_assignments"])


def test_mattermost_ingress_security_rejection():
    gateway = MattermostIngressGateway(enforce_tailscale=True)

    # Untrusted public IP should be rejected with 403
    untrusted_msg = IngressMessage(
        command="/trade",
        text="status",
        remote_ip="203.0.113.195",  # Public internet IP
    )
    resp = gateway.handle_request(untrusted_msg)
    assert resp.status_code == 403
    assert "ACCESS DENIED" in resp.text


def test_mattermost_ingress_slash_commands():
    # Clean baseline state
    reset_kill_switch(actor="Test Runner")

    dag = LangGraphCyclicStateDAG()
    gateway = MattermostIngressGateway(dag=dag, enforce_tailscale=True)

    # 1. /trade status
    status_msg = IngressMessage(
        command="/trade",
        text="status",
        remote_ip="100.82.140.22",
    )
    resp_status = gateway.handle_request(status_msg)
    assert resp_status.status_code == 200
    assert "Net Liquidity" in resp_status.text
    assert "VIX" in resp_status.text

    # 2. /trade estop (Emergency Halt)
    estop_msg = IngressMessage(
        command="/trade",
        text="estop Field operator observed hyper-gamma anomaly",
        remote_ip="100.82.140.22",
    )
    resp_estop = gateway.handle_request(estop_msg)
    assert resp_estop.status_code == 200
    assert "KILL SWITCH ENGAGED" in resp_estop.text
    assert get_risk_status().kill_switch_active is True

    # 3. /trade reset-estop
    reset_msg = IngressMessage(
        command="/trade",
        text="reset-estop",
        remote_ip="100.82.140.22",
    )
    resp_reset = gateway.handle_request(reset_msg)
    assert resp_reset.status_code == 200
    assert "KILL SWITCH DISENGAGED" in resp_reset.text
    assert get_risk_status().kill_switch_active is False

    # 4. /trade flatten-0dte
    flatten_msg = IngressMessage(
        command="/trade",
        text="flatten-0dte",
        remote_ip="100.82.140.22",
    )
    resp_flatten = gateway.handle_request(flatten_msg)
    assert resp_flatten.status_code == 200
    assert "0DTE Premium Flattening" in resp_flatten.text

    # 5. /trade hedge-delta
    hedge_msg = IngressMessage(
        command="/trade",
        text="hedge-delta",
        remote_ip="100.82.140.22",
    )
    resp_hedge = gateway.handle_request(hedge_msg)
    assert resp_hedge.status_code == 200
    assert "Delta Neutralization" in resp_hedge.text

    # 6. /trade brief (Strategy intake per Strategy Intake Guide)
    brief_msg = IngressMessage(
        command="/trade",
        text="brief Dale Perryman 0DTE Iron Fly | Short ATM straddle harvest at 83% decay | SPX",
        remote_ip="100.82.140.22",
    )
    resp_brief = gateway.handle_request(brief_msg)
    assert resp_brief.status_code == 200
    assert "Strategy Brief Captured" in resp_brief.text

    # 7. /trade help
    help_msg = IngressMessage(
        command="/trade",
        text="help",
        remote_ip="100.82.140.22",
    )
    resp_help = gateway.handle_request(help_msg)
    assert resp_help.status_code == 200
    assert "/trade estop" in resp_help.text


def test_mattermost_egress_notifier_failsoft():
    # When webhook URL is unconfigured, should return False gracefully without raising exceptions
    notifier = MattermostEgressNotifier(webhook_url="")
    assert notifier.is_configured() is False
    assert notifier.notify_kill_switch_engaged(reason="Test", actor="Test") is False
    assert notifier.notify_hyper_gamma_breach(gamma=250.0, threshold=200.0) is False
    assert notifier.notify_proposal_staged("P-001", "SPY", "BUY", 100, "REGCOND-1", "Test") is False


def test_dashboard_service_dispatch():
    status = get_mattermost_gateway_status()
    assert status["status"] == "ONLINE"
    assert status["tailscale_ip"] == "100.82.140.22"

    res = dispatch_mobile_mattermost_command(
        command="/trade",
        text="status",
        remote_ip="100.82.140.22",
    )
    assert "Net Liquidity" in res["text"]
