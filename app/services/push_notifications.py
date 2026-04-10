"""
Expo Push Notification service.

Sends native push notifications (like M-Pesa) to clients via Expo's Push API,
which routes to FCM (Android) and APNS (iOS) automatically.

Usage from async context:
    await push_client(client_id, db, title="...", body="...", data={})

Usage from sync context (background thread):
    # Use the sync wrapper via _run_on_main_loop in booking_emails.py
"""
import logging
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal
from app.models import ClientPushToken

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"

# Notification types map to Android channel IDs (register these in Expo app)
CHANNEL_BOOKING = "bookings"
CHANNEL_PAYMENT = "payments"
CHANNEL_REMINDER = "reminders"
CHANNEL_DEFAULT = "default"


def _build_message(token: str, title: str, body: str, data: dict, channel: str, badge: int) -> dict:
    return {
        "to": token,
        "title": title,
        "body": body,
        "data": data,
        "sound": "default",
        "priority": "high",
        "channelId": channel,
        "badge": badge,
    }


async def _send_to_tokens(tokens: list[str], title: str, body: str, data: dict, channel: str, badge: int) -> bool:
    """Send one notification to a list of Expo push tokens (batched, max 100 each)."""
    valid = [t for t in tokens if t and t.startswith("ExponentPushToken")]
    if not valid:
        return False

    messages = [_build_message(t, title, body, data, channel, badge) for t in valid]

    ok = True
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            for i in range(0, len(messages), 100):
                batch = messages[i:i + 100]
                resp = await client.post(
                    EXPO_PUSH_URL,
                    json=batch,
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                )
                if resp.status_code != 200:
                    logger.error("[Push] Expo API error %s: %s", resp.status_code, resp.text[:300])
                    ok = False
                else:
                    # Log any per-ticket errors
                    for ticket in resp.json().get("data", []):
                        if ticket.get("status") == "error":
                            logger.warning("[Push] Ticket error: %s", ticket)
    except Exception as e:
        logger.exception("[Push] Failed to send push notification: %s", e)
        return False

    return ok


async def push_client(
    client_id: int,
    db: AsyncSession,
    title: str,
    body: str,
    data: Optional[dict] = None,
    channel: str = CHANNEL_DEFAULT,
    badge: int = 1,
) -> bool:
    """
    Send a push notification to all registered devices for a client.
    Call this from async endpoints or async background tasks.

    Args:
        client_id: The client's database ID.
        db: Active AsyncSession (from request or SessionLocal context).
        title: Notification title (bold line users see first).
        body: Notification body text.
        data: Extra JSON payload for the app to handle on tap.
        channel: Android channel ID.
        badge: iOS badge count.
    """
    result = await db.execute(
        select(ClientPushToken.token).filter(ClientPushToken.client_id == client_id)
    )
    tokens = [row[0] for row in result.fetchall()]

    if not tokens:
        logger.debug("[Push] No push tokens for client_id=%s", client_id)
        return False

    return await _send_to_tokens(tokens, title, body, data or {}, channel, badge)


async def push_client_standalone(
    client_id: int,
    title: str,
    body: str,
    data: Optional[dict] = None,
    channel: str = CHANNEL_DEFAULT,
    badge: int = 1,
) -> bool:
    """
    Send a push notification opening its own DB session.
    Use this from booking_emails.py async functions or other places
    that don't have an existing session.
    """
    async with SessionLocal() as db:
        return await push_client(client_id, db, title, body, data, channel, badge)


# ── Convenience wrappers for each event type ──────────────────────────────────

async def notify_booking_confirmed(client_id: int, booking_ref: str, car_name: str, pickup_date: str):
    await push_client_standalone(
        client_id,
        title="Booking Confirmed!",
        body=f"Your {car_name} is booked. Pickup: {pickup_date}",
        data={"type": "booking_confirmed", "booking_id": booking_ref},
        channel=CHANNEL_BOOKING,
    )


async def notify_pickup_reminder(client_id: int, booking_ref: str, car_name: str, pickup_time: str, pickup_location: str):
    await push_client_standalone(
        client_id,
        title="Pickup Tomorrow!",
        body=f"Don't forget — {car_name} at {pickup_time}, {pickup_location}",
        data={"type": "pickup_reminder", "booking_id": booking_ref},
        channel=CHANNEL_REMINDER,
    )


async def notify_trip_started(client_id: int, booking_ref: str, car_name: str):
    await push_client_standalone(
        client_id,
        title="Your Trip Has Started!",
        body=f"Enjoy your ride in the {car_name}. Drive safe!",
        data={"type": "trip_started", "booking_id": booking_ref},
        channel=CHANNEL_BOOKING,
    )


async def notify_trip_completed(client_id: int, booking_ref: str, car_name: str):
    await push_client_standalone(
        client_id,
        title="Trip Complete!",
        body=f"Thanks for renting the {car_name}. Tap to rate your experience.",
        data={"type": "trip_completed", "booking_id": booking_ref},
        channel=CHANNEL_BOOKING,
    )


async def notify_booking_cancelled(client_id: int, booking_ref: str, reason: Optional[str] = None):
    body = "Your booking has been cancelled."
    if reason:
        body += f" Reason: {reason}"
    await push_client_standalone(
        client_id,
        title="Booking Cancelled",
        body=body,
        data={"type": "booking_cancelled", "booking_id": booking_ref},
        channel=CHANNEL_BOOKING,
    )


async def notify_dropoff_approaching(client_id: int, booking_ref: str, return_time: str, return_location: str):
    await push_client_standalone(
        client_id,
        title="Return Approaching",
        body=f"Please return the car by {return_time} at {return_location}.",
        data={"type": "dropoff_reminder", "booking_id": booking_ref},
        channel=CHANNEL_REMINDER,
    )
