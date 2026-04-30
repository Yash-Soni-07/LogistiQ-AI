"""tests/unit/test_risk_scorer.py — Unit tests for ml/risk_scorer.py."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ml.risk_scorer import (
    _W_FIRE,
    _W_FLOOD,
    _W_QUAKE,
    _W_STRIKE,
    RiskScore,
    _fire_proximity_score,
    _haversine_km,
    _quake_score,
    compute_risk,
)

# ── Constants ─────────────────────────────────────────────────


def test_weights_sum_to_one():
    total = _W_FLOOD + _W_FIRE + _W_STRIKE + _W_QUAKE
    assert abs(total - 1.0) < 1e-9


# ── Haversine ─────────────────────────────────────────────────


def test_haversine_mumbai_chennai():
    d = _haversine_km(19.076, 72.877, 13.082, 80.270)
    assert 900 < d < 1200, f"Expected ~1033 km, got {d}"


def test_haversine_same_point():
    assert _haversine_km(19.0, 72.0, 19.0, 72.0) == pytest.approx(0.0, abs=0.001)


# ── Fire proximity ────────────────────────────────────────────


def _fire_feature(lat: float, lon: float, frp: float = 15.0) -> dict:
    return {"geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": {"frp": frp}}


def test_fire_proximity_within_5km():
    # Fire at exact same lat/lon as query → distance = 0 km < 5 km
    score = _fire_proximity_score(19.076, 72.877, [_fire_feature(19.076, 72.877)])
    assert score == 0.9


def test_fire_proximity_within_10km():
    # Place fire ~7 km away (roughly 0.063 degrees latitude)
    # dist_weight = 0.5, frp_weight = 0.9 (for FRP > 10.0) -> 0.45
    score = _fire_proximity_score(19.076, 72.877, [_fire_feature(19.139, 72.877)])
    assert score == pytest.approx(0.45, abs=0.01)


def test_fire_proximity_outside_10km():
    # Fire in Chennai when checking Mumbai → ~1000 km away
    score = _fire_proximity_score(19.076, 72.877, [_fire_feature(13.082, 80.270)])
    assert score == 0.0


def test_fire_proximity_empty_features():
    assert _fire_proximity_score(19.076, 72.877, []) == 0.0


def test_fire_proximity_malformed_feature():
    bad = [{"geometry": {"coordinates": []}}]
    assert _fire_proximity_score(19.076, 72.877, bad) == 0.0


# ── Quake score ───────────────────────────────────────────────


def test_quake_score_significant():
    quakes = [{"magnitude": 5.0, "depth_km": 10.0}]
    score = _quake_score(quakes)
    # min(5/5,1) * (1 - 10/30) = 1.0 * 0.667 = 0.667
    assert score == pytest.approx(0.667, abs=0.01)


def test_quake_score_below_threshold():
    quakes = [{"magnitude": 2.0, "depth_km": 5.0}]
    assert _quake_score(quakes) == 0.0


def test_quake_score_takes_max():
    quakes = [
        {"magnitude": 4.0, "depth_km": 20.0},
        {"magnitude": 6.0, "depth_km": 5.0},
    ]
    score = _quake_score(quakes)
    # Second quake: min(6/5,1)*(1-5/30) = 1.0 * 0.833 = 0.833
    assert score == pytest.approx(0.833, abs=0.01)


def test_quake_score_empty():
    assert _quake_score([]) == 0.0


# ── compute_risk with mocked MCPs ────────────────────────────


@pytest.mark.asyncio
async def test_compute_risk_returns_risk_score(mock_mcp_clients, redis_mock):
    score = await compute_risk(19.076, 72.877, "seg-001", mock_mcp_clients)
    assert isinstance(score, RiskScore)
    assert 0.0 <= score.risk_score <= 1.0
    assert score.cache_hit is False
    assert score.computed_at != ""


@pytest.mark.asyncio
async def test_compute_risk_cache_hit(mock_mcp_clients, redis_mock):
    # First call → cache miss
    s1 = await compute_risk(19.076, 72.877, "seg-cache", mock_mcp_clients)
    assert s1.cache_hit is False
    # Second call same coords → cache hit
    s2 = await compute_risk(19.076, 72.877, "seg-cache", mock_mcp_clients)
    assert s2.cache_hit is True
    assert s2.risk_score == s1.risk_score


@pytest.mark.asyncio
async def test_compute_risk_no_clients(redis_mock):
    """No MCP clients → all zero scores, no crash."""
    score = await compute_risk(19.076, 72.877, "seg-none", {})
    assert score.risk_score >= 0.0
    assert score.fire_proximity_score == 0.0
    assert score.quake_score == 0.0


@pytest.mark.asyncio
async def test_compute_risk_reads_strike_from_redis(mock_mcp_clients, redis_mock):
    await redis_mock.set("news:seg-strike:strike_probability", "0.8")
    score = await compute_risk(19.076, 72.877, "seg-strike", mock_mcp_clients)
    assert score.strike_score == pytest.approx(0.8, abs=0.001)
    assert "redis:gdelt_strike" in score.sources_used


@pytest.mark.asyncio
async def test_compute_risk_high_flood_elevates_composite(redis_mock):
    """Weather MCP returning risk_score=0.9 should drive composite high."""
    high_flood = AsyncMock()
    high_flood.call.return_value = {"risk_score": 0.9, "rain_24h_mm": 80.0, "elevation_m": 2.0}
    low_sat = AsyncMock()
    low_sat.call.return_value = {"features": []}

    score = await compute_risk(
        19.0, 72.0, "seg-flood", {"weather": high_flood, "satellite": low_sat}
    )
    # flood weight=0.40 → composite >= 0.36
    assert score.risk_score >= 0.36
