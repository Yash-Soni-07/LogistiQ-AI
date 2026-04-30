"""tests/unit/test_gdelt_scanner.py — Unit tests for agents/gdelt_scanner.py."""

from __future__ import annotations

import pytest

from agents.gdelt_scanner import (
    _article_segment_id,
    classify_article,
)
from db.models import DisruptionType

# ── classify_article ──────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected_type,min_prob",
    [
        (
            "Major truck driver strike blocks NH-8 highway India logistics",
            DisruptionType.STRIKE,
            0.5,
        ),
        (
            "Cyclone Biparjoy floods Gujarat ports disrupts cargo",
            DisruptionType.WEATHER,
            0.5,
        ),
        (
            "Port closure Nhava Sheva blocked by labour walkout",
            DisruptionType.STRIKE,  # walkout matches STRIKE
            0.5,
        ),
        (
            "Landslide mudslide blocks NH-10 Sikkim road",
            DisruptionType.NATURAL_DISASTER,
            0.5,
        ),
        (
            "Train derail cancels cargo Howrah route",
            DisruptionType.TRAFFIC,
            0.5,
        ),
        (
            "Road accident pileup on Mumbai-Pune expressway",
            DisruptionType.ACCIDENT,
            0.5,
        ),
    ],
)
def test_classify_article_known_signals(text, expected_type, min_prob):
    d_type, prob = classify_article(text)
    assert d_type == expected_type, (
        f"Expected {expected_type.value}, got {d_type.value} for: {text}"
    )
    assert prob >= min_prob, f"Expected prob >= {min_prob}, got {prob}"


def test_classify_article_no_match():
    """Irrelevant article text should return probability 0.0."""
    _, prob = classify_article("Scientists discover new species of beetle in Amazon rainforest")
    assert prob == 0.0


def test_classify_article_multiple_matches_higher_prob():
    """More keyword hits → higher confidence (capped at 1.0)."""
    text = "Strike walkout protest blockade workers India logistics"
    _, prob = classify_article(text)
    # Multiple strike-related words should push probability above base 0.80
    assert prob >= 0.80


def test_classify_article_case_insensitive():
    _, prob1 = classify_article("STRIKE BLOCKS HIGHWAY")
    _, prob2 = classify_article("strike blocks highway")
    assert prob1 == prob2


# ── _article_segment_id ───────────────────────────────────────


def test_article_segment_id_stable():
    article = {"url": "https://example.com/article/123"}
    id1 = _article_segment_id(article)
    id2 = _article_segment_id(article)
    assert id1 == id2


def test_article_segment_id_different_urls():
    a1 = {"url": "https://news.com/article/1"}
    a2 = {"url": "https://news.com/article/2"}
    assert _article_segment_id(a1) != _article_segment_id(a2)


def test_article_segment_id_prefixed():
    article = {"url": "https://example.com/article"}
    seg_id = _article_segment_id(article)
    assert seg_id.startswith("gdelt:")


def test_article_segment_id_uses_title_fallback():
    """If url is absent, title is used."""
    article = {"title": "Some unique headline"}
    seg_id = _article_segment_id(article)
    assert seg_id.startswith("gdelt:")
    assert len(seg_id) > 7


def test_article_segment_id_unknown_fallback():
    """Empty article uses 'unknown' as hash input."""
    seg_id = _article_segment_id({})
    assert seg_id.startswith("gdelt:")
