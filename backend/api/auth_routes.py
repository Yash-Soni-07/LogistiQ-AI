from datetime import timedelta

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from core import schemas
from core.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    verify_password,
)
from core.config import settings
from core.redis import redis_client
from db import models
from db.database import get_db_session

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=schemas.Token, status_code=status.HTTP_201_CREATED)
async def register(data: schemas.RegisterRequest, db: AsyncSession = Depends(get_db_session)):
    """
    Register a new tenant and an admin user.
    Creates Stripe customer and sends welcome email (mocks).
    """
    # Check if user already exists
    result = await db.execute(select(models.User).where(models.User.email == data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    try:
        # 1. Create Tenant
        tenant = models.Tenant(name=data.company_name)
        db.add(tenant)
        await db.flush()  # Get tenant ID

        # 2. Create Admin User
        hashed_pwd = hash_password(data.password)
        user = models.User(
            email=data.email,
            full_name=f"{data.first_name} {data.last_name}",
            hashed_password=hashed_pwd,
            role=models.UserRole.ADMIN,
            tenant_id=tenant.id,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        # 2.5 Seed Demo Data (skipped in TESTING mode to preserve test isolation)
        if not settings.TESTING:
            try:
                from db.seed import (
                    create_carriers,
                    create_disruption_events,
                    create_news_alerts,
                    create_route_segments,
                    create_shipments,
                )

                carriers = await create_carriers(db, str(tenant.id))
                shipments = await create_shipments(db, str(tenant.id), carriers)
                await create_route_segments(db, shipments)
                await create_disruption_events(db, str(tenant.id))
                await create_news_alerts(db, str(tenant.id))
                logger.info("Demo data seeded for new tenant", tenant_id=str(tenant.id))
            except Exception as seed_err:
                logger.warning("Failed to seed demo data", error=str(seed_err))

        # 3. Create Stripe Customer (Mock)
        logger.info("Creating Stripe customer", email=user.email, tenant_id=tenant.id)
        # stripe_customer = stripe.Customer.create(email=user.email, name=data.company_name)

        # 4. Send Welcome Email (Mock)
        logger.info("Sending welcome email", email=user.email)

        # 5. Generate Tokens
        access_token = create_access_token(user.id, tenant.id, user.role.value)
        refresh_token = create_refresh_token(user.id, tenant.id)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        }

    except Exception as e:
        await db.rollback()
        logger.error("Registration failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not complete registration",
        ) from e


@router.post("/login", response_model=schemas.Token)
async def login(data: schemas.UserLogin, db: AsyncSession = Depends(get_db_session)):
    """
    Authenticate user and return tokens.
    Includes rate limiting (5 attempts/min).
    """
    rate_limit_key = f"auth:login_attempts:{data.email}"
    attempts = await redis_client.get(rate_limit_key)

    if attempts and int(attempts) >= 5:
        logger.warning("Rate limit exceeded for login", email=data.email)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again in a minute.",
        )

    result = await db.execute(select(models.User).where(models.User.email == data.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.hashed_password):
        # Increment failure counter
        await redis_client.incr(rate_limit_key)
        await redis_client.expire(rate_limit_key, 60)

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )

    # Success - clear rate limit
    await redis_client.delete(rate_limit_key)

    access_token = create_access_token(user.id, user.tenant_id, user.role.value)
    refresh_token = create_refresh_token(user.id, user.tenant_id)

    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}


