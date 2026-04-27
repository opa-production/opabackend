"""
Gava Connect / KRA PIN checker service.

Fetches an OAuth 2.0 access token (GET with Basic Auth + query param), then
calls POST /checker/v1/pinbypin with the KRA PIN to retrieve the registered
name and PIN status.

Environment variables required:
    GAVACONNECT_CONSUMER_KEY
    GAVACONNECT_CONSUMER_SECRET
    GAVACONNECT_BASE_URL   (default: https://sbx.kra.go.ke  — sandbox)
                            production: https://api.kra.go.ke
"""
import base64
import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_TOKEN_PATH = "/v1/token/generate"
_PIN_CHECK_PATH = "/checker/v1/pinbypin"


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
        raise ValueError("Gava Connect: invalid consumer credentials (401).")

    resp.raise_for_status()

    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise ValueError(f"Gava Connect did not return an access_token: {resp.text[:300]}")

    logger.info("[GavaConnect] OAuth token obtained")
    return token


async def check_pin(kra_pin: str) -> dict:
    """
    Validate a KRA PIN via the Gava Connect PIN checker.

    Returns a dict with at minimum:
        name     str  — taxpayer name as registered with KRA
        kra_pin  str  — the KRA PIN (echoed back)
        status   str  — e.g. "Active"
        raw      dict — full API response

    Raises ValueError on API / auth / not-found errors.
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
            json={"KRAPIN": kra_pin.strip().upper()},
        )

        logger.info(
            "[GavaConnect] /checker/v1/pinbypin status=%s pin=%s…",
            resp.status_code,
            kra_pin[:4],
        )

        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}

        if resp.status_code == 401:
            raise ValueError("Gava Connect: token rejected (401). Check credentials.")

        if resp.status_code == 404 or (data.get("ResponseCode") and data["ResponseCode"] != "23000"):
            msg = data.get("Message") or data.get("errorMessage") or "KRA PIN not found."
            raise ValueError(f"Gava Connect: {msg}")

        resp.raise_for_status()

        pin_data = data.get("PINDATA") or {}
        name = (pin_data.get("Name") or "").strip()
        returned_pin = (pin_data.get("KRAPIN") or kra_pin).strip()
        pin_status = (pin_data.get("StatusOfPIN") or "").strip()

        if not name:
            raise ValueError("Gava Connect returned no name for this KRA PIN.")

        return {"name": name, "kra_pin": returned_pin, "pin_status": pin_status, "raw": data}


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
