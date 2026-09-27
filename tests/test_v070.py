"""Tests for the 0.7.0 allocate workflow (trade-allocate delegation).

The CLI and library paths run the same canonical engine, so a scripted
run and a ``trade-suite allocate`` run agree exactly. The seeded demo is
deterministic and works offline.
"""

from __future__ import annotations

import json

import pytest

trade_allocate = pytest.importorskip("trade_allocate")

from trade_suite import cli, pipeline


def test_run_allocate_demo_is_deterministic():
    r1 = pipeline.run_allocate()
    r2 = pipeline.run_allocate()
    assert r1["weights"] == r2["weights"]
    assert r1["suite_demo"] is True


def test_run_allocate_demo_result_shape():
    result = pipeline.run_allocate(method="risk_parity")
    assert result["schema_version"] == 1
    assert set(result["weights_by_id"]) == set(result["ids"])
    assert abs(sum(result["weights"]) - 1.0) < 1e-9
    assert "portfolio_gates" in result
    assert "pm_payload" in result and "risk_payload" in result
    assert "paper_payload" in result


def test_run_allocate_methods_agree_on_engine():
    from trade_allocate import adapters, demo
    from trade_allocate import pipeline as alloc

    streams = demo.synthetic_streams(seed=7)
    inputs = {sid: adapters.strategy_input(sid, s, demo.synthetic_evidence(sid))
              for sid, s in streams.items()}
    for method in ("risk_parity", "hrp", "equal"):
        expected = alloc.run(inputs, method=method)
        got = pipeline.run_allocate(method=method)
        assert got["weights"] == pytest.approx(expected["weights"])


def test_run_allocate_rejects_bad_method():
    with pytest.raises(ValueError):
        pipeline.run_allocate(method="max_sharpe")


def test_run_allocate_missing_inputs_file():
    with pytest.raises(FileNotFoundError):
        pipeline.run_allocate(inputs_path="/nonexistent/inputs.json")


def test_run_allocate_inputs_file(tmp_path):
    from trade_allocate import demo

    streams = demo.synthetic_streams(seed=7)
    raw = {sid: {"returns": series,
                 "evidence": demo.synthetic_evidence(sid)}
           for sid, series in streams.items()}
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    result = pipeline.run_allocate(inputs_path=str(path), method="hrp")
    assert result["suite_demo"] is False
    assert abs(sum(result["weights"]) - 1.0) < 1e-9


def test_run_allocate_needs_engine(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "trade_allocate", None)
    with pytest.raises(RuntimeError, match="trade-allocate"):
        pipeline.run_allocate()


def test_summarize_allocate_labels_demo():
    result = pipeline.run_allocate()
    text = pipeline.summarize_allocate(result)
    assert "DEMO" in text
    assert "risk_parity" in text
    assert "portfolio gates" in text


def test_cli_allocate_runs():
    assert cli.main(["allocate", "--method", "equal"]) == 0


def test_cli_allocate_json(capsys):
    assert cli.main(["allocate", "--json", "--method", "hrp"]) == 0
    out = capsys.readouterr().out
    parsed = json.loads(out[out.index("{"):])
    assert parsed["method"] == "hrp"
