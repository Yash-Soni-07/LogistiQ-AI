"""tests/unit/test_gdelt_scanner.py — Unit tests for agents/gdelt_scanner.py.

Tests the private `_classify_article` function that actually exists in the
implementation. The speculative `classify_article` / `_article_segment_id`
API was never implemented; these tests cover the real contract instead.
"""

from __future__ import annotations

import pytest

from agents.gdelt_scanner import _classify_article

# ── _classify_article ──────────────────────────────────────────────────────────
# Returns a category string ("strike", "flood", "fuel", "tariff", "port",
# "cyber") when a keyword phrase is found, or None when no match.


@pytest.mark.parametrize(
    "text,expected_category",
    [
        # ── Strike keywords ───────────────────────────────────────────────────
        ("Trucker strike blocks NH-8 highway", "strike"),
        ("Driver agitation hits logistics sector in Maharashtra", "strike"),
        ("Lorry bandh called by union across three states", "strike"),
        ("Transport strike disrupts supply chain operations", "strike"),
        ("Chakka jam protests block freight movement", "strike"),
        # ── Flood keywords ────────────────────────────────────────────────────
        ("Highway flooded near Mumbai after heavy rains", "flood"),
        ("NH closed flood damage on Pune-Bangalore route", "flood"),
        ("Bridge washed away cutting off cargo route", "flood"),
        ("Road blocked rain waterlogging disrupts trucks", "flood"),
        ("Major flood disrupts cargo movement in Gujarat", "flood"),
        # ── Port keywords ─────────────────────────────────────────────────────
        ("Port congestion delays vessel clearance at JNPT", "port"),
        ("Container shortage reported at major ports", "port"),
        ("Port strike halts loading operations", "port"),
        ("Vessel delay JNPT cargo backlog grows", "port"),
        ("Mundra port operations hit by labour dispute", "port"),
        # ── Fuel keywords ─────────────────────────────────────────────────────
        ("Fuel scarcity hits truckers across highway network", "fuel"),
        ("Petrol shortage forces fleet operators to halt", "fuel"),
        ("Diesel crisis disrupts long-haul logistics", "fuel"),
        ("Truckers halt fuel protest outside depot", "fuel"),
        # ── Tariff keywords ───────────────────────────────────────────────────
        ("Export ban on steel hits manufacturers", "tariff"),
        ("Import duty hike affects electronics supply chain", "tariff"),
        ("Trade restriction imposed on agricultural commodities", "tariff"),
        ("Border closure tariff dispute slows cross-border freight", "tariff"),
        # ── Cyber keywords ────────────────────────────────────────────────────
        ("Ransomware logistics firm systems encrypted", "cyber"),
        ("Shipping system hack disrupts container tracking", "cyber"),
        ("Supply chain cyber attack on freight operator", "cyber"),
    ],
)
def test_classify_article_known_signals(text: str, expected_category: str) -> None:
    """Each keyword phrase must resolve to the correct category."""
    result = _classify_article(text)
    assert result == expected_category, (
        f"Expected '{expected_category}', got {result!r} for: {text!r}"
    )


def test_classify_article_no_match() -> None:
    """Irrelevant text must return None — no false positives."""
    result = _classify_article(
        "Scientists discover new species of beetle in Amazon rainforest"
    )
    assert result is None


def test_classify_article_empty_string() -> None:
    """Empty string must return None without raising."""
    assert _classify_article("") is None


def test_classify_article_case_insensitive() -> None:
    """Pattern matching is case-insensitive — UPPER and lower must agree."""
    upper = _classify_article("TRUCKER STRIKE blocks major highway")
    lower = _classify_article("trucker strike blocks major highway")
    assert upper == lower == "strike"


def test_classify_article_returns_string_not_none_on_match() -> None:
    """Return type must be str (not None) when a keyword is matched."""
    result = _classify_article("Port congestion reported at JNPT")
    assert isinstance(result, str)
    assert result == "port"


def test_classify_article_partial_phrase_no_match() -> None:
    """A single word that is only part of a multi-word keyword must not match."""
    # "trucker" alone is not a keyword — only "trucker strike" is
    result = _classify_article("Independent trucker on long haul route")
    assert result is None
