"""
Gava Connect / KRA PIN checker by ID service.

Flow:
  1. GET /v1/token/generate?grant_type=client_credentials  (Basic Auth)
  2. POST /checker/v1/pin  with {"TaxpayerType": "KE", "TaxpayerID": "<id_number>"}
     Returns {"TaxpayerPIN": "A000000000I", "TaxpayerName": "JANE ACHIENG OTIENO"}

Environment variables required:
    GAVACONNECT_CONSUMER_KEY
    GAVACONNECT_CONSUMER_SECRET
    GAVACONNECT_BASE_URL   (default: https://sbx.kra.go.ke — sandbox)
                            production: https://api.kra.go.ke
"""
import base64
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_TOKEN_PATH = "/v1/token/generate"
_PIN_CHECK_PATH = "/checker/v1/pin"


def _require_config() -> None:
    if not settings.GAVACONNECT_CONSUMER_KEY or not settings.GAVACONNECT_CONSUMER_SECRET:
        raise ValueError("GAVACONNECT_CONSUMER_KEY and GAVACONNECT_CONSUMER_SECRET must be set.")


async def _fetch_token(client: httpx.AsyncClient) -> str:
    credentials = base64.b64encode(
        f"{settings.GAVACONNECT_CONSUMER_KEY}:{settings.GAVACONNECT_CONSUMER_SECRET}".encode()
    ).decode()

    resp = await client.get(
        f"{settings.GAVACONNECT_BASE_URL}{_TOKEN_PATH}",
        params={"grant_type": "client_credentials"},
        headers={"Authorization": f"Basic {credentials}"},
        timeout=15,
    )

    if resp.status_code == 401:
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        raise ValueError(f"Gava Connect: invalid credentials — {data.get('errorMessage', '401')}")

    resp.raise_for_status()

    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise ValueError(f"Gava Connect did not return an access_token: {resp.text[:300]}")

    logger.info("[GavaConnect] OAuth token obtained")
    return token


async def check_id(id_number: str, taxpayer_type: str = "KE") -> dict:
    """
    Look up a national ID via the Gava Connect PIN Checker by ID.

    Returns a dict with:
        name     str  — TaxpayerName from KRA
        kra_pin  str  — TaxpayerPIN from KRA
        raw      dict — full API response

    Raises ValueError on auth / not-found / validation errors.
    """
    _require_config()

    async with httpx.AsyncClient(timeout=20) as client:
        token = await _fetch_token(client)

        resp = await client.post(
            f"{settings.GAVACONNECT_BASE_URL}{_PIN_CHECK_PATH}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"TaxpayerType": taxpayer_type, "TaxpayerID": id_number.strip()},
        )

        logger.warning(
            "[GavaConnect] /checker/v1/pin status=%s id=%.4s…",
            resp.status_code,
            id_number,
        )

        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}

        if resp.status_code == 401:
            raise ValueError("Gava Connect: token rejected (401).")

        # Error responses use ErrorCode / errorCode
        error_code = data.get("ErrorCode") or data.get("errorCode")
        if error_code:
            msg = data.get("ErrorMessage") or data.get("errorMessage") or f"Error {error_code}"
            raise ValueError(f"Gava Connect: {msg}")

        resp.raise_for_status()

        name = (data.get("TaxpayerName") or "").strip()
        kra_pin = (data.get("TaxpayerPIN") or "").strip()

        if not name:
            raise ValueError("Gava Connect returned no name for this ID number.")

        return {"name": name, "kra_pin": kra_pin, "raw": data}


def _name_tokens(name: str) -> set[str]:
    return {t.upper() for t in name.split() if len(t) > 1}


def names_match(entered: str, official: str, threshold: int = 2) -> tuple[bool, int]:
    """
    Return (passed, matched_count).
    Passes when at least `threshold` name tokens from `official` appear in `entered`.
    """
    entered_tokens = _name_tokens(entered)
    official_tokens = _name_tokens(official)
    matched = entered_tokens & official_tokens
    return len(matched) >= threshold, len(matched)
