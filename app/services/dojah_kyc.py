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
    Normalise a Dojah EasyLookup webhook payload.

    Actual Dojah payload (array element) structure:
    {
      "reference_id": "<uuid>",
      "status": true,                        # boolean
      "verification_status": "Completed",    # string
      "id_type": "KE-ID",
      "message": "Successfully completed...",
      "data": {
        "user_data": { "data": { "first_name": "...", "last_name": "...", "dob": "..." } },
        "selfie":    { "data": { "match_score": ..., "liveness_score": ... } },
        ...
      }
    }
    """
    # reference_id at root
    reference_id = (body.get("reference_id") or body.get("referenceId") or "").strip()

    # Status: verification_status string takes priority over status boolean
    verification_status = (body.get("verification_status") or "").lower()
    status_bool = body.get("status")
    if verification_status in ("completed", "verified", "success") or status_bool is True:
        kyc_status = "approved"
    elif verification_status in ("failed", "rejected", "error", "declined") or status_bool is False:
        kyc_status = "declined"
    else:
        kyc_status = "pending"

    # Name and DOB from data.user_data.data
    inner_data = body.get("data") or {}
    user_data = (inner_data.get("user_data") or {}).get("data") or {}
    first = (user_data.get("first_name") or "").strip()
    middle = (user_data.get("middle_name") or "").strip()
    last = (user_data.get("last_name") or "").strip()
    verified_name = " ".join(filter(None, [first, middle, last])) or None

    raw_dob = user_data.get("dob") or user_data.get("date_of_birth")
    verified_dob = raw_dob.strip() if isinstance(raw_dob, str) else None

    # Gender not typically provided by Dojah for KE-ID
    verified_gender = None

    # Face/liveness score from data.selfie.data
    selfie_data = (inner_data.get("selfie") or {}).get("data") or {}
    face_match_score: Optional[float] = None
    try:
        score = selfie_data.get("match_score") or selfie_data.get("liveness_score")
        face_match_score = float(score) if score is not None else None
    except (TypeError, ValueError):
        pass

    # Document type from id_type or verification_type
    document_type = (body.get("id_type") or body.get("verification_type") or "").lower() or None

    decision_reason = None
    if kyc_status == "declined":
        decision_reason = body.get("message")

    return {
        "reference_id": reference_id,
        "status": kyc_status,
        "document_type": document_type,
        "verified_name": verified_name,
        "verified_dob": verified_dob,
        "verified_gender": verified_gender,
        "face_match_score": face_match_score,
        "decision_reason": decision_reason,
    }
