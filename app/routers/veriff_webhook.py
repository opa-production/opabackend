"""
Veriff decision webhook: receives verification result and updates HostKyc.
Configure this URL in Veriff Customer Portal → Integration → Webhook decisions URL.
E.g. https://api.ardena.xyz/api/v1/veriff/webhook
"""
import hmac
import hashlib
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response, status

from app.config import settings
from app.database import SessionLocal
from app.models import HostKyc

router = APIRouter(tags=["Veriff Webhook"])
logger = logging.getLogger(__name__)


def _get_webhook_secret() -> str | None:
    """Use VERIFF_WEBHOOK_SECRET, or SHARED_SECRET_KEY, or MASTER_SECRET_KEY (first set)."""
    for key in (
        getattr(settings, "VERIFF_WEBHOOK_SECRET", None),
        getattr(settings, "SHARED_SECRET_KEY", None),
        getattr(settings, "MASTER_SECRET_KEY", None),
    ):
        if key and str(key).strip():
            return str(key).strip()
    return None


def _parse_verified_at(payload: dict) -> datetime | None:
    for key in ("decisionTime", "decision_time", "submissionTime", "submission_time"):
        val = payload.get(key)
        if val:
            try:
                if isinstance(val, str):
                    return datetime.fromisoformat(val.replace("Z", "+00:00"))
                return val
            except Exception:
                pass
    ver = payload.get("verification") or {}
    for key in ("decisionTime", "decision_time"):
        val = ver.get(key)
        if val:
            try:
                if isinstance(val, str):
                    return datetime.fromisoformat(val.replace("Z", "+00:00"))
                return val
            except Exception:
                pass
    return None


def _parse_document_type(payload: dict) -> str | None:
    doc = payload.get("document") or payload.get("documentInfo") or {}
    if isinstance(doc, dict):
        return doc.get("type") or doc.get("documentType")
    return None


@router.post("/veriff/webhook")
async def veriff_webhook(request: Request) -> Response:
    """
    Veriff calls this when a verification decision is made.
    We update HostKyc by session id (or create from vendorData) and store status only.
    """
    body_bytes = await request.body()
    try:
        body = json.loads(body_bytes) if body_bytes else {}
    except Exception as e:
        logger.warning("Veriff webhook invalid JSON: %s", e)
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    if not isinstance(body, dict):
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    # Verify X-HMAC-SIGNATURE if any webhook secret is set (VERIFF_WEBHOOK_SECRET, SHARED_SECRET_KEY, or MASTER_SECRET_KEY)
    secret = _get_webhook_secret()
    if secret:
        sig_header = request.headers.get("X-HMAC-SIGNATURE") or request.headers.get("x-hmac-signature")
        if not sig_header:
            logger.warning(
                "Veriff webhook rejected: missing X-HMAC-SIGNATURE. "
                "Ensure Veriff dashboard has your webhook URL and that you set VERIFF_WEBHOOK_SECRET to the shared secret from Veriff."
            )
            return Response(status_code=status.HTTP_401_UNAUTHORIZED)
        expected = hmac.new(
            secret.encode("utf-8"),
            body_bytes,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, sig_header.strip()):
            logger.warning(
                "Veriff webhook rejected: invalid X-HMAC-SIGNATURE. "
                "VERIFF_WEBHOOK_SECRET must match the 'Shared secret' in Veriff Customer Portal → Integration → Webhooks."
            )
            return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    verification = body.get("verification") or {}
    # Veriff sends session UUID at top-level "id" or in verification.id or as sessionId
    session_id = (
        str(
            body.get("id")
            or verification.get("id")
            or body.get("sessionId")
            or body.get("verificationId")
            or ""
        )
    ).strip()
    status_val = (
        verification.get("status")
        or verification.get("decision")
        or body.get("status")
        or body.get("decision")
        or "unknown"
    )
    if isinstance(status_val, str):
        status_val = status_val.lower()
    decision_reason = (
        verification.get("reason")
        or verification.get("decisionReason")
        or body.get("reason")
        or body.get("decisionReason")
    )
    document_type = _parse_document_type(body) or _parse_document_type(verification)
    _at = _parse_verified_at(body) or _parse_verified_at(verification)
    if _at and _at.tzinfo is None:
        _at = _at.replace(tzinfo=timezone.utc)
    verified_at = _at or datetime.now(timezone.utc)

    if not session_id:
        logger.warning("Veriff webhook missing session/verification id. Top-level keys: %s", list(body.keys()))
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    logger.info(
        "Veriff webhook received: session_id=%s status=%s (will update host_kycs if row exists)",
        session_id,
        status_val,
    )

    db = SessionLocal()
    try:
        kyc = db.query(HostKyc).filter(HostKyc.veriff_session_id == session_id).first()
        if not kyc:
            vendor_data = body.get("vendorData") or (verification.get("vendorData"))
            if vendor_data is not None and str(vendor_data).isdigit():
                host_id = int(vendor_data)
                kyc = HostKyc(
                    host_id=host_id,
                    veriff_session_id=session_id,
                    status=status_val,
                    document_type=document_type,
                    decision_reason=decision_reason,
                    verified_at=verified_at,
                )
                db.add(kyc)
            else:
                logger.warning(
                    "Veriff webhook: no host_kycs row for session_id=%s and no vendorData in payload. "
                    "Ensure sessions are created via POST /host/kyc/session so veriff_session_id is stored.",
                    session_id,
                )
                return Response(status_code=status.HTTP_200_OK)  # 200 so Veriff doesn't retry
        else:
            kyc.status = status_val
            kyc.document_type = document_type
            kyc.decision_reason = decision_reason
            kyc.verified_at = verified_at
        db.commit()
        logger.info("Veriff webhook updated host_kyc session_id=%s status=%s", session_id, status_val)
    except Exception as e:
        logger.exception("Veriff webhook DB error: %s", e)
        db.rollback()
        return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        db.close()

    return Response(status_code=status.HTTP_200_OK)
