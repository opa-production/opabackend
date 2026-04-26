"""
Email sending via Resend: welcome emails, password reset, and generic send.
Domain verified: ardena.co.ke  — all mail comes from hello@ardena.co.ke
"""
import asyncio
import base64
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import resend

from app.config import settings

logger = logging.getLogger(__name__)

FROM_ADDRESS = "Ardena Group Team <hello@ardena.co.ke>"

# Global thread pool for email sending
email_executor = ThreadPoolExecutor(max_workers=3)


def _configured() -> bool:
    if not settings.RESEND_API_KEY:
        logger.warning("[Email] RESEND_API_KEY not set; skipping send")
        return False
    resend.api_key = settings.RESEND_API_KEY
    return True


def _send_email_sync(to: str, subject: str, html: str) -> bool:
    if not _configured():
        return False
    try:
        resend.Emails.send({
            "from": FROM_ADDRESS,
            "to": [to],
            "subject": subject,
            "html": html,
        })
        logger.info("[Email] Sent to %s: %s", to, subject)
        return True
    except Exception as e:
        logger.exception("[Email] Failed to send to %s: %s", to, e)
        return False


async def send_email(to: str, subject: str, html: str) -> bool:
    """
    Send one email via Resend (no attachments).
    Non-blocking — runs in a thread pool.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(email_executor, _send_email_sync, to, subject, html)


def _send_email_with_attachment_sync(
    to: str,
    subject: str,
    html: str,
    attachment_bytes: bytes,
    filename: str,
    mime_type: str,
    attachment_disposition: str,
) -> bool:
    if not _configured():
        return False
    try:
        resend.Emails.send({
            "from": FROM_ADDRESS,
            "to": [to],
            "subject": subject,
            "html": html,
            "attachments": [{
                "filename": filename,
                "content": base64.b64encode(attachment_bytes).decode("utf-8"),
            }],
        })
        logger.info("[Email] Sent with attachment to %s: %s (%s)", to, subject, filename)
        return True
    except Exception as e:
        logger.exception("[Email] Failed to send with attachment to %s (%s): %s", to, filename, e)
        return False


async def send_email_with_attachment(
    to: str,
    subject: str,
    html: str,
    attachment_bytes: bytes,
    filename: str,
    mime_type: str = "application/pdf",
    attachment_disposition: str = "attachment",
) -> bool:
    """
    Send one email via Resend with a single attachment.
    Non-blocking — runs in a thread pool.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        email_executor,
        _send_email_with_attachment_sync,
        to,
        subject,
        html,
        attachment_bytes,
        filename,
        mime_type,
        attachment_disposition,
    )


async def send_welcome_email_client(to_email: str, full_name: str) -> bool:
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
    return await send_email(to_email, subject, html)


async def send_welcome_email_host(to_email: str, full_name: str) -> bool:
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
    return await send_email(to_email, subject, html)


async def send_forgotpassword_email(to_email: str, full_name: str, reset_link: str) -> bool:
    subject = "Ardena Password Reset Request"
    first_name = full_name.split()[0] if full_name else "there"
    html = f"""
    <div style="font-family: sans-serif; max-width: 560px; margin: 0 auto;">
      <p>Dear {first_name},</p>
      <p>We received a request to reset your password for your Ardena account. If you made this request, please click the link below to set a new password:</p>
      <p><a href="{reset_link}" style="background-color: #007BFF; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px;">Reset My Password</a></p>
      <p>If you did not request a password reset, please ignore this email. Your account is safe.</p>
      <p style="margin-top: 24px;">Best regards,<br><strong>The Ardena Group Team</strong></p>
    </div>
    """
    return await send_email(to_email, subject, html)
