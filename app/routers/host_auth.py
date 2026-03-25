import html
import secrets
from datetime import datetime, timedelta, timezone
import hashlib
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status, BackgroundTasks
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.database import get_db
from app.models import Host, Notification, HostBiometricToken
from app.schemas import (
    HostRegisterRequest,
    HostRegisterResponse,
    HostLoginRequest,
    GoogleLoginRequest,
    HostLoginResponseWithRefresh,
    HostProfileUpdateRequest,
    HostProfileResponse,
    RefreshTokenRequest,
    TokenPairResponse,
    HostNotificationResponse,
    HostNotificationListResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    HostChangePasswordRequest,
    BiometricLoginRequest,
    BiometricRevokeRequest,
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
    get_host_by_email,
    get_current_host,
    ACCESS_TOKEN_EXPIRE_MINUTES
)
from app.config import settings
from app.services.email_welcome import send_welcome_email_host, send_email

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post("/host/auth/register", response_model=HostRegisterResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register_host(
    body: HostRegisterRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Register a new host (car owner)
    
    - **full_name**: Full name of the host
    - **email**: Email address (must be unique)
    - **password**: Password (minimum 8 characters)
    - **password_confirmation**: Password confirmation (must match password)
    """
    # Check if email already exists
    existing_host = await get_host_by_email(db, body.email)
    if existing_host:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create new host
    hashed_password = get_password_hash(body.password)
    db_host = Host(
        full_name=body.full_name,
        email=body.email,
        hashed_password=hashed_password
    )
    
    db.add(db_host)
    await db.commit()
    await db.refresh(db_host)

    # Send welcome email (non-blocking; registration succeeds even if email fails)
    background_tasks.add_task(send_welcome_email_host, db_host.email, db_host.full_name)

    return db_host


@router.post("/host/auth/login", response_model=HostLoginResponseWithRefresh)
@limiter.limit("10/minute")
async def login_host(
    body: HostLoginRequest,
    db: AsyncSession = Depends(get_db)
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
    host = await get_host_by_email(db, body.email)
    if not host:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify password
    if not verify_password(body.password, host.hashed_password):
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

    # Optionally issue a device token for biometric login (one-time reveal, host app)
    device_token_raw = None
    if getattr(body, "enable_biometrics", False):
        device_token_raw = secrets.token_urlsafe(32)
        device_token_hash = hashlib.sha256(device_token_raw.encode("utf-8")).hexdigest()

        db_token = HostBiometricToken(
            host_id=host.id,
            device_token_hash=device_token_hash,
            device_name=getattr(body, "device_name", None),
        )
        db.add(db_token)
        await db.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # Convert to seconds
        "host": host,
        "device_token": device_token_raw,
    }


@router.post("/host/auth/biometric-login", response_model=HostLoginResponseWithRefresh)
async def host_biometric_login(
    request: BiometricLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Host login using a previously issued device token (for biometric unlock in host app).

    The host app should:
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
        select(HostBiometricToken).filter(
            HostBiometricToken.device_token_hash == device_hash,
            HostBiometricToken.revoked == False,
        )
    )
    db_token = result.scalar_one_or_none()

    if not db_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked device token",
        )

    result = await db.execute(select(Host).filter(Host.id == db_token.host_id))
    host = result.scalar_one_or_none()
    if not host or not host.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Host not found or inactive",
        )

    # Update last_used_at for auditing
    db_token.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    token_data = {"sub": str(host.id), "role": "host"}
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data=token_data, expires_delta=access_token_expires)
    refresh_token = create_refresh_token(data=token_data)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "host": host,
        "device_token": None,  # Never issue a new device token here
    }


@router.post("/host/auth/biometric-revoke")
async def revoke_host_biometric_tokens(
    request: BiometricRevokeRequest,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Revoke biometric device tokens for the current host.

    - If device_token is provided, only that device is revoked.
    - If omitted, all biometric tokens for this host are revoked.
    """
    stmt = update(HostBiometricToken).filter(
        HostBiometricToken.host_id == current_host.id,
        HostBiometricToken.revoked == False,
    ).values(revoked=True)

    if request.device_token:
        device_hash = hashlib.sha256(request.device_token.encode("utf-8")).hexdigest()
        stmt = stmt.filter(HostBiometricToken.device_token_hash == device_hash)

    result = await db.execute(stmt)
    await db.commit()

    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No biometric tokens found to revoke",
        )

    scope = "this device" if request.device_token else "all devices"
    return {"message": f"Biometric login disabled for {scope}"}


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
    db: AsyncSession = Depends(get_db)
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
    
    result = await db.execute(select(Host).filter(Host.id == host_id))
    host = result.scalar_one_or_none()
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
    db: AsyncSession = Depends(get_db)
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
    
    await db.commit()
    await db.refresh(current_host)
    
    return current_host


@router.post("/host/terms/accept", response_model=HostProfileResponse)
async def accept_terms_host(
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Record that the authenticated host has accepted the terms and conditions.
    Call this when the user checks the T&C checkbox. Status is stored so you do not prompt again.
    """
    current_host.terms_accepted_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(current_host)
    return current_host


@router.post("/host/auth/forgot-password")
@limiter.limit("3/minute")
async def forgot_password(
    body: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Request a password reset email for hosts.
    
    If the email exists, sends a reset link. Always returns success to prevent
    email enumeration. The link expires in 1 hour.
    
    - **email**: Registered email address
    """
    host = await get_host_by_email(db, body.email)
    if not host:
        # Don't reveal if email exists - same response for both cases
        return {"message": "If an account exists with this email, you will receive a password reset link."}

    if not settings.SENDGRID_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email service is not configured. Please try again later.",
        )

    reset_token = create_password_reset_token(host.id)
    # Prefer web reset page (full URL e.g. https://ardena.xyz/reset-password.html) when set; else use API redirect to app deep link.
    web_url = (settings.HOST_PASSWORD_RESET_WEB_URL or "").strip()
    if web_url:
        sep = "&" if "?" in web_url else "?"
        reset_link = f"{web_url.rstrip('/')}{sep}token={reset_token}"
    else:
        reset_link = f"{request.url_for('host_password_reset_redirect')}?token={reset_token}"

    background_tasks.add_task(
        send_email,
        host.email,
        "Reset your Ardena host password",
        f"""
        <div style="font-family: Arial, sans-serif; max-width: 560px; margin: 0 auto; color: #111827;">
          <p>Hi {host.full_name},</p>
          <p>You requested to reset your password for your Ardena host account.</p>
          <p>This link expires in 1 hour.</p>
          <p style="margin: 24px 0;">
            <a
              href="{reset_link}"
              style="display: inline-block; padding: 12px 18px; background: #111827; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: 600;"
            >
              Reset Password in App
            </a>
          </p>
          <p style="font-size: 14px; color: #4b5563;">
            If the button does not open automatically, open this secure link in your browser:
          </p>
          <p style="font-size: 14px; word-break: break-all;">
            <a href="{reset_link}">{reset_link}</a>
          </p>
          <p>If you didn't request this, you can safely ignore this email.</p>
          <p>— The Ardena Group Team</p>
        </div>
        """,
    )

    return {"message": "If an account exists with this email, you will receive a password reset link."}


@router.get("/host/auth/reset-password/redirect", response_class=HTMLResponse, name="host_password_reset_redirect")
async def host_password_reset_redirect(
    token: str = Query(..., description="Password reset token"),
):
    """
    Email-safe HTTPS endpoint that redirects to the host app deep link.
    This avoids email clients blocking custom schemes directly in emails.
    """
    base_url = (settings.PASSWORD_RESET_LINK_BASE_URL or "ardenahost://").strip()
    if base_url.endswith("://"):
        deep_link = f"{base_url}reset-password?token={token}"
    else:
        deep_link = f"{base_url.rstrip('/')}/reset-password?token={token}"

    escaped = html.escape(deep_link, quote=True)
    content = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Open Ardena Host</title>
  </head>
  <body style="font-family: Arial, sans-serif; padding: 24px;">
    <p>Redirecting to the Ardena Host app...</p>
    <script>
      // Use explicit JS navigation so the exact deep link is preserved.
      window.location.href = "{escaped}";
    </script>
    <p><a href="{escaped}">Open Ardena Host</a></p>
  </body>
</html>"""
    return HTMLResponse(content=content)


@router.post("/host/auth/reset-password")
async def reset_password(
    request: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Reset host password using the token from the forgot-password email.
    
    - **token**: Reset token from the email link
    - **new_password**: New password (min 8 characters)
    - **new_password_confirmation**: Must match new_password
    """
    payload = verify_password_reset_token(request.token)
    host_id = int(payload["sub"])

    result = await db.execute(select(Host).filter(Host.id == host_id))
    host = result.scalar_one_or_none()
    if not host:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset link.",
        )

    host.hashed_password = get_password_hash(request.new_password)
    await db.commit()
    await db.refresh(host)

    return {"message": "Password has been reset successfully. You can now log in with your new password."}


