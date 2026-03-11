"""
Email sending via SendGrid: welcome emails and generic send for password reset etc.
"""
import base64
import logging
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

FROM_NAME = "Ardena Group Team"
DEFAULT_FROM = "Ardena Group Team <hello@ardena.xyz>"


def _get_from_email() -> str:
    return settings.SENDGRID_FROM_EMAIL or DEFAULT_FROM


def send_email(to: str, subject: str, html: str) -> bool:
    """
    Send one email via SendGrid (no attachments).
    Returns True on success, False on failure (logs error).
    Use this for welcome emails, password reset, etc.
    """
    if not settings.SENDGRID_API_KEY:
        logger.warning("[Email] SENDGRID_API_KEY not set; skipping send")
        return False
    from_email = _get_from_email()
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        message = Mail(
            from_email=from_email,
            to_emails=to,
            subject=subject,
            html_content=html,
        )
        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        sg.send(message)
        logger.info(f"[Email] Sent to {to}: {subject}")
        return True
    except Exception as e:
        logger.exception(f"[Email] Failed to send to {to}: {e}")
        return False


def send_email_with_attachment(
    to: str,
    subject: str,
    html: str,
    attachment_bytes: bytes,
    filename: str,
    mime_type: str = "application/pdf",
    attachment_disposition: str = "attachment",
) -> bool:
    """
    Send one email via SendGrid with a single attachment.
    Intended for things like data export PDFs or receipts.
    """
    if not settings.SENDGRID_API_KEY:
        logger.warning("[Email] SENDGRID_API_KEY not set; skipping send with attachment")
        return False

    from_email = _get_from_email()

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import (
            Mail,
            Attachment,
            FileContent,
            FileName,
            FileType,
            Disposition,
        )

        encoded_file = base64.b64encode(attachment_bytes).decode("utf-8")

        attachment = Attachment(
            FileContent(encoded_file),
            FileName(filename),
            FileType(mime_type),
            Disposition(attachment_disposition),
        )

        message = Mail(
            from_email=from_email,
            to_emails=to,
            subject=subject,
            html_content=html,
        )
        message.attachment = attachment

        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        sg.send(message)
        logger.info(f"[Email] Sent with attachment to {to}: {subject} ({filename})")
        return True
    except Exception as e:
        logger.exception(
            f"[Email] Failed to send with attachment to {to} ({filename}): {e}"
        )
        return False


def send_welcome_email_client(to_email: str, full_name: str) -> bool:
    """
    Send welcome email to a new client (car renter).
    """
    subject = "Welcome to Ardena — Your journey starts here"
    first_name = full_name.split()[0] if full_name else "there"
    html = f"""
    <div style="font-family: sans-serif; max-width: 560px; margin: 0 auto;">
      <p>Dear {first_name},</p>
      <p>Thank you for joining Ardena. This isn't just another app — it's a place where we help people like you get on the road without the hassle.</p>
      <p>We know that finding a car you can trust, at a price that works, can feel overwhelming. That's why we built Ardena: to connect you with real car owners who care, and to make every trip a little easier.</p>
      <p>You're not just a user to us. You're part of a community that believes in simple, honest, and human-friendly car rental. We're genuinely glad you're here.</p>
      <p>If you ever need a hand — whether it's choosing your first ride or understanding how things work — we're only a message away. We've got you.</p>
      <p>Welcome again. We can't wait to see where you go.</p>
      <p style="margin-top: 24px;">With warmth,<br><strong>The Ardena Group Team</strong></p>
    </div>
    """
    return send_email(to_email, subject, html)


def send_welcome_email_host(to_email: str, full_name: str) -> bool:
    """
    Send welcome email to a new host (car owner).
    """
    subject = "Welcome to Ardena — Your car, your impact"
    first_name = full_name.split()[0] if full_name else "there"
    html = f"""
    <div style="font-family: sans-serif; max-width: 560px; margin: 0 auto;">
      <p>Dear {first_name},</p>
      <p>Thank you for becoming part of Ardena. By listing your car with us, you're not just opening a side income — you're giving other people the freedom to move, to explore, and to get where they need to go.</p>
      <p>We know that trusting your vehicle with strangers can feel like a big step. That's why we're committed to building a safe, respectful community: verified renters, clear rules, and support every step of the way. You're in control of your car and your calendar.</p>
      <p>Every trip someone takes in your car is a story you're part of. We don't take that lightly, and we're here to make sure your experience as a host is smooth, fair, and rewarding.</p>
      <p>Welcome to the team. We're honoured to have you.</p>
      <p style="margin-top: 24px;">With gratitude,<br><strong>The Ardena Group Team</strong></p>
    </div>
    """
    return send_email(to_email, subject, html)
