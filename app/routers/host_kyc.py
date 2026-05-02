"""
Host KYC via Dojah — mirrors client_kyc.py but authenticates as a host.

Step 1  POST /host/kyc/lookup       — Government ID prefill
Step 2  POST /host/kyc/initialize   — Launch Dojah widget
Step 3  GET  /host/kyc/status       — Poll verification result
"""
import logging
from datetime import date as date_type, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import RedirectResponse

from app.auth import get_current_host
from app.config import settings
from app.database import get_db
from app.models import Host, HostKyc
from app.schemas import KycLookupRequest, KycLookupResponse, KycWidgetInitResponse, HostKycStatusResponse
from app.services import dojah_kyc as dojah


def _require_dojah_config() -> None:
    """Raise 503 if Dojah API keys are not yet configured."""
    if not settings.DOJAH_APP_ID or not settings.DOJAH_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Identity verification is not yet available. Please try again later.",
        )

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
    _require_dojah_config()
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
    _require_dojah_config()
    try:
        creds = dojah.generate_widget_credentials()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))

    # Delete any abandoned pending rows so the user gets a clean fresh verification.
    from sqlalchemy import delete as sa_delete
    await db.execute(
        sa_delete(HostKyc)
        .where(HostKyc.host_id == current_host.id)
        .where(HostKyc.status == "pending")
    )

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
        .order_by(
            (HostKyc.status == "approved").desc(),
            HostKyc.created_at.desc(),
        )
    )
    latest = result.scalars().first()

    # Treat a stale pending row as not_started so the user can restart.
    # 30 minutes is plenty of time for a user to complete the widget flow.
    PENDING_EXPIRY = timedelta(minutes=30)
    if latest and latest.status == "pending":
        age = datetime.now(timezone.utc) - latest.created_at.replace(tzinfo=timezone.utc)
        if age > PENDING_EXPIRY:
            latest = None

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


def build_kyc_redirect_response(return_to: Optional[str] = None):
    """
    Build a redirect response back to the host app after Dojah verification.
    This is used by the /host/kyc/redirect endpoint in main.py.
    """
    host_frontend_url = (settings.HOST_FRONTEND_URL or "ardenahost://").rstrip("/")
    # Default deep link if no return_to is provided
    deep_link = f"{host_frontend_url}/kyc/result"
    
    if return_to:
        deep_link = return_to
        
    return RedirectResponse(url=deep_link)