@router.post("/google", response_model=schemas.Token, status_code=status.HTTP_200_OK)
async def google_auth(data: schemas.GoogleAuthRequest, db: AsyncSession = Depends(get_db_session)):
    """
    Exchange a Google OAuth access_token for a LogistiQ JWT.

    Verification: calls Google's /userinfo endpoint (fully async via httpx).
    Flow:
      - Existing email → login  → return JWT
      - New email     → create tenant + admin user + seed demo data → return JWT
    """
    # 1. Verify the access_token by calling Google's userinfo endpoint
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {data.access_token}"},
            )
    except httpx.RequestError as exc:
        logger.error("Failed to reach Google userinfo endpoint", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not verify Google account. Please try again.",
        ) from exc

    if resp.status_code != 200:
        logger.warning("Google userinfo rejected access_token", status=resp.status_code)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Google token. Please sign in again.",
        )

    user_info = resp.json()
    google_email: str = user_info.get("email", "")
    if not google_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google account did not return an email address.",
        )
    google_name: str = user_info.get("name") or google_email.split("@")[0]

    # 2. Look up existing user
    result = await db.execute(select(models.User).where(models.User.email == google_email))
    user = result.scalar_one_or_none()

    if user:
        # ── Existing user: issue new tokens (same as /login success path) ──────
        logger.info("Google OAuth login", email=google_email, user_id=str(user.id))
        access_token = create_access_token(user.id, user.tenant_id, user.role.value)
        refresh_token = create_refresh_token(user.id, user.tenant_id)
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        }
    # ── New user: create tenant + admin user + seed demo data ────────────────
    try:
        company = data.company_name or f"{google_name}'s Workspace"
        tenant = models.Tenant(name=company)
        db.add(tenant)
        await db.flush()  # get tenant.id

        user = models.User(
            email=google_email,
            full_name=google_name,
            hashed_password=None,  # Google OAuth users have no password
            role=models.UserRole.ADMIN,
            tenant_id=tenant.id,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        # Seed demo data (skipped in TESTING mode for test isolation)
        if not settings.TESTING:
            try:
                from db.seed import (
                    create_carriers,
                    create_disruption_events,
                    create_news_alerts,
                    create_route_segments,
                    create_shipments,
                )

                carriers = await create_carriers(db, str(tenant.id))
                shipments = await create_shipments(db, str(tenant.id), carriers)
                await create_route_segments(db, shipments)
                await create_disruption_events(db, str(tenant.id))
                await create_news_alerts(db, str(tenant.id))
                logger.info("Demo data seeded for Google OAuth user", tenant_id=str(tenant.id))
            except Exception as seed_err:
                logger.warning("Failed to seed demo data (google oauth)", error=str(seed_err))

        logger.info("Google OAuth registration", email=google_email, tenant_id=str(tenant.id))
        access_token = create_access_token(user.id, tenant.id, user.role.value)
        refresh_token = create_refresh_token(user.id, tenant.id)
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        }
    except Exception as exc:
        await db.rollback()
        logger.error("Google OAuth registration failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not complete Google sign-in. Please try again.",
        ) from exc


@router.post("/refresh", response_model=schemas.Token)
async def refresh(token_data: schemas.Token):
    """Exchange a valid refresh token for a new access token"""
    payload = decode_token(token_data.refresh_token)

    if payload.type != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    # Check blacklist
    jti = payload.jti if hasattr(payload, "jti") else f"ref:{payload.user_id}"
    if await redis_client.exists(f"blacklist:{jti}"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked"
        )

    access_token = create_access_token(payload.user_id, payload.tenant_id, payload.role)
    refresh_token = create_refresh_token(payload.user_id, payload.tenant_id)

    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}


@router.post("/logout")
async def logout(token_data: schemas.Token):
    """Blacklist the refresh token"""
    try:
        payload = decode_token(token_data.refresh_token)
        jti = payload.jti if hasattr(payload, "jti") else f"ref:{payload.user_id}"

        # Blacklist for the remainder of its life (default 7 days)
        await redis_client.setex(
            f"blacklist:{jti}", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS), "revoked"
        )
        return {"message": "Successfully logged out"}
    except Exception:
        # Even if token is already invalid, we return success
        return {"message": "Successfully logged out"}


@router.get("/me", response_model=schemas.UserProfile)
async def get_me(
    user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db_session)
):
    """Get current user and tenant profile"""
    result = await db.execute(select(models.Tenant).where(models.Tenant.id == user.tenant_id))
    tenant = result.scalar_one()

    return schemas.UserProfile(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        tenant_id=user.tenant_id,
        created_at=user.created_at,
        tenant=schemas.TenantProfile(id=tenant.id, name=tenant.name, created_at=tenant.created_at),
    )
