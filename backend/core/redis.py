"""
core/redis.py — Async Redis client for LogistiQ AI.

The module-level ``redis_client`` is the single shared connection pool.
Tests patch ``api.auth_routes.redis_client`` and other importers directly
via ``monkeypatch.setattr(module, "redis_client", fake)`` — no proxy needed.
"""

import redis.asyncio as redis

from core.config import settings

redis_client = redis.from_url(
    settings.REDIS_URL,
    encoding="utf-8",
    decode_responses=True,
)
