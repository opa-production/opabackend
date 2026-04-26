"""
Client KYC via Dojah — two-step flow:

Step 1  POST /client/kyc/lookup
        Look up the client's government ID to retrieve their official name, DOB,
        and gender.  The profile (full_name, date_of_birth, gender, id_number) is
        updated with the verified government data and returned to the app for
        pre-filling the KYC details screen.

Step 2  POST /client/kyc/initialize
        Generate a unique reference_id and return the Dojah widget credentials so
        the mobile app can launch the EasyLookup widget for document scan + liveness
        + face match.  A pending ClientKyc row is created keyed by reference_id.

Step 3  GET /client/kyc/status
        Return the latest KYC status for the current client.  Poll this after the
        widget completes (Dojah webhook updates the row asynchronously).
"""
import logging
from datetime import date as date_type, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import delete as sa_delete

from app.auth import get_current_client
from app.config import settings
from app.database import get_db
from app.models import Client, ClientKyc
from app.schemas import KycLookupRequest, KycLookupResponse, KycWidgetInitResponse, ClientKycStatusResponse
from app.services import dojah_kyc as dojah


def _require_dojah_config() -> None:
    """Raise 503 if Dojah API keys are not yet configured."""
    if not settings.DOJAH_APP_ID or not settings.DOJAH_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Identity verification is not yet available. Please try again later.",
        )

router = APIRouter(tags=["Client KYC"])
logger = logging.getLogger(__name__)


@router.post(
    "/client/kyc/lookup",
    response_model=KycLookupResponse,
    summary="Step 1 — Government ID lookup (prefill)",
)
async def client_kyc_lookup(
    body: KycLookupRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Look up the client's government ID via Dojah and return their verified identity.

    Also updates the client's profile (full_name, date_of_birth, gender, id_number)
    with the government-verified data so the app can prefill both the KYC details
    screen and the profile screen.
    """
    _require_dojah_config()
    try:
        result = await dojah.lookup_government_id(body.id_type, body.id_number, body.country)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # Prefill profile with government-verified data
    if result.get("verified_name"):
        current_client.full_name = result["verified_name"]
    if result.get("date_of_birth"):
        try:
            current_client.date_of_birth = date_type.fromisoformat(result["date_of_birth"])
        except (ValueError, TypeError):
            pass
    if result.get("gender"):
        current_client.gender = result["gender"]
    current_client.id_number = result["id_number"]

    await db.commit()

    logger.info("[KYC] client_id=%s lookup success: %s %s", current_client.id, body.id_type, body.country)

    return KycLookupResponse(
        verified_name=result.get("verified_name"),
        date_of_birth=current_client.date_of_birth,
        gender=current_client.gender,
        id_number=result["id_number"],
        id_type=result["id_type"],
        country=result["country"],
    )


@router.post(
    "/client/kyc/initialize",
    response_model=KycWidgetInitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Step 2 — Initialize Dojah widget (document + liveness)",
)
async def client_kyc_initialize(
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a unique reference_id and return the Dojah EasyLookup widget credentials.

    The mobile app passes these to the Dojah widget SDK to run the document scan,
    liveness check, and face match.  A pending ClientKyc row is stored so the
    webhook can update it when Dojah sends the decision.
    """
    _require_dojah_config()
    try:
        creds = dojah.generate_widget_credentials()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))

    # Delete any abandoned pending rows so the user gets a clean fresh verification.
    # Approved/declined rows are preserved.
    await db.execute(
        sa_delete(ClientKyc)
        .where(ClientKyc.client_id == current_client.id)
        .where(ClientKyc.status == "pending")
    )

    kyc = ClientKyc(
        client_id=current_client.id,
        dojah_reference_id=creds["reference_id"],
        status="pending",
    )
    db.add(kyc)
    await db.commit()

    logger.info("[KYC] client_id=%s widget initialized ref=%s", current_client.id, creds["reference_id"])

    return KycWidgetInitResponse(**creds)


@router.get(
    "/client/kyc/status",
    response_model=ClientKycStatusResponse,
    summary="Step 3 — Poll KYC verification status",
)
async def get_client_kyc_status(
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the latest KYC verification status for the current client.
    Poll this after the Dojah widget completes — the webhook updates it asynchronously.
    """
    result = await db.execute(
        select(ClientKyc)
        .filter(ClientKyc.client_id == current_client.id)
        .order_by(
            (ClientKyc.status == "approved").desc(),
            ClientKyc.created_at.desc(),
        )
    )
    latest = result.scalars().first()

    # Treat a stale pending row as not_started so the user can restart.
    # 3 minutes is enough for a genuine webhook to arrive after completion.
    PENDING_EXPIRY = timedelta(minutes=3)
    if latest and latest.status == "pending":
        age = datetime.now(timezone.utc) - latest.created_at.replace(tzinfo=timezone.utc)
        if age > PENDING_EXPIRY:
            latest = None

    if not latest:
        return ClientKycStatusResponse(
            user_id=current_client.id,
            reference_id=None,
            status="not_started",
            document_type=None,
            verified_name=None,
            verified_dob=None,
            face_match_score=None,
            decision_reason=None,
            verified_at=None,
        )

    return ClientKycStatusResponse(
        user_id=current_client.id,
        reference_id=latest.dojah_reference_id,
        status=latest.status,
        document_type=latest.document_type,
        verified_name=latest.verified_name,
        verified_dob=latest.verified_dob,
        face_match_score=latest.face_match_score,
        decision_reason=latest.decision_reason,
        verified_at=latest.verified_at,
    )
