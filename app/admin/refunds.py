"""
Admin Refund Management endpoints

These endpoints allow finance/admin users to record and track refunds for bookings.
They do NOT themselves move money; they exist so finance can reconcile against PSP/bank
and keep a clear audit trail of what should have been refunded and why.
"""
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import (
    Refund,
    RefundStatus,
    Booking,
    Payment,
    Client,
    Admin,
)
from app.auth import get_current_admin
from app.schemas import (
    RefundCreateRequest,
    RefundUpdateRequest,
    RefundResponse,
    RefundListResponse,
)


router = APIRouter()


def _refund_to_response(refund: Refund) -> RefundResponse:
    """Map Refund ORM object to RefundResponse schema with helpful denormalized fields."""
    booking = getattr(refund, "booking", None)
    client = getattr(refund, "client", None)

    booking_code = getattr(booking, "booking_id", None) if booking else None
    client_name = getattr(client, "full_name", None) if client else None
    client_email = getattr(client, "email", None) if client else None

    return RefundResponse(
        id=refund.id,
        booking_id=refund.booking_id,
        payment_id=refund.payment_id,
        client_id=refund.client_id,
        amount_original=refund.amount_original,
        amount_refund=refund.amount_refund,
        percentage=refund.percentage,
        status=refund.status.value,
        reason=refund.reason,
        internal_note=refund.internal_note,
        created_by_admin_id=refund.created_by_admin_id,
        processed_by_admin_id=refund.processed_by_admin_id,
        external_reference=refund.external_reference,
        created_at=refund.created_at,
        updated_at=refund.updated_at,
        processed_at=refund.processed_at,
        booking_code=booking_code,
        client_name=client_name,
        client_email=client_email,
    )


@router.get("/admin/refunds", response_model=RefundListResponse)
async def list_refunds(
    page: int = Query(1, ge=1, description="Page number (1‑based)"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(
        None,
        description="Filter by refund status: pending, processing, completed, failed, cancelled",
    ),
    booking_code: Optional[str] = Query(
        None,
        description="Filter by human‑readable booking code (BK‑…)",
    ),
    client_email: Optional[str] = Query(
        None,
        description="Filter by client email (case‑insensitive, partial match)",
    ),
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    List refunds for finance/admin.

    - Supports pagination.
    - Filter by status, booking code, and client email.
    - Requires admin authentication.
    """
    q = (
        db.query(Refund)
        .options(
            joinedload(Refund.booking),
            joinedload(Refund.client),
        )
    )

    if status:
        status_lower = status.lower()
        try:
            status_enum = RefundStatus(status_lower)
        except ValueError:
            valid = [s.value for s in RefundStatus]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Valid values: {valid}",
            )
        q = q.filter(Refund.status == status_enum)

    if booking_code:
        q = q.join(Booking).filter(Booking.booking_id.ilike(f"%{booking_code}%"))

    if client_email:
        q = q.join(Client).filter(Client.email.ilike(f"%{client_email}%"))

    total = q.count()
    skip = (page - 1) * limit
    rows = (
        q.order_by(Refund.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return RefundListResponse(
        refunds=[_refund_to_response(r) for r in rows],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/admin/refunds/{refund_id}", response_model=RefundResponse)
async def get_refund_details(
    refund_id: int,
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Get detailed information about a single refund."""
    refund = (
        db.query(Refund)
        .options(
            joinedload(Refund.booking),
            joinedload(Refund.client),
        )
        .filter(Refund.id == refund_id)
        .first()
    )
    if not refund:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Refund not found",
        )
    return _refund_to_response(refund)


@router.post("/admin/refunds", response_model=RefundResponse, status_code=status.HTTP_201_CREATED)
async def create_refund(
    body: RefundCreateRequest,
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Create a refund record for a booking/payment.

    Typical flow:
    - Booking was cancelled (by client or admin).
    - Cancellation/refund policy indicates an amount to refund.
    - Admin creates a refund record with the decided amount and reason.

    This does not call any PSP APIs by itself; it is purely for tracking.
    """
    booking = (
        db.query(Booking)
        .options(joinedload(Booking.client))
        .filter(Booking.id == body.booking_id)
        .first()
    )
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    client = booking.client
    if not client:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Booking has no associated client record.",
        )

    payment = None
    if body.payment_id is not None:
        payment = (
            db.query(Payment)
            .filter(
                Payment.id == body.payment_id,
                Payment.booking_id == booking.id,
            )
            .first()
        )
        if not payment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment not found for this booking",
            )

    # Determine original amount reference for reporting – default to booking.total_price,
    # or specific payment.amount if a payment is referenced.
    if payment is not None:
        amount_original = float(payment.amount)
    else:
        amount_original = float(booking.total_price)  # type: ignore

    if body.amount_refund > amount_original:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Refund amount cannot exceed the original amount.",
        )

    percentage = body.percentage
    if percentage is None and amount_original > 0:
        percentage = round(body.amount_refund / amount_original, 4)

    refund = Refund(
        booking_id=booking.id,
        payment_id=payment.id if payment else None,
        client_id=client.id,
        amount_original=amount_original,
        amount_refund=body.amount_refund,
        percentage=percentage,
        status=RefundStatus.PENDING,
        reason=body.reason,
        internal_note=body.internal_note,
        created_by_admin_id=current_admin.id if current_admin else None,
    )

    db.add(refund)
    db.commit()
    db.refresh(refund)

    refund = (
        db.query(Refund)
        .options(
            joinedload(Refund.booking),
            joinedload(Refund.client),
        )
        .filter(Refund.id == refund.id)
        .first()
    )

    return _refund_to_response(refund)


@router.put("/admin/refunds/{refund_id}", response_model=RefundResponse)
async def update_refund(
    refund_id: int,
    body: RefundUpdateRequest,
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Update the status and internal details of an existing refund.

    Finance can use this when:
    - Marking a refund as processing/completed/failed/cancelled.
    - Storing PSP/bank reference and internal notes.
    """
    refund = db.query(Refund).filter(Refund.id == refund_id).first()
    if not refund:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Refund not found",
        )

    # Transition status
    new_status = RefundStatus(body.status.value)
    refund.status = new_status

    # Update notes and external reference
    if body.internal_note is not None:
        refund.internal_note = body.internal_note
    if body.external_reference is not None:
        refund.external_reference = body.external_reference

    # Set processed_by_admin + processed_at when final states are reached
    if new_status in (
        RefundStatus.COMPLETED,
        RefundStatus.FAILED,
        RefundStatus.CANCELLED,
    ):
        refund.processed_by_admin_id = current_admin.id
        refund.processed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(refund)

    refund = (
        db.query(Refund)
        .options(
            joinedload(Refund.booking),
            joinedload(Refund.client),
        )
        .filter(Refund.id == refund.id)
        .first()
    )

    return _refund_to_response(refund)

