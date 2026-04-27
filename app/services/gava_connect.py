"""
Gava Connect (Kenya e-Government) PIN checker service.

Fetches an OAuth 2.0 access token using client credentials, then calls
/checker/v1/pin with a national ID number to retrieve the registered
name and KRA PIN.

Environment variables required:
    GAVACONNECT_CONSUMER_KEY
    GAVACONNECT_CONSUMER_SECRET
    GAVACONNECT_BASE_URL   (default: https://developer.go.ke)
"""
import base64
import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_TOKEN_PATH = "/api/oauth2/v2/token"
_PIN_CHECK_PATH = "/checker/v1/pin"

_cached_token: Optional[str] = None


def _require_config() -> None:
    if not settings.GAVACONNECT_CONSUMER_KEY or not settings.GAVACONNECT_CONSUMER_SECRET:
        raise ValueError("GAVACONNECT_CONSUMER_KEY and GAVACONNECT_CONSUMER_SECRET must be set.")


async def _fetch_token(client: httpx.AsyncClient) -> str:
    credentials = base64.b64encode(
        f"{settings.GAVACONNECT_CONSUMER_KEY}:{settings.GAVACONNECT_CONSUMER_SECRET}".encode()
    ).decode()

    resp = await client.post(
        f"{settings.GAVACONNECT_BASE_URL}{_TOKEN_PATH}",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "client_credentials"},
        timeout=15,
    )
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise ValueError(f"Gava Connect did not return an access_token: {resp.text[:300]}")
    logger.info("[GavaConnect] OAuth token obtained")
    return token


async def check_pin(id_number: str) -> dict:
    """
    Check an ID number against the Gava Connect PIN checker.

    Returns a dict with at minimum:
        name     str  — full name as registered with KRA
        kra_pin  str  — the KRA PIN for that ID
        raw      dict — full API response for future-proofing

    Raises ValueError on API / auth errors.
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
            json={"id_number": id_number.strip()},
        )

        logger.info("[GavaConnect] /checker/v1/pin status=%s id=%s…", resp.status_code, id_number[:4])

        if resp.status_code == 404:
            raise ValueError("ID number not found in KRA records.")

        if resp.status_code == 400:
            detail = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text
            raise ValueError(f"Invalid request to Gava Connect: {detail}")

        resp.raise_for_status()

        data = resp.json()
        # Gava Connect wraps results in a "data" key
        inner = data.get("data") or data
        name = (
            inner.get("name")
            or inner.get("full_name")
            or inner.get("taxpayer_name")
            or ""
        ).strip()
        kra_pin = (inner.get("kra_pin") or inner.get("pin") or "").strip()

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
