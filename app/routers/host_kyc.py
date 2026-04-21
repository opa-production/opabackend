"""
Host KYC via Dojah — mirrors client_kyc.py but authenticates as a host.

Step 1  POST /host/kyc/lookup       — Government ID prefill
Step 2  POST /host/kyc/initialize   — Launch Dojah widget
Step 3  GET  /host/kyc/status       — Poll verification result
"""
import logging
from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_host
from app.database import get_db
from app.models import Host, HostKyc
from app.schemas import KycLookupRequest, KycLookupResponse, KycWidgetInitResponse, HostKycStatusResponse
from app.services import dojah_kyc as dojah

router = APIRouter(tags=["Host KYC"])
logger = logging.getLogger(__name__)


@router.post(
    "/host/kyc/lookup",
    response_model=KycLookupResponse,
    summary="Step 1 — Government ID lookup (prefill)",
)
async def host_kyc_lookup(
    body: KycLookupRequest,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Look up the host's government ID via Dojah and return their verified identity.

    Updates full_name and id_number on the host profile with government-verified data.
    """
    try:
        result = await dojah.lookup_government_id(body.id_type, body.id_number, body.country)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if result.get("verified_name"):
        current_host.full_name = result["verified_name"]
    current_host.id_number = result["id_number"]

    await db.commit()
    await db.refresh(current_host)

    logger.info("[KYC] host_id=%s lookup success: %s %s", current_host.id, body.id_type, body.country)

    return KycLookupResponse(
        verified_name=result.get("verified_name"),
        date_of_birth=None,   # Host model has no dob column — returned for display only
        gender=result.get("gender"),
        id_number=result["id_number"],
        id_type=result["id_type"],
        country=result["country"],
    )


@router.post(
    "/host/kyc/initialize",
    response_model=KycWidgetInitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Step 2 — Initialize Dojah widget (document + liveness)",
)
async def host_kyc_initialize(
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a unique reference_id and return the Dojah EasyLookup widget credentials
    for the host app.
    """
    try:
        creds = dojah.generate_widget_credentials()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))

    kyc = HostKyc(
        host_id=current_host.id,
        dojah_reference_id=creds["reference_id"],
        status="pending",
    )
    db.add(kyc)
    await db.commit()

    logger.info("[KYC] host_id=%s widget initialized ref=%s", current_host.id, creds["reference_id"])

    return KycWidgetInitResponse(**creds)


@router.get(
    "/host/kyc/status",
    response_model=HostKycStatusResponse,
    summary="Step 3 — Poll KYC verification status",
)
async def get_host_kyc_status(
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """Return the latest KYC verification status for the current host."""
    result = await db.execute(
        select(HostKyc)
        .filter(HostKyc.host_id == current_host.id)
        .order_by(HostKyc.created_at.desc())
    )
    latest = result.scalars().first()

    if not latest:
        return HostKycStatusResponse(
            user_id=current_host.id,
            reference_id=None,
            status="not_started",
            document_type=None,
            verified_name=None,
            verified_dob=None,
            face_match_score=None,
            decision_reason=None,
            verified_at=None,
        )

    return HostKycStatusResponse(
        user_id=current_host.id,
        reference_id=latest.dojah_reference_id,
        status=latest.status,
        document_type=latest.document_type,
        verified_name=latest.verified_name,
        verified_dob=latest.verified_dob,
        face_match_score=latest.face_match_score,
        decision_reason=latest.decision_reason,
        verified_at=latest.verified_at,
    )
