"""
Send booking-related emails: ticket after payment, pickup reminder 24h before.
Uses SendGrid via email_welcome. Runs with its own DB session (safe for background threads).
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.models import Booking, Car, Client, Payment, PaymentStatus
from app.services.receipt import build_receipt_pdf
from app.services.email_welcome import send_email, send_email_with_attachment

logger = logging.getLogger(__name__)


def _fmt_date(dt):
    if dt is None:
        return "—"
    if getattr(dt, "tzinfo", None):
        dt = dt.replace(tzinfo=timezone.utc).astimezone(tz=None)
    return dt.strftime("%d %b %Y %H:%M")


def send_booking_ticket_email(booking_id: int) -> bool:
    """
    Load booking (with car, client, host), build receipt PDF, and send ticket email to the client.
    Call from a background thread after successful payment. Uses its own DB session.
    """
    db = SessionLocal()
    try:
        booking = (
            db.query(Booking)
            .options(
                joinedload(Booking.car).joinedload(Car.host),
                joinedload(Booking.client),
            )
            .filter(Booking.id == booking_id)
            .first()
        )
        if not booking:
            logger.warning("[BookingEmail] Ticket: booking_id=%s not found", booking_id)
            return False
        client = getattr(booking, "client", None)
        if not client:
            client = db.query(Client).filter(Client.id == booking.client_id).first()
        if not client or not client.email:
            logger.warning("[BookingEmail] Ticket: no client email for booking_id=%s", booking_id)
            return False
        to_email = client.email
        client_name = getattr(client, "full_name", None) or "there"
        first_name = (client_name.split() or ["there"])[0]

        paid_payment = (
            db.query(Payment)
            .filter(Payment.booking_id == booking_id, Payment.status == PaymentStatus.COMPLETED)
            .order_by(Payment.id.desc())
            .first()
        )
        pdf_bytes = build_receipt_pdf(booking, paid_payment)
        subject = f"Your booking confirmation — {getattr(booking, 'booking_id', '')}"
        html = f"""
        <div style="font-family: sans-serif; max-width: 560px; margin:  auto;">
          <p>Hi {first_name},</p>
          <p>Your payment was successful. Your booking is confirmed.</p>
          <p><strong>Booking ID:</strong> {getattr(booking, 'booking_id', '')}</p>
          <p><strong>Pick-up:</strong> {_fmt_date(getattr(booking, 'start_date', None))} — {getattr(booking, 'pickup_location', '') or '—'}</p>
          <p><strong>Return:</strong> {_fmt_date(getattr(booking, 'end_date', None))} — {getattr(booking, 'return_location', '') or '—'}</p>
          <p>Please find your receipt attached. See you soon!</p>
          <p style="margin-top: 24px;">— <strong>The Ardena Group Team</strong></p>
        </div>
        """
        ok = send_email_with_attachment(
            to=to_email,
            subject=subject,
            html=html,
            attachment_bytes=pdf_bytes,
            filename=f"booking-receipt-{getattr(booking, 'booking_id', booking_id)}.pdf",
        )
        if ok:
            logger.info("[BookingEmail] Ticket sent to %s for booking_id=%s", to_email, booking_id)
        return ok
    except Exception as e:
        logger.exception("[BookingEmail] Ticket failed for booking_id=%s: %s", booking_id, e)
        return False
    finally:
        db.close()


def send_pickup_reminder_email(booking_id: int) -> bool:
    """
    Send a reminder to the client that pickup is in 24 hours. Uses its own DB session.
    """
    db = SessionLocal()
    try:
        booking = (
            db.query(Booking)
            .options(
                joinedload(Booking.car),
                joinedload(Booking.client),
            )
            .filter(Booking.id == booking_id)
            .first()
        )
        if not booking:
            return False
        client = getattr(booking, "client", None) or db.query(Client).filter(Client.id == booking.client_id).first()
        if not client or not getattr(client, "email_notifications_enabled", True):
            return False
        to_email = client.email
        if not to_email:
            return False
        client_name = getattr(client, "full_name", None) or "there"
        first_name = (client_name.split() or ["there"])[0]
        car = getattr(booking, "car", None)
        car_name = ""
        if car:
            car_name = f"{getattr(car, 'name', '')} {getattr(car, 'model', '')} {getattr(car, 'year', '')}".strip() or "your vehicle"
        subject = f"Reminder: Pick up your car tomorrow — {getattr(booking, 'booking_id', '')}"
        html = f"""
        <div style="font-family: sans-serif; max-width: 560px; margin: 0 auto;">
          <p>Hi {first_name},</p>
          <p>This is a friendly reminder that your car rental pickup is <strong>in 24 hours</strong>.</p>
          <p><strong>Booking ID:</strong> {getattr(booking, 'booking_id', '')}</p>
          <p><strong>Vehicle:</strong> {car_name}</p>
          <p><strong>Pick-up time:</strong> {_fmt_date(getattr(booking, 'start_date', None))}</p>
          <p><strong>Pick-up location:</strong> {getattr(booking, 'pickup_location', '') or '—'}</p>
          <p>We look forward to seeing you. Safe travels!</p>
          <p style="margin-top: 24px;">— <strong>The Ardena Group Team</strong></p>
        </div>
        """
        ok = send_email(to_email, subject, html)
        if ok:
            logger.info("[BookingEmail] Pickup reminder sent to %s for booking_id=%s", to_email, booking_id)
        return ok
    except Exception as e:
        logger.exception("[BookingEmail] Pickup reminder failed for booking_id=%s: %s", booking_id, e)
        return False
    finally:
        db.close()
