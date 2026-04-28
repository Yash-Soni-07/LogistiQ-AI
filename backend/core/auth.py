import bcrypt
from datetime import datetime, timedelta
from typing import Optional, Any, Union
from jose import jwt, JWTError
from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import structlog

from core.config import settings
from core.exceptions import ForbiddenError, UnauthorizedError
from core.schemas import TokenPayload
from db.models import User, UserRole
from db.database import get_db_session
from core.redis import redis_client

logger = structlog.get_logger(__name__)
security = HTTPBearer(auto_error=False)

def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash"""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), 
        hashed_password.encode("utf-8")
    )

def create_access_token(
    user_id: str, 
    tenant_id: str, 
    role: str, 
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create a JWT access token"""
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {
        "user_id": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role,
        "exp": expire,
        "type": "access"
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def create_refresh_token(
    user_id: str, 
    tenant_id: str, 
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create a JWT refresh token"""
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    
    to_encode = {
        "user_id": str(user_id),
        "tenant_id": str(tenant_id),
        "exp": expire,
        "type": "refresh"
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def decode_token(token: str) -> TokenPayload:
    """Decode and validate a JWT token. Raises UnauthorizedError on failure."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return TokenPayload(**payload)
    except JWTError as exc:
        logger.warning("token.decode_failed", error=str(exc))
        raise UnauthorizedError("Could not validate credentials") from exc
    except Exception as exc:
        logger.warning("token.decode_unexpected", error=str(exc))
        raise UnauthorizedError("Invalid token") from exc

async def get_current_user(
    token: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db_session)
) -> User:
    """FastAPI dependency to get the current authenticated user."""
    if token is None:
        raise ForbiddenError("Authentication credentials were not provided")
    payload = decode_token(token.credentials)

    result = await db.execute(select(User).where(User.id == payload.user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise UnauthorizedError("User not found")

    if not getattr(user, "is_active", True):  # is_active may be absent in older schema
        raise UnauthorizedError("Account is deactivated")

    return user

def require_role(required_role: UserRole):
    """FastAPI dependency factory to enforce RBAC."""
    async def role_checker(user: User = Depends(get_current_user)) -> User:
        # ADMIN bypasses all role checks
        if user.role == UserRole.ADMIN.value or user.role == UserRole.ADMIN:
            return user

        user_role_val = user.role.value if isinstance(user.role, UserRole) else user.role
        required_role_val = required_role.value if isinstance(required_role, UserRole) else required_role

        if user_role_val != required_role_val:
            logger.warning(
                "role.check_failed",
                user_id=user.id,
                required=required_role_val,
                actual=user_role_val,
            )
            raise ForbiddenError(
                f"Role '{required_role_val}' required",
                required_role=required_role_val,
            )
        return user
    return role_checker