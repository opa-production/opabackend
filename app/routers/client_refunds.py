"""
Client refund endpoints.

These endpoints allow a client to see refund records that were created for
their bookings (e.g. after cancellations).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from typing import Optional
from datetime import datetime, timezone

from app.database import get_db
from app.auth import get_current_client
from app.models import Refund, Client, RefundStatus
from app.schemas import ClientRefundResponse, ClientRefundListResponse

router = APIRouter()


def _client_refund_to_response(refund: Refund) -> ClientRefundResponse:
    booking = getattr(refund, "booking", None)
    booking_code = getattr(booking, "booking_id", None) if booking else None
    return ClientRefundResponse(
        id=refund.id,
        booking_id=refund.booking_id,
        amount_refund=refund.amount_refund,
        status=refund.status.value,
        reason=refund.reason,
        created_at=refund.created_at,
        processed_at=refund.processed_at,
        booking_code=booking_code,
    )


@router.get("/client/refunds", response_model=ClientRefundListResponse)
async def list_my_refunds(
    booking_id: Optional[int] = Query(
        None,
        description="Optional numeric booking id to filter by",
    ),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    List refunds for the current authenticated client.

    - Optionally filter by a specific booking (numeric id).
    - Results are paginated and sorted by newest first.
    """
    conditions = [
        Refund.client_id == current_client.id,
        Refund.client_deleted_at.is_(None),
    ]
    if booking_id is not None:
        conditions.append(Refund.booking_id == booking_id)
    where_clause = and_(*conditions)

    count_result = await db.execute(
        select(func.count()).select_from(Refund).where(where_clause)
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(Refund)
        .options(joinedload(Refund.booking))
        .where(where_clause)
        .order_by(Refund.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    rows = result.scalars().all()

    return ClientRefundListResponse(
        refunds=[_client_refund_to_response(r) for r in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/client/refunds/{refund_id}", response_model=ClientRefundResponse)
async def get_my_refund_details(
    refund_id: int,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Get details of a single refund belonging to the current client.
    """
    result = await db.execute(
        select(Refund)
        .options(joinedload(Refund.booking))
        .where(
            Refund.id == refund_id,
            Refund.client_id == current_client.id,
        )
    )
    refund = result.scalar_one_or_none()
    if not refund:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Refund not found",
        )
    return _client_refund_to_response(refund)


@router.delete("/client/refunds/{refund_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_refund(
    refund_id: int,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Hide/delete a refund from the client's view.

    - Only refunds belonging to the current client are allowed.
    - Only `completed` or `failed` refunds can be deleted.
    - This is a soft delete: sets `client_deleted_at` so it no longer appears
      in `/client/refunds` responses.
    """
    result = await db.execute(
        select(Refund).where(
            Refund.id == refund_id,
            Refund.client_id == current_client.id,
        )
    )
    refund = result.scalar_one_or_none()
    if not refund:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Refund not found",
        )

    if refund.status not in (RefundStatus.COMPLETED, RefundStatus.FAILED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only completed or failed refunds can be deleted.",
        )

    if refund.client_deleted_at is not None:
        return None

    refund.client_deleted_at = datetime.now(timezone.utc)
    await db.commit()

    return None
