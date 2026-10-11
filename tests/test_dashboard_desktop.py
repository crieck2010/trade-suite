"""Unit tests for Windows desktop launcher and packaging integration."""

from pathlib import Path
import pytest

from trade_dashboard_app.desktop import (
    find_free_port,
    get_app_script_path,
    wait_for_server,
)


def test_find_free_port():
    port = find_free_port(start_port=8501, max_tries=50)
    assert isinstance(port, int)
    assert 8501 <= port <= 8551


def test_get_app_script_path():
    path = get_app_script_path()
    assert isinstance(path, Path)
    assert path.name == "app.py"
    assert path.exists()


def test_wait_for_server_timeout():
    # An unused port should quickly time out
    is_ready = wait_for_server("http://127.0.0.1:59999", timeout_sec=0.4)
    assert is_ready is False


def test_spec_file_validity():
    spec_path = Path(__file__).resolve().parent.parent / "packaging" / "trade_dashboard_app.spec"
    assert spec_path.exists()
    content = spec_path.read_text(encoding="utf-8")
    assert "TradeDashboardApp" in content
    assert "trade_dashboard_app" in content
    assert "streamlit" in content
