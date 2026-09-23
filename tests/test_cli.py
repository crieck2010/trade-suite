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
