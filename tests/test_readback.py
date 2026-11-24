"""Tests for trade_execution.readback — post-placement read-back verification."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

requires_moomoo_sdk = pytest.mark.skipif(
    importlib.util.find_spec("moomoo") is None,
    reason="moomoo-api SDK not installed (optional 'execution' extra)",
)

from trade_execution import (
    ExecutionEnvironment,
    ExecutionResult,
    MoomooAdapterConfig,
    MoomooExecutionAdapter,
    OrderAction,
    OrderPayload,
    canonical_status,
    normalize_order_row,
    verify_execution,
    verify_readback,
)


def _result(order_id: str = "ord-1") -> ExecutionResult:
    return ExecutionResult(
        success=True,
        order_id=order_id,
        client_tag="t",
        env=ExecutionEnvironment.SIMULATE,
        status="SUBMITTED",
    )


def test_canonical_status_mapping():
    assert canonical_status("FILLED_ALL") == "FILLED"
    assert canonical_status("filled") == "FILLED"
    assert canonical_status("FILLED_PART") == "PARTIAL"
    assert canonical_status("SUBMITTED") == "WORKING"
    assert canonical_status("CANCELLED_ALL") == "CANCELLED"
    assert canonical_status("FAILED") == "FAILED"
    assert canonical_status("SOMETHING_NEW") == "UNKNOWN"
    assert canonical_status(None) == "UNKNOWN"


def test_normalize_futu_style_row():
    view = normalize_order_row(
        {"order_id": 12345, "order_status": "FILLED_ALL", "dealt_qty": 2, "dealt_avg_price": 1.35, "code": "US.SPY"}
    )
    assert view is not None
    assert view.order_id == "12345"
    assert view.status == "FILLED"
    assert view.filled_qty == 2.0
    assert view.avg_price == 1.35
    assert view.symbol == "US.SPY"


def test_normalize_simulated_style_row_and_idless_row():
    view = normalize_order_row({"order_id": "sim-1", "status": "FILLED", "filled_qty": 1, "avg_price": 10.0})
    assert view is not None and view.status == "FILLED"
    assert normalize_order_row({"status": "FILLED"}) is None


def test_verify_found_and_matching():
    rows = [{"order_id": "ord-1", "order_status": "FILLED_ALL", "dealt_qty": 1, "dealt_avg_price": 2.5}]
    report = verify_readback(rows, "ord-1", expect_filled_qty=1)
    assert report.found and report.verified
    assert report.mismatches == []


def test_verify_missing_order_is_not_verified():
    report = verify_readback([{"order_id": "other", "status": "FILLED"}], "ord-1")
    assert not report.found and not report.verified
    assert "not present" in report.mismatches[0]


def test_verify_filled_qty_mismatch_is_named():
    rows = [{"order_id": "ord-1", "order_status": "FILLED_PART", "dealt_qty": 1}]
    report = verify_readback(rows, "ord-1", expect_filled_qty=2)
    assert report.found and not report.verified
    assert any("filled_qty" in m for m in report.mismatches)


def test_verify_failed_status_fails_default_expectation():
    rows = [{"order_id": "ord-1", "order_status": "FAILED", "dealt_qty": 0}]
    report = verify_readback(rows, "ord-1")
    assert report.found and not report.verified
    assert any("status" in m for m in report.mismatches)


def test_verify_execution_polls_until_filled():
    snapshots = iter(
        [
            [{"order_id": "ord-1", "order_status": "SUBMITTED", "dealt_qty": 0}],
            [{"order_id": "ord-1", "order_status": "FILLED_ALL", "dealt_qty": 1}],
        ]
    )
    report = verify_execution(
        lambda: next(snapshots),
        _result(),
        expect_statuses=["FILLED"],
        expect_filled_qty=1,
        attempts=3,
        sleep=lambda s: None,
    )
    assert report.verified
    assert report.attempts_used == 2


def test_verify_execution_stops_early_on_terminal_mismatch():
    calls = {"n": 0}

    def source():
        calls["n"] += 1
        return [{"order_id": "ord-1", "order_status": "FAILED", "dealt_qty": 0}]

    report = verify_execution(source, _result(), attempts=5, sleep=lambda s: None)
    assert not report.verified
    assert calls["n"] == 1  # terminal: no point polling


@requires_moomoo_sdk
def test_adapter_verify_order_readback(tmp_path: Path):
    adapter = MoomooExecutionAdapter(
        MoomooAdapterConfig(
            host="127.0.0.1",
            port=11111,
            env=ExecutionEnvironment.SIMULATE,
            allow_live_trading=False,
            audit_log_path=tmp_path / "audit_log.json",
        )
    )
    placed = adapter.place_order(
        OrderPayload(symbol="SPY", action=OrderAction.BUY, quantity=1, price=500.0)
    )
    assert placed.success
    # Offline simulation keeps no broker-side order book, so stub the
    # broker's view the way a live OpenD query would return it.
    adapter.query_orders = lambda status_filter_list=None: [  # type: ignore[method-assign]
        {
            "order_id": placed.order_id,
            "order_status": "FILLED_ALL",
            "dealt_qty": 1,
            "dealt_avg_price": 500.0,
        }
    ]
    report = adapter.verify_order_readback(placed, expect_filled_qty=1)
    assert report.verified
    assert report.observed is not None and report.observed.status == "FILLED"


def test_verify_execution_rejects_bad_source():
    with pytest.raises(TypeError):
        verify_execution(object(), _result())
