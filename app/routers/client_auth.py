from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Client, DrivingLicense, Notification
from app.schemas import (
    ClientRegisterRequest,
    ClientRegisterResponse,
    ClientLoginRequest,
    GoogleLoginRequest,
    ClientLoginResponseWithRefresh,
    ClientProfileUpdateRequest,
    ClientProfileResponse,
    RefreshTokenRequest,
    TokenPairResponse,
    DrivingLicenseRequest,
    DrivingLicenseResponse,
    ClientNotificationListResponse,
    ClientNotificationResponse
)
from app.auth import (
    get_password_hash,
    verify_password,
    verify_google_token,
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
    
    # Create welcome notification from CEO
    welcome_message = (
        f"Hey {db_client.full_name}! Welcome to Ardena. I'm Deon, the founder. "
        f"We built this platform to make car rental simple, affordable, and convenient for you. "
        f"I'm so glad you've joined our community. You're in great hands with our support team, "
        f"but I also want to make sure you have my direct line: +254702248984. "
        f"Don't hesitate to say hi or ask a question. Happy renting!"
    )
    
    welcome_notification = Notification(
        recipient_type="client",
        recipient_id=db_client.id,
        title="Welcome Message from CEO",
        message=welcome_message,
        notification_type="info",
        sender_name="Deon, CEO Ardena"
    )
    
    db.add(welcome_notification)
    db.commit()
    
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
    
    Returns complete client profile including:
    - **id**: Client ID
    - **full_name**: Full name of the client
    - **email**: Email address
    - **mobile_number**: Mobile phone number
    - **id_number**: ID number, passport, or driver's license number
    - **date_of_birth**: Date of birth (YYYY-MM-DD)
    - **gender**: Gender (e.g., 'male', 'female', 'other')
    - **bio**: Client bio/description (optional)
    - **fun_fact**: Fun fact about the client (optional)
    - **avatar_url**: Profile avatar URL (optional)
    - **id_document_url**: ID document URL (optional)
    - **license_document_url**: License document URL (optional)
    - **created_at**: Account creation timestamp
    - **updated_at**: Last update timestamp (optional)
    
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
    
    **Required Fields:**
    - **mobile_number**: Mobile phone number (required, max 50 characters)
    - **id_number**: ID number, passport, or driver's license number (required, max 100 characters)
    - **date_of_birth**: Date of birth (required, format: YYYY-MM-DD, e.g., "1990-01-15")
    - **gender**: Gender (required, max 20 characters, e.g., 'male', 'female', 'other')
    
    **Optional Fields:**
    - **bio**: Client bio/description (optional, max 2000 characters)
    - **fun_fact**: Fun fact about the client (optional, max 500 characters)
    
    Updates the authenticated client's profile. All required fields must be provided.
    Returns the updated client profile with all fields including full_name, email, and profile details.
    """
    # Update optional fields
    if request.bio is not None:
        current_client.bio = request.bio
    if request.fun_fact is not None:
        current_client.fun_fact = request.fun_fact
    
    # Update required fields (always provided)
    current_client.mobile_number = request.mobile_number
    current_client.id_number = request.id_number
    current_client.date_of_birth = request.date_of_birth
    current_client.gender = request.gender
    
    db.commit()
    db.refresh(current_client)
    
    return current_client


# ==================== DRIVING LICENSE ENDPOINTS ====================

@router.post("/client/driving-license", response_model=DrivingLicenseResponse, status_code=status.HTTP_201_CREATED)
async def add_driving_license(
    request: DrivingLicenseRequest,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """
    Add driving license information for the authenticated client
    
    - **license_number**: License number (mix of letters and numbers, 5-50 characters)
    - **category**: License category (one letter + number, e.g., B1, C2, D1)
    - **issue_date**: License issue date (YYYY-MM-DD)
    - **expiry_date**: License expiry date (YYYY-MM-DD, must be ~3 years from issue date)
    
    Validates according to Kenyan driving license system:
    - License expires 3 years from issue date
    - Category format: one letter followed by numbers
    - License number must contain both letters and numbers
    """
    # Check if client already has a license
    existing_license = db.query(DrivingLicense).filter(
        DrivingLicense.client_id == current_client.id
    ).first()
    
    if existing_license:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Driving license already exists. Use PUT /client/driving-license to update."
        )
    
    # Check if license number already exists (belongs to another client)
    license_number_exists = db.query(DrivingLicense).filter(
        DrivingLicense.license_number == request.license_number,
        DrivingLicense.client_id != current_client.id
    ).first()
    
    if license_number_exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This license number is already registered to another account"
        )
    
    # Create new driving license
    db_license = DrivingLicense(
        client_id=current_client.id,
        license_number=request.license_number.upper().replace(' ', ''),  # Normalize: uppercase, no spaces
        category=request.category,
        issue_date=request.issue_date,
        expiry_date=request.expiry_date,
        is_verified=False  # Requires admin verification
    )
    
    db.add(db_license)
    db.commit()
    db.refresh(db_license)
    
    return db_license


@router.put("/client/driving-license", response_model=DrivingLicenseResponse)
async def update_driving_license(
    request: DrivingLicenseRequest,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """
    Update driving license information for the authenticated client
    
    - **license_number**: License number (mix of letters and numbers, 5-50 characters)
    - **category**: License category (one letter + number, e.g., B1, C2, D1)
    - **issue_date**: License issue date (YYYY-MM-DD)
    - **expiry_date**: License expiry date (YYYY-MM-DD, must be ~3 years from issue date)
    
    Validates according to Kenyan driving license system.
    Note: Updating license information will reset verification status.
    """
    # Get existing license
    db_license = db.query(DrivingLicense).filter(
        DrivingLicense.client_id == current_client.id
    ).first()
    
    if not db_license:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No driving license found. Use POST /client/driving-license to add one."
        )
    
    # Check if license number is being changed and if new number exists
    new_license_number = request.license_number.upper().replace(' ', '')
    if new_license_number != db_license.license_number:
        license_number_exists = db.query(DrivingLicense).filter(
            DrivingLicense.license_number == new_license_number,
            DrivingLicense.client_id != current_client.id
        ).first()
        
        if license_number_exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This license number is already registered to another account"
            )
    
    # Update license information
    db_license.license_number = new_license_number
    db_license.category = request.category
    db_license.issue_date = request.issue_date
    db_license.expiry_date = request.expiry_date
    db_license.is_verified = False  # Reset verification when updated
    db_license.verification_notes = None
    
    db.commit()
    db.refresh(db_license)
    
    return db_license


@router.get("/client/driving-license", response_model=DrivingLicenseResponse)
async def get_driving_license(
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """
    Get driving license information for the authenticated client
    """
    db_license = db.query(DrivingLicense).filter(
        DrivingLicense.client_id == current_client.id
    ).first()
    
    if not db_license:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No driving license found"
        )
    
    return db_license


@router.delete("/client/driving-license")
async def delete_driving_license(
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """
    Delete driving license information for the authenticated client
    """
    db_license = db.query(DrivingLicense).filter(
        DrivingLicense.client_id == current_client.id
    ).first()
    
    if not db_license:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No driving license found"
        )
    
    db.delete(db_license)
    db.commit()
    
    return {"message": "Driving license deleted successfully"}


@router.post("/client/auth/google", response_model=ClientLoginResponseWithRefresh)
async def client_google_auth(
    request: GoogleLoginRequest,
    db: Session = Depends(get_db)
):
    """
    Continue with Google authentication for clients.
    
    If the user doesn't exist, a new account is created.
    If the user exists but hasn't linked Google, it will be linked if the email matches.
    
    Returns:
    - access_token: Short-lived JWT for API access
    - refresh_token: Long-lived JWT for refreshing access tokens
    - expires_in: Access token expiration time in seconds
    - client: Client profile information
    """
    # Verify Google token
    idinfo = verify_google_token(request.id_token)
    
    google_id = idinfo['sub']
    email = idinfo['email']
    full_name = idinfo.get('name', '')
    avatar_url = idinfo.get('picture')

    # 1. Try to find by google_id
    client = db.query(Client).filter(Client.google_id == google_id).first()
    
    if not client:
        # 2. Try to find by email
        client = db.query(Client).filter(Client.email == email).first()
        
        if client:
            # Link Google account to existing email account
            client.google_id = google_id
            if not client.avatar_url and avatar_url:
                client.avatar_url = avatar_url
            db.commit()
        else:
            # 3. Create new client
            client = Client(
                full_name=full_name,
                email=email,
                google_id=google_id,
                avatar_url=avatar_url,
                is_active=True
            )
            db.add(client)
            db.commit()
            db.refresh(client)
            
            # Create welcome notification from CEO
            welcome_message = (
                f"Hey {client.full_name}! Welcome to Ardena. I'm Deon, the founder. "
                f"We built this platform to make car rental simple, affordable, and convenient for you. "
                f"I'm so glad you've joined our community. You're in great hands with our support team, "
                f"but I also want to make sure you have my direct line: +254702248984. "
                f"Don't hesitate to say hi or ask a question. Happy renting!"
            )
            
            welcome_notification = Notification(
                recipient_type="client",
                recipient_id=client.id,
                title="Welcome Message from CEO",
                message=welcome_message,
                notification_type="info",
                sender_name="Deon, CEO Ardena"
            )
            db.add(welcome_notification)
            db.commit()

    if not client.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive"
        )

    # Create tokens
    token_data = {"sub": str(client.id), "role": "client"}
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data=token_data, expires_delta=access_token_expires)
    refresh_token = create_refresh_token(data=token_data)
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "client": client
    }


# TODO: Implement "Continue with Apple" integration
# @router.post("/client/auth/apple")
# async def client_apple_auth():
#     """Continue with Apple authentication for clients"""
#     pass


# ==================== NOTIFICATION ENDPOINTS ====================

@router.get("/client/notifications", response_model=ClientNotificationListResponse)
async def get_client_notifications(
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """
    Get all notifications for the authenticated client
    
    Returns all admin notifications sent to this client, ordered by creation date (newest first).
    Includes unread count.
    """
    # Get all notifications for this client
    notifications = db.query(Notification).filter(
        Notification.recipient_type == "client",
        Notification.recipient_id == current_client.id
    ).order_by(Notification.created_at.desc()).all()
    
    # Count unread notifications
    unread_count = db.query(Notification).filter(
        Notification.recipient_type == "client",
        Notification.recipient_id == current_client.id,
        Notification.is_read == False
    ).count()
    
    # Build response
    notification_list = [ClientNotificationResponse(
        id=notification.id,
        title=notification.title,
        message=notification.message,
        notification_type=notification.notification_type,
        sender_name=notification.sender_name,
        is_read=notification.is_read,
        created_at=notification.created_at
    ) for notification in notifications]
    
    return ClientNotificationListResponse(
        notifications=notification_list,
        total=len(notification_list),
        unread_count=unread_count
    )


@router.put("/client/notifications/{notification_id}/read")
async def mark_client_notification_as_read(
    notification_id: int,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """
    Mark a notification as read
    
    - **notification_id**: ID of the notification to mark as read
    """
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.recipient_type == "client",
        Notification.recipient_id == current_client.id
    ).first()
    
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )
    
    notification.is_read = True
    db.commit()
    
    return {"message": "Notification marked as read"}

