from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import HTTPException, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Admin, Client, Host

# JWT settings
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS


def verify_google_token(token: str) -> dict:
    """
    Verify a Google ID token.

    Args:
        token: The Google ID token string

    Returns:
        Decoded token payload (contains email, name, sub/google_id, etc.)

    Raises:
        HTTPException: If token is invalid or expired
    """
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google authentication is not configured. Set GOOGLE_CLIENT_ID in .env",
        )
    try:
        idinfo = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            settings.GOOGLE_CLIENT_ID,
        )
        return idinfo
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Google token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode.update(
        {
            "exp": expire,
            "type": "access",  # Token type identifier
            "iat": datetime.now(timezone.utc),  # Issued at timestamp
        }
    )
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """
    Create JWT refresh token with longer expiration.

    Args:
        data: Dictionary containing token payload (must include 'sub' and 'role')

    Returns:
        Encoded JWT refresh token string
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode.update(
        {
            "exp": expire,
            "type": "refresh",  # Token type identifier
            "iat": datetime.now(timezone.utc),  # Issued at timestamp
        }
    )
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_password_reset_token(client_id: int) -> str:
    """Create JWT for password reset (1 hour expiry)"""
    to_encode = {
        "sub": str(client_id),
        "type": "password_reset",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_password_reset_token(token: str) -> dict:
    """Verify and decode a password reset token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "password_reset":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid token type",
            )
        return payload
    except JWTError as e:
        error_msg = str(e)
        if "expired" in error_msg.lower():
            detail = "Password reset link has expired. Please request a new one."
        else:
            detail = "Invalid or expired reset link."
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )


def verify_refresh_token(token: str) -> dict:
    """
    Verify and decode a refresh token.

    Args:
        token: The refresh token string

    Returns:
        Decoded token payload

    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        # Verify this is a refresh token
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type - expected refresh token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return payload
    except JWTError as e:
        error_msg = str(e)
        if "expired" in error_msg.lower():
            detail = "Refresh token has expired. Please login again."
        else:
            detail = f"Invalid refresh token: {error_msg}"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_host_by_email(db: AsyncSession, email: str) -> Optional[Host]:
    """Get host by email"""
    result = await db.execute(select(Host).filter(Host.email == email))
    return result.scalar_one_or_none()


async def get_client_by_email(db: AsyncSession, email: str) -> Optional[Client]:
    """Get client by email"""
    result = await db.execute(select(Client).filter(Client.email == email))
    return result.scalar_one_or_none()


async def get_admin_by_email(db: AsyncSession, email: str) -> Optional[Admin]:
    """Get admin by email"""
    result = await db.execute(select(Admin).filter(Admin.email == email))
    return result.scalar_one_or_none()
