"""Adapter wiring tests for the safety kernel (live-roadmap Phase 1).

The fail-closed REAL tests deliberately avoid touching the moomoo SDK:
the refusal must happen before any SDK enum is dereferenced, so they
run on machines without the SDK (including CI).
"""

import importlib.util
from pathlib import Path

import pytest

from trade_execution.exceptions import (
    LiveSafetyError,
    OpenDConnectionError,
    SafetyBlockedError,
)
from trade_execution.models import ExecutionEnvironment, OrderAction, OrderPayload
from trade_execution.moomoo_adapter import MoomooAdapterConfig, MoomooExecutionAdapter
from trade_safety import ApprovalMode, SafetyConfig

_MOOMOO = importlib.util.find_spec("moomoo") is not None
requires_moomoo = pytest.mark.skipif(
    not _MOOMOO, reason="moomoo-api SDK not installed (optional 'execution' extra)"
)


def make_adapter(tmp_path: Path, **cfg_kwargs) -> MoomooExecutionAdapter:
    cfg_kwargs.setdefault("audit_log_path", tmp_path / "audit_log.json")
    return MoomooExecutionAdapter(MoomooAdapterConfig(**cfg_kwargs))


def autonomous_config(**overrides) -> SafetyConfig:
    base = dict(
        approval_mode=ApprovalMode.AUTONOMOUS,
        max_total_exposure_pct=None,  # adapter's canned paper book is ~fully invested
    )
    base.update(overrides)
    return SafetyConfig(**base)


def test_adapter_without_safety_config_has_no_kernel(tmp_path):
    adapter = make_adapter(tmp_path)
    assert adapter.safety is None


def test_real_place_order_fail_closed_when_gateway_down(tmp_path):
    adapter = make_adapter(
        tmp_path,
        env=ExecutionEnvironment.REAL,
        allow_live_trading=True,
    )
    adapter._is_unlocked = True  # as after a successful unlock_live_trading()
    order = OrderPayload(symbol="SPY", action=OrderAction.BUY, quantity=1, price=100.0)
    with pytest.raises(OpenDConnectionError):
        adapter.place_order(order)


def test_real_combo_fail_closed(tmp_path):
    adapter = make_adapter(
        tmp_path,
        env=ExecutionEnvironment.REAL,
        allow_live_trading=True,
    )
    adapter._is_unlocked = True
    combo = MoomooExecutionAdapter.create_0dte_iron_fly_payload(
        expiry_yymmdd="261016", atm_strike=5800.0, net_credit=25.0
    )
    with pytest.raises((LiveSafetyError, OpenDConnectionError)):
        adapter.place_combo_order(combo)


def test_safety_gate_blocks_when_estop_engaged(tmp_path):
    adapter = make_adapter(
        tmp_path,
        env=ExecutionEnvironment.SIMULATE,
        safety_config=autonomous_config(),
    )
    assert adapter.safety is not None
    adapter.safety.engage_estop(actor="Charlie", reason="wiring test")
    with pytest.raises(SafetyBlockedError) as excinfo:
        adapter._safety_gate(
            symbol="SPY", action="BUY", quantity=1, price=100.0, strategy="test"
        )
    assert excinfo.value.reasons


def test_safety_gate_allows_clean_order(tmp_path):
    adapter = make_adapter(
        tmp_path,
        env=ExecutionEnvironment.SIMULATE,
        safety_config=autonomous_config(),
    )
    # Must not raise: canned paper account is profitable, cushion is 85%,
    # $100 notional is under the per-trade cap, approval is autonomous.
    adapter._safety_gate(
        symbol="SPY", action="BUY", quantity=1, price=100.0, strategy="test"
    )


@requires_moomoo
def test_simulated_order_blocked_by_kernel_estop(tmp_path):
    adapter = make_adapter(
        tmp_path,
        env=ExecutionEnvironment.SIMULATE,
        safety_config=autonomous_config(),
    )
    adapter.safety.engage_estop(actor="Charlie", reason="wiring test")
    order = OrderPayload(symbol="SPY", action=OrderAction.BUY, quantity=1, price=100.0)
    with pytest.raises(SafetyBlockedError):
        adapter.place_order(order)
