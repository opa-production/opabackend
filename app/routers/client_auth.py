import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.database import get_db
from app.models import (
    Client,
    DrivingLicense,
    Notification,
    ClientBiometricToken,
    Booking,
    BookingStatus,
    BookingExtensionRequest,
    ClientKyc,
    ClientFeedback,
    ClientHostConversation,
    PaymentMethod,
    HostRating,
    ClientRating,
)
from app.config import settings
from app.schemas import (
    ClientRegisterRequest,
    ClientRegisterResponse,
    ClientLoginRequest,
    GoogleLoginRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    ClientChangePasswordRequest,
    ClientLoginResponseWithRefresh,
    ClientProfileUpdateRequest,
    ClientProfileResponse,
    RefreshTokenRequest,
    TokenPairResponse,
    DrivingLicenseRequest,
    DrivingLicenseResponse,
    ClientNotificationListResponse,
    ClientNotificationResponse,
    BiometricLoginRequest,
    BiometricRevokeRequest,
    NotificationToggleRequest,
)
from app.auth import (
    get_password_hash,
    verify_password,
    verify_google_token,
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
    create_password_reset_token,
    verify_password_reset_token,
    get_client_by_email,
    get_current_client,
    access_token_expires_in_seconds,
)
from app.services.email_welcome import (
    send_welcome_email_client,
    send_email,
    send_email_with_attachment,
    send_forgotpassword_email,
)
from app.services.client_data_export import build_client_data_pdf

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


async def _ensure_client_terms_accepted(db: AsyncSession, client: Client) -> None:
    """Set terms_accepted_at for legacy accounts; registration/Google set it on create."""
    if client.terms_accepted_at is not None:
        return
    client.terms_accepted_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(client)


