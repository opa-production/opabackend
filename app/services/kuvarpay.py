"""
KuvarPay crypto payment service.
Handles checkout session creation and webhook signature verification.
"""
import hashlib
import hmac
import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

KUVARPAY_BASE_URL = "https://payment.kuvarpay.com"


async def create_checkout_session(
    amount_ksh: float,
    booking_id: str,
    client_email: Optional[str] = None,
    client_name: Optional[str] = None,
) -> dict:
    """
    Create a KuvarPay checkout session via the KuvarPay REST API.
    Returns the full session object (contains sessionId, status, authToken).
    """
    payload: dict = {
        "amount": round(amount_ksh, 2),
        "currency": "KES",
        "description": f"Ardena car booking {booking_id}",
        "callbackUrl": f"https://api.ardena.xyz/api/v1/kuvarpay/webhook",
        "metadata": {
            "booking_id": booking_id,
            "platform": "ardena",
        },
    }
    if client_email:
        payload["customer"] = {"email": client_email, "name": client_name or ""}

    headers = {
        "Authorization": f"Bearer {settings.KUVARPAY_SECRET_KEY}",
        "Content-Type": "application/json",
        "X-Business-Id": settings.KUVARPAY_BUSINESS_ID or "",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{KUVARPAY_BASE_URL}/api/v1/checkout-sessions",
            json=payload,
            headers=headers,
        )
        if not resp.is_success:
            logger.error(
                "[KUVARPAY] %s %s — response body: %s",
                resp.status_code,
                resp.url,
                resp.text,
            )
        resp.raise_for_status()
        return resp.json()


async def get_checkout_session(session_id: str) -> dict:
    """Fetch the current state of a KuvarPay checkout session."""
    headers = {
        "Authorization": f"Bearer {settings.KUVARPAY_SECRET_KEY}",
        "X-Business-Id": settings.KUVARPAY_BUSINESS_ID or "",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{KUVARPAY_BASE_URL}/api/v1/checkout-sessions/{session_id}",
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()


def verify_webhook_signature(raw_body: bytes, signature_header: Optional[str]) -> bool:
    """
    Verify the X-KuvarPay-Signature header.
    Expected format: sha256=<hex_digest>
    Uses constant-time comparison to resist timing attacks.
    """
    if not signature_header or not settings.KUVARPAY_WEBHOOK_SECRET:
        return False
    try:
        algo, expected = signature_header.split("=", 1)
    except ValueError:
        return False
    if algo != "sha256":
        return False

    mac = hmac.new(
        settings.KUVARPAY_WEBHOOK_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    )
    digest = mac.hexdigest()
    return hmac.compare_digest(digest, expected)
