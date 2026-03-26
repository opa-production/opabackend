from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Admin
from app.schemas import (
    AdminLoginRequest,
    AdminLoginResponse,
    AdminProfileResponse
)
from app.auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_admin_by_email,
    get_current_admin,
    ACCESS_TOKEN_EXPIRE_MINUTES
)

router = APIRouter()


@router.post("/admin/auth/login", response_model=AdminLoginResponse)
async def login_admin(
    request: AdminLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Login for administrators
    
    - **email**: Admin email address
    - **password**: Admin password
    
    Returns JWT access token for admin endpoints.

    """
    # Get admin by email
    admin = await get_admin_by_email(db, request.email)
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if admin is active
    if not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin account is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify password
    if not verify_password(request.password, admin.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create access token with role
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(admin.id), "role": "admin"}, expires_delta=access_token_expires
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "admin": admin
    }


@router.post("/admin/auth/logout")
async def logout_admin(current_admin: Admin = Depends(get_current_admin)):
    """
    Logout endpoint for admins
    
    Note: JWT tokens are stateless. The client should discard the token.
    """
    return {"message": "Successfully logged out"}


@router.get("/admin/me", response_model=AdminProfileResponse)
async def get_current_admin_info(current_admin: Admin = Depends(get_current_admin)):
    """
    Get current authenticated admin information
    
    Requires Bearer token authentication.
    """
    return current_admin
