"""tests/unit/test_auth.py — Unit tests for core/auth.py."""

from __future__ import annotations

from datetime import timedelta

import pytest

from core.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from core.exceptions import UnauthorizedError

# ── Password hashing ──────────────────────────────────────────


def test_hash_password_is_not_plaintext():
    hashed = hash_password("MySecret123")
    assert hashed != "MySecret123"
    assert len(hashed) > 20


def test_verify_password_correct():
    hashed = hash_password("CorrectHorse")
    assert verify_password("CorrectHorse", hashed) is True


def test_verify_password_wrong():
    hashed = hash_password("RightPassword")
    assert verify_password("WrongPassword", hashed) is False


def test_hash_is_unique_per_call():
    h1 = hash_password("same")
    h2 = hash_password("same")
    # bcrypt salts make each hash unique
    assert h1 != h2


# ── JWT creation and decoding ─────────────────────────────────


def test_create_and_decode_access_token():
    token = create_access_token("user-1", "tenant-1", "admin")
    payload = decode_token(token)
    assert payload.user_id == "user-1"
    assert payload.tenant_id == "tenant-1"
    assert payload.role == "admin"
    assert payload.type == "access"


def test_access_token_custom_expiry():
    token = create_access_token("u", "t", "viewer", expires_delta=timedelta(hours=1))
    payload = decode_token(token)
    assert payload.user_id == "u"


def test_create_refresh_token_type():
    from jose import jwt

    from core.config import settings

    token = create_refresh_token("user-2", "tenant-2")
    # Decode without validation to inspect type field
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert payload["type"] == "refresh"
    assert payload["user_id"] == "user-2"
    assert payload["tenant_id"] == "tenant-2"


def test_decode_token_invalid_raises_401():
    with pytest.raises(UnauthorizedError) as exc_info:
        decode_token("this.is.not.a.valid.jwt")
    assert exc_info.value.status_code == 401


def test_decode_expired_token_raises_401():
    token = create_access_token("u", "t", "admin", expires_delta=timedelta(seconds=-1))
    with pytest.raises(UnauthorizedError) as exc_info:
        decode_token(token)
    assert exc_info.value.status_code == 401


def test_decode_token_wrong_secret():
    """Token signed with different secret should fail."""
    from unittest.mock import patch

    token = create_access_token("u", "t", "admin")
    with patch("core.auth.settings") as mock_settings:
        mock_settings.SECRET_KEY = "completely-different-secret"
        mock_settings.ALGORITHM = "HS256"
        with pytest.raises(UnauthorizedError) as exc_info:
            decode_token(token)
    assert exc_info.value.status_code == 401
