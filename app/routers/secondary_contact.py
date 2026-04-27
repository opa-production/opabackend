"""
Secondary contact verification endpoints.

Flow:
  1. POST /client/secondary-contact/info   — save phone + names
  2. POST /client/secondary-contact/verify — submit ID number → Gava Connect lookup → name match
  3. GET  /client/secondary-contact/status — current verification state
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_client
from app.database import get_db
from app.models import Client
from app.schemas import (
    SecondaryContactInfoRequest,
    SecondaryContactStatusResponse,
    SecondaryContactVerifyRequest,
)
from app.services import gava_connect

router = APIRouter()
logger = logging.getLogger(__name__)


def _status_response(client: Client, message: str | None = None) -> SecondaryContactStatusResponse:
    return SecondaryContactStatusResponse(
        status=client.secondary_contact_status or "not_started",
        phone=client.secondary_contact_phone,
        names=client.secondary_contact_names,
        official_name=client.secondary_contact_official_name,
        kra_pin=client.secondary_contact_kra_pin,
        matched_names=client.secondary_contact_matched_names,
        verified_at=client.secondary_contact_verified_at,
        message=message,
    )


@router.post("/client/secondary-contact/info", response_model=SecondaryContactStatusResponse)
async def save_secondary_contact_info(
    body: SecondaryContactInfoRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Save the secondary contact phone number and entered names (Step 1)."""
    result = await db.execute(select(Client).where(Client.id == current_client.id))
    client = result.scalar_one()

    client.secondary_contact_phone = body.phone.strip()
    client.secondary_contact_names = body.names.strip()
    # Reset any prior verification if they're re-entering info
    client.secondary_contact_status = "not_started"
    client.secondary_contact_id_number = None
    client.secondary_contact_official_name = None
    client.secondary_contact_kra_pin = None
    client.secondary_contact_matched_names = 0
    client.secondary_contact_verified_at = None

    await db.commit()
    return _status_response(client, message="Secondary contact info saved. Please proceed to ID verification.")


@router.post("/client/secondary-contact/verify", response_model=SecondaryContactStatusResponse)
async def verify_secondary_contact(
    body: SecondaryContactVerifyRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Submit secondary contact ID number (Step 2).
    Calls Gava Connect, compares returned name with saved names, marks verified/failed.
    """
    result = await db.execute(select(Client).where(Client.id == current_client.id))
    client = result.scalar_one()

    if not client.secondary_contact_names:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please save secondary contact info (phone + names) first.",
        )

    client.secondary_contact_status = "pending"
    client.secondary_contact_id_number = body.kra_pin.strip().upper()
    await db.commit()

    try:
        gc_result = await gava_connect.check_pin(body.kra_pin)
    except ValueError as exc:
        logger.warning(
            "[secondary_contact] Gava Connect error for client %s: %s", current_client.id, exc
        )
        client.secondary_contact_status = "failed"
        client.secondary_contact_official_name = None
        client.secondary_contact_kra_pin = None
        client.secondary_contact_matched_names = 0
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    official_name: str = gc_result["name"]
    kra_pin: str = gc_result.get("kra_pin", "")

    passed, matched_count = gava_connect.names_match(
        entered=client.secondary_contact_names,
        official=official_name,
    )

    client.secondary_contact_official_name = official_name
    client.secondary_contact_kra_pin = kra_pin
    client.secondary_contact_matched_names = matched_count

    if passed:
        client.secondary_contact_status = "verified"
        client.secondary_contact_verified_at = datetime.now(timezone.utc)
        msg = "Secondary contact verified successfully."
    else:
        client.secondary_contact_status = "failed"
        msg = (
            f"Name verification failed — only {matched_count} name(s) matched "
            "the official record (2 required). Please check the names and try again."
        )

    await db.commit()

    logger.warning(
        "[secondary_contact] client=%s kra_pin=%.4s… official=%r entered=%r matched=%d status=%s",
        current_client.id,
        body.kra_pin,
        official_name,
        client.secondary_contact_names,
        matched_count,
        client.secondary_contact_status,
    )

    return _status_response(client, message=msg)


@router.get("/client/secondary-contact/status", response_model=SecondaryContactStatusResponse)
async def get_secondary_contact_status(
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Return the current secondary contact verification state."""
    result = await db.execute(select(Client).where(Client.id == current_client.id))
    client = result.scalar_one()
    return _status_response(client)
