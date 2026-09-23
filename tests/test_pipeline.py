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


def _paper_config(tmp_path):
    import json
    p = tmp_path / "paper-config.json"
    p.write_text(json.dumps({
        "broker": {"name": "fake"},
        "data_source": "demo",
        "db_path": str(tmp_path / "trade-paper.db"),
        "symbols_equities": ["AAA"],
        "symbols_crypto": [],
    }))
    return str(p)


def test_paper_overview_fake_broker(tmp_path):
    pytest.importorskip("trade_paper")
    view = pipeline.paper_overview(_paper_config(tmp_path))
    assert view["paper_only"] and view["broker"] == "fake"
    assert view["equity"] == 100000.0
    assert view["positions"] == []
    assert view["pending_approvals"] == []
    assert view["active_strategies"] == 0


def test_paper_overview_missing_engine_errors(monkeypatch, tmp_path):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("trade_paper"):
            raise ImportError("no trade_paper")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="trade-paper"):
        pipeline.paper_overview(str(tmp_path / "paper-config.json"))


class _FakePop:
    def __init__(self, symbol, bullishness, conviction, n_mentions):
        self.symbol = symbol
        self.bullishness = bullishness
        self.conviction = conviction
        self.n_mentions = n_mentions
        self.volume_zscore = 4.2
        self.tone_shift = 0.35
        self.drivers = ["moon"]
        self.verdict = (f"{symbol} has a pop in sentiment of "
                        f"{bullishness}/10 bullishness "
                        f"(conviction {conviction}/10)")


def _fake_sentiment_module(monkeypatch):
    import sys
    import types

    pops = [
        _FakePop("XYZ", 9.0, 8.5, 60),   # clears the bar
        _FakePop("MEH", 6.0, 2.0, 8),    # below min_conviction
    ]
    mod = types.ModuleType("trade_sentiment")
    mod.scan = lambda symbols, window_hours=24, min_mentions=5: pops
    monkeypatch.setitem(sys.modules, "trade_sentiment", mod)
    return pops


def test_sentiment_scan_returns_plain_data(monkeypatch):
    _fake_sentiment_module(monkeypatch)
    out = pipeline.sentiment_scan(["xyz", " MEH "], window_hours=12)
    assert out["window_hours"] == 12
    assert out["symbols"] == ["XYZ", "MEH"]
    assert len(out["pops"]) == 1  # MEH filtered by conviction bar
    pop = out["pops"][0]
    assert pop["symbol"] == "XYZ"
    assert pop["bullishness_10"] == 9.0
    assert pop["conviction_10"] == 8.5
    assert pop["n_mentions"] == 60
    assert pop["drivers"] == ["moon"]
    assert "9.0/10 bullishness" in pop["verdict"]
    assert len(out["verdicts"]) == 1


def test_sentiment_scan_validates_symbols(monkeypatch):
    _fake_sentiment_module(monkeypatch)
    with pytest.raises(ValueError):
        pipeline.sentiment_scan(["  "])


def test_sentiment_scan_missing_engine_errors(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("trade_sentiment"):
            raise ImportError("no trade_sentiment")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="trade-sentiment"):
        pipeline.sentiment_scan(["XYZ"])


def test_summarize_sentiment(monkeypatch):
    _fake_sentiment_module(monkeypatch)
    out = pipeline.sentiment_scan(["XYZ"])
    text = pipeline.summarize_sentiment(out)
    assert "Sentiment scan (24h)" in text
    assert "1 pops" in text
    assert "9.0/10 bullishness" in text
