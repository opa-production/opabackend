"""
Admin Refund Management endpoints

These endpoints allow finance/admin users to record and track refunds for bookings.
They do NOT themselves move money; they exist so finance can reconcile against PSP/bank
and keep a clear audit trail of what should have been refunded and why.
"""
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import joinedload

from app.database import get_db
from app.models import Refund, RefundStatus, Booking, Payment, Client, Admin
from app.auth import get_current_admin
from app.schemas import (
    RefundCreateRequest,
    RefundUpdateRequest,
    RefundResponse,
    RefundListResponse,
)

router = APIRouter()


def _refund_to_response(refund: Refund) -> RefundResponse:
    booking = getattr(refund, "booking", None)
    client = getattr(refund, "client", None)

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
        booking_code=getattr(booking, "booking_id", None) if booking else None,
        client_name=getattr(client, "full_name", None) if client else None,
        client_email=getattr(client, "email", None) if client else None,
    )


@router.get("/admin/refunds", response_model=RefundListResponse)
async def list_refunds(
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        description="Filter by status: pending, processing, completed, failed, cancelled",
    ),
    booking_code: Optional[str] = Query(None, description="Filter by booking code (BK-…)"),
    client_email: Optional[str] = Query(None, description="Filter by client email (partial)"),
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Refund).options(
        joinedload(Refund.booking),
        joinedload(Refund.client),
    )

    if status_filter:
        try:
            status_enum = RefundStatus(status_filter.lower())
        except ValueError:
            valid = [s.value for s in RefundStatus]
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Valid values: {valid}",
            )
        stmt = stmt.filter(Refund.status == status_enum)

    if booking_code:
        stmt = stmt.join(Booking, Refund.booking_id == Booking.id).filter(
            Booking.booking_id.ilike(f"%{booking_code}%")
        )

    if client_email:
        stmt = stmt.join(Client, Refund.client_id == Client.id).filter(
            Client.email.ilike(f"%{client_email}%")
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    skip = (page - 1) * limit
    rows_result = await db.execute(
        stmt.order_by(Refund.created_at.desc()).offset(skip).limit(limit)
    )
    rows = rows_result.scalars().unique().all()

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
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Refund)
        .options(joinedload(Refund.booking), joinedload(Refund.client))
        .filter(Refund.id == refund_id)
    )
    refund = result.scalar_one_or_none()
    if not refund:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Refund not found")
    return _refund_to_response(refund)


@router.post("/admin/refunds", response_model=RefundResponse, status_code=http_status.HTTP_201_CREATED)
async def create_refund(
    body: RefundCreateRequest,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    booking_result = await db.execute(
        select(Booking)
        .options(joinedload(Booking.client))
        .filter(Booking.id == body.booking_id)
    )
    booking = booking_result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Booking not found")

    client = booking.client
    if not client:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Booking has no associated client record.",
        )

    payment = None
    if body.payment_id is not None:
        payment_result = await db.execute(
            select(Payment).filter(
                Payment.id == body.payment_id,
                Payment.booking_id == booking.id,
            )
        )
        payment = payment_result.scalar_one_or_none()
        if not payment:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Payment not found for this booking",
            )

    amount_original = float(payment.amount) if payment else float(booking.total_price)

    if body.amount_refund > amount_original:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
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
    await db.commit()

    # Re-fetch with relationships for the response
    result = await db.execute(
        select(Refund)
        .options(joinedload(Refund.booking), joinedload(Refund.client))
        .filter(Refund.id == refund.id)
    )
    refund = result.scalar_one()
    return _refund_to_response(refund)


@router.put("/admin/refunds/{refund_id}", response_model=RefundResponse)
async def update_refund(
    refund_id: int,
    body: RefundUpdateRequest,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Refund).filter(Refund.id == refund_id))
    refund = result.scalar_one_or_none()
    if not refund:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Refund not found")

    new_status = RefundStatus(body.status.value)
    refund.status = new_status

    if body.internal_note is not None:
        refund.internal_note = body.internal_note
    if body.external_reference is not None:
        refund.external_reference = body.external_reference

    if new_status in (RefundStatus.COMPLETED, RefundStatus.FAILED, RefundStatus.CANCELLED):
        refund.processed_by_admin_id = current_admin.id
        refund.processed_at = datetime.now(timezone.utc)

    await db.commit()

    # Re-fetch with relationships for the response
    result = await db.execute(
        select(Refund)
        .options(joinedload(Refund.booking), joinedload(Refund.client))
        .filter(Refund.id == refund.id)
    )
    refund = result.scalar_one()
    return _refund_to_response(refund)
