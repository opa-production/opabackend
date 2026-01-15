from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Client
from app.schemas import (
    ClientRegisterRequest,
    ClientRegisterResponse,
    ClientLoginRequest,
    ClientLoginResponseWithRefresh,
    ClientProfileUpdateRequest,
    ClientProfileResponse,
    RefreshTokenRequest,
    TokenPairResponse
)
from app.auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
    get_client_by_email,
    get_current_client,
    ACCESS_TOKEN_EXPIRE_MINUTES
)

router = APIRouter()


@router.post("/client/auth/register", response_model=ClientRegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_client(
    request: ClientRegisterRequest,
    db: Session = Depends(get_db)
):
    """
    Register a new client (car renter)
    
    - **full_name**: Full name of the client
    - **email**: Email address (must be unique)
    - **password**: Password (minimum 8 characters)
    - **password_confirmation**: Password confirmation (must match password)
    """
    # Check if email already exists
    existing_client = get_client_by_email(db, request.email)
    if existing_client:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create new client
    hashed_password = get_password_hash(request.password)
    db_client = Client(
        full_name=request.full_name,
        email=request.email,
        hashed_password=hashed_password
    )
    
    db.add(db_client)
    db.commit()
    db.refresh(db_client)
    
    return db_client


@router.post("/client/auth/login", response_model=ClientLoginResponseWithRefresh)
async def login_client(
    request: ClientLoginRequest,
    db: Session = Depends(get_db)
):
    """
    Login for clients - returns access and refresh tokens
    
    - **email**: Registered email address
    - **password**: Password
    
    Returns:
    - access_token: Short-lived JWT for API access
    - refresh_token: Long-lived JWT for refreshing access tokens
    - expires_in: Access token expiration time in seconds
    - client: Client profile information
    """
    # Get client by email
    client = get_client_by_email(db, request.email)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify password
    if not verify_password(request.password, client.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create access token with role
    token_data = {"sub": str(client.id), "role": "client"}
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data=token_data, expires_delta=access_token_expires)
    
    # Create refresh token
    refresh_token = create_refresh_token(data=token_data)
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # Convert to seconds
        "client": client
    }


@router.post("/client/auth/logout")
async def logout_client(current_client: Client = Depends(get_current_client)):
    """
    Logout endpoint for clients
    
    Note: JWT tokens are stateless. In a production environment, you might want to
    implement token blacklisting. For now, this endpoint is provided for API
    consistency. The client should discard the token.
    """
    return {"message": "Successfully logged out"}


@router.post("/client/auth/refresh", response_model=TokenPairResponse)
async def refresh_client_token(
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
    
    # Verify role is client
    role = payload.get("role")
    if role != "client":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token - not a client token"
        )
    
    # Get client from database to ensure they still exist
    client_id_str = payload.get("sub")
    try:
        client_id = int(client_id_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token - malformed client ID"
        )
    
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Client no longer exists"
        )
    
    # Create new token pair
    token_data = {"sub": str(client.id), "role": "client"}
    access_token = create_access_token(data=token_data)
    refresh_token = create_refresh_token(data=token_data)
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }


@router.get("/client/me", response_model=ClientProfileResponse)
async def get_current_client_info(current_client: Client = Depends(get_current_client)):
    """
    Get current authenticated client profile information
    
    Requires Bearer token authentication.
    """
    return current_client


@router.put("/client/profile", response_model=ClientProfileResponse)
async def update_client_profile(
    request: ClientProfileUpdateRequest,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """
    Update client profile information
    
    - **bio**: Client bio/description (optional, max 2000 characters)
    - **fun_fact**: Fun fact about the client (optional, max 500 characters)
    - **mobile_number**: Mobile phone number (optional, max 50 characters)
    - **id_number**: Driver's licence, passport, or ID number (optional, max 100 characters)
    
    Updates the authenticated client's profile. All fields are optional.
    Only provided fields will be updated.
    """
    # Update only provided fields
    if request.bio is not None:
        current_client.bio = request.bio
    if request.fun_fact is not None:
        current_client.fun_fact = request.fun_fact
    if request.mobile_number is not None:
        current_client.mobile_number = request.mobile_number
    if request.id_number is not None:
        current_client.id_number = request.id_number
    
    db.commit()
    db.refresh(current_client)
    
    return current_client


# Social Auth Placeholders
# TODO: Implement "Continue with Google" integration
# @router.post("/client/auth/google")
# async def client_google_auth():
#     """Continue with Google authentication for clients"""
#     pass


# TODO: Implement "Continue with Apple" integration
# @router.post("/client/auth/apple")
# async def client_apple_auth():
#     """Continue with Apple authentication for clients"""
#     pass

