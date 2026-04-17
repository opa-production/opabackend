"""
Paystack payment integration.
Hosted payment page — no card data is collected or stored on our end.
Paystack's API base: https://api.paystack.co
"""
import hashlib
import hmac
import logging
import os
from typing import Dict, Any, Optional

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "")
PAYSTACK_BASE_URL = "https://api.paystack.co"


def initialize_transaction(
    email: str,
    amount_kes: float,
    reference: str,
    callback_url: str,
    metadata: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Initialize a Paystack transaction and return the hosted payment authorization_url.
    amount_kes is in KES; Paystack requires the amount in the smallest currency unit (kobo),
    so we multiply by 100.
    """
    if not PAYSTACK_SECRET_KEY:
        logger.error("[PAYSTACK] PAYSTACK_SECRET_KEY not configured")
        return {"status": "error", "message": "Paystack is not configured. Set PAYSTACK_SECRET_KEY."}

    amount_kobo = int(round(amount_kes * 100))
    payload: Dict[str, Any] = {
        "email": email,
        "amount": amount_kobo,
        "currency": "KES",
        "reference": reference,
        "callback_url": callback_url,
    }
    if metadata:
        payload["metadata"] = metadata

    try:
        response = requests.post(
            f"{PAYSTACK_BASE_URL}/transaction/initialize",
            json=payload,
            headers={
                "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        data = response.json()
        if response.status_code == 200 and data.get("status"):
            tx = data["data"]
            logger.info("[PAYSTACK] Transaction initialized: ref=%s", reference)
            return {
                "status": "success",
                "authorization_url": tx["authorization_url"],
                "access_code": tx["access_code"],
                "reference": tx["reference"],
            }
        msg = data.get("message", "Paystack initialization error")
        logger.error("[PAYSTACK] Init failed: %s", msg)
        return {"status": "error", "message": msg}
    except Exception as e:
        logger.error("[PAYSTACK] Init exception: %s", e)
        return {"status": "error", "message": f"Connection error: {e}"}


def verify_transaction(reference: str) -> Dict[str, Any]:
    """
    Verify a Paystack transaction by reference.
    Returns normalized dict with payment_status ("success" | "failed" | "abandoned"),
    authorization_code, card_last4, card_brand, and channel.
    """
    if not PAYSTACK_SECRET_KEY:
        return {"status": "error", "message": "Paystack is not configured"}

    try:
        response = requests.get(
            f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}",
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"},
            timeout=30,
        )
        data = response.json()
        if response.status_code == 200 and data.get("status"):
            tx = data["data"]
            auth = tx.get("authorization") or {}
            payment_status = tx.get("status", "")
            logger.info("[PAYSTACK] Verified: ref=%s, status=%s", reference, payment_status)
            return {
                "status": "success",
                "payment_status": payment_status,
                "reference": tx.get("reference"),
                "amount_kobo": tx.get("amount"),
                "currency": tx.get("currency"),
                "channel": tx.get("channel"),
                "authorization_code": auth.get("authorization_code"),
                "card_last4": auth.get("last4"),
                "card_brand": auth.get("card_type"),
                "bank": auth.get("bank"),
                "message": data.get("message", ""),
            }
        msg = data.get("message", "Verification failed")
        logger.error("[PAYSTACK] Verify failed: ref=%s, msg=%s", reference, msg)
        return {"status": "error", "message": msg}
    except Exception as e:
        logger.error("[PAYSTACK] Verify exception: %s", e)
        return {"status": "error", "message": f"Connection error: {e}"}


def verify_webhook_signature(payload_bytes: bytes, signature: str) -> bool:
    """
    Verify that the incoming webhook request originated from Paystack.
    Paystack signs the raw request body with PAYSTACK_SECRET_KEY using HMAC-SHA512
    and sends the hex digest in X-Paystack-Signature.
    """
    if not PAYSTACK_SECRET_KEY:
        return False
    expected = hmac.new(
        PAYSTACK_SECRET_KEY.encode("utf-8"),
        payload_bytes,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")
