"""
Secondary contact verification via SMS OTP (Africa's Talking).

Flow:
  1. POST /client/secondary-contact/info     — save phone + names
  2. POST /client/secondary-contact/send-otp — send 5-digit OTP to secondary phone
  3. POST /client/secondary-contact/verify   — verify OTP (expires in 2 min)
  4. GET  /client/secondary-contact/status   — current verification state
"""
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_client
from app.database import get_db
from app.models import Client
from app.schemas import (
    SecondaryContactInfoRequest,
    SecondaryContactVerifyOTPRequest,
    SecondaryContactStatusResponse,
)
from app.services import sms

router = APIRouter()
logger = logging.getLogger(__name__)

OTP_EXPIRY_MINUTES = 2


def _status_response(client: Client, message: str | None = None) -> SecondaryContactStatusResponse:
    return SecondaryContactStatusResponse(
        status=client.secondary_contact_status or "not_started",
        phone=client.secondary_contact_phone,
        names=client.secondary_contact_names,
        verified_at=client.secondary_contact_verified_at,
        message=message,
    )


@router.post("/client/secondary-contact/info", response_model=SecondaryContactStatusResponse)
async def save_secondary_contact_info(
    body: SecondaryContactInfoRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Step 1 — save secondary contact phone + names, reset any prior verification."""
    result = await db.execute(select(Client).where(Client.id == current_client.id))
    client = result.scalar_one()

    client.secondary_contact_phone = body.phone.strip()
    client.secondary_contact_names = body.names.strip()
    client.secondary_contact_status = "not_started"
    client.secondary_contact_otp = None
    client.secondary_contact_otp_expires_at = None
    client.secondary_contact_verified_at = None

    await db.commit()
    return _status_response(client, message="Info saved. Tap 'Send OTP' to verify the number.")


@router.post("/client/secondary-contact/send-otp", response_model=SecondaryContactStatusResponse)
async def send_secondary_contact_otp(
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Step 2 — generate a 5-digit OTP and SMS it to the saved secondary contact phone."""
    result = await db.execute(select(Client).where(Client.id == current_client.id))
    client = result.scalar_one()

    if not client.secondary_contact_phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please save secondary contact info (phone + names) first.",
        )

    otp = sms.generate_otp()
    client.secondary_contact_otp = otp
    client.secondary_contact_otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES)
    client.secondary_contact_status = "otp_sent"
    await db.commit()

    await sms.send_otp(client.secondary_contact_phone, otp)
    logger.warning(
        "[secondary_contact] OTP sent client=%s phone=%.5s…", current_client.id, client.secondary_contact_phone
    )

    return _status_response(client, message="OTP sent. Ask your secondary contact to share the code. Valid for 2 minutes.")


@router.post("/client/secondary-contact/verify", response_model=SecondaryContactStatusResponse)
async def verify_secondary_contact_otp(
    body: SecondaryContactVerifyOTPRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Step 3 — verify the 5-digit OTP. Fails if expired or wrong."""
    result = await db.execute(select(Client).where(Client.id == current_client.id))
    client = result.scalar_one()

    if not client.secondary_contact_otp or not client.secondary_contact_otp_expires_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No OTP active. Please request a new one.",
        )

    if datetime.now(timezone.utc) > client.secondary_contact_otp_expires_at:
        client.secondary_contact_otp = None
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OTP has expired. Please request a new one.",
        )

    if body.otp.strip() != client.secondary_contact_otp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect OTP. Please try again.",
        )

    client.secondary_contact_status = "verified"
    client.secondary_contact_otp = None
    client.secondary_contact_otp_expires_at = None
    client.secondary_contact_verified_at = datetime.now(timezone.utc)
    await db.commit()

    logger.warning("[secondary_contact] verified client=%s", current_client.id)
    return _status_response(client, message="Secondary contact verified successfully.")


@router.get("/client/secondary-contact/status", response_model=SecondaryContactStatusResponse)
async def get_secondary_contact_status(
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Return the current secondary contact verification state."""
    result = await db.execute(select(Client).where(Client.id == current_client.id))
    client = result.scalar_one()
    return _status_response(client)
