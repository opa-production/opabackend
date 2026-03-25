"""
Expire unpaid PENDING bookings after a configured time so the car becomes available again.
"""
import os
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Booking, Payment, BookingStatus, PaymentStatus

logger = logging.getLogger(__name__)

# Default: cancel PENDING bookings that are older than this and have no completed payment
DEFAULT_EXPIRE_MINUTES = 30
CANCELLATION_REASON = "Booking expired (payment not completed in time). The car is available for other renters."


def get_expire_minutes() -> int:
    """Read PENDING_BOOKING_EXPIRE_MINUTES from env; default 30."""
    try:
        val = os.getenv("PENDING_BOOKING_EXPIRE_MINUTES", str(DEFAULT_EXPIRE_MINUTES))
        return max(1, int(val))
    except (ValueError, TypeError):
        return DEFAULT_EXPIRE_MINUTES


async def expire_pending_bookings(db: AsyncSession, expire_minutes: int | None = None) -> int:
    """
    Find PENDING bookings older than expire_minutes with no completed payment,
    set them to CANCELLED so the car is available again.
    Returns the number of bookings expired.
    """
    if expire_minutes is None:
        expire_minutes = get_expire_minutes()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=expire_minutes)

    result = await db.execute(
        select(Booking).where(
            Booking.status == BookingStatus.PENDING,
            Booking.created_at < cutoff,
        )
    )
    pending = result.scalars().all()
    expired_count = 0
    now = datetime.now(timezone.utc)
    for booking in pending:
        pay_row = await db.execute(
            select(Payment.id).where(
                Payment.booking_id == booking.id,
                Payment.status == PaymentStatus.COMPLETED,
            ).limit(1)
        )
        has_completed = pay_row.scalar_one_or_none() is not None
        if has_completed:
            continue
        booking.status = BookingStatus.CANCELLED
        booking.cancellation_reason = CANCELLATION_REASON
        booking.status_updated_at = now
        expired_count += 1
        logger.info(
            "[EXPIRE] Cancelled unpaid booking id=%s booking_id=%s (created %s)",
            booking.id,
            booking.booking_id,
            booking.created_at,
        )
    if expired_count:
        await db.commit()
    return expired_count