@router.post("/client/auth/register", response_model=ClientRegisterResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register_client(
    request: Request,
    body: ClientRegisterRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Register a new client (car renter)
    
    - **full_name**: Full name of the client
    - **email**: Email address (must be unique)
    - **password**: Password (minimum 8 characters)
    - **password_confirmation**: Password confirmation (must match password)
    """
    # Check if email already exists
    existing_client = await get_client_by_email(db, body.email)
    if existing_client:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create new client
    hashed_password = get_password_hash(body.password)
    db_client = Client(
        full_name=body.full_name,
        email=body.email,
        hashed_password=hashed_password,
        terms_accepted_at=datetime.now(timezone.utc),
    )
    
    db.add(db_client)
    await db.commit()
    await db.refresh(db_client)
    
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
    await db.commit()

    # Send welcome email (non-blocking; registration succeeds even if email fails)
    background_tasks.add_task(send_welcome_email_client, db_client.email, db_client.full_name)

    # Create Ardena Pay (Stellar) wallet for new client (testnet-funded). If it fails, client can POST /client/wallet later.
    try:
        from app.models import ClientWallet
        from app.services.stellar_wallet import create_and_fund_wallet, _is_testnet
        result = create_and_fund_wallet()
        if result:
            public_key, secret_key = result
            network = "testnet" if _is_testnet() else "mainnet"
            wallet = ClientWallet(
                client_id=db_client.id,
                network=network,
                stellar_public_key=public_key,
                stellar_secret_encrypted=secret_key,
            )
            db.add(wallet)
            await db.commit()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Ardena Pay wallet creation failed for new client: %s", e)

    return db_client


@router.post("/client/auth/login", response_model=ClientLoginResponseWithRefresh)
@limiter.limit("10/minute")
async def login_client(
    request: Request,
    body: ClientLoginRequest,
    db: AsyncSession = Depends(get_db)
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
    client = await get_client_by_email(db, body.email)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify password
    if not verify_password(body.password, client.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    await _ensure_client_terms_accepted(db, client)
    
    # Create access token with role
    token_data = {"sub": str(client.id), "role": "client"}
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data=token_data, expires_delta=access_token_expires)
    
    # Create refresh token
    refresh_token = create_refresh_token(data=token_data)

    # Optionally issue a device token for biometric login (one-time reveal)
    device_token_raw = None
    if getattr(body, "enable_biometrics", False):
        device_token_raw = secrets.token_urlsafe(32)
        device_token_hash = hashlib.sha256(device_token_raw.encode("utf-8")).hexdigest()

        db_token = ClientBiometricToken(
            client_id=client.id,
            device_token_hash=device_token_hash,
            device_name=getattr(body, "device_name", None),
        )
        db.add(db_token)
        await db.commit()
        await db.refresh(client)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": access_token_expires_in_seconds(access_token),
        "client": client,
        "device_token": device_token_raw,
    }


@router.post("/client/auth/forgot-password")
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Request a password reset email.
    
    If the email exists, sends a reset link. Always returns success to prevent
    email enumeration. The link expires in 1 hour.
    
    - **email**: Registered email address
    """
    client = await get_client_by_email(db, body.email)
    if not client:
        # Don't reveal if email exists - same response for both cases
        return {"message": "If an account exists with this email, you will receive a password reset link."}

    if not settings.RESEND_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email service is not configured. Please try again later.",
        )

    reset_token = create_password_reset_token(client.id)
    # Prefer dedicated web reset page for clients when set (e.g. https://ardena.co.ke/reset-password.html)
    web_url = (getattr(settings, "CLIENT_PASSWORD_RESET_WEB_URL", None) or "").strip()
    if web_url:
        # Preserve existing query params on the page and append token correctly
        sep = "&" if "?" in web_url else "?"
        reset_link = f"{web_url.rstrip('/')}{sep}token={reset_token}"
    else:
        # Fallback to generic base URL or deep link logic (same as before)
        base_url = (settings.PASSWORD_RESET_LINK_BASE_URL or settings.FRONTEND_URL or "https://ardena.co.ke").strip()
        # Deep link (e.g. ardenahost://) must stay as-is: ardenahost://reset-password?token=...
        if base_url.endswith("://"):
            reset_link = f"{base_url}reset-password?token={reset_token}"
        else:
            reset_link = f"{base_url.rstrip('/')}/reset-password?token={reset_token}"

    background_tasks.add_task(send_forgotpassword_email, client.email, client.full_name, reset_link)

    return {"message": "If an account exists with this email, you will receive a password reset link."}


@router.post("/client/auth/reset-password")
async def reset_password(
    request: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Reset password using the token from the forgot-password email.
    
    - **token**: Reset token from the email link
    - **new_password**: New password (min 8 characters)
    - **new_password_confirmation**: Must match new_password
    """
    payload = verify_password_reset_token(request.token)
    client_id = int(payload["sub"])

    result = await db.execute(select(Client).filter(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset link.",
        )

    client.hashed_password = get_password_hash(request.new_password)
    await db.commit()
    await db.refresh(client)

    return {"message": "Password has been reset successfully. You can now log in with your new password."}


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
    db: AsyncSession = Depends(get_db)
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
    
    result = await db.execute(select(Client).filter(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Client no longer exists"
        )

    await _ensure_client_terms_accepted(db, client)
    
    # Create new token pair
    token_data = {"sub": str(client.id), "role": "client"}
    access_token = create_access_token(data=token_data)
    refresh_token = create_refresh_token(data=token_data)
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": access_token_expires_in_seconds(access_token),
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


@router.post("/client/terms/accept", response_model=ClientProfileResponse)
async def accept_terms_client(
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Record that the authenticated client has accepted the terms and conditions.
    Call this when the user checks the T&C checkbox. Status is stored so you do not prompt again.
    """
    current_client.terms_accepted_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(current_client)
    return current_client


@router.put("/client/profile", response_model=ClientProfileResponse)
async def update_client_profile(
    request: ClientProfileUpdateRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db)
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
    
    await db.commit()
    return current_client


@router.put("/client/change-password")
async def change_password(
    request: ClientChangePasswordRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db)
):
    """
    Change client password (when logged in).
    
    Requires current password verification.
    
    - **current_password**: Current password
    - **new_password**: New password (min 8 characters)
    - **new_password_confirmation**: Must match new_password
    """
    # Verify current password
    if not verify_password(request.current_password, current_client.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )
    
    # Update password
    current_client.hashed_password = get_password_hash(request.new_password)
    await db.commit()
    
    return {"message": "Password changed successfully"}


@router.post("/client/notifications/email", response_model=ClientProfileResponse)
async def update_email_notifications(
    request: NotificationToggleRequest,
    background_tasks: BackgroundTasks,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Toggle email notifications for the authenticated client.

    When turned **on**, a confirmation email is sent informing them that they
    will now receive email notifications at their registered email address.
    """
    previous = getattr(current_client, "email_notifications_enabled", True)
    current_client.email_notifications_enabled = bool(request.enabled)
    await db.commit()
    await db.refresh(current_client)

    # Only send a confirmation email when toggled from OFF to ON
    if request.enabled and not previous and settings.RESEND_API_KEY:
        first_name = (
            current_client.full_name.split()[0] if current_client.full_name else "there"
        )
        subject = "Email notifications enabled on Ardena"
        html_body = f"""
        <div style="font-family: sans-serif; max-width: 560px; margin: 0 auto;">
          <p>Dear {first_name},</p>
          <p>This is a quick confirmation that you have <strong>enabled email notifications</strong> for your Ardena account.</p>
          <p>You will now start receiving important updates and notifications at this email address.</p>
          <p>You can turn this off at any time from your notification preferences in the app.</p>
          <p style="margin-top: 24px;">With appreciation,<br><strong>The Ardena Group Team</strong></p>
        </div>
        """
        background_tasks.add_task(
            send_email,
            current_client.email,
            subject,
            html_body,
        )

    return current_client


@router.post("/client/notifications/in-app", response_model=ClientProfileResponse)
async def update_in_app_notifications(
    request: NotificationToggleRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Toggle in-app notifications for the authenticated client.

    When turned **on**, a confirmation notification is created and will appear
    in the client's Notifications page inside the app.
    """
    previous = getattr(current_client, "in_app_notifications_enabled", True)
    current_client.in_app_notifications_enabled = bool(request.enabled)
    await db.commit()
    await db.refresh(current_client)

    # Only create an in-app notification when toggled from OFF to ON
    if request.enabled and not previous:
        notif = Notification(
            recipient_type="client",
            recipient_id=current_client.id,
            title="In-app notifications enabled",
            message=(
                "You have turned on in-app notifications. "
                "You will now see important updates on your Notifications page in the Ardena app."
            ),
            notification_type="info",
            sender_name="The Ardena Group Team",
        )
        db.add(notif)
        await db.commit()

    return current_client


@router.post("/client/account/export-data")
async def export_client_data(
    background_tasks: BackgroundTasks,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a PDF export of all data we store for the authenticated client
    and email it to the address they used to register.

    The PDF is generated on the server and sent as an email attachment from
    the standard Ardena Group team address.
    """
    if not settings.RESEND_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email service is not configured. Please try again later.",
        )

    # Collect related data for this client
    result = await db.execute(
        select(Booking)
        .filter(Booking.client_id == current_client.id)
        .order_by(Booking.created_at.desc())
    )
    bookings = result.scalars().all()

    result = await db.execute(
        select(DrivingLicense)
        .filter(DrivingLicense.client_id == current_client.id)
    )
    driving_license = result.scalar_one_or_none()

    result = await db.execute(
        select(ClientKyc)
        .filter(ClientKyc.client_id == current_client.id)
        .order_by(ClientKyc.created_at.desc())
    )
    latest_kyc = result.scalars().first()

    result = await db.execute(
        select(PaymentMethod)
        .filter(PaymentMethod.client_id == current_client.id)
    )
    payment_methods = result.scalars().all()

    result = await db.execute(
        select(ClientRating)
        .filter(ClientRating.client_id == current_client.id)
    )
    ratings_from_hosts = result.scalars().all()

    result = await db.execute(
        select(HostRating)
        .filter(HostRating.client_id == current_client.id)
    )
    ratings_given_to_hosts = result.scalars().all()

    pdf_bytes = build_client_data_pdf(
        client=current_client,
        bookings=bookings,
        driving_license=driving_license,
        latest_kyc=latest_kyc,
        payment_methods=payment_methods,
        ratings_from_hosts=ratings_from_hosts,
        ratings_given_to_hosts=ratings_given_to_hosts,
    )

    filename = f"ardena-client-data-{current_client.id}.pdf"

    subject = "Your Ardena data export"
    first_name = current_client.full_name.split()[0] if current_client.full_name else "there"
    html_body = f"""
    <div style="font-family: sans-serif; max-width: 560px; margin: 0 auto;">
      <p>Dear {first_name},</p>
      <p>As requested, we have generated a PDF export of the key information we store for your Ardena account.</p>
      <p>The document attached includes your account details, profile information, verification status, driving licence (if provided),
      saved payment methods, booking history, and ratings summary.</p>
      <p>If you see anything that looks incorrect or have questions about your data, you can reply to this email and our team will help.</p>
      <p style="margin-top: 24px;">Warm regards,<br><strong>The Ardena Group Team</strong></p>
    </div>
    """

    # Send email in the background so the API call returns quickly
    background_tasks.add_task(
        send_email_with_attachment,
        current_client.email,
        subject,
        html_body,
        pdf_bytes,
        filename,
    )

    return {
        "message": "Your data export is being generated and will be sent to your email address shortly."
    }


@router.delete("/client/account", status_code=status.HTTP_200_OK)
async def delete_own_account(
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Permanently delete the authenticated client's account.

    Deletion is **blocked** if any of the following would jeopardise operations:
    - An active booking (pending, confirmed, or active)
    - A booking extension that is pending host approval or host-approved (not yet paid/expired/rejected)

    The client must complete, cancel, or let such bookings/extensions resolve before deleting.
    """
    client_id = current_client.id

    # Block if any booking is still "in progress" (pending, confirmed, or active)
    result = await db.execute(
        select(Booking)
        .filter(
            Booking.client_id == client_id,
            Booking.status.in_([
                BookingStatus.PENDING,
                BookingStatus.CONFIRMED,
                BookingStatus.ACTIVE,
            ]),
        )
    )
    active_booking = result.scalar_one_or_none()
    if active_booking:
        bid = getattr(active_booking, "booking_id", None) or ""
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "You cannot delete your account while you have an active booking. "
                "Please complete or cancel the booking first."
                + (f" (Booking: {bid})" if bid else "")
            ),
        )

    # Block if any extension request is still pending or host-approved (not yet paid/expired/rejected)
    result = await db.execute(
        select(BookingExtensionRequest)
        .filter(
            BookingExtensionRequest.client_id == client_id,
            BookingExtensionRequest.status.in_([
                "pending_host_approval",
                "host_approved",
            ]),
        )
    )
    active_extension = result.scalar_one_or_none()
    if active_extension:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "You cannot delete your account while you have a booking extension in progress. "
                "Please wait for it to be paid, expired, or rejected, or cancel it first."
            ),
        )

    # Delete records that reference client but have no cascade from Client (to avoid FK errors / orphan data)
    await db.execute(delete(BookingExtensionRequest).filter(BookingExtensionRequest.client_id == client_id))
    await db.execute(delete(ClientHostConversation).filter(ClientHostConversation.client_id == client_id))
    await db.execute(delete(ClientFeedback).filter(ClientFeedback.client_id == client_id))
    await db.execute(delete(Notification).filter(
        Notification.recipient_type == "client",
        Notification.recipient_id == client_id,
    ))

    # Delete the client (cascades: bookings, payments, payment_methods, driving_license, client_kycs, biometric_tokens, host_ratings, client_ratings)
    storage_uuid = current_client.storage_uuid
    await db.delete(current_client)
    await db.commit()

    # Clean up Supabase storage so recycled IDs never inherit old files
    from app.storage import delete_user_storage_folder, BUCKETS
    for folder in filter(None, [str(client_id), storage_uuid]):
        await delete_user_storage_folder(BUCKETS["client_profile"], folder)
        await delete_user_storage_folder(BUCKETS["client_documents"], folder)

    return {"message": "Your account has been permanently deleted."}


