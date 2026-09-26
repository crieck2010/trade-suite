"""trade-suite 0.5.0 tests: terminal-wave wiring (trades / performance /
agents / network / risk).

Delegation tests stub ``pipeline._services()`` so they run with no sibling
installed.  Real-delegation tests ``pytest.importorskip`` the dashboard web
engine and additionally skip when the canonical terminal job has not
landed in the installed dashboard yet — missing engines/panels skip,
never fail.
"""

from __future__ import annotations

import builtins
import importlib
import json
import sys
import types

import pytest

from trade_suite import cli, env, pipeline


# -- helpers ---------------------------------------------------------------

def _block_packages(monkeypatch, *packages: str):
    """Make ``packages`` unimportable, however the workflow reaches for them.

    Mirrors the helper in test_v040.py: ``from X import Y`` goes
    through ``builtins.__import__``; ``env.require()`` uses
    ``importlib.import_module``.  Block both and scrub ``sys.modules``.
    """
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if any(name == p or name.startswith(p + ".") for p in packages):
            raise ImportError(f"no {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    real_import_module = importlib.import_module

    def fake_import_module(name, *args, **kwargs):
        if any(name == p or name.startswith(p + ".") for p in packages):
            raise ImportError(f"no {name}")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    for mod in [m for m in sys.modules
                if any(m == p or m.startswith(p + ".") for p in packages)]:
        monkeypatch.delitem(sys.modules, mod)


def _stub_services(monkeypatch, **jobs):
    """Replace ``pipeline._services()`` with a stub recording calls."""
    calls: dict[str, dict] = {}

    def make(name):
        def job(*args, **kwargs):
            calls[name] = {"args": args, "kwargs": kwargs}
            return {"job": name, "kwargs": kwargs, "args": args}
        return job

    stub = types.SimpleNamespace(**{n: make(n) for n in jobs})
    monkeypatch.setattr(pipeline, "_services", lambda: stub)
    return calls


_TERMINAL_JOBS = ("run_trades_job", "run_performance_job",
                  "run_agent_activity_job", "run_network_job",
                  "run_risk_monitor_job", "trades_to_csv")


# -- registry: terminal wave adds NO new engines --------------------------------
#
# The 0.5.0 terminal jobs are dashboard *views* over already-wired engines
# (trade-paper ledgers, trade-agents track records, trade-hedge state).
# They live in trade-dashboard-web (already registered) and add no
# registry entries of their own.

def test_registry_stays_twenty_three():
    dists = [m.dist for m in env.MODULES]
    assert len(env.MODULES) == 23
    assert "trade-dashboard-web" in dists


# -- delegation (stubbed services; runs anywhere) -----------------------------

def test_run_trades_delegates_with_same_arg_names(monkeypatch):
    calls = _stub_services(monkeypatch, run_trades_job=None)
    out = pipeline.run_trades(ledger_path="x.db", date_from="2026-01-01",
                              date_to="2026-09-01", symbol="SPY",
                              side="buy", strategy="sma", agent="scout",
                              outcome="win", limit=10)
    assert out["job"] == "run_trades_job"
    assert calls["run_trades_job"]["kwargs"] == {
        "ledger_path": "x.db", "date_from": "2026-01-01",
        "date_to": "2026-09-01", "symbol": "SPY", "side": "buy",
        "strategy": "sma", "agent": "scout", "outcome": "win", "limit": 10}


def test_run_trades_defaults(monkeypatch):
    calls = _stub_services(monkeypatch, run_trades_job=None)
    pipeline.run_trades()
    assert calls["run_trades_job"]["kwargs"] == {
        "ledger_path": None, "date_from": None, "date_to": None,
        "symbol": None, "side": None, "strategy": None, "agent": None,
        "outcome": None, "limit": 500}


def test_trades_to_csv_delegates(monkeypatch):
    calls = _stub_services(monkeypatch, trades_to_csv=None)
    result = {"trades": []}
    out = pipeline.trades_to_csv(result)
    assert out["job"] == "trades_to_csv"
    assert calls["trades_to_csv"]["args"] == (result,)


def test_run_performance_delegates(monkeypatch):
    calls = _stub_services(monkeypatch, run_performance_job=None)
    out = pipeline.run_performance(source="backtest", backtest_path="b.json",
                                   risk_free=0.02)
    assert out["job"] == "run_performance_job"
    assert calls["run_performance_job"]["kwargs"] == {
        "source": "backtest", "ledger_path": None, "backtest": None,
        "backtest_path": "b.json", "risk_free": 0.02}


def test_run_performance_defaults(monkeypatch):
    calls = _stub_services(monkeypatch, run_performance_job=None)
    pipeline.run_performance()
    assert calls["run_performance_job"]["kwargs"] == {
        "source": "paper", "ledger_path": None, "backtest": None,
        "backtest_path": None, "risk_free": 0.0}


def test_run_agent_activity_delegates(monkeypatch):
    calls = _stub_services(monkeypatch, run_agent_activity_job=None)
    out = pipeline.run_agent_activity(track_record_path="tr.jsonl",
                                      approvals_ledger_path="a.db", limit=10)
    assert out["job"] == "run_agent_activity_job"
    assert calls["run_agent_activity_job"]["kwargs"] == {
        "track_record_path": "tr.jsonl", "approvals_ledger_path": "a.db",
        "limit": 10}


def test_run_agent_activity_defaults(monkeypatch):
    calls = _stub_services(monkeypatch, run_agent_activity_job=None)
    pipeline.run_agent_activity()
    assert calls["run_agent_activity_job"]["kwargs"] == {
        "track_record_path": None, "approvals_ledger_path": None,
        "limit": 50}


def test_run_network_delegates(monkeypatch):
    calls = _stub_services(monkeypatch, run_network_job=None)
    out = pipeline.run_network(symbols=["spy", "qqq"], source="demo",
                               days=100, method="spearman", seed=3)
    assert out["job"] == "run_network_job"
    # symbols are upper-cleaned before delegation
    assert calls["run_network_job"]["kwargs"] == {
        "symbols": ["SPY", "QQQ"], "source": "demo", "days": 100,
        "method": "spearman", "seed": 3,
        "breadth": None, "macro": None, "regime": None}


def test_run_network_defaults(monkeypatch):
    calls = _stub_services(monkeypatch, run_network_job=None)
    pipeline.run_network()
    kw = calls["run_network_job"]["kwargs"]
    assert kw["symbols"] is None
    assert kw["source"] == "yfinance"
    assert kw["days"] == 252
    assert kw["method"] == "pearson"
    assert kw["seed"] == 7


def test_run_risk_monitor_delegates(monkeypatch):
    calls = _stub_services(monkeypatch, run_risk_monitor_job=None)
    out = pipeline.run_risk_monitor(ledger_path="x.db",
                                    hedge_state_path="h.json",
                                    regime={"conviction": 60}, vol_days=30)
    assert out["job"] == "run_risk_monitor_job"
    assert calls["run_risk_monitor_job"]["kwargs"] == {
        "ledger_path": "x.db", "hedge_state_path": "h.json",
        "regime": {"conviction": 60}, "vol_days": 30}


def test_run_risk_monitor_defaults(monkeypatch):
    calls = _stub_services(monkeypatch, run_risk_monitor_job=None)
    pipeline.run_risk_monitor()
    assert calls["run_risk_monitor_job"]["kwargs"] == {
        "ledger_path": None, "hedge_state_path": None, "regime": None,
        "vol_days": 63}


# -- missing dashboard / missing terminal jobs -----------------------------------

def test_missing_dashboard_errors_all_five(monkeypatch):
    _block_packages(monkeypatch, "trade_dashboard_web",
                    "trade_dashboard_desktop")
    calls = (
        pipeline.run_trades, pipeline.run_performance,
        pipeline.run_agent_activity, pipeline.run_network,
        pipeline.run_risk_monitor,
        lambda: pipeline.trades_to_csv({}),
    )
    for call in calls:
        with pytest.raises(RuntimeError, match="dashboard"):
            call()


def test_desktop_fallback_without_terminal_jobs_errors_clearly(monkeypatch):
    # Web missing, desktop present but lacking the 0.5.0 jobs: the
    # workflows must raise the standard RuntimeError, not AttributeError.
    monkeypatch.setattr(pipeline, "_services",
                        lambda: types.SimpleNamespace())
    with pytest.raises(RuntimeError, match="run_trades_job"):
        pipeline.run_trades()
    with pytest.raises(RuntimeError, match="run_risk_monitor_job"):
        pipeline.run_risk_monitor()


# -- summarize_* smoke tests (contract-shaped fixtures; run anywhere) ----------

def _trades_result():
    return {
        "trades": [
            {"id": "o1", "symbol": "SPY", "side": "buy", "qty": 10.0,
             "filled_qty": 10.0, "avg_fill_price": 500.0, "commission": 0.1,
             "strategy": "sma", "state": "filled",
             "created_at": "2026-01-02T14:30:00+00:00",
             "filled_at": "2026-01-02T15:30:00+00:00",
             "realized_pnl": 120.5, "outcome": "win", "demo": True}],
        "count": 1, "filters": {"limit": 500}, "demo": True,
        "ledger_path": None, "message": "DEMO synthetic"}


def _performance_result():
    return {
        "equity": [], "drawdown": [], "monthly": [], "years": [2026],
        "rolling_sharpe": [], "rolling_vol": [], "histogram": {},
        "summary": {"win_rate": 0.6, "profit_factor": 1.8,
                    "expectancy": 12.5, "max_drawdown": 0.08,
                    "cagr": 0.15, "n_trades": 10,
                    "start": "2026-01-02", "end": "2026-09-26"},
        "source": "paper", "equity_source": "fills_reconstructed",
        "risk_free": 0.0, "demo": False,
        "message": "reconstructed curve"}


def _agents_result():
    return {
        "leaderboards": {
            "researcher": [{"label": "scout-a", "role": "researcher",
                            "score": 0.72}],
            "risk_desk": [], "pm": []},
        "elo_curves": {"scout-a": [{"ts": "2026-01-01", "rating": 1510.0}]},
        "brier": {"bins": [0.05], "observed": [0.0], "n": [3]},
        "debates": [{"idea_id": "i1"}],
        "approval_queue": [{"id": 1}],
        "track_record_path": "tr.jsonl",
        "message": "3 events"}


def _network_result():
    return {
        "nodes": [{"id": 0, "symbol": "SPY", "x": 1.0, "y": 2.0,
                   "vol": 0.15, "cluster": 0}],
        "edges": [], "symbols": ["SPY"],
        "correlation": [[1.0]], "clusters": [{"id": 0, "members": ["SPY"]}],
        "regime": {"conviction": 70}, "breadth": None, "macro": None,
        "params": {"source": "yfinance", "days": 252, "method": "pearson",
                   "seed": 7, "n_obs": 251, "mst_cut_distance": 1.0,
                   "demo": True}}


def _risk_result():
    return {
        "exposures": {"n_positions": 2, "per_symbol": [],
                      "net_delta_dollars": 1000.0, "gross_dollars": 5000.0,
                      "herfindahl": 0.5,
                      "largest_position": {"symbol": "SPY", "weight": 0.6}},
        "vol_regime": {"as_of": [], "vol": [], "window": 21},
        "volforecast": None,
        "kill_switch": {"status": "active"},
        "regime": {"conviction": 62, "hysteresis_state": "held"},
        "demo": False, "ledger_path": "x.db", "message": "2 positions"}


def test_summarize_trades():
    text = pipeline.summarize_trades(_trades_result())
    assert "Trade blotter" in text and "SPY" in text
    assert "+120.50" in text and "win" in text and "DEMO" in text


def test_summarize_trades_empty():
    text = pipeline.summarize_trades({"trades": [], "count": 0, "demo": False})
    assert "0 rows" in text


def test_summarize_performance():
    text = pipeline.summarize_performance(_performance_result())
    assert "Performance" in text and "win rate 60.0%" in text
    assert "max DD 8.0%" in text and "RECONSTRUCTED" in text


def test_summarize_agent_activity():
    text = pipeline.summarize_agent_activity(_agents_result())
    assert "Agent activity" in text and "scout-a" in text
    assert "1 agents" in text and "3 forecast/outcome pairs" in text
    assert "debates: 1" in text and "approvals pending: 1" in text


def test_summarize_agent_activity_empty():
    result = _agents_result()
    result["leaderboards"] = {"researcher": [], "risk_desk": [], "pm": []}
    text = pipeline.summarize_agent_activity(result)
    assert "no leaderboards" in text


def test_summarize_network():
    text = pipeline.summarize_network(_network_result())
    assert "Network" in text and "pearson" in text
    assert "cluster 0: SPY" in text and "conviction 70" in text
    assert "DEMO" in text


def test_summarize_risk_monitor():
    text = pipeline.summarize_risk_monitor(_risk_result())
    assert "Risk monitor" in text and "2 positions" in text
    assert "kill-switch active" in text
    assert "conviction 62" in text and "SPY" in text


# -- real delegation against the installed web engine (skip bare) ----------------

def _web():
    engine = pytest.importorskip("trade_dashboard_web.engine")
    for job in _TERMINAL_JOBS:
        if not hasattr(engine, job):
            pytest.skip(f"web engine lacks {job}")
    return engine


def test_real_delegation_all_five_deterministic():
    _web()
    t = pipeline.run_trades()
    p = pipeline.run_performance()
    a = pipeline.run_agent_activity()
    n1 = pipeline.run_network()
    n2 = pipeline.run_network()
    r = pipeline.run_risk_monitor()
    # demo mode everywhere with no ledger/track-record present
    assert t["demo"] and t["count"] > 0
    assert p["demo"] and p["summary"]["n_trades"] > 0
    assert isinstance(a["leaderboards"], dict)
    assert n1["params"]["demo"] and n1["nodes"] == n2["nodes"]
    assert r["demo"] and r["kill_switch"]["status"] == "unknown"
    # plain data: JSON-serializable
    for out in (t, p, a, n1, r):
        json.dumps(out)
    # summarizers run on the real payloads
    for fn, out in ((pipeline.summarize_trades, t),
                    (pipeline.summarize_performance, p),
                    (pipeline.summarize_agent_activity, a),
                    (pipeline.summarize_network, n1),
                    (pipeline.summarize_risk_monitor, r)):
        assert isinstance(fn(out), str) and fn(out)


def test_real_trades_csv_roundtrip():
    _web()
    csv_text = pipeline.trades_to_csv(pipeline.run_trades(limit=3))
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("id,symbol,side,")
    assert len(lines) == 4  # header + 3 rows


def test_real_network_real_symbols_need_source_demo_for_no_network():
    _web()
    out = pipeline.run_network(source="demo")
    assert out["params"]["source"] == "demo"
    assert len(out["nodes"]) == len(out["symbols"]) > 0
    json.dumps(out)


# -- CLI -----------------------------------------------------------------------

def test_parser_terminal_command_defaults():
    p = cli.build_parser()
    args = p.parse_args(["trades"])
    assert args.command == "trades" and args.limit == 500 \
        and args.symbol is None and args.outcome is None
    args = p.parse_args(["trades", "export", "--from", "2026-01-01",
                         "--out", "t.csv"])
    assert args.trades_action == "export" and args.from_date == "2026-01-01" \
        and args.out == "t.csv" and args.format == "csv"
    args = p.parse_args(["performance"])
    assert args.source == "paper" and args.backtest_path is None
    args = p.parse_args(["agents"])
    assert args.limit == 50
    args = p.parse_args(["network"])
    assert args.symbols == "" and args.source == "yfinance" \
        and args.days == 252 and args.method == "pearson" and args.seed == 7
    args = p.parse_args(["risk"])
    assert args.vol_days == 63


def _stub_terminal(monkeypatch):
    monkeypatch.setattr(pipeline, "run_trades", lambda **kw: _trades_result())
    monkeypatch.setattr(pipeline, "trades_to_csv",
                        lambda result: "id,symbol\n")
    monkeypatch.setattr(pipeline, "run_performance",
                        lambda **kw: _performance_result())
    monkeypatch.setattr(pipeline, "run_agent_activity",
                        lambda **kw: _agents_result())
    monkeypatch.setattr(pipeline, "run_network", lambda **kw: _network_result())
    monkeypatch.setattr(pipeline, "run_risk_monitor",
                        lambda **kw: _risk_result())


def test_cmd_trades_runs(capsys, monkeypatch):
    _stub_terminal(monkeypatch)
    assert cli.main(["trades", "--limit", "10"]) == 0
    out = capsys.readouterr().out
    assert "Trade blotter" in out and "SPY" in out


def test_cmd_trades_export_stdout(capsys, monkeypatch):
    _stub_terminal(monkeypatch)
    assert cli.main(["trades", "export"]) == 0
    out = capsys.readouterr().out
    assert out == "id,symbol\n"


def test_cmd_trades_export_to_file(monkeypatch, tmp_path):
    _stub_terminal(monkeypatch)
    target = tmp_path / "trades.csv"
    assert cli.main(["trades", "export", "--out", str(target)]) == 0
    assert target.read_text() == "id,symbol\n"


def test_cmd_performance_runs(capsys, monkeypatch):
    _stub_terminal(monkeypatch)
    assert cli.main(["performance"]) == 0
    out = capsys.readouterr().out
    assert "Computing performance analytics" in out and "Performance" in out


def test_cmd_performance_backtest_needs_path(capsys, monkeypatch):
    _stub_terminal(monkeypatch)
    assert cli.main(["performance", "--source", "backtest"]) == 2
    assert "needs --backtest-path" in capsys.readouterr().err


def test_cmd_agents_runs(capsys, monkeypatch):
    _stub_terminal(monkeypatch)
    assert cli.main(["agents"]) == 0
    out = capsys.readouterr().out
    assert "Agent activity" in out


def test_cmd_network_runs(capsys, monkeypatch):
    _stub_terminal(monkeypatch)
    assert cli.main(["network"]) == 0
    out = capsys.readouterr().out
    assert "correlation network" in out and "Network" in out


def test_cmd_risk_runs(capsys, monkeypatch):
    _stub_terminal(monkeypatch)
    assert cli.main(["risk"]) == 0
    out = capsys.readouterr().out
    assert "Risk monitor" in out


def test_real_cli_commands_run_with_web_engine():
    _web()
    for argv in (["trades", "--limit", "2"], ["trades", "export", "--limit", "2"],
                 ["performance"], ["agents"], ["network"], ["risk"]):
        assert cli.main(argv) == 0, argv
