"""trade-suite 0.4.0 tests: breadth / macro / stream / reconcile wiring.

Delegation tests stub ``pipeline._services()`` so they run with no sibling
installed.  Full-stack agreement tests ``pytest.importorskip`` the dashboard
+ engines and additionally skip when the canonical job has not landed in the
installed dashboard yet — missing engines/panels skip, never fail.
"""

from __future__ import annotations

import builtins
import importlib
import sys
import types

import pytest

from trade_suite import cli, env, pipeline


# -- helpers ---------------------------------------------------------------

def _block_packages(monkeypatch, *packages: str):
    """Make ``packages`` unimportable, however the workflow reaches for them.

    Mirrors the helper in test_research_lab.py: ``from X import Y`` goes
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
        def job(**kwargs):
            calls[name] = kwargs
            return {"job": name, "kwargs": kwargs}
        return job

    stub = types.SimpleNamespace(**{n: make(n) for n in jobs})
    monkeypatch.setattr(pipeline, "_services", lambda: stub)
    return calls


# -- registry ----------------------------------------------------------------

def test_registry_has_twenty_three_including_new_three():
    dists = [m.dist for m in env.MODULES]
    assert len(env.MODULES) == 23
    for dist in ("trade-breadth", "trade-macro", "trade-stream"):
        assert dist in dists
        mod = next(m for m in env.MODULES if m.dist == dist)
        assert mod.package.startswith("trade_")
        assert mod.repo == f"https://github.com/crieck2010/{dist}"


def test_new_three_installed_in_full_env():
    for dist, pkg in (("trade-breadth", "trade_breadth"),
                      ("trade-macro", "trade_macro"),
                      ("trade-stream", "trade_stream")):
        pytest.importorskip(pkg)
    installed = {m.dist for m in env.installed_modules()}
    assert {"trade-breadth", "trade-macro", "trade-stream"} <= installed


# -- delegation (stubbed services; runs anywhere) -----------------------------

def test_run_breadth_delegates(monkeypatch):
    calls = _stub_services(monkeypatch, run_breadth_job=None)
    out = pipeline.run_breadth(preset="wide", seed=3, n_days=100)
    assert out["job"] == "run_breadth_job"
    assert calls["run_breadth_job"] == {"preset": "wide", "seed": 3,
                                       "n_days": 100}


def test_run_breadth_defaults(monkeypatch):
    calls = _stub_services(monkeypatch, run_breadth_job=None)
    pipeline.run_breadth()
    assert calls["run_breadth_job"] == {"preset": "standard", "seed": 7,
                                       "n_days": 600}


def test_run_macro_delegates(monkeypatch):
    calls = _stub_services(monkeypatch, run_macro_job=None)
    out = pipeline.run_macro(seed=9, days=200)
    assert out["job"] == "run_macro_job"
    assert calls["run_macro_job"] == {"preset": "standard", "seed": 9,
                                     "days": 200}


def test_run_stream_demo_delegates(monkeypatch):
    calls = _stub_services(monkeypatch, run_stream_demo_job=None)
    out = pipeline.run_stream_demo(symbols=("AAA", "BBB"), seed=5,
                                   n_ticks=50)
    assert out["job"] == "run_stream_demo_job"
    # tuple in, list out — the canonical job takes a list
    assert calls["run_stream_demo_job"] == {"symbols": ["AAA", "BBB"],
                                           "seed": 5, "n_ticks": 50}


def test_run_reconcile_demo_delegates(monkeypatch):
    calls = _stub_services(monkeypatch, run_reconcile_demo_job=None)
    out = pipeline.run_reconcile_demo()
    assert out["job"] == "run_reconcile_demo_job"
    assert calls["run_reconcile_demo_job"] == {}


# -- missing dashboard (skip-not-fail territory) --------------------------------

def test_missing_dashboard_errors_all_four(monkeypatch):
    _block_packages(monkeypatch, "trade_dashboard_web",
                    "trade_dashboard_desktop")
    for call in (lambda: pipeline.run_breadth(),
                 lambda: pipeline.run_macro(),
                 lambda: pipeline.run_stream_demo(),
                 lambda: pipeline.run_reconcile_demo()):
        with pytest.raises(RuntimeError, match="dashboard"):
            call()


# -- summarize_* smoke tests (contract-shaped fixtures; run anywhere) -----------

def _breadth_result():
    return {
        "source": "trade-breadth", "seed": 7, "n_days": 600, "n_symbols": 50,
        "snapshot": {
            "regime": "broadening", "regime_score": 0.62, "fragility": 0.31,
            "indicators": {"ad_pct": 0.58},
            "thrusts_recent": [{"date": "2026-09-20", "kind": "breadth_thrust"}],
            "warnings": [],
        },
    }


def _macro_result():
    return {
        "source": "trade-macro", "seed": 42, "days": 600,
        "snapshot": {"regime": "EXPANSION", "z_score": 1.24, "ratio": 6.9,
                     "transition_alert": True},
    }


def _stream_result():
    return {
        "symbols": ["AAA", "BBB", "CCC"], "seed": 7, "n_ticks": 600,
        "n_alerts": 1, "n_bars": 12,
        "alerts": [{"symbol": "AAA", "move_pct": 0.072, "price": 107.2,
                    "ts": 1_700_000_000.0}],
    }


def _reconcile_result(dirty=True):
    return {
        "demo": True,
        "paper_positions": {"AAA": 100.0, "BBB": -50.0},
        "broker_positions": {"AAA": 100.0, "CCC": 25.0},
        "reconcile": {
            "matched": ["AAA"],
            "missing_from_broker": [{"symbol": "BBB", "paper": -50.0}],
            "missing_from_ledger": [{"symbol": "CCC", "broker": 25.0}],
            "quantity_mismatches": [] if not dirty else [
                {"symbol": "DDD", "paper": 10.0, "broker": 12.0, "diff": 2.0}],
            "clean": not dirty,
        },
    }


def test_summarize_breadth():
    text = pipeline.summarize_breadth(_breadth_result())
    assert "Market breadth" in text and "broadening" in text
    assert "fragility 0.31" in text and "breadth_thrust" in text


def test_summarize_macro():
    text = pipeline.summarize_macro(_macro_result())
    assert "Macro regime" in text and "EXPANSION" in text
    assert "copper:gold 6.9000" in text and "z +1.24" in text
    assert "TRANSITION ALERT" in text


def test_summarize_macro_tolerates_missing_fields():
    result = _macro_result()
    result["snapshot"] = {"regime": "NEUTRAL", "transition_alert": False}
    text = pipeline.summarize_macro(result)
    assert "NEUTRAL" in text and "TRANSITION ALERT" not in text


def test_summarize_stream_demo():
    text = pipeline.summarize_stream_demo(_stream_result())
    assert "Demo tick stream" in text and "600 ticks" in text
    assert "1 spike alerts" in text and "AAA" in text


def test_summarize_reconcile_clean():
    text = pipeline.summarize_reconcile(_reconcile_result(dirty=False))
    assert "CLEAN" in text


def test_summarize_reconcile_drift():
    text = pipeline.summarize_reconcile(_reconcile_result(dirty=True))
    assert "DRIFT" in text and "BBB" in text and "DDD" in text


# -- CLI -----------------------------------------------------------------------

def test_parser_new_command_defaults():
    p = cli.build_parser()
    args = p.parse_args(["breadth"])
    assert args.command == "breadth" and args.preset == "standard" \
        and args.seed == 7 and args.days == 600
    args = p.parse_args(["macro"])
    assert args.command == "macro" and args.preset == "standard" \
        and args.seed == 42 and args.days == 600
    args = p.parse_args(["stream"])
    assert args.command == "stream" and args.symbols == "AAA,BBB,CCC" \
        and args.seed == 7 and args.ticks == 600
    args = p.parse_args(["reconcile"])
    assert args.command == "reconcile"


def _stub_all_four(monkeypatch):
    monkeypatch.setattr(pipeline, "_services",
                        lambda: types.SimpleNamespace(
                            run_breadth_job=lambda **kw: _breadth_result(),
                            run_macro_job=lambda **kw: _macro_result(),
                            run_stream_demo_job=lambda **kw: _stream_result(),
                            run_reconcile_demo_job=(
                                lambda: _reconcile_result())))


def test_cmd_breadth_runs(capsys, monkeypatch):
    _stub_all_four(monkeypatch)
    assert cli.main(["breadth", "--days", "100"]) == 0
    out = capsys.readouterr().out
    assert "Running market-breadth snapshot" in out
    assert "Market breadth" in out


def test_cmd_macro_runs(capsys, monkeypatch):
    _stub_all_four(monkeypatch)
    assert cli.main(["macro"]) == 0
    out = capsys.readouterr().out
    assert "Running macro regime snapshot" in out
    assert "Macro regime" in out


def test_cmd_stream_runs(capsys, monkeypatch):
    _stub_all_four(monkeypatch)
    assert cli.main(["stream", "--symbols", "AAA,BBB"]) == 0
    out = capsys.readouterr().out
    assert "Running demo tick stream" in out
    assert "Demo tick stream" in out


def test_cmd_reconcile_runs(capsys, monkeypatch):
    _stub_all_four(monkeypatch)
    assert cli.main(["reconcile"]) == 0
    out = capsys.readouterr().out
    assert "DEMO — read-only reconcile against a mock broker" in out
    assert "reconcile" in out


# -- full-stack agreement (skip when engines/jobs are absent) --------------------

def _canonical(job_name: str):
    """The installed dashboard engine's canonical job, or skip."""
    pytest.importorskip("trade_dashboard_web")
    engine = importlib.import_module("trade_dashboard_web.engine")
    job = getattr(engine, job_name, None)
    if job is None:
        pytest.skip(f"{job_name} not in the installed dashboard engine yet")
    return engine, job


def test_breadth_agrees_with_canonical_job():
    pytest.importorskip("trade_breadth")
    engine, job = _canonical("run_breadth_job")
    kw = {"preset": "standard", "seed": 7, "n_days": 60}
    assert pipeline.run_breadth(**kw) == job(**kw)


def test_macro_agrees_with_canonical_job():
    pytest.importorskip("trade_macro")
    engine, job = _canonical("run_macro_job")
    kw = {"preset": "standard", "seed": 42, "days": 300}  # job needs >= 250
    assert pipeline.run_macro(**kw) == job(**kw)


def test_stream_demo_agrees_with_canonical_job():
    pytest.importorskip("trade_stream")
    engine, job = _canonical("run_stream_demo_job")
    kw = {"symbols": ["AAA", "BBB"], "seed": 7, "n_ticks": 60}
    assert pipeline.run_stream_demo(symbols=tuple(kw["symbols"]), seed=7,
                                   n_ticks=60) == job(**kw)


def test_reconcile_demo_agrees_with_canonical_job():
    engine, job = _canonical("run_reconcile_demo_job")
    assert pipeline.run_reconcile_demo() == job()
