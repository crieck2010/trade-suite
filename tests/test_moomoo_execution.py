"""Unit and integration tests for MoomooExecutionAdapter and trade_execution models."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import pytest

from trade_execution.exceptions import (
    LiveSafetyError,
    TradeUnlockError,
)
from trade_execution.models import (
    ComboLegPayload,
    ComboOrderPayload,
    ComboStrategyType,
    ExecutionEnvironment,
    OrderAction,
    OrderPayload,
    OrderType,
    SecurityType,
)
from trade_execution.moomoo_adapter import MoomooAdapterConfig, MoomooExecutionAdapter


# The moomoo-api SDK is an optional dependency (pyproject 'execution'
# extra). Tests that exercise SDK-shaped adapter paths skip cleanly on
# machines without it; everywhere else in this file is SDK-free.
requires_moomoo_sdk = pytest.mark.skipif(
    importlib.util.find_spec("moomoo") is None,
    reason="moomoo-api SDK not installed (optional 'execution' extra)",
)


@pytest.fixture
def temp_audit_log(tmp_path: Path) -> Path:
    return tmp_path / "test_audit_log.json"


@pytest.fixture
def sim_adapter(temp_audit_log: Path) -> MoomooExecutionAdapter:
    cfg = MoomooAdapterConfig(
        host="127.0.0.1",
        port=11111,
        env=ExecutionEnvironment.SIMULATE,
        allow_live_trading=False,
        audit_log_path=temp_audit_log,
    )
    return MoomooExecutionAdapter(cfg)


def test_order_payload_validation():
    """Verify single-leg order payload validation rules."""
    # Valid equity order
    order = OrderPayload(
        symbol="SPY",
        action=OrderAction.BUY,
        quantity=100,
        price=580.0,
        order_type=OrderType.LIMIT,
    )
    assert order.symbol == "SPY"
    assert order.quantity == 100
    assert order.price == 580.0

    # Negative quantity raises ValueError
    with pytest.raises(ValueError, match="Quantity must be positive"):
        OrderPayload(symbol="SPY", action=OrderAction.BUY, quantity=0, price=580.0)

    # Limit order without positive price raises ValueError
    with pytest.raises(ValueError, match="Limit order requires positive price"):
        OrderPayload(symbol="SPY", action=OrderAction.BUY, quantity=10, price=0.0, order_type=OrderType.LIMIT)


def test_combo_order_payload_validation():
    """Verify combo order payload validation rules."""
    leg1 = ComboLegPayload(code="US..SPXW261012C05800000", action=OrderAction.SELL, qty_ratio=1)
    leg2 = ComboLegPayload(code="US..SPXW261012P05800000", action=OrderAction.SELL, qty_ratio=1)

    combo = ComboOrderPayload(
        legs=[leg1, leg2],
        quantity=2,
        net_price=15.50,
        combo_type=ComboStrategyType.STRADDLE,
    )
    assert len(combo.legs) == 2
    assert combo.quantity == 2
    assert combo.net_price == 15.50

    # Empty legs raises ValueError
    with pytest.raises(ValueError, match="Combo order must have at least one leg"):
        ComboOrderPayload(legs=[], quantity=1, net_price=10.0)


def test_spx_symbol_formatting():
    """Verify official Moomoo option contract symbol generation."""
    spx_call = MoomooExecutionAdapter.format_spx_option_code("261012", "C", 5800.0, is_mini_xsp=False)
    assert spx_call == "US.SPXW261012C5800000"

    spx_put = MoomooExecutionAdapter.format_spx_option_code("261012", "P", 5750.0, is_mini_xsp=False)
    assert spx_put == "US.SPXW261012P5750000"

    xsp_call = MoomooExecutionAdapter.format_spx_option_code("261012", "C", 580.0, is_mini_xsp=True)
    assert xsp_call == "US.XSP261012C580000"


def test_create_0dte_iron_fly_payload():
    """Verify 4-leg European cash-settled Iron-Fly generation."""
    fly = MoomooExecutionAdapter.create_0dte_iron_fly_payload(
        expiry_yymmdd="261012",
        atm_strike=5802.3,  # Should round to 5800 (multiples of 5)
        wing_width=52.0,    # Should round to 50
        quantity=1,
        net_credit=18.40,
        is_mini_xsp=False,
    )

    assert fly.combo_type == ComboStrategyType.IRON_FLY
    assert fly.quantity == 1
    assert fly.net_price == 18.40
    assert len(fly.legs) == 4

    # Leg 1: Short ATM Call (5800)
    assert fly.legs[0].action == OrderAction.SELL
    assert fly.legs[0].strike == 5800.0
    assert fly.legs[0].code == "US.SPXW261012C5800000"

    # Leg 2: Short ATM Put (5800)
    assert fly.legs[1].action == OrderAction.SELL
    assert fly.legs[1].strike == 5800.0
    assert fly.legs[1].code == "US.SPXW261012P5800000"

    # Leg 3: Long OTM Call (5850)
    assert fly.legs[2].action == OrderAction.BUY
    assert fly.legs[2].strike == 5850.0
    assert fly.legs[2].code == "US.SPXW261012C5850000"

    # Leg 4: Long OTM Put (5750)
    assert fly.legs[3].action == OrderAction.BUY
    assert fly.legs[3].strike == 5750.0
    assert fly.legs[3].code == "US.SPXW261012P5750000"


@requires_moomoo_sdk
def test_simulated_order_execution(sim_adapter: MoomooExecutionAdapter, temp_audit_log: Path):
    """Verify paper trading order execution and atomic audit logging."""
    order = OrderPayload(
        symbol="SPY",
        action=OrderAction.BUY,
        quantity=100,
        price=582.50,
        order_type=OrderType.LIMIT,
        strategy="regcond1_expansion",
    )

    res = sim_adapter.place_order(order)
    assert res.success is True
    assert res.env == ExecutionEnvironment.SIMULATE
    assert "moomoo-sim-" in res.order_id
    assert res.filled_qty == 100

    # Verify audit log was written atomically
    assert temp_audit_log.exists()
    with open(temp_audit_log, "r", encoding="utf-8") as f:
        logs = json.load(f)
    assert len(logs) >= 1
    assert logs[-1]["action"] == "MOOMOO_SIMULATED_ORDER"
    assert logs[-1]["details"]["symbol"] == "SPY"


def test_simulated_combo_execution(sim_adapter: MoomooExecutionAdapter, temp_audit_log: Path):
    """Verify atomic multi-leg 0DTE Iron-Fly paper execution."""
    fly = MoomooExecutionAdapter.create_0dte_iron_fly_payload(
        expiry_yymmdd="261012",
        atm_strike=5800.0,
        wing_width=50.0,
        quantity=2,
        net_credit=19.20,
    )

    res = sim_adapter.place_combo_order(fly)
    assert res.success is True
    assert res.env == ExecutionEnvironment.SIMULATE
    assert "moomoo-combo-sim-" in res.order_id
    assert res.filled_qty == 2

    # Verify audit log
    with open(temp_audit_log, "r", encoding="utf-8") as f:
        logs = json.load(f)
    combo_log = [l for l in logs if l["action"] == "MOOMOO_SIMULATED_COMBO"]
    assert len(combo_log) == 1
    assert combo_log[0]["details"]["quantity"] == 2
    assert len(combo_log[0]["details"]["legs"]) == 4


@requires_moomoo_sdk
def test_account_and_positions_query(sim_adapter: MoomooExecutionAdapter):
    """Verify account and positions querying."""
    account = sim_adapter.get_account()
    assert account.net_liquidity > 0
    assert account.buying_power >= account.net_liquidity
    assert account.currency == "USD"

    positions = sim_adapter.get_positions()
    symbols = {p.symbol for p in positions}
    assert "SPY" in symbols
    assert "TLT" in symbols
    assert "GLD" in symbols
    assert "CPER" in symbols


def test_live_safety_barriers(temp_audit_log: Path):
    """Verify that live execution strictly refuses orders when gates are locked."""
    # Scenario 1: REAL env but allow_live_trading is False
    cfg_locked = MoomooAdapterConfig(
        env=ExecutionEnvironment.REAL,
        allow_live_trading=False,
        audit_log_path=temp_audit_log,
    )
    adapter_locked = MoomooExecutionAdapter(cfg_locked)

    order = OrderPayload("SPY", OrderAction.BUY, 100, price=580.0)
    with pytest.raises(LiveSafetyError, match="Refusing live real-money execution"):
        adapter_locked.place_order(order)

    # Scenario 2: Attempting to unlock live trading when allow_live_trading is False
    with pytest.raises(LiveSafetyError, match="Refusing to unlock live trading"):
        adapter_locked.unlock_live_trading("test_password")

    # Scenario 3: Missing password raises TradeUnlockError
    with pytest.raises(TradeUnlockError, match="Trade unlock password required"):
        adapter_locked.unlock_live_trading("")

    # Scenario 4: REAL env with allow_live_trading=True, but trading not yet unlocked
    cfg_unlocked_candidate = MoomooAdapterConfig(
        env=ExecutionEnvironment.REAL,
        allow_live_trading=True,
        audit_log_path=temp_audit_log,
    )
    adapter_unlocked_candidate = MoomooExecutionAdapter(cfg_unlocked_candidate)
    with pytest.raises(LiveSafetyError, match="Moomoo live trade context is locked"):
        adapter_unlocked_candidate.place_order(order)
