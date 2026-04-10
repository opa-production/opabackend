"""
Send booking-related emails: ticket after payment, rental agreement, pickup reminder.
Uses SendGrid via email_welcome. Runs with its own DB session (safe for background threads).
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.models import Booking, Car, Client, Host, Payment, PaymentStatus
from app.services.receipt import build_receipt_pdf
from app.services.agreement import build_agreement_pdf
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


def send_rental_agreement_emails(booking_id: int) -> bool:
    """
    Build the rental agreement PDF and send it to both the client and the host.
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
            logger.warning("[AgreementEmail] booking_id=%s not found", booking_id)
            return False

        client = getattr(booking, "client", None)
        car = getattr(booking, "car", None)
        host = getattr(booking, "host", None) or (car.host if car else None)

        paid_payment = (
            db.query(Payment)
            .filter(Payment.booking_id == booking_id, Payment.status == PaymentStatus.COMPLETED)
            .order_by(Payment.id.desc())
            .first()
        )

        pdf_bytes = build_agreement_pdf(booking, paid_payment)
        booking_ref = getattr(booking, "booking_id", f"#{booking_id}")
        filename = f"rental-agreement-{booking_ref}.pdf"
        subject = f"Your Rental Agreement — {booking_ref}"

        # --- send to client ---
        if client and client.email:
            client_first = (getattr(client, "full_name", None) or "there").split()[0]
            client_html = f"""
            <div style="font-family: sans-serif; max-width: 560px; margin: 0 auto;">
              <p>Hi {client_first},</p>
              <p>Your booking <strong>{booking_ref}</strong> is confirmed and your rental agreement is ready.</p>
              <p>Please find your <strong>Vehicle Rental Agreement</strong> attached to this email.
                 Keep it for your records — it contains all details about your rental, vehicle rules,
                 and your rights and obligations as a renter.</p>
              <p>If you have any questions before pickup, reply to this email or contact us at
                 <a href="mailto:hello@ardena.xyz">hello@ardena.xyz</a>.</p>
              <p style="margin-top: 24px;">Safe travels,<br><strong>The Ardena Group Team</strong></p>
            </div>
            """
            ok_client = send_email_with_attachment(
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
            ok_client = False

        # --- send to host ---
        if host and host.email:
            host_first = (getattr(host, "full_name", None) or "there").split()[0]
            car_label = ""
            if car:
                car_label = f"{getattr(car, 'name', '')} {getattr(car, 'model', '')}".strip()
            host_html = f"""
            <div style="font-family: sans-serif; max-width: 560px; margin: 0 auto;">
              <p>Hi {host_first},</p>
              <p>A new booking for your vehicle{' <strong>' + car_label + '</strong>' if car_label else ''} has been confirmed
                 and paid (Booking ID: <strong>{booking_ref}</strong>).</p>
              <p>Please find the <strong>Vehicle Rental Agreement</strong> attached. It contains the renter's
                 details, rental period, agreed financial terms, and standard platform rules.
                 Keep this document for your records.</p>
              <p>If you have any concerns about the booking, contact us at
                 <a href="mailto:hello@ardena.xyz">hello@ardena.xyz</a>.</p>
              <p style="margin-top: 24px;">Thank you for hosting on Ardena,<br><strong>The Ardena Group Team</strong></p>
            </div>
            """
            ok_host = send_email_with_attachment(
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
            ok_host = False

        return ok_client or ok_host

    except Exception as e:
        logger.exception("[AgreementEmail] Failed for booking_id=%s: %s", booking_id, e)
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
