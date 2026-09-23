"""CLI tests (argparse + status/doctor; no subprocesses)."""

from __future__ import annotations

import pytest

from trade_suite import cli


def test_parser_requires_command():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])


def test_parser_demo_defaults():
    args = cli.build_parser().parse_args(["demo"])
    assert args.command == "demo" and args.symbols == "SPY,AAPL"


def test_parser_backtest_options():
    args = cli.build_parser().parse_args(
        ["backtest", "--strategy", "sma_crossover", "--symbols", "SPY,QQQ",
         "--params", "fast=10,slow=30"])
    assert args.strategy == "sma_crossover"
    assert args.symbols == "SPY,QQQ"
    assert args.params == "fast=10,slow=30"


def test_cmd_status_prints_modules(capsys):
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "trade-backtest" in out and "modules installed" in out


def test_cmd_doctor_runs(capsys):
    code = cli.main(["doctor"])
    assert code in (0, 1)
    out = capsys.readouterr().out
    assert "trade-suite doctor" in out


def test_cmd_demo_runs():
    pytest.importorskip("trade_dashboard_web")
    pytest.importorskip("trade_agents")
    assert cli.main(["demo", "--symbols", "SPY", "--days", "120"]) == 0


def test_cmd_backtest_runs():
    pytest.importorskip("trade_dashboard_web")
    pytest.importorskip("trade_strategies")
    assert cli.main(["backtest", "--symbols", "SPY", "--days", "120"]) == 0


def test_main_entry_point():
    from trade_suite import __main__  # noqa: F401  (import check)
    assert callable(cli.main)


def test_parser_paper_defaults():
    args = cli.build_parser().parse_args(["paper"])
    assert args.command == "paper" and args.config == "paper-config.json"


def test_cmd_paper_fake_broker(tmp_path, capsys):
    pytest.importorskip("trade_paper")
    import json
    cfg = tmp_path / "paper-config.json"
    cfg.write_text(json.dumps({
        "broker": {"name": "fake"},
        "data_source": "demo",
        "db_path": str(tmp_path / "trade-paper.db"),
        "symbols_equities": ["AAA"],
        "symbols_crypto": [],
    }))
    assert cli.main(["paper", "--config", str(cfg)]) == 0
    out = capsys.readouterr().out
    assert "paper account (fake)" in out and "approvals pending: 0" in out


def test_parser_sentiment_defaults():
    args = cli.build_parser().parse_args(["sentiment"])
    assert args.command == "sentiment"
    assert args.symbols == "SPY,AAPL,MSFT,NVDA,TSLA"
    assert args.window_hours == 24
    assert args.min_conviction == 5.0


def test_cmd_sentiment_runs(monkeypatch, capsys):
    from trade_suite import pipeline
    import sys
    import types

    class _Pop:
        symbol = "XYZ"
        bullishness = 8.0
        conviction = 7.5
        n_mentions = 40
        volume_zscore = 3.1
        tone_shift = 0.2
        drivers = ["calls"]
        verdict = "XYZ has a pop in sentiment of 8.0/10 bullishness"

    mod = types.ModuleType("trade_sentiment")
    mod.scan = lambda symbols, window_hours=24, min_mentions=5: [_Pop()]
    monkeypatch.setitem(sys.modules, "trade_sentiment", mod)

    assert cli.main(["sentiment", "--symbols", "XYZ"]) == 0
    out = capsys.readouterr().out
    assert "Sentiment scan (24h)" in out
    assert "8.0/10 bullishness" in out
