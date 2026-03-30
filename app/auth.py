import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt, JWTError
import bcrypt
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from fastapi import Depends, HTTPException, status, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.database import get_db
from app.models import Host, Client, Admin
from app.schemas import TokenData
from app.config import settings

# JWT settings
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS

# HTTPBearer for Swagger UI token input
security = HTTPBearer()
client_security = HTTPBearer()
admin_security = HTTPBearer()


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
            settings.GOOGLE_CLIENT_ID
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
        plain_password.encode('utf-8'),
        hashed_password.encode('utf-8')
    )


def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def access_token_expires_in_seconds(token: str) -> int:
    """Seconds until JWT exp; matches the issued token (avoids API/client TTL drift)."""
    claims = jwt.get_unverified_claims(token)
    exp = claims.get("exp")
    if exp is None:
        return 0
    return max(0, int(exp) - int(time.time()))


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT access token"""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({
        "exp": expire,
        "type": "access",  # Token type identifier
        "iat": now  # Issued at timestamp
    })
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
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode.update({
        "exp": expire,
        "type": "refresh",  # Token type identifier
        "iat": now  # Issued at timestamp
    })
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_password_reset_token(client_id: int) -> str:
    """Create JWT for password reset (1 hour expiry)"""
    now = datetime.now(timezone.utc)
    to_encode = {
        "sub": str(client_id),
        "type": "password_reset",
        "exp": now + timedelta(hours=1),
        "iat": now,
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


async def get_current_host(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: AsyncSession = Depends(get_db)
) -> Host:
    """Dependency to get current authenticated host from JWT token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # Verify token role is "host"
        role = payload.get("role")
        if role != "host":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This endpoint requires host authentication",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        host_id_str = payload.get("sub")
        
        if host_id_str is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing subject (sub) claim",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Convert string to int (JWT sub claim must be a string)
        try:
            host_id = int(host_id_str)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid host ID in token",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except JWTError as e:
        error_msg = str(e)
        if "expired" in error_msg.lower() or "exp" in error_msg.lower():
            detail = "Token has expired"
        else:
            detail = f"Invalid token: {error_msg}"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Error validating token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    result = await db.execute(select(Host).filter(Host.id == host_id))
    host = result.scalar_one_or_none()
    if host is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Host not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if host is active
    if not host.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Host account is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return host


async def get_current_client(
    credentials: HTTPAuthorizationCredentials = Security(client_security),
    db: AsyncSession = Depends(get_db)
) -> Client:
    """Dependency to get current authenticated client from JWT token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # Verify token role is "client"
        role = payload.get("role")
        if role != "client":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This endpoint requires client authentication",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        client_id_str = payload.get("sub")
        
        if client_id_str is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing subject (sub) claim",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Convert string to int (JWT sub claim must be a string)
        try:
            client_id = int(client_id_str)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid client ID in token",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except JWTError as e:
        error_msg = str(e)
        if "expired" in error_msg.lower() or "exp" in error_msg.lower():
            detail = "Token has expired"
        else:
            detail = f"Invalid token: {error_msg}"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Error validating token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    result = await db.execute(
        select(Client).options(joinedload(Client.driving_license)).filter(Client.id == client_id)
    )
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Client not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if client is active
    if not client.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client account is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return client


async def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Security(admin_security),
    db: AsyncSession = Depends(get_db)
) -> Admin:
    """Dependency to get current authenticated admin from JWT token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # Verify token role is "admin"
        role = payload.get("role")
        if role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This endpoint requires admin authentication",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        admin_id_str = payload.get("sub")
        
        if admin_id_str is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing subject (sub) claim",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Convert string to int (JWT sub claim must be a string)
        try:
            admin_id = int(admin_id_str)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid admin ID in token",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except JWTError as e:
        error_msg = str(e)
        if "expired" in error_msg.lower() or "exp" in error_msg.lower():
            detail = "Token has expired"
        else:
            detail = f"Invalid token: {error_msg}"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Error validating token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    result = await db.execute(select(Admin).filter(Admin.id == admin_id))
    admin = result.scalar_one_or_none()
    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if admin is active
    if not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin account is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return admin
