"""Tests for trade_press.classify — deterministic keyword rules."""

from __future__ import annotations

from datetime import datetime, timezone

from trade_press.classify import classify_hits, classify_item, classify_items
from trade_press.models import PressItem, make_item_id
from trade_press.themes import get_theme

NOW = datetime(2026, 10, 19, 16, 0, tzinfo=timezone.utc)
THEME = get_theme("ai_infrastructure_capex")


def item(title: str, summary: str = "") -> PressItem:
    return PressItem(
        id=make_item_id(f"https://example.com/{abs(hash(title))}", title),
        source="google_news", title=title, summary=summary,
        url="https://example.com/x", publisher="Reuters",
        published_at=NOW, observed_at=NOW, recorded_at=NOW,
    )


def test_two_include_terms_match():
    it = item("Microsoft data center buildout accelerates",
              "Capex guidance raised again.")
    hits = classify_hits(it, THEME)
    assert hits is not None
    assert set(hits) == {"data center", "buildout", "capex"}


def test_one_include_term_is_not_enough():
    it = item("Capex season is here", "A quiet day for spending.")
    assert classify_hits(it, THEME) is None
    assert not classify_item(it, THEME)


def test_hits_follow_pack_order_not_text_order():
    it = item("Buildout of the data center campus begins",
              "The buildout pairs with new capex.")
    hits = classify_hits(it, THEME)
    assert hits == tuple(
        t for t in THEME.include_terms if t in hits)


def test_exclude_term_vetoes_despite_includes():
    it = item("Data center capex lawsuit dismissed",
              "The data center buildout continues.")
    assert classify_hits(it, THEME) is None


def test_matching_is_case_insensitive():
    it = item("DATA CENTER expansion", "CAPEX plans confirmed.")
    assert classify_item(it, THEME)


def test_summary_counts_toward_match():
    it = item("Spending plans confirmed",
              "The hyperscaler cited power capacity and its data center "
              "footprint.")
    hits = classify_hits(it, THEME)
    assert hits is not None
    assert "hyperscaler" in hits and "power capacity" in hits


def test_classify_items_filters_and_keeps_hits():
    good = item("GPU cluster buildout expands", "Data center capex rises.")
    bad = item("Local bakery wins award", "Best sourdough in the county.")
    out = classify_items([good, bad], THEME)
    assert [i for i, _ in out] == [good]
    assert out[0][1]


def test_deterministic_same_input_same_output():
    it = item("AI infrastructure spending climbs",
              "Hyperscaler capex and data center buildout lead.")
    assert classify_hits(it, THEME) == classify_hits(it, THEME)
