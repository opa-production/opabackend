"""
KuvarPay webhook endpoint.
Receives payment lifecycle events and updates bookings accordingly.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import SessionLocal, get_db
from app.models import Booking, BookingStatus, Payment, PaymentStatus
from app.services.kuvarpay import verify_webhook_signature

router = APIRouter()
logger = logging.getLogger(__name__)

# Events that mean the payment is done and the booking can be confirmed
_COMPLETED_EVENTS = {
    "checkout_session.completed",
    "checkout_session.payment_received",
}
_FAILED_EVENTS = {
    "checkout_session.failed",
    "checkout_session.expired",
}


@router.post("/kuvarpay/webhook")
async def kuvarpay_webhook(
    background_tasks: BackgroundTasks,
    request: Request,
):
    """
    KuvarPay webhook receiver.
    Verifies HMAC-SHA256 signature then dispatches processing to a background task.
    Always returns 200 immediately so KuvarPay does not retry on our processing time.

    Register this URL in the KuvarPay dashboard:
        https://api.ardena.xyz/api/v1/kuvarpay/webhook
    """
    raw_body = await request.body()
    signature = request.headers.get("x-kuvarpay-signature", "")
    event_type = request.headers.get("x-kuvarpay-event", "")
    delivery_id = request.headers.get("x-kuvarpay-delivery", "")

    if not verify_webhook_signature(raw_body, signature):
        logger.warning("[KUVARPAY WEBHOOK] Invalid signature — ignoring delivery_id=%s", delivery_id)
        # Still return 200 so KuvarPay doesn't keep retrying a bad secret config
        return {"status": "ok"}

    try:
        payload = json.loads(raw_body)
    except Exception:
        logger.warning("[KUVARPAY WEBHOOK] Non-JSON body delivery_id=%s", delivery_id)
        return {"status": "ok"}

    logger.info("[KUVARPAY WEBHOOK] event=%s delivery_id=%s", event_type, delivery_id)

    if event_type in _COMPLETED_EVENTS:
        background_tasks.add_task(
            _handle_session_completed,
            payload=payload,
            delivery_id=delivery_id,
        )
    elif event_type in _FAILED_EVENTS:
        background_tasks.add_task(
            _handle_session_failed,
            payload=payload,
            event_type=event_type,
            delivery_id=delivery_id,
        )
    elif event_type == "webhook.test":
        logger.info("[KUVARPAY WEBHOOK] Test event received OK")

    return {"status": "ok"}


async def _handle_session_completed(payload: dict, delivery_id: str) -> None:
    """Mark the payment COMPLETED and confirm the booking."""
    session_id = _extract_session_id(payload)
    if not session_id:
        logger.warning("[KUVARPAY] completed event missing session id: %s", payload)
        return

    async with SessionLocal() as db:
        try:
            payment = await _get_pending_payment(db, session_id)
            if not payment:
                logger.warning("[KUVARPAY] No pending payment for session_id=%s", session_id)
                return

            # Idempotency: if already processed skip
            if payment.status == PaymentStatus.COMPLETED:
                logger.info("[KUVARPAY] Already completed session_id=%s", session_id)
                return

            now = datetime.now(timezone.utc)
            payment.status = PaymentStatus.COMPLETED
            payment.result_desc = "KuvarPay crypto payment completed"
            payment.updated_at = now

            booking_id = payment.booking_id
            res = await db.execute(
                select(Booking)
                .options(joinedload(Booking.car))
                .filter(Booking.id == booking_id)
            )
            booking = res.scalar_one_or_none()
            if booking and booking.status == BookingStatus.PENDING:
                booking.status = BookingStatus.CONFIRMED
                booking.status_updated_at = now

            await db.commit()
            logger.info(
                "[KUVARPAY] ✅ Booking confirmed booking_id=%s session_id=%s",
                booking_id,
                session_id,
            )

            if booking:
                _fire_confirmation_notifications(booking)

        except Exception:
            logger.exception("[KUVARPAY] Error processing completed event session_id=%s", session_id)
            await db.rollback()


async def _handle_session_failed(payload: dict, event_type: str, delivery_id: str) -> None:
    """Mark the payment FAILED."""
    session_id = _extract_session_id(payload)
    if not session_id:
        return

    async with SessionLocal() as db:
        try:
            payment = await _get_pending_payment(db, session_id)
            if not payment:
                return
            if payment.status != PaymentStatus.PENDING:
                return

            payment.status = PaymentStatus.FAILED
            payment.result_desc = f"KuvarPay session {event_type.split('.')[-1]}"
            payment.updated_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info("[KUVARPAY] Payment failed/expired session_id=%s event=%s", session_id, event_type)

        except Exception:
            logger.exception("[KUVARPAY] Error processing failed event session_id=%s", session_id)
            await db.rollback()


async def _get_pending_payment(db: AsyncSession, session_id: str) -> Payment | None:
    res = await db.execute(
        select(Payment).filter(Payment.kuvarpay_session_id == session_id)
    )
    return res.scalar_one_or_none()


def _extract_session_id(payload: dict) -> str | None:
    """Extract the session ID from various KuvarPay payload shapes."""
    return (
        payload.get("sessionId")
        or payload.get("session_id")
        or payload.get("id")
        or (payload.get("checkout_session") or {}).get("sessionId")
        or (payload.get("checkout_session") or {}).get("id")
        or (payload.get("data") or {}).get("sessionId")
        or (payload.get("data") or {}).get("id")
    )


def _fire_confirmation_notifications(booking: Booking) -> None:
    """Fire push notifications for booking confirmation (fire-and-forget)."""
    try:
        from app.services.push_notifications import (
            notify_booking_confirmed,
            notify_host_payment_received,
        )
        car_name = ""
        if booking.car:
            car_name = f"{booking.car.name} {booking.car.model or ''}".strip()
        pickup_date = booking.start_date.strftime("%b %d, %Y") if booking.start_date else ""
        asyncio.ensure_future(
            notify_booking_confirmed(booking.client_id, str(booking.booking_id), car_name, pickup_date)
        )
        if booking.car:
            asyncio.ensure_future(
                notify_host_payment_received(
                    booking.car.host_id,
                    str(booking.booking_id),
                    car_name,
                    pickup_date,
                )
            )
    except Exception:
        logger.exception("[KUVARPAY] Failed to fire notifications booking_id=%s", booking.id)
