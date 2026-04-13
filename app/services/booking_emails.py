"""
Send booking-related emails: ticket after payment, pickup reminder 24h before.
Uses SendGrid via email_welcome. Runs with its own DB session (safe for background threads).
"""

import logging
import asyncio
from datetime import timezone
from typing import Optional

from sqlalchemy.orm import joinedload
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Booking, Car, Payment, PaymentStatus
from app.services.email_welcome import send_email, send_email_with_attachment
from app.services.receipt import build_receipt_pdf
from app.services.push_notifications import notify_booking_confirmed, notify_pickup_reminder
from app.services.agreement import build_agreement_pdf

logger = logging.getLogger(__name__)


# Holds a reference to the running event loop, set at app startup.
_main_loop: Optional[asyncio.AbstractEventLoop] = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Call once at startup: set_main_loop(asyncio.get_running_loop())"""
    global _main_loop
    _main_loop = loop


def _run_on_main_loop(coro, timeout: int = 120):
    """
    Schedule a coroutine on the main app event loop from any thread.
    Blocks the calling thread until the coroutine completes or times out.
    """
    if _main_loop is None:
        raise RuntimeError(
            "[BookingEmails] Main event loop not set. "
            "Call set_main_loop() in the app startup event."
        )
    future = asyncio.run_coroutine_threadsafe(coro, _main_loop)
    return future.result(timeout=timeout)


def _fmt_date(dt) -> str:
    if dt is None:
        return "—"
    if getattr(dt, "tzinfo", None):
        dt = dt.replace(tzinfo=timezone.utc).astimezone(tz=None)
    return dt.strftime("%d %b %Y %H:%M")


# ─────────────────────────────────────────────────────────────────
#  BOOKING TICKET EMAIL
# ─────────────────────────────────────────────────────────────────

async def _async_send_booking_ticket_email(booking_id: int) -> bool:
    """Async implementation — runs on the main event loop."""
    try:
        async with SessionLocal() as db:
            result = await db.execute(
                select(Booking)
                .options(
                    joinedload(Booking.car).joinedload(Car.host),
                    joinedload(Booking.client),
                )
                .filter(Booking.id == booking_id)
            )
            booking = result.scalar_one_or_none()
            if not booking:
                logger.warning("[BookingEmail] Ticket: booking_id=%s not found", booking_id)
                return False

            client = booking.client
            if not client or not client.email:
                logger.warning("[BookingEmail] Ticket: no client email for booking_id=%s", booking_id)
                return False

            pay_result = await db.execute(
                select(Payment)
                .filter(Payment.booking_id == booking_id, Payment.status == PaymentStatus.COMPLETED)
                .order_by(Payment.id.desc())
            )
            paid_payment = pay_result.scalars().first()

        # Build PDF and send outside the session (data already loaded)
        pdf_bytes = build_receipt_pdf(booking, paid_payment)
        booking_ref = getattr(booking, "booking_id", f"#{booking_id}")
        first_name = (client.full_name.split() or ["there"])[0]

        subject = f"Your booking confirmation — {booking_ref}"
        html = f"""
        <div style="font-family: sans-serif; max-width: 560px; margin: auto;">
          <p>Hi {first_name},</p>
          <p>Your payment was successful. Your booking is confirmed.</p>
          <p><strong>Booking ID:</strong> {booking_ref}</p>
          <p><strong>Pick-up:</strong> {_fmt_date(booking.start_date)} — {booking.pickup_location or '—'}</p>
          <p><strong>Return:</strong> {_fmt_date(booking.end_date)} — {booking.return_location or '—'}</p>
          <p>Please find your receipt attached. See you soon!</p>
          <p style="margin-top: 24px;">— <strong>The Ardena Group Team</strong></p>
        </div>
        """
        ok = await send_email_with_attachment(
            to=client.email,
            subject=subject,
            html=html,
            attachment_bytes=pdf_bytes,
            filename=f"booking-receipt-{booking_ref}.pdf",
        )
        if ok:
            logger.info("[BookingEmail] Ticket sent to %s for booking_id=%s", client.email, booking_id)

        # Push notification — fire and forget (don't fail email if push fails)
        try:
            car = booking.car
            car_name = f"{getattr(car, 'name', '')} {getattr(car, 'model', '')}".strip() if car else "your car"
            pickup_str = _fmt_date(booking.start_date)
            await notify_booking_confirmed(client.id, booking_ref, car_name, pickup_str)
        except Exception as push_err:
            logger.warning("[BookingEmail] Push failed for booking_id=%s: %s", booking_id, push_err)

        return ok

    except Exception as e:
        logger.exception("[BookingEmail] Ticket failed for booking_id=%s: %s", booking_id, e)
        return False


def send_booking_ticket_email(booking_id: int) -> bool:
    """Sync wrapper — safe to call from background threads (Pesapal IPN, executors)."""
    try:
        return _run_on_main_loop(_async_send_booking_ticket_email(booking_id))
    except Exception as e:
        logger.exception("[BookingEmail] Ticket sync-wrapper failed for booking_id=%s: %s", booking_id, e)
        return False


# ─────────────────────────────────────────────────────────────────
#  RENTAL AGREEMENT EMAIL (client + host)
# ─────────────────────────────────────────────────────────────────

async def _async_send_rental_agreement_emails(booking_id: int) -> bool:
    """Async implementation — runs on the main event loop."""
    try:
        async with SessionLocal() as db:
            result = await db.execute(
                select(Booking)
                .options(
                    joinedload(Booking.car).joinedload(Car.host),
                    joinedload(Booking.client),
                )
                .filter(Booking.id == booking_id)
            )
            booking = result.scalar_one_or_none()
            if not booking:
                logger.warning("[AgreementEmail] booking_id=%s not found", booking_id)
                return False

            client = booking.client
            car = booking.car
            host = car.host if car else None

            pay_result = await db.execute(
                select(Payment)
                .filter(Payment.booking_id == booking_id, Payment.status == PaymentStatus.COMPLETED)
                .order_by(Payment.id.desc())
            )
            paid_payment = pay_result.scalars().first()

        # Build PDF outside the session
        pdf_bytes = build_agreement_pdf(booking, paid_payment)
        booking_ref = getattr(booking, "booking_id", f"#{booking_id}")
        filename = f"rental-agreement-{booking_ref}.pdf"
        subject = f"Your Rental Agreement — {booking_ref}"

        ok_client = False
        ok_host = False

        # ── client ──
        if client and client.email:
            first_name = (client.full_name.split() or ["there"])[0]
            client_html = f"""
            <div style="font-family: sans-serif; max-width: 560px; margin: 0 auto;">
              <p>Hi {first_name},</p>
              <p>Your booking <strong>{booking_ref}</strong> is confirmed and your rental agreement is ready.</p>
              <p>Please find your <strong>Vehicle Rental Agreement</strong> attached.
                 Keep it for your records — it contains all rental details, vehicle rules,
                 and your rights and obligations as a renter.</p>
              <p>Questions before pickup? Contact us at
                 <a href="mailto:hello@ardena.xyz">hello@ardena.xyz</a>.</p>
              <p style="margin-top: 24px;">Safe travels,<br><strong>The Ardena Group Team</strong></p>
            </div>
            """
            ok_client = await send_email_with_attachment(
                to=client.email,
                subject=subject,
                html=client_html,
                attachment_bytes=pdf_bytes,
                filename=filename,
            )
            if ok_client:
                logger.info("[AgreementEmail] Sent to client %s for booking_id=%s", client.email, booking_id)
        else:
            logger.warning("[AgreementEmail] No client email for booking_id=%s", booking_id)

        # ── host ──
        if host and host.email:
            host_first = (host.full_name.split() or ["there"])[0]
            car_label = f"{getattr(car, 'name', '')} {getattr(car, 'model', '')}".strip() if car else ""
            host_html = f"""
            <div style="font-family: sans-serif; max-width: 560px; margin: 0 auto;">
              <p>Hi {host_first},</p>
              <p>A new booking for your vehicle{' <strong>' + car_label + '</strong>' if car_label else ''}
                 has been confirmed and paid (Booking ID: <strong>{booking_ref}</strong>).</p>
              <p>Please find the <strong>Vehicle Rental Agreement</strong> attached. It contains the
                 renter's details, rental period, financial terms, and platform rules.
                 Keep this document for your records.</p>
              <p>Concerns about the booking? Contact us at
                 <a href="mailto:hello@ardena.xyz">hello@ardena.xyz</a>.</p>
              <p style="margin-top: 24px;">Thank you for hosting on Ardena,<br><strong>The Ardena Group Team</strong></p>
            </div>
            """
            ok_host = await send_email_with_attachment(
                to=host.email,
                subject=subject,
                html=host_html,
                attachment_bytes=pdf_bytes,
                filename=filename,
            )
            if ok_host:
                logger.info("[AgreementEmail] Sent to host %s for booking_id=%s", host.email, booking_id)
        else:
            logger.warning("[AgreementEmail] No host email for booking_id=%s", booking_id)

        return ok_client or ok_host

    except Exception as e:
        logger.exception("[AgreementEmail] Failed for booking_id=%s: %s", booking_id, e)
        return False


def send_rental_agreement_emails(booking_id: int) -> bool:
    """Sync wrapper — safe to call from background threads (Pesapal IPN, executors)."""
    try:
        return _run_on_main_loop(_async_send_rental_agreement_emails(booking_id))
    except Exception as e:
        logger.exception("[AgreementEmail] Sync-wrapper failed for booking_id=%s: %s", booking_id, e)
        return False


# ─────────────────────────────────────────────────────────────────
#  PICKUP REMINDER EMAIL
# ─────────────────────────────────────────────────────────────────

async def _async_send_pickup_reminder_email(booking_id: int) -> bool:
    """Async implementation — runs on the main event loop."""
    try:
        async with SessionLocal() as db:
            result = await db.execute(
                select(Booking)
                .options(
                    joinedload(Booking.car),
                    joinedload(Booking.client),
                )
                .filter(Booking.id == booking_id)
            )
            booking = result.scalar_one_or_none()
            if not booking:
                return False

            client = booking.client
            if not client or not getattr(client, "email_notifications_enabled", True):
                return False
            if not client.email:
                return False

            car = booking.car
            car_name = (
                f"{getattr(car, 'name', '')} {getattr(car, 'model', '')} {getattr(car, 'year', '')}".strip()
                or "your vehicle"
            ) if car else "your vehicle"

        first_name = (client.full_name.split() or ["there"])[0]
        subject = f"Reminder: Pick up your car tomorrow — {getattr(booking, 'booking_id', '')}"
        html = f"""
        <div style="font-family: sans-serif; max-width: 560px; margin: 0 auto;">
          <p>Hi {first_name},</p>
          <p>This is a friendly reminder that your car rental pickup is <strong>in 24 hours</strong>.</p>
          <p><strong>Booking ID:</strong> {getattr(booking, 'booking_id', '')}</p>
          <p><strong>Vehicle:</strong> {car_name}</p>
          <p><strong>Pick-up time:</strong> {_fmt_date(booking.start_date)}</p>
          <p><strong>Pick-up location:</strong> {booking.pickup_location or '—'}</p>
          <p>We look forward to seeing you. Safe travels!</p>
          <p style="margin-top: 24px;">— <strong>The Ardena Group Team</strong></p>
        </div>
        """
        ok = await send_email(client.email, subject, html)
        if ok:
            logger.info("[BookingEmail] Pickup reminder sent to %s for booking_id=%s", client.email, booking_id)

        # Push notification
        try:
            pickup_time_str = _fmt_date(booking.start_date)
            pickup_loc = booking.pickup_location or "the pickup location"
            await notify_pickup_reminder(
                client.id,
                getattr(booking, "booking_id", ""),
                car_name,
                pickup_time_str,
                pickup_loc,
            )
        except Exception as push_err:
            logger.warning("[BookingEmail] Pickup push failed for booking_id=%s: %s", booking_id, push_err)

        return ok

    except Exception as e:
        logger.exception("[BookingEmail] Pickup reminder failed for booking_id=%s: %s", booking_id, e)
        return False


def send_pickup_reminder_email(booking_id: int) -> bool:
    """Sync wrapper — safe to call from background threads."""
    try:
        return _run_on_main_loop(_async_send_pickup_reminder_email(booking_id))
    except Exception as e:
        logger.exception("[BookingEmail] Pickup reminder sync-wrapper failed for booking_id=%s: %s", booking_id, e)
        return False
