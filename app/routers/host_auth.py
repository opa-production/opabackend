from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Host
from app.schemas import (
    HostRegisterRequest,
    HostRegisterResponse,
    HostLoginRequest,
    HostLoginResponseWithRefresh,
    HostProfileUpdateRequest,
    HostProfileResponse,
    RefreshTokenRequest,
    TokenPairResponse
)
from app.auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
    get_host_by_email,
    get_current_host,
    ACCESS_TOKEN_EXPIRE_MINUTES
)

router = APIRouter()


@router.post("/host/auth/register", response_model=HostRegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_host(
    request: HostRegisterRequest,
    db: Session = Depends(get_db)
):
    """
    Register a new host (car owner)
    
    - **full_name**: Full name of the host
    - **email**: Email address (must be unique)
    - **password**: Password (minimum 8 characters)
    - **password_confirmation**: Password confirmation (must match password)
    """
    # Check if email already exists
    existing_host = get_host_by_email(db, request.email)
    if existing_host:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create new host
    hashed_password = get_password_hash(request.password)
    db_host = Host(
        full_name=request.full_name,
        email=request.email,
        hashed_password=hashed_password
    )
    
    db.add(db_host)
    db.commit()
    db.refresh(db_host)
    
    return db_host


@router.post("/host/auth/login", response_model=HostLoginResponseWithRefresh)
async def login_host(
    request: HostLoginRequest,
    db: Session = Depends(get_db)
):
    """
    Login for hosts - returns access and refresh tokens
    
    - **email**: Registered email address
    - **password**: Password
    
    Returns:
    - access_token: Short-lived JWT for API access
    - refresh_token: Long-lived JWT for refreshing access tokens
    - expires_in: Access token expiration time in seconds
    - host: Host profile information
    """
    # Get host by email
    host = get_host_by_email(db, request.email)
    if not host:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify password
    if not verify_password(request.password, host.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create access token with role
    token_data = {"sub": str(host.id), "role": "host"}
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data=token_data, expires_delta=access_token_expires)
    
    # Create refresh token
    refresh_token = create_refresh_token(data=token_data)
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # Convert to seconds
        "host": host
    }


@router.post("/host/auth/logout")
async def logout_host(current_host: Host = Depends(get_current_host)):
    """
    Logout endpoint for hosts
    
    Note: JWT tokens are stateless. In a production environment, you might want to
    implement token blacklisting. For now, this endpoint is provided for API
    consistency. The client should discard the token.
    """
    return {"message": "Successfully logged out"}


@router.post("/host/auth/refresh", response_model=TokenPairResponse)
async def refresh_host_token(
    request: RefreshTokenRequest,
    db: Session = Depends(get_db)
):
    """
    Refresh access token using refresh token
    
    - **refresh_token**: Valid refresh token obtained during login
    
    Returns new access and refresh tokens. The old refresh token is invalidated.
    """
    # Verify the refresh token
    payload = verify_refresh_token(request.refresh_token)
    
    # Verify role is host
    role = payload.get("role")
    if role != "host":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token - not a host token"
        )
    
    # Get host from database to ensure they still exist
    host_id_str = payload.get("sub")
    try:
        host_id = int(host_id_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token - malformed host ID"
        )
    
    host = db.query(Host).filter(Host.id == host_id).first()
    if not host:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Host no longer exists"
        )
    
    # Create new token pair
    token_data = {"sub": str(host.id), "role": "host"}
    access_token = create_access_token(data=token_data)
    refresh_token = create_refresh_token(data=token_data)
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }


@router.get("/host/me", response_model=HostProfileResponse)
async def get_current_host_info(current_host: Host = Depends(get_current_host)):
    """
    Get current authenticated host information
    
    Requires Bearer token authentication.
    """
    return current_host


@router.put("/host/profile", response_model=HostProfileResponse)
async def update_host_profile(
    request: HostProfileUpdateRequest,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db)
):
    """
    Update host profile information
    
    - **bio**: Host bio/description (optional, max 2000 characters)
    - **mobile_number**: Mobile phone number (optional, max 50 characters)
    - **id_number**: ID number, passport number, or driver's license number (optional, max 100 characters)
    
    Updates the authenticated host's profile. All fields are optional.
    Only provided fields will be updated.
    """
    # Update only provided fields
    if request.bio is not None:
        current_host.bio = request.bio
    if request.mobile_number is not None:
        current_host.mobile_number = request.mobile_number
    if request.id_number is not None:
        current_host.id_number = request.id_number
    
    db.commit()
    db.refresh(current_host)
    
    return current_host


# Social Auth Placeholders
# TODO: Implement "Continue with Google" integration
# @router.post("/host/auth/google")
# async def host_google_auth():
#     """Continue with Google authentication for hosts"""
#     pass


# TODO: Implement "Continue with Apple" integration
# @router.post("/host/auth/apple")
# async def host_apple_auth():
#     """Continue with Apple authentication for hosts"""
#     pass