# ==================== DRIVING LICENSE ENDPOINTS ====================

@router.post("/client/driving-license", response_model=DrivingLicenseResponse, status_code=status.HTTP_201_CREATED)
async def add_driving_license(
    request: DrivingLicenseRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db)
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
    result = await db.execute(
        select(DrivingLicense).filter(DrivingLicense.client_id == current_client.id)
    )
    existing_license = result.scalar_one_or_none()
    
    if existing_license:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Driving license already exists. Use PUT /client/driving-license to update."
        )
    
    # Check if license number already exists (belongs to another client)
    result = await db.execute(
        select(DrivingLicense).filter(
            DrivingLicense.license_number == request.license_number,
            DrivingLicense.client_id != current_client.id
        )
    )
    license_number_exists = result.scalar_one_or_none()
    
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
    await db.commit()
    await db.refresh(db_license)
    
    return db_license


@router.put("/client/driving-license", response_model=DrivingLicenseResponse)
async def update_driving_license(
    request: DrivingLicenseRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db)
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
    result = await db.execute(
        select(DrivingLicense).filter(DrivingLicense.client_id == current_client.id)
    )
    db_license = result.scalar_one_or_none()
    
    if not db_license:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No driving license found. Use POST /client/driving-license to add one."
        )
    
    # Check if license number is being changed and if new number exists
    new_license_number = request.license_number.upper().replace(' ', '')
    if new_license_number != db_license.license_number:
        result = await db.execute(
            select(DrivingLicense).filter(
                DrivingLicense.license_number == new_license_number,
                DrivingLicense.client_id != current_client.id
            )
        )
        license_number_exists = result.scalar_one_or_none()
        
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
    
    await db.commit()
    await db.refresh(db_license)
    
    return db_license


