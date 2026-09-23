"""Pipeline / data workflow tests (need the dashboard + engine siblings)."""

from __future__ import annotations

import pytest

from trade_suite import data, pipeline


def _need_full_stack():
    pytest.importorskip("trade_dashboard_web")
    pytest.importorskip("trade_strategies")
    pytest.importorskip("trade_backtest")


def test_get_bars_demo_shape():
    pytest.importorskip("trade_dashboard_web")
    bars = data.get_bars("SPY", source="demo", days=120)
    assert len(bars) == 120
    assert set(bars[0]) == {"symbol", "timestamp", "open", "high",
                            "low", "close", "volume"}


def test_get_bars_many_keys_uppercase():
    pytest.importorskip("trade_dashboard_web")
    out = data.get_bars_many(["spy", "aapl"], source="demo", days=60)
    assert set(out) == {"SPY", "AAPL"}
    assert len(out["SPY"]) == 60


def test_get_bars_many_validates():
    with pytest.raises(ValueError):
        data.get_bars_many(["  "], source="demo")


def test_run_backtest_demo():
    _need_full_stack()
    result = pipeline.run_backtest("donchian_breakout", ["SPY"],
                                   {"entry": 20, "exit": 10},
                                   source="demo", days=200)
    assert result["final_equity"] > 0
    assert len(result["equity_curve"]) == 200
    assert "sharpe_ratio" in result["metrics"]
    summary = pipeline.summarize_backtest(result)
    assert "donchian_breakout" in summary and "SPY" in summary


def test_run_desk_demo():
    pytest.importorskip("trade_dashboard_web")
    pytest.importorskip("trade_agents")
    report = pipeline.run_desk(["SPY"], source="demo", days=200)
    assert {"briefs", "allocations", "approved_orders", "vetoes"} <= set(report)
    assert len(report["briefs"]) > 0
    summary = pipeline.summarize_desk(report)
    assert "Desk report" in summary


def test_evaluate_orders_veto():
    pytest.importorskip("trade_dashboard_web")
    pytest.importorskip("trade_agents")
    pytest.importorskip("trade_risk")
    result = pipeline.evaluate_orders(
        [{"symbol": "SPY", "side": "buy", "quantity": 10, "price": 580.0}],
        limits=[["max_position_notional", {"max_pct": 0.01}]],
        equity=100_000.0,
    )
    assert len(result["vetoed"]) == 1 and not result["approved"]


def test_research_pipeline_demo():
    _need_full_stack()
    pytest.importorskip("trade_agents")
    out = pipeline.research_pipeline(["SPY"], source="demo", days=200,
                                     backtest_strategy="donchian_breakout",
                                     backtest_params={"entry": 20, "exit": 10})
    assert {"desk", "backtest", "risk"} <= set(out)
    assert out["backtest"]["final_equity"] > 0
