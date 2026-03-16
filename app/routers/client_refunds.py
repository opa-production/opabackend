"""
Client refund endpoints.

These endpoints allow a client to see refund records that were created for
their bookings (e.g. after cancellations).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload
from typing import Optional

from app.database import get_db
from app.auth import get_current_client
from app.models import Refund, Booking, Client
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
    db: Session = Depends(get_db),
):
    """
    List refunds for the current authenticated client.

    - Optionally filter by a specific booking (numeric id).
    - Results are paginated and sorted by newest first.
    """
    q = (
        db.query(Refund)
        .options(joinedload(Refund.booking))
        .filter(Refund.client_id == current_client.id)
    )

    if booking_id is not None:
        q = q.filter(Refund.booking_id == booking_id)

    total = q.count()
    rows = (
        q.order_by(Refund.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

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
    db: Session = Depends(get_db),
):
    """
    Get details of a single refund belonging to the current client.
    """
    refund = (
        db.query(Refund)
        .options(joinedload(Refund.booking))
        .filter(
            Refund.id == refund_id,
            Refund.client_id == current_client.id,
        )
        .first()
    )
    if not refund:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Refund not found",
        )
    return _client_refund_to_response(refund)

