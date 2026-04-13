import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import joinedload

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


async def _run_push_reminder_loop():
    """
    Every 15 min fire push reminders to clients at three windows before pickup:
      - 10 hours before  → "Pickup in 10 hours"
      - 5 hours before   → "Pickup in 5 hours"
      - 1 hour before    → "Pickup in 1 hour"
    Each reminder is sent at most once per booking (tracked by push_reminder_Xh_sent_at).
    """
    from app.models import Booking, BookingStatus
    from app.services.push_notifications import push_client_standalone, CHANNEL_REMINDER

    _log = logging.getLogger(__name__)
    interval_seconds = 15 * 60  # check every 15 minutes
    half_window = timedelta(minutes=30)  # ±30 min window around each target

    _log.info("[PUSH_REMINDER] Loop started, check every 15 min")

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with SessionLocal() as db:
                now = datetime.now(timezone.utc)

                # Each entry: (hours_before, column_attr, title, body_template)
                windows = [
                    (10, "push_reminder_10h_sent_at", "Pickup in 10 Hours",
                     "Your {car} pickup is in 10 hours. Head to {location} at {time}."),
                    (5,  "push_reminder_5h_sent_at",  "Pickup in 5 Hours",
                     "Reminder: {car} pickup in 5 hours at {location}."),
                    (1,  "push_reminder_1h_sent_at",  "Pickup in 1 Hour!",
                     "Almost time! Your {car} pickup is in 1 hour at {location}."),
                ]

                for hours_before, col, title, body_tpl in windows:
                    target_start = now + timedelta(hours=hours_before) - half_window
                    target_end   = now + timedelta(hours=hours_before) + half_window
                    sent_col = getattr(Booking, col)

                    result = await db.execute(
                        select(Booking)
                        .options(joinedload(Booking.car))
                        .where(
                            Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.ACTIVE]),
                            Booking.start_date >= target_start,
                            Booking.start_date <= target_end,
                            sent_col.is_(None),
                        )
                    )
                    bookings = result.scalars().all()

                    for b in bookings:
                        try:
                            car_name = "your car"
                            if b.car:
                                car_name = f"{b.car.name} {b.car.model}".strip() if b.car.model else b.car.name
                            location = b.pickup_location or "the pickup point"
                            pickup_time = b.pickup_time or "your scheduled time"

                            body = body_tpl.format(
                                car=car_name, location=location, time=pickup_time
                            )
                            await push_client_standalone(
                                client_id=b.client_id,
                                title=title,
                                body=body,
                                data={
                                    "type": "pickup_reminder",
                                    "booking_id": str(b.booking_id),
                                    "hours_before": hours_before,
                                },
                                channel=CHANNEL_REMINDER,
                            )
                            setattr(b, col, now)
                            await db.commit()
                            _log.info(
                                "[PUSH_REMINDER] Sent %dh reminder for booking %s (client_id=%s)",
                                hours_before, b.booking_id, b.client_id,
                            )
                        except Exception as e:
                            _log.exception(
                                "[PUSH_REMINDER] Failed %dh reminder for booking %s: %s",
                                hours_before, b.booking_id, e,
                            )
        except Exception as e:
            _log.exception("[PUSH_REMINDER] Loop error: %s", e)

