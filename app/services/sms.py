"""
Africa's Talking SMS service.

Used for:
  1. OTP delivery for secondary contact phone verification (5-digit, 2 min expiry)
  2. Booking lifecycle notifications (max 4 per booking journey)

Environment variables:
    AFRICASTALKING_API_KEY   — required
    AFRICASTALKING_USERNAME  — defaults to "sandbox"; set to your AT username in production
"""
import logging
import random

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_SANDBOX_URL = "https://api.sandbox.africastalking.com/version1/messaging"
_PROD_URL = "https://api.africastalking.com/version1/messaging"


def _api_url() -> str:
    return _SANDBOX_URL if settings.AFRICASTALKING_USERNAME == "sandbox" else _PROD_URL


def _normalise_phone(phone: str) -> str:
    p = phone.strip()
    if p.startswith("0"):
        return "+254" + p[1:]
    if not p.startswith("+"):
        return "+" + p
    return p


async def send_sms(to: str, message: str) -> bool:
    if not settings.AFRICASTALKING_API_KEY:
        logger.warning("[SMS] AFRICASTALKING_API_KEY not set — skipping SMS to %s", to)
        return False

    phone = _normalise_phone(to)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                _api_url(),
                headers={
                    "apiKey": settings.AFRICASTALKING_API_KEY,
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "username": settings.AFRICASTALKING_USERNAME,
                    "to": phone,
                    "message": message,
                },
            )
        logger.warning("[SMS] to=%s status=%s body=%.200s", phone, resp.status_code, resp.text)
        return resp.status_code == 201
    except Exception as exc:
        logger.warning("[SMS] failed to=%s error=%s", phone, exc)
        return False


def generate_otp() -> str:
    return str(random.randint(10000, 99999))


# ── OTP ──────────────────────────────────────────────────────────────────────

async def send_otp(phone: str, otp: str) -> bool:
    return await send_sms(
        phone,
        f"Your Ardena verification code is {otp}. Valid for 2 minutes. Do not share this code.",
    )


# ── Booking notifications (4 per journey) ────────────────────────────────────

async def send_booking_created(phone: str, car_name: str, start_date: str) -> None:
    """Sent immediately when client creates a booking (still pending confirmation)."""
    await send_sms(
        phone,
        f"Booking received! Your request for {car_name} starting {start_date} is awaiting host confirmation. We'll notify you once confirmed.",
    )


async def send_booking_confirmed(phone: str, car_name: str, start_date: str) -> None:
    """Sent when admin/host confirms the booking."""
    await send_sms(
        phone,
        f"Booking confirmed! Your {car_name} rental starting {start_date} is confirmed. Open the app for full details.",
    )


async def send_booking_cancelled(phone: str, car_name: str, refund_amount: float | None = None) -> None:
    """Sent when booking is cancelled."""
    if refund_amount and refund_amount > 0:
        msg = f"Your {car_name} booking has been cancelled. A refund of KES {refund_amount:,.0f} will be processed within 3-5 business days."
    else:
        msg = f"Your {car_name} booking has been cancelled. No charges apply."
    await send_sms(phone, msg)


async def send_pickup_reminder(phone: str, car_name: str, pickup_time: str) -> None:
    """Sent ~2 hours before rental start (scheduled job)."""
    await send_sms(
        phone,
        f"Reminder: Your {car_name} rental starts at {pickup_time} today. Please be on time for pickup.",
    )


async def send_dropoff_reminder(phone: str, car_name: str, dropoff_time: str) -> None:
    """Sent ~2 hours before rental end (scheduled job)."""
    await send_sms(
        phone,
        f"Reminder: Your {car_name} rental ends at {dropoff_time} today. Please return the car on time to avoid late fees.",
    )
