"""
Dojah KYC service.

Step 1 — Government ID lookup (prefill): call Dojah's identity API with the user's
          ID number to retrieve their official name, DOB, and gender.
Step 2 — Widget init: generate a unique reference_id and return the Dojah widget
          credentials so the mobile app can launch the EasyLookup widget for
          document scan + liveness + face match.
Step 3 — Webhook: Dojah POSTs the result back; dojah_webhook.py handles that.
"""
import hashlib
import hmac
import logging
import uuid
from typing import Any, Dict, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SAFE_ERROR = "Identity verification is temporarily unavailable. Please try again later."

# Dojah endpoint paths per country+id_type.
# Kenya has country-specific paths; fallback used for unlisted countries.
_KE_PATHS: Dict[str, str] = {
    "NATIONAL_ID":    "/api/v1/ke/kyc/id",
    "PASSPORT":       "/api/v1/ke/kyc/passport",
    "DRIVERS_LICENSE": "/api/v1/ke/kyc/dl",
}
_DEFAULT_PATHS: Dict[str, str] = {
    "NATIONAL_ID": "/api/v1/kyc/id",
    "PASSPORT":    "/api/v1/kyc/passport",
    "DRIVERS_LICENSE": "/api/v1/kyc/dl",
}
_COUNTRY_PATHS: Dict[str, Dict[str, str]] = {
    "KE": _KE_PATHS,
}


def _dojah_headers() -> Dict[str, str]:
    return {
        "AppId": settings.DOJAH_APP_ID or "",
        "Authorization": settings.DOJAH_SECRET_KEY or "",
        "Content-Type": "application/json",
    }


def _base_url() -> str:
    return (settings.DOJAH_BASE_URL or "https://api.dojah.io").rstrip("/")


async def lookup_government_id(
    id_type: str,
    id_number: str,
    country: str = "KE",
) -> Dict[str, Any]:
    """
    Call Dojah's identity lookup API and return normalised identity data.

    Returns dict with keys: verified_name, date_of_birth, gender, id_number, id_type, country.
    Raises ValueError with a user-safe message on any failure.
    """
    country_upper = country.upper()
    id_type_upper = id_type.upper()

    country_paths = _COUNTRY_PATHS.get(country_upper, _DEFAULT_PATHS)
    path = country_paths.get(id_type_upper)
    if not path:
        raise ValueError(f"Unsupported id_type '{id_type}'. Use NATIONAL_ID, PASSPORT, or DRIVERS_LICENSE.")

    if not settings.DOJAH_APP_ID or not settings.DOJAH_SECRET_KEY:
        logger.error("[Dojah] DOJAH_APP_ID or DOJAH_SECRET_KEY not configured")
        raise ValueError(SAFE_ERROR)

    url = _base_url() + path
    params = {"id": id_number.strip()}

    logger.info("[Dojah] Lookup request: country=%s id_type=%s url=%s", country_upper, id_type_upper, url)

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            resp = await client.get(url, params=params, headers=_dojah_headers())

        if resp.status_code in (301, 302, 307, 308):
            location = resp.headers.get("location", "(no location header)")
            logger.error(
                "[Dojah] Lookup redirected %s → %s  (url=%s) — check Dojah dashboard: "
                "is this id_type enabled for country=%s on your app?",
                resp.status_code, location, url, country_upper,
            )
            raise ValueError(SAFE_ERROR)
        if resp.status_code == 404:
            raise ValueError("No record found for the provided ID number. Please check and try again.")
        if resp.status_code in (401, 403):
            logger.error("[Dojah] Auth error %s on lookup — check DOJAH_APP_ID / DOJAH_SECRET_KEY", resp.status_code)
            raise ValueError(SAFE_ERROR)
        if not resp.is_success:
            body = resp.text[:300]
            logger.error("[Dojah] Lookup error %s: %s", resp.status_code, body)
            raise ValueError(SAFE_ERROR)

        data = resp.json()
    except httpx.RequestError as exc:
        logger.exception("[Dojah] Lookup connection error: %s", exc)
        raise ValueError(SAFE_ERROR) from exc

    entity = data.get("entity") or {}
    if not entity:
        logger.warning("[Dojah] Empty entity in lookup response: %s", data)
        raise ValueError("No record found for the provided ID number. Please check and try again.")

    first = (entity.get("first_name") or "").strip()
    middle = (entity.get("middle_name") or "").strip()
    last = (entity.get("last_name") or "").strip()
    full = (entity.get("full_name") or "").strip()
    verified_name = full or " ".join(filter(None, [first, middle, last])) or None

    raw_dob = entity.get("date_of_birth") or entity.get("dob")
    date_of_birth: Optional[str] = raw_dob.strip() if isinstance(raw_dob, str) else None

    gender_raw = (entity.get("gender") or "").strip().lower()
    gender = {"m": "male", "f": "female", "male": "male", "female": "female"}.get(gender_raw)

    logger.info("[Dojah] Lookup success: id_type=%s country=%s name=%s", id_type, country, verified_name)

    return {
        "verified_name": verified_name,
        "date_of_birth": date_of_birth,
        "gender": gender,
        "id_number": id_number.strip(),
        "id_type": id_type.upper(),
        "country": country.upper(),
        "photo": entity.get("photo"),  # base64 from govt DB; not stored, returned for client display only
    }


