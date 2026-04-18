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
from app.models import ClientPushToken, HostPushToken

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


async def _delete_stale_tokens(stale: list[str]) -> None:
    """Remove tokens that Expo reported as DeviceNotRegistered so they stop accumulating."""
    if not stale:
        return
    from sqlalchemy import delete as _delete
    async with SessionLocal() as db:
        await db.execute(
            _delete(ClientPushToken).where(ClientPushToken.token.in_(stale))
        )
        await db.execute(
            _delete(HostPushToken).where(HostPushToken.token.in_(stale))
        )
        await db.commit()
    logger.info("[Push] Deleted %d stale DeviceNotRegistered token(s): %s", len(stale), stale)


async def _send_to_tokens(tokens: list[str], title: str, body: str, data: dict, channel: str, badge: int) -> bool:
    """Send one notification to a list of Expo push tokens (batched, max 100 each)."""
    valid = [t for t in tokens if t and t.startswith("ExponentPushToken")]
    if not valid:
        return False

    messages = [_build_message(t, title, body, data, channel, badge) for t in valid]

    ok = True
    stale_tokens: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            for i in range(0, len(messages), 100):
                batch_tokens = valid[i:i + 100]
                batch_msgs = messages[i:i + 100]
                resp = await client.post(
                    EXPO_PUSH_URL,
                    json=batch_msgs,
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                )
                if resp.status_code != 200:
                    logger.error("[Push] Expo API error %s: %s", resp.status_code, resp.text[:300])
                    ok = False
                else:
                    logger.info("[Push] Expo accepted batch of %d message(s)", len(batch_msgs))
                    tickets = resp.json().get("data", [])
                    for token, ticket in zip(batch_tokens, tickets):
                        if ticket.get("status") == "error":
                            err = (ticket.get("details") or {}).get("error", "")
                            logger.warning("[Push] Ticket error for token %s: %s", token[:30], ticket)
                            if err == "DeviceNotRegistered":
                                stale_tokens.append(token)
    except Exception as e:
        logger.exception("[Push] Failed to send push notification: %s", e)
        return False

    if stale_tokens:
        import asyncio as _asyncio
        _asyncio.ensure_future(_delete_stale_tokens(stale_tokens))

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
        logger.warning("[Push] No push tokens for client_id=%s — notification not sent", client_id)
        return False

    logger.info("[Push] Sending to client_id=%s (%d token(s)): %s", client_id, len(tokens), title)
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


# ── Host push notification helpers ────────────────────────────────────────────

async def push_host(
    host_id: int,
    db: AsyncSession,
    title: str,
    body: str,
    data: Optional[dict] = None,
    channel: str = CHANNEL_DEFAULT,
    badge: int = 1,
) -> bool:
    """Send a push notification to all registered devices for a host."""
    result = await db.execute(
        select(HostPushToken.token).filter(HostPushToken.host_id == host_id)
    )
    tokens = [row[0] for row in result.fetchall()]
    if not tokens:
        logger.warning("[Push] No push tokens for host_id=%s — notification not sent", host_id)
        return False
    logger.info("[Push] Sending to host_id=%s (%d token(s)): %s", host_id, len(tokens), title)
    return await _send_to_tokens(tokens, title, body, data or {}, channel, badge)


async def push_host_standalone(
    host_id: int,
    title: str,
    body: str,
    data: Optional[dict] = None,
    channel: str = CHANNEL_DEFAULT,
    badge: int = 1,
) -> bool:
    """Send a push notification to a host, opening its own DB session."""
    async with SessionLocal() as db:
        return await push_host(host_id, db, title, body, data, channel, badge)


# ── Host event wrappers ───────────────────────────────────────────────────────

async def notify_host_new_booking(host_id: int, booking_ref: str, client_name: str, car_name: str, start_date: str):
    await push_host_standalone(
        host_id,
        title="New Booking Request!",
        body=f"{client_name} booked your {car_name}. Pickup: {start_date}",
        data={"type": "new_booking", "booking_id": booking_ref},
        channel=CHANNEL_BOOKING,
    )


async def notify_host_booking_cancelled(host_id: int, booking_ref: str, car_name: str, reason: Optional[str] = None):
    body = f"A booking for your {car_name} has been cancelled."
    if reason:
        body += f" Reason: {reason}"
    await push_host_standalone(
        host_id,
        title="Booking Cancelled",
        body=body,
        data={"type": "booking_cancelled", "booking_id": booking_ref},
        channel=CHANNEL_BOOKING,
    )


async def notify_host_payment_received(host_id: int, booking_ref: str, car_name: str, amount: float):
    await push_host_standalone(
        host_id,
        title="Payment Received!",
        body=f"KES {amount:,.0f} received for your {car_name}. Booking {booking_ref} is now confirmed.",
        data={"type": "payment_received", "booking_id": booking_ref},
        channel=CHANNEL_PAYMENT,
    )


async def notify_host_new_rating(host_id: int, client_name: str, rating: int, car_name: str):
    stars = "★" * rating + "☆" * (5 - rating)
    await push_host_standalone(
        host_id,
        title="New Rating Received",
        body=f"{client_name} rated your {car_name} {stars} ({rating}/5)",
        data={"type": "new_rating"},
        channel=CHANNEL_DEFAULT,
    )


async def notify_host_extension_requested(host_id: int, booking_ref: str, car_name: str, extra_days: int):
    await push_host_standalone(
        host_id,
        title="Extension Request",
        body=f"A renter wants to extend the {car_name} booking by {extra_days} day{'s' if extra_days != 1 else ''}. Tap to review.",
        data={"type": "extension_requested", "booking_id": booking_ref},
        channel=CHANNEL_BOOKING,
    )


async def notify_host_withdrawal_completed(host_id: int, amount: float):
    await push_host_standalone(
        host_id,
        title="Withdrawal Processed!",
        body=f"Your withdrawal of KES {amount:,.0f} has been sent successfully.",
        data={"type": "withdrawal_completed"},
        channel=CHANNEL_PAYMENT,
    )


async def notify_host_withdrawal_rejected(host_id: int, amount: float):
    await push_host_standalone(
        host_id,
        title="Withdrawal Rejected",
        body=f"Your withdrawal request of KES {amount:,.0f} was rejected. Contact support for details.",
        data={"type": "withdrawal_rejected"},
        channel=CHANNEL_PAYMENT,
    )


async def notify_host_withdrawal_failed(host_id: int, amount: float):
    await push_host_standalone(
        host_id,
        title="Withdrawal Failed",
        body=f"Your payout of KES {amount:,.0f} could not be processed. Please check your payment details.",
        data={"type": "withdrawal_failed"},
        channel=CHANNEL_PAYMENT,
    )