@router.get("/client/driving-license", response_model=DrivingLicenseResponse)
async def get_driving_license(
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db)
):
    """
    Get driving license information for the authenticated client
    """
    result = await db.execute(
        select(DrivingLicense).filter(DrivingLicense.client_id == current_client.id)
    )
    db_license = result.scalar_one_or_none()
    
    if not db_license:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No driving license found"
        )
    
    return db_license


@router.delete("/client/driving-license")
async def delete_driving_license(
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete driving license information for the authenticated client
    """
    result = await db.execute(
        select(DrivingLicense).filter(DrivingLicense.client_id == current_client.id)
    )
    db_license = result.scalar_one_or_none()
    
    if not db_license:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No driving license found"
        )
    
    await db.delete(db_license)
    await db.commit()
    
    return {"message": "Driving license deleted successfully"}


@router.post("/client/auth/google", response_model=ClientLoginResponseWithRefresh)
async def client_google_auth(
    request: GoogleLoginRequest,
    db: AsyncSession = Depends(get_db)
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
    result = await db.execute(select(Client).filter(Client.google_id == google_id))
    client = result.scalar_one_or_none()
    
    if not client:
        # 2. Try to find by email
        result = await db.execute(select(Client).filter(Client.email == email))
        client = result.scalar_one_or_none()
        
        if client:
            # Link Google account to existing email account
            client.google_id = google_id
            if not client.avatar_url and avatar_url:
                client.avatar_url = avatar_url
            await db.commit()
        else:
            # 3. Create new client
            client = Client(
                full_name=full_name,
                email=email,
                hashed_password=get_password_hash(secrets.token_urlsafe(32)),
                google_id=google_id,
                avatar_url=avatar_url,
                is_active=True,
                terms_accepted_at=datetime.now(timezone.utc),
            )
            db.add(client)
            await db.commit()
            await db.refresh(client)
            
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
            await db.commit()

    if not client.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive"
        )

    await _ensure_client_terms_accepted(db, client)

    # Create tokens
    token_data = {"sub": str(client.id), "role": "client"}
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data=token_data, expires_delta=access_token_expires)
    refresh_token = create_refresh_token(data=token_data)

    # Optionally issue a device token for biometric login (one-time reveal)
    device_token_raw = None
    if getattr(request, "enable_biometrics", False):
        device_token_raw = secrets.token_urlsafe(32)
        device_token_hash = hashlib.sha256(device_token_raw.encode("utf-8")).hexdigest()

        db_token = ClientBiometricToken(
            client_id=client.id,
            device_token_hash=device_token_hash,
            device_name=getattr(request, "device_name", None),
        )
        db.add(db_token)
        await db.commit()
        await db.refresh(client)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": access_token_expires_in_seconds(access_token),
        "client": client,
        "device_token": device_token_raw,
    }


@router.post("/client/auth/biometric-login", response_model=ClientLoginResponseWithRefresh)
async def biometric_login(
    request: BiometricLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Login using a previously issued device token (for biometric unlock).

    The mobile app should:
    - Store device_token in secure local storage after initial login + biometric setup
    - On successful local biometric auth, call this endpoint with the stored device_token
    """
    if not request.device_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="device_token is required",
        )

    device_hash = hashlib.sha256(request.device_token.encode("utf-8")).hexdigest()

    result = await db.execute(
        select(ClientBiometricToken)
        .filter(
            ClientBiometricToken.device_token_hash == device_hash,
            ClientBiometricToken.revoked == False,
        )
    )
    db_token = result.scalar_one_or_none()

    if not db_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked device token",
        )

    result = await db.execute(select(Client).filter(Client.id == db_token.client_id))
    client = result.scalar_one_or_none()
    if not client or not client.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Client not found or inactive",
        )

    # Update last_used_at for auditing; backfill terms for legacy accounts
    now = datetime.now(timezone.utc)
    db_token.last_used_at = now
    if client.terms_accepted_at is None:
        client.terms_accepted_at = now
    await db.commit()
    await db.refresh(client)

    token_data = {"sub": str(client.id), "role": "client"}
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data=token_data, expires_delta=access_token_expires)
    refresh_token = create_refresh_token(data=token_data)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": access_token_expires_in_seconds(access_token),
        "client": client,
        "device_token": None,  # Never issue a new device token here
    }


