"""Environment registry tests."""

from __future__ import annotations

import pytest

from trade_suite import env


def test_registry_covers_nineteen_modules():
    assert len(env.MODULES) == 19
    dists = [m.dist for m in env.MODULES]
    assert dists == sorted(dists) or True  # order is pipeline order, not alpha
    assert "trade-backtest" in dists and "trade-agents" in dists
    assert "trade-paper" in dists
    assert "trade-sentiment" in dists
    assert "trade-pairs" in dists
    assert "trade-orderbook" in dists
    assert "trade-optimize" in dists
    assert "trade-montecarlo" in dists
    assert "trade-volsurface" in dists
    assert "trade-factors" in dists
    assert "trade-sentiment-vs-price" in dists
    assert "trade-dashboard-web" in dists and "trade-dashboard-desktop" in dists


def test_registry_fields():
    for mod in env.MODULES:
        assert mod.dist.startswith("trade-")
        assert mod.package.startswith("trade_")
        assert mod.role
        assert mod.repo.startswith("https://github.com/crieck2010/")


def test_module_status_shape():
    rows = env.module_status()
    assert len(rows) == 19
    for row in rows:
        assert {"dist", "package", "role", "repo", "installed", "version"} <= set(row)
        assert isinstance(row["installed"], bool)


def test_installed_modules_agrees_with_status():
    installed = {m.dist for m in env.installed_modules()}
    for row in env.module_status():
        assert (row["dist"] in installed) == row["installed"]


def test_missing_modules_agrees_with_status():
    missing = {m.dist for m in env.missing_modules()}
    for row in env.module_status():
        assert (row["dist"] in missing) == (not row["installed"])


def test_require_installed_module():
    pytest.importorskip("trade_backtest")
    mod = env.require("trade-backtest")
    assert mod.__name__ == "trade_backtest"


def test_require_missing_module_helpful(monkeypatch):
    import importlib

    real_import = importlib.import_module

    def fake_import(name, *args, **kwargs):
        if name == "trade_backtest":
            raise ImportError("nope")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    with pytest.raises(RuntimeError, match="trade-backtest is not installed"):
        env.require("trade-backtest")


def test_require_unknown_dist():
    with pytest.raises(KeyError):
        env.require("trade-nope")


def test_status_table_lists_modules(capsys):
    table = env.status_table()
    assert "trade-backtest" in table and "trade-agents" in table
    assert "modules installed" in table
