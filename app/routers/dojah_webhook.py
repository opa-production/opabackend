"""
Dojah EasyLookup webhook handler.

Dojah POSTs the verification decision here when the user completes the widget flow.
Configure this URL in your Dojah dashboard → App Settings → Webhook URL:
  https://api.ardena.xyz/api/v1/dojah/webhook

The handler:
  1. Validates the X-Dojah-Signature HMAC-SHA512 header.
  2. Finds the pending ClientKyc or HostKyc row by reference_id.
  3. Updates it with the verified name, DOB, gender, face match score, and status.
  4. Updates the user's profile (full_name, date_of_birth, gender) if not already set.
"""
import json
import logging
from datetime import date as date_type, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from app.database import SessionLocal
from app.models import ClientKyc, HostKyc, Client, Host
from app.services.dojah_kyc import verify_webhook_signature, parse_webhook_payload

router = APIRouter(tags=["Dojah Webhook"])
logger = logging.getLogger(__name__)


def _parse_date(raw: Optional[str]) -> Optional[date_type]:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except (ValueError, TypeError):
            pass
    return None


@router.post("/dojah/webhook")
async def dojah_webhook(request: Request) -> Response:
    """
    Receive Dojah EasyLookup decision webhook and update KYC records.
    Always return 200 so Dojah does not retry on our processing errors.
    """
    body_bytes = await request.body()

    try:
        body = json.loads(body_bytes) if body_bytes else {}
    except Exception as exc:
        logger.warning("[Dojah webhook] Invalid JSON: %s", exc)
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    if not isinstance(body, dict):
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    sig_header = (
        request.headers.get("X-Dojah-Signature")
        or request.headers.get("x-dojah-signature")
        or ""
    )
    if not verify_webhook_signature(body_bytes, sig_header):
        logger.warning("[Dojah webhook] Invalid signature — rejected")
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    # Log raw body so we can see exactly what Dojah sends
    logger.info("[Dojah webhook] raw body: %s", body_bytes[:800].decode("utf-8", errors="replace"))

    parsed = parse_webhook_payload(body)
    reference_id = parsed["reference_id"]

    if not reference_id:
        data_val = body.get("data")
        data_preview = list(data_val.keys()) if isinstance(data_val, dict) else repr(data_val)[:300]
        logger.warning("[Dojah webhook] Missing referenceId — top-level keys: %s, data: %s",
                       list(body.keys()), data_preview)
        return Response(status_code=status.HTTP_200_OK)

    logger.info(
        "[Dojah webhook] ref=%s status=%s name=%s face_score=%s",
        reference_id, parsed["status"], parsed.get("verified_name"), parsed.get("face_match_score"),
    )

    verified_dob = _parse_date(parsed.get("verified_dob"))
    verified_at = datetime.now(timezone.utc)

    async with SessionLocal() as db:
        try:
            # Try client_kycs first
            client_result = await db.execute(
                select(ClientKyc).filter(ClientKyc.dojah_reference_id == reference_id)
            )
            client_kyc = client_result.scalar_one_or_none()

            host_result = await db.execute(
                select(HostKyc).filter(HostKyc.dojah_reference_id == reference_id)
            )
            host_kyc = host_result.scalar_one_or_none()

            if client_kyc:
                client_kyc.status = parsed["status"]
                client_kyc.document_type = parsed.get("document_type")
                client_kyc.verified_name = parsed.get("verified_name")
                client_kyc.verified_dob = verified_dob
                client_kyc.verified_gender = parsed.get("verified_gender")
                client_kyc.face_match_score = parsed.get("face_match_score")
                client_kyc.decision_reason = parsed.get("decision_reason")
                client_kyc.verified_at = verified_at

                # Update client profile with government-verified data (only overwrite if set)
                if parsed["status"] == "approved":
                    client_res = await db.execute(
                        select(Client).filter(Client.id == client_kyc.client_id)
                    )
                    client = client_res.scalar_one_or_none()
                    if client:
                        if parsed.get("verified_name"):
                            client.full_name = parsed["verified_name"]
                        if verified_dob and not client.date_of_birth:
                            client.date_of_birth = verified_dob
                        if parsed.get("verified_gender") and not client.gender:
                            client.gender = parsed["verified_gender"]

                logger.info("[Dojah webhook] Updated client_kyc id=%s ref=%s status=%s",
                            client_kyc.id, reference_id, parsed["status"])

            elif host_kyc:
                host_kyc.status = parsed["status"]
                host_kyc.document_type = parsed.get("document_type")
                host_kyc.verified_name = parsed.get("verified_name")
                host_kyc.verified_dob = verified_dob
                host_kyc.verified_gender = parsed.get("verified_gender")
                host_kyc.face_match_score = parsed.get("face_match_score")
                host_kyc.decision_reason = parsed.get("decision_reason")
                host_kyc.verified_at = verified_at

                if parsed["status"] == "approved":
                    host_res = await db.execute(
                        select(Host).filter(Host.id == host_kyc.host_id)
                    )
                    host = host_res.scalar_one_or_none()
                    if host and parsed.get("verified_name"):
                        host.full_name = parsed["verified_name"]

                logger.info("[Dojah webhook] Updated host_kyc id=%s ref=%s status=%s",
                            host_kyc.id, reference_id, parsed["status"])

            else:
                logger.warning(
                    "[Dojah webhook] No KYC row found for ref=%s — widget may not have been initialized via /kyc/initialize",
                    reference_id,
                )

            await db.commit()

        except Exception as exc:
            logger.exception("[Dojah webhook] DB error: %s", exc)
            await db.rollback()
            return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response(status_code=status.HTTP_200_OK)
