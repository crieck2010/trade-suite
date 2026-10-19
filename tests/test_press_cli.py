"""Tests for trade_press.cli — scan/rollup/state smoke tests (no network)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from trade_press import cli
from trade_press.models import PressItem, make_item_id
from trade_press.themes import get_theme

THEME = get_theme("ai_infrastructure_capex")


def _fixture_items():
    now = datetime.now(timezone.utc)
    out = []
    stories = (
        ("Data center buildout accelerates as capex climbs",
         "AI infrastructure spending and data center capex."),
        ("Hyperscaler power capacity crunch eases",
         "AI infrastructure spending and data center capex."),
        ("Bakery of the year announced downtown",  # must NOT match
         "Sourdough and croissants take top honors this year."),
    )
    for i, (title, summary) in enumerate(stories):
        pub = now - timedelta(hours=2)
        out.append(PressItem(
            id=make_item_id(f"https://example.com/{i}", title),
            source="stub", title=title, summary=summary,
            url=f"https://example.com/{i}", publisher="Reuters",
            published_at=pub, observed_at=pub, recorded_at=now))
    return out


class _StubSource:
    name = "stub"
    rate_limit_note = "test double"

    def fetch(self, theme, limit=50):
        return _fixture_items()


@pytest.fixture()
def stubbed(monkeypatch):
    monkeypatch.setattr("trade_press.pipeline.get_source",
                        lambda name: _StubSource())


def test_scan_rollup_state_flow(stubbed, tmp_path, capsys):
    db = str(tmp_path / "press.db")
    today = datetime.now(timezone.utc).date().isoformat()

    assert cli.main(["scan", "--theme", THEME.theme_id,
                     "--archive", db]) == 0
    out = capsys.readouterr().out
    assert "matched=2" in out  # the bakery story is classified out

    assert cli.main(["rollup", "--theme", THEME.theme_id,
                     "--archive", db]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "press.narrative_state.v1"
    assert payload["state"] == "INSUFFICIENT_DATA"  # honest day one
    assert payload["n_items"] == 2

    assert cli.main(["state", "--theme", THEME.theme_id,
                     "--archive", db, "--as-of", today]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["as_of"] == today


def test_state_without_rollup_returns_2(stubbed, tmp_path, capsys):
    db = str(tmp_path / "press.db")
    rc = cli.main(["state", "--theme", THEME.theme_id, "--archive", db,
                   "--as-of", "2020-01-01"])
    assert rc == 2
    assert "no narrative state" in capsys.readouterr().err


def test_scan_is_idempotent_on_the_archive(stubbed, tmp_path, capsys):
    db = str(tmp_path / "press.db")
    cli.main(["scan", "--theme", THEME.theme_id, "--archive", db])
    capsys.readouterr()
    cli.main(["scan", "--theme", THEME.theme_id, "--archive", db])
    out = capsys.readouterr().out
    assert "archive_total=2" in out  # dedupe: second scan adds nothing


def test_themes_listing(capsys):
    assert cli.main(["themes"]) == 0
    assert THEME.theme_id in capsys.readouterr().out


def test_policy_listing(capsys):
    assert cli.main(["policy"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "full article text" in payload["never_stored"]
