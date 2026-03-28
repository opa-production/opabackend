import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.session import SessionLocal


async def _run_expire_pending_bookings_loop():
    """Every N minutes, cancel PENDING bookings older than PENDING_BOOKING_EXPIRE_MINUTES with no completed payment."""
    from app.services.expire_pending_bookings import (
        expire_pending_bookings,
        get_expire_minutes,
    )

    _log = logging.getLogger(__name__)
    interval_minutes = max(
        1, int(os.getenv("PENDING_BOOKING_EXPIRE_CHECK_INTERVAL_MINUTES", "1"))
    )
    interval_seconds = interval_minutes * 60
    expire_mins = get_expire_minutes()
    _log.info(
        "[EXPIRE] Pending booking expiry: expire after %s min, check every %s min",
        expire_mins,
        interval_minutes,
    )
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with SessionLocal() as db:
                n = await expire_pending_bookings(db)
            if n:
                _log.info("[EXPIRE] Expired %s unpaid pending booking(s)", n)
        except Exception as e:
            _log.exception("[EXPIRE] Error expiring pending bookings: %s", e)


async def _run_pickup_reminder_loop():
    """Every 30–60 min, send pickup reminder emails for bookings whose start_date is in ~24 hours."""
    from app.models import Booking, BookingStatus
    from app.services.booking_emails import send_pickup_reminder_email

    _log = logging.getLogger(__name__)
    interval_minutes = max(
        15, int(os.getenv("PICKUP_REMINDER_CHECK_INTERVAL_MINUTES", "30"))
    )
    interval_seconds = interval_minutes * 60
    _log.info("[PICKUP_REMINDER] Loop started, check every %s min", interval_minutes)
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with SessionLocal() as db:
                now = datetime.now(timezone.utc)
                window_start = now + timedelta(hours=23)
                window_end = now + timedelta(hours=25)
                result = await db.execute(
                    select(Booking).where(
                        Booking.status.in_(
                            [BookingStatus.CONFIRMED, BookingStatus.ACTIVE]
                        ),
                        Booking.start_date >= window_start,
                        Booking.start_date <= window_end,
                        Booking.pickup_reminder_sent_at.is_(None),
                    )
                )
                bookings = result.scalars().all()
                for b in bookings:
                    try:
                        ok = await asyncio.to_thread(send_pickup_reminder_email, b.id)
                        if ok:
                            b.pickup_reminder_sent_at = now
                            await db.commit()
                    except Exception as e:
                        _log.exception(
                            "[PICKUP_REMINDER] Failed for booking_id=%s: %s", b.id, e
                        )
        except Exception as e:
            _log.exception("[PICKUP_REMINDER] Loop error: %s", e)
