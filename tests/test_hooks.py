"""Licensing + update-check hook tests."""

from __future__ import annotations

import urllib.error

import pytest

from trade_suite import licensing, updates


@pytest.fixture
def key_file(tmp_path, monkeypatch):
    monkeypatch.setattr(licensing, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(licensing, "KEY_FILE", tmp_path / "license.key")


def test_format_valid():
    assert licensing.format_valid("TS-AB12-CD34-EF56")
    assert not licensing.format_valid("TD-AB12-CD34-EF56")  # wrong prefix
    assert not licensing.format_valid("nope")


def test_save_load_clear(key_file):
    assert licensing.save_key("TS-AB12-CD34-EF56").valid
    assert licensing.load_key() == "TS-AB12-CD34-EF56"
    assert licensing.current_status().tier == "pro"
    licensing.clear_key()
    assert licensing.current_status().tier == "community"


def test_is_newer():
    assert updates.is_newer("v0.2.0", "0.1.0")
    assert not updates.is_newer("v0.1.0", "0.1.0")


def test_check_for_updates_offline(monkeypatch):
    def _raise(req, timeout):
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(updates.urllib.request, "urlopen", _raise)
    assert "error" in updates.check_for_updates("0.1.0")
