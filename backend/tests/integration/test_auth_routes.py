"""tests/integration/test_auth_routes.py — Integration tests for /auth/* endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

# ── /auth/register ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_creates_tokens(app_client: AsyncClient):
    resp = await app_client.post(
        "/api/v1/auth/register",
        json={
            "email": "newuser@test.com",
            "password": "StrongPass123!",
            "company_name": "Acme Logistics",
            "first_name": "John",
            "last_name": "Doe",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_duplicate_email(app_client: AsyncClient):
    payload = {
        "email": "dup@test.com",
        "password": "Pass123!",
        "company_name": "Corp",
        "first_name": "A",
        "last_name": "B",
    }
    await app_client.post("/api/v1/auth/register", json=payload)
    resp = await app_client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 400
    assert "already registered" in resp.json()["detail"].lower()


# ── /auth/login ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_valid_credentials(app_client: AsyncClient):
    # Register first
    await app_client.post(
        "/api/v1/auth/register",
        json={
            "email": "login@test.com",
            "password": "MyPass123!",
            "company_name": "Corp",
            "first_name": "X",
            "last_name": "Y",
        },
    )
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={
            "email": "login@test.com",
            "password": "MyPass123!",
        },
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_login_wrong_password(app_client: AsyncClient):
    await app_client.post(
        "/api/v1/auth/register",
        json={
            "email": "badpw@test.com",
            "password": "CorrectPw!",
            "company_name": "Corp",
            "first_name": "A",
            "last_name": "B",
        },
    )
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={
            "email": "badpw@test.com",
            "password": "WrongPw!",
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email(app_client: AsyncClient):
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={
            "email": "ghost@test.com",
            "password": "anything",
        },
    )
    assert resp.status_code == 401


# ── /auth/me ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_me_authenticated(app_client: AsyncClient):
    reg = await app_client.post(
        "/api/v1/auth/register",
        json={
            "email": "me@test.com",
            "password": "Pass123!",
            "company_name": "Corp",
            "first_name": "Me",
            "last_name": "Test",
        },
    )
    token = reg.json()["access_token"]
    resp = await app_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "me@test.com"
    assert "tenant" in data


@pytest.mark.asyncio
async def test_get_me_unauthenticated(app_client: AsyncClient):
    resp = await app_client.get("/api/v1/auth/me")
    assert resp.status_code == 403  # HTTPBearer returns 403 when no credentials


# ── /auth/logout ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_logout_succeeds(app_client: AsyncClient, redis_mock):
    reg = await app_client.post(
        "/api/v1/auth/register",
        json={
            "email": "logout@test.com",
            "password": "Pass123!",
            "company_name": "Corp",
            "first_name": "L",
            "last_name": "O",
        },
    )
    refresh_token = reg.json()["refresh_token"]
    resp = await app_client.post(
        "/api/v1/auth/logout",
        json={
            "access_token": reg.json()["access_token"],
            "refresh_token": refresh_token,
            "token_type": "bearer",
        },
    )
    assert resp.status_code == 200
    assert "logged out" in resp.json()["message"].lower()