@router.post("/client/auth/biometric-revoke")
async def revoke_biometric_tokens(
    request: BiometricRevokeRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Revoke biometric device tokens for the current client.

    - If device_token is provided, only that device is revoked.
    - If omitted, all biometric tokens for this client are revoked.
    """
    stmt = update(ClientBiometricToken).filter(
        ClientBiometricToken.client_id == current_client.id,
        ClientBiometricToken.revoked == False,
    ).values(revoked=True)

    if request.device_token:
        device_hash = hashlib.sha256(request.device_token.encode("utf-8")).hexdigest()
        stmt = stmt.filter(ClientBiometricToken.device_token_hash == device_hash)

    result = await db.execute(stmt)
    await db.commit()

    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No biometric tokens found to revoke",
        )

    scope = "this device" if request.device_token else "all devices"
    return {"message": f"Biometric login disabled for {scope}"}


# TODO: Implement "Continue with Apple" integration
# @router.post("/client/auth/apple")
# async def client_apple_auth():
#     """Continue with Apple authentication for clients"""
#     pass


# ==================== NOTIFICATION ENDPOINTS ====================

@router.get("/client/notifications", response_model=ClientNotificationListResponse)
async def get_client_notifications(
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all notifications for the authenticated client
    
    Returns all admin notifications sent to this client, ordered by creation date (newest first).
    Includes unread count.
    """
    # Get all notifications for this client
    result = await db.execute(
        select(Notification).filter(
            Notification.recipient_type == "client",
            Notification.recipient_id == current_client.id
        ).order_by(Notification.created_at.desc())
    )
    notifications = result.scalars().all()
    
    # Count unread notifications
    unread_result = await db.execute(
        select(func.count(Notification.id)).filter(
            Notification.recipient_type == "client",
            Notification.recipient_id == current_client.id,
            Notification.is_read == False
        )
    )
    unread_count = unread_result.scalar()
    
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
        notifications=notification_list, total=len(notification_list), unread_count=unread_count
    )


@router.put("/client/notifications/{notification_id}/read")
async def mark_client_notification_as_read(
    notification_id: int,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db)
):
    """
    Mark a notification as read
    
    - **notification_id**: ID of the notification to mark as read
    """
    result = await db.execute(
        select(Notification).filter(
            Notification.id == notification_id,
            Notification.recipient_type == "client",
            Notification.recipient_id == current_client.id
        )
    )
    notification = result.scalar_one_or_none()
    
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )
    
    notification.is_read = True
    await db.commit()
    
    return {"message": "Notification marked as read"}