@router.put("/host/change-password")
async def change_password(
    request: HostChangePasswordRequest,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db)
):
    """
    Change host password (when logged in).
    
    Requires current password verification.
    
    - **current_password**: Current password
    - **new_password**: New password (min 8 characters)
    - **new_password_confirmation**: Must match new_password
    """
    # Verify current password
    if not verify_password(request.current_password, current_host.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )
    
    # Update password
    current_host.hashed_password = get_password_hash(request.new_password)
    await db.commit()
    
    return {"message": "Password changed successfully"}


@router.get("/host/notifications", response_model=HostNotificationListResponse)
async def get_host_notifications(
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all notifications for the authenticated host
    
    Returns all admin notifications sent to this host, ordered by creation date (newest first).
    Includes unread count.
    """
    # Get all notifications for this host
    result = await db.execute(
        select(Notification).filter(
            Notification.recipient_type == "host",
            Notification.recipient_id == current_host.id
        ).order_by(Notification.created_at.desc())
    )
    notifications = result.scalars().all()
    
    # Count unread notifications
    unread_result = await db.execute(
        select(func.count(Notification.id)).filter(
            Notification.recipient_type == "host",
            Notification.recipient_id == current_host.id,
            Notification.is_read == False
        )
    )
    unread_count = unread_result.scalar()
    
    # Build response
    notification_list = [HostNotificationResponse(
        id=notification.id,
        title=notification.title,
        message=notification.message,
        notification_type=notification.notification_type,
        sender_name=notification.sender_name,
        is_read=notification.is_read,
        created_at=notification.created_at
    ) for notification in notifications]
    
    return HostNotificationListResponse(
        notifications=notification_list, total=len(notification_list), unread_count=unread_count
    )


@router.put("/host/notifications/{notification_id}/read")
async def mark_host_notification_as_read(
    notification_id: int,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db)
):
    """
    Mark a notification as read
    
    - **notification_id**: ID of the notification to mark as read
    - Only notifications belonging to the authenticated host can be marked as read
    """
    # Find the notification
    result = await db.execute(
        select(Notification).filter(
            Notification.id == notification_id,
            Notification.recipient_type == "host",
            Notification.recipient_id == current_host.id
        )
    )
    notification = result.scalar_one_or_none()
    
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )
    
    # Mark as read
    notification.is_read = True
    await db.commit()
    
    return {"message": "Notification marked as read"}


@router.post("/host/auth/google", response_model=HostLoginResponseWithRefresh)
async def host_google_auth(
    request: GoogleLoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Continue with Google authentication for hosts.
    
    If the host doesn't exist, a new account is created.
    If the host exists but hasn't linked Google, it will be linked if the email matches.
    
    Returns:
    - access_token: Short-lived JWT for API access
    - refresh_token: Long-lived JWT for refreshing access tokens
    - expires_in: Access token expiration time in seconds
    - host: Host profile information
    """
    # Verify Google token
    idinfo = verify_google_token(request.id_token)
    
    google_id = idinfo['sub']
    email = idinfo['email']
    full_name = idinfo.get('name', '')
    avatar_url = idinfo.get('picture')

    # 1. Try to find by google_id
    result = await db.execute(select(Host).filter(Host.google_id == google_id))
    host = result.scalar_one_or_none()
    
    if not host:
        # 2. Try to find by email
        result = await db.execute(select(Host).filter(Host.email == email))
        host = result.scalar_one_or_none()
        
        if host:
            # Link Google account to existing email account
            host.google_id = google_id
            if not host.avatar_url and avatar_url:
                host.avatar_url = avatar_url
            await db.commit()
        else:
            # 3. Create new host
            host = Host(
                full_name=full_name,
                email=email,
                hashed_password=get_password_hash(secrets.token_urlsafe(32)),
                google_id=google_id,
                avatar_url=avatar_url,
                is_active=True
            )
            db.add(host)
            await db.commit()
            await db.refresh(host)

    if not host.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive"
        )

    # Create tokens
    token_data = {"sub": str(host.id), "role": "host"}
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data=token_data, expires_delta=access_token_expires)
    refresh_token = create_refresh_token(data=token_data)
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "host": host
    }


# TODO: Implement "Continue with Apple" integration
# @router.post("/host/auth/apple")
# async def host_apple_auth():
#     """Continue with Apple authentication for hosts"""
#     pass