def generate_widget_credentials() -> Dict[str, str]:
    """
    Generate a unique reference_id and return the widget credentials the mobile app
    needs to launch the Dojah EasyLookup widget.
    """
    if not settings.DOJAH_APP_ID or not settings.DOJAH_PUBLIC_KEY or not settings.DOJAH_WIDGET_ID:
        logger.error("[Dojah] Widget credentials not fully configured")
        raise ValueError(SAFE_ERROR)

    reference_id = str(uuid.uuid4())
    return {
        "reference_id": reference_id,
        "app_id": settings.DOJAH_APP_ID,
        "p_key": settings.DOJAH_PUBLIC_KEY,
        "widget_id": settings.DOJAH_WIDGET_ID,
    }


def verify_webhook_signature(payload_bytes: bytes, signature: str) -> bool:
    """
    Validate the X-Dojah-Signature header (HMAC-SHA512).
    Returns True if the signature matches or if no webhook secret is configured (dev mode).
    """
    secret = settings.DOJAH_WEBHOOK_SECRET
    if not secret:
        logger.warning("[Dojah] DOJAH_WEBHOOK_SECRET not set — skipping webhook signature check")
        return True

    expected = hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(expected, (signature or "").strip())


def parse_webhook_payload(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalise a Dojah EasyLookup webhook payload into a flat dict.

    Dojah delivers via Convoy with the event in a "data" key.
    "data" may be a nested dict or a JSON-encoded string — both are handled.
    Falls back to root body for direct/legacy payloads.
    """
    raw_data = body.get("data")
    if isinstance(raw_data, dict):
        event = raw_data
    elif isinstance(raw_data, str):
        try:
            import json as _json
            parsed = _json.loads(raw_data)
            event = parsed if isinstance(parsed, dict) else body
        except Exception:
            event = body
    else:
        event = body

    reference_id = (event.get("referenceId") or event.get("reference_id") or "").strip()
    raw_status = (event.get("status") or "").lower()
    status = "approved" if raw_status == "success" else ("declined" if raw_status in ("failed", "error") else "pending")

    verifications = event.get("verifications") or {}

    # Government data
    gov = verifications.get("government_data") or {}
    verified_name = None
    verified_dob = None
    verified_gender = None
    if isinstance(gov, dict):
        first = (gov.get("first_name") or "").strip()
        middle = (gov.get("middle_name") or "").strip()
        last = (gov.get("last_name") or "").strip()
        full = (gov.get("full_name") or "").strip()
        verified_name = full or " ".join(filter(None, [first, middle, last])) or None
        raw_dob = gov.get("date_of_birth") or gov.get("dob")
        verified_dob = raw_dob.strip() if isinstance(raw_dob, str) else None
        raw_gender = (gov.get("gender") or "").strip().lower()
        verified_gender = {"m": "male", "f": "female", "male": "male", "female": "female"}.get(raw_gender)

    # Face match confidence
    face = verifications.get("face_id") or {}
    face_match_score: Optional[float] = None
    if isinstance(face, dict):
        conf = face.get("confidence") or face.get("score")
        try:
            face_match_score = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            pass

    # Document type
    id_check = verifications.get("id") or {}
    document_type = None
    if isinstance(id_check, dict):
        document_type = (id_check.get("id_type") or id_check.get("document_type") or "").lower() or None

    # Reason for failure
    decision_reason = None
    if status == "declined":
        decision_reason = event.get("reason") or event.get("message")

    return {
        "reference_id": reference_id,
        "status": status,
        "document_type": document_type,
        "verified_name": verified_name,
        "verified_dob": verified_dob,
        "verified_gender": verified_gender,
        "face_match_score": face_match_score,
        "decision_reason": decision_reason,
    }
