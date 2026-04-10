"""
Rental Agreement download endpoints.

Clients and hosts can download the signed rental agreement PDF for any of
their confirmed/active/completed bookings.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth import get_current_client, get_current_host
from app.database import get_db
from app.models import Booking, BookingStatus, Car, Client, Host, Payment, PaymentStatus
from app.services.agreement import build_agreement_pdf

logger = logging.getLogger(__name__)

router = APIRouter()

# Bookings eligible for an agreement (payment was made)
_ELIGIBLE_STATUSES = {
    BookingStatus.CONFIRMED,
    BookingStatus.ACTIVE,
    BookingStatus.COMPLETED,
}


def _pdf_response(pdf_bytes: bytes, filename: str) -> Response:
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _load_booking_full(db: AsyncSession, booking_db_id: int):
    """Load a booking with all relationships needed for the agreement PDF."""
    stmt = (
        select(Booking)
        .options(
            joinedload(Booking.car).joinedload(Car.host),
            joinedload(Booking.client),
        )
        .filter(Booking.id == booking_db_id)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _load_paid_payment(db: AsyncSession, booking_db_id: int):
    stmt = (
        select(Payment)
        .filter(
            Payment.booking_id == booking_db_id,
            Payment.status == PaymentStatus.COMPLETED,
        )
        .order_by(Payment.id.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().first()


# ──────────────────────────────────────────────────────────────────
#  CLIENT ENDPOINTS
# ──────────────────────────────────────────────────────────────────

@router.get(
    "/client/bookings/{booking_ref}/agreement",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
    summary="Download rental agreement (client)",
    tags=["Rental Agreements"],
)
async def client_download_agreement(
    booking_ref: str,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Download the Vehicle Rental Agreement PDF for a booking.

    - **booking_ref**: Human-readable booking ID (e.g. `BK-ABC12345`)
    - Only the client who made the booking can download it
    - Booking must be in `confirmed`, `active`, or `completed` status
    - Returns a PDF file download
    """
    # Look up by human-readable booking_id
    stmt = select(Booking).filter(
        Booking.booking_id == booking_ref,
        Booking.client_id == current_client.id,
    )
    result = await db.execute(stmt)
    booking_row = result.scalar_one_or_none()

    if not booking_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    if booking_row.status not in _ELIGIBLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agreement is only available for confirmed, active, or completed bookings",
        )

    booking = await _load_booking_full(db, booking_row.id)
    paid_payment = await _load_paid_payment(db, booking_row.id)

    try:
        pdf_bytes = build_agreement_pdf(booking, paid_payment)
    except Exception as e:
        logger.exception("[Agreement] PDF build failed for booking %s: %s", booking_ref, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate agreement PDF",
        )

    filename = f"rental-agreement-{booking_ref}.pdf"
    return _pdf_response(pdf_bytes, filename)


# ──────────────────────────────────────────────────────────────────
#  HOST ENDPOINTS
# ──────────────────────────────────────────────────────────────────

@router.get(
    "/host/bookings/{booking_ref}/agreement",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
    summary="Download rental agreement (host)",
    tags=["Rental Agreements"],
)
async def host_download_agreement(
    booking_ref: str,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Download the Vehicle Rental Agreement PDF for a booking.

    - **booking_ref**: Human-readable booking ID (e.g. `BK-ABC12345`)
    - Only the host whose car is in the booking can download it
    - Booking must be in `confirmed`, `active`, or `completed` status
    - Returns a PDF file download
    """
    # Verify the booking belongs to one of this host's cars
    stmt = (
        select(Booking)
        .join(Car, Booking.car_id == Car.id)
        .filter(
            Booking.booking_id == booking_ref,
            Car.host_id == current_host.id,
        )
    )
    result = await db.execute(stmt)
    booking_row = result.scalar_one_or_none()

    if not booking_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    if booking_row.status not in _ELIGIBLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agreement is only available for confirmed, active, or completed bookings",
        )

    booking = await _load_booking_full(db, booking_row.id)
    paid_payment = await _load_paid_payment(db, booking_row.id)

    try:
        pdf_bytes = build_agreement_pdf(booking, paid_payment)
    except Exception as e:
        logger.exception("[Agreement] PDF build failed for booking %s: %s", booking_ref, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate agreement PDF",
        )

    filename = f"rental-agreement-{booking_ref}.pdf"
    return _pdf_response(pdf_bytes, filename)
