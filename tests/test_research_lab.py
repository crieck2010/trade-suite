"""Research-lab workflow tests (trade-suite 0.2.0).

Full-stack tests need the dashboard + engine siblings installed and are
skipped otherwise (``pytest.importorskip``).  Missing-engine and
input-validation tests run anywhere.
"""

from __future__ import annotations

import builtins

import pytest

from trade_suite import cli, pipeline


def _block_engine(monkeypatch, package: str):
    """Make ``package`` unimportable, however the workflow reaches for it.

    Workflows import engines two ways: ``from X import Y`` statements go
    through ``builtins.__import__``; ``env.require()`` uses
    ``importlib.import_module``, which does not.  Block both, and scrub any
    already-imported copy from ``sys.modules``.
    """
    import importlib
    import sys

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == package or name.startswith(package + "."):
            raise ImportError(f"no {package}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    real_import_module = importlib.import_module

    def fake_import_module(name, *args, **kwargs):
        if name == package or name.startswith(package + "."):
            raise ImportError(f"no {package}")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    for mod in [m for m in sys.modules
                if m == package or m.startswith(package + ".")]:
        monkeypatch.delitem(sys.modules, mod)


def test_pairs_missing_engine_errors(monkeypatch):
    _block_engine(monkeypatch, "trade_pairs")
    with pytest.raises(RuntimeError, match="trade-pairs"):
        pipeline.run_pairs_screen(["SPY", "AAPL"])


def test_pairs_validates_symbols():
    with pytest.raises(ValueError):
        pipeline.run_pairs_screen(["  "])


def test_pairs_demo():
    pytest.importorskip("trade_dashboard_web")
    pytest.importorskip("trade_pairs")
    result = pipeline.run_pairs_screen(["SPY", "AAPL", "MSFT"],
                                       days=300, max_pairs=5)
    assert result["lookback"] == 252
    assert len(result["pairs"]) <= 5
    assert "hedge_ratio" in result["pairs"][0]
    assert "Pairs screen" in pipeline.summarize_pairs(result)


def test_orderbook_missing_engine_errors(monkeypatch):
    _block_engine(monkeypatch, "trade_orderbook")
    with pytest.raises(RuntimeError, match="trade-orderbook"):
        pipeline.run_orderbook_sim()


def test_orderbook_validates_side_and_type():
    with pytest.raises(ValueError, match="side"):
        pipeline.run_orderbook_sim(side="sideways")
    with pytest.raises(ValueError, match="order_type"):
        pipeline.run_orderbook_sim(order_type="stop")


def test_orderbook_demo():
    pytest.importorskip("trade_orderbook")
    result = pipeline.run_orderbook_sim(quantity=120.0)
    assert result["filled_qty"] == pytest.approx(120.0)
    assert result["fill_ratio"] == pytest.approx(1.0)
    assert "spread_bps" in result["book_features"]
    assert "slippage" in pipeline.summarize_orderbook(result)


def test_optimize_missing_engine_errors(monkeypatch):
    _block_engine(monkeypatch, "trade_optimize")
    with pytest.raises(RuntimeError, match="trade-optimize"):
        pipeline.run_optimize(["SPY", "AAPL"])


def test_optimize_validates_symbols():
    with pytest.raises(ValueError):
        pipeline.run_optimize([])


def test_optimize_demo():
    pytest.importorskip("trade_dashboard_web")
    pytest.importorskip("trade_optimize")
    result = pipeline.run_optimize(["SPY", "AAPL", "MSFT"],
                                   method="max_sharpe")
    assert abs(sum(result["weights"].values()) - 1.0) < 1e-6
    assert len(result["frontier"]) == 20
    assert "Sharpe" in pipeline.summarize_optimize(result)


def test_optimize_rejects_unknown_method():
    pytest.importorskip("trade_dashboard_web")
    pytest.importorskip("trade_optimize")
    with pytest.raises(ValueError, match="unknown method"):
        pipeline.run_optimize(["SPY", "AAPL"], method="yolo")


def test_montecarlo_missing_engine_errors(monkeypatch):
    _block_engine(monkeypatch, "trade_montecarlo")
    with pytest.raises(RuntimeError, match="trade-montecarlo"):
        pipeline.run_montecarlo(["SPY"])


def test_montecarlo_demo():
    pytest.importorskip("trade_dashboard_web")
    pytest.importorskip("trade_montecarlo")
    result = pipeline.run_montecarlo(["SPY", "AAPL"], n_paths=500,
                                     n_steps=60)
    assert result["var"] > 0
    assert result["cvar"] >= result["var"]
    assert 0.0 <= result["prob_profit"] <= 1.0
    assert "VaR" in pipeline.summarize_montecarlo(result)


def test_volsurface_missing_engine_errors(monkeypatch):
    _block_engine(monkeypatch, "trade_volsurface")
    with pytest.raises(RuntimeError, match="trade-volsurface"):
        pipeline.run_vol_surface()


def test_volsurface_demo():
    pytest.importorskip("trade_volsurface")
    result = pipeline.run_vol_surface()
    assert result["n_quotes"] == 52
    assert len(result["svi_fits"]) == 4
    assert "SVI fits" in pipeline.summarize_volsurface(result)


def test_factors_missing_engine_errors(monkeypatch):
    _block_engine(monkeypatch, "trade_factors")
    with pytest.raises(RuntimeError, match="trade-factors"):
        pipeline.run_factor_analysis(["SPY"])


def test_factors_validates_symbols():
    with pytest.raises(ValueError):
        pipeline.run_factor_analysis([" "])


def test_factors_demo():
    pytest.importorskip("trade_dashboard_web")
    pytest.importorskip("trade_factors")
    result = pipeline.run_factor_analysis(["SPY", "AAPL"], model="ff3")
    assert set(result["assets"]) == {"SPY", "AAPL"}
    assert "alpha" in result["assets"]["SPY"]
    assert result["grs"]["pvalue"] >= 0.0
    assert "Factor analysis (ff3" in pipeline.summarize_factors(result)


def test_sentiment_price_missing_engine_errors(monkeypatch):
    _block_engine(monkeypatch, "trade_sentiment_vs_price")
    with pytest.raises(RuntimeError, match="trade-sentiment-vs-price"):
        pipeline.run_sentiment_price("DEMO")


def test_sentiment_price_validates_symbol():
    with pytest.raises(ValueError):
        pipeline.run_sentiment_price("  ")


def test_sentiment_price_rejects_non_demo_without_rows():
    pytest.importorskip("trade_sentiment_vs_price")
    with pytest.raises(ValueError, match="sentiment_rows"):
        pipeline.run_sentiment_price("SPY", source="equities")


def test_sentiment_price_demo():
    pytest.importorskip("trade_sentiment_vs_price")
    result = pipeline.run_sentiment_price("DEMO")
    assert result["lead_lag"]["verdict"] == "sentiment leads"
    assert "IC=" in pipeline.summarize_sentiment_price(result)


def test_research_pipeline_enrichment_flags():
    pytest.importorskip("trade_dashboard_web")
    pytest.importorskip("trade_agents")
    pytest.importorskip("trade_sentiment_vs_price")
    pytest.importorskip("trade_factors")
    out = pipeline.research_pipeline(["SPY"], days=120,
                                     sentiment_price=True,
                                     factor_model="ff3")
    assert "sentiment_price" in out and "factors" in out
    assert out["sentiment_price"]["SPY"]["symbol"] == "SPY"


def test_research_pipeline_defaults_skip_enrichment():
    pytest.importorskip("trade_dashboard_web")
    pytest.importorskip("trade_agents")
    out = pipeline.research_pipeline(["SPY"], days=120)
    assert "sentiment_price" not in out and "factors" not in out


# -- CLI --------------------------------------------------------------------

def test_parser_research_lab_defaults():
    p = cli.build_parser()
    args = p.parse_args(["pairs"])
    assert args.command == "pairs" and args.lookback == 252
    args = p.parse_args(["orderbook"])
    assert args.side == "buy" and args.order_type == "market"
    args = p.parse_args(["optimize"])
    assert args.method == "max_sharpe"
    args = p.parse_args(["montecarlo"])
    assert args.paths == 5_000 and args.weights == ""
    args = p.parse_args(["factors"])
    assert args.model == "ff5"
    args = p.parse_args(["sentiment-price"])
    assert args.symbol == "DEMO"
    args = p.parse_args(["volsurface"])
    assert args.symbol == "SPY" and args.risk_free == 0.03


def test_cmd_orderbook_runs(capsys):
    pytest.importorskip("trade_orderbook")
    assert cli.main(["orderbook", "--quantity", "50"]) == 0
    assert "slippage" in capsys.readouterr().out


def test_cmd_volsurface_runs(capsys):
    pytest.importorskip("trade_volsurface")
    assert cli.main(["volsurface"]) == 0
    assert "SVI fits" in capsys.readouterr().out
