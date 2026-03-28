"""
Client (renter) rating endpoints

These endpoints allow hosts to rate clients after completing bookings.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_host
from app.db.session import get_db
from app.models import Booking, BookingStatus, Car, Client, ClientRating, Host
from app.schemas import (
    ClientProfileForHostResponse,
    ClientRatingCreateRequest,
    ClientRatingListResponse,
    ClientRatingResponse,
    ClientRatingUpdateRequest,
)

router = APIRouter()


def rating_to_response(rating: ClientRating) -> dict:
    """Convert ClientRating model to ClientRatingResponse dict"""
    return {
        "id": rating.id,
        "client_id": rating.client_id,
        "host_id": rating.host_id,
        "booking_id": rating.booking_id,
        "rating": rating.rating,
        "review": rating.review,
        "created_at": rating.created_at,
        "updated_at": rating.updated_at,
        "client_name": rating.client.full_name if rating.client else None,
        "host_name": rating.host.full_name if rating.host else None,
    }


@router.post(
    "/host/client-ratings",
    response_model=ClientRatingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_client_rating(
    request: ClientRatingCreateRequest,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a rating for a client (renter).

    - Only authenticated hosts can create ratings
    - If booking_id is provided, booking must belong to this host and be completed
    - Only one host rating per booking is allowed
    """
    client_stmt = select(Client).filter(Client.id == request.client_id)
    client_result = await db.execute(client_stmt)
    client = client_result.scalar_one_or_none()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
        )

    if request.booking_id:
        booking_stmt = (
            select(Booking)
            .options(joinedload(Booking.car))
            .join(Car)
            .filter(
                Booking.id == request.booking_id,
                Booking.client_id == request.client_id,
                Car.host_id == current_host.id,
            )
        )
        booking_result = await db.execute(booking_stmt)
        booking = booking_result.scalar_one_or_none()

        if not booking:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Booking not found or you don't have access to it",
            )
        if booking.status != BookingStatus.COMPLETED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You can only rate clients for completed bookings",
            )

        existing_stmt = select(ClientRating).filter(
            ClientRating.booking_id == request.booking_id,
            ClientRating.host_id == current_host.id,
        )
        existing_result = await db.execute(existing_stmt)
        existing = existing_result.scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You have already rated this booking",
            )

    rating = ClientRating(
        client_id=request.client_id,
        host_id=current_host.id,
        booking_id=request.booking_id,
        rating=request.rating,
        review=request.review.strip() if request.review else None,
    )
    db.add(rating)
    await db.commit()
    await db.refresh(rating)

    rating_stmt = (
        select(ClientRating)
        .options(
            joinedload(ClientRating.client),
            joinedload(ClientRating.host),
        )
        .filter(ClientRating.id == rating.id)
    )
    rating_result = await db.execute(rating_stmt)
    rating = rating_result.scalar_one_or_none()

    return rating_to_response(rating)


@router.get("/host/client-ratings", response_model=ClientRatingListResponse)
async def get_host_submitted_client_ratings(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(
        20, ge=1, le=100, description="Maximum number of records to return"
    ),
    client_id: Optional[int] = Query(None, description="Filter by client ID"),
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """Get ratings submitted by the current host."""
    stmt = (
        select(ClientRating)
        .options(
            joinedload(ClientRating.client),
            joinedload(ClientRating.host),
        )
        .filter(ClientRating.host_id == current_host.id)
    )

    if client_id:
        stmt = stmt.filter(ClientRating.client_id == client_id)

    # Get total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    stmt = stmt.order_by(ClientRating.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    ratings = result.scalars().all()

    return ClientRatingListResponse(
        ratings=[rating_to_response(r) for r in ratings],
        total=total,
        average_rating=None,
    )


@router.get("/host/client-ratings/{rating_id}", response_model=ClientRatingResponse)
async def get_host_client_rating_details(
    rating_id: int,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """Get one client rating created by the current host."""
    stmt = (
        select(ClientRating)
        .options(
            joinedload(ClientRating.client),
            joinedload(ClientRating.host),
        )
        .filter(
            ClientRating.id == rating_id,
            ClientRating.host_id == current_host.id,
        )
    )
    result = await db.execute(stmt)
    rating = result.scalar_one_or_none()

    if not rating:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Rating not found"
        )
    return rating_to_response(rating)


@router.put("/host/client-ratings/{rating_id}", response_model=ClientRatingResponse)
async def update_host_client_rating(
    rating_id: int,
    request: ClientRatingUpdateRequest,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """Update a client rating created by the current host."""
    stmt = select(ClientRating).filter(
        ClientRating.id == rating_id,
        ClientRating.host_id == current_host.id,
    )
    result = await db.execute(stmt)
    rating = result.scalar_one_or_none()
    if not rating:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Rating not found"
        )

    rating.rating = request.rating
    rating.review = request.review.strip() if request.review else None
    await db.commit()
    await db.refresh(rating)

    rating_stmt = (
        select(ClientRating)
        .options(
            joinedload(ClientRating.client),
            joinedload(ClientRating.host),
        )
        .filter(ClientRating.id == rating.id)
    )
    rating_result = await db.execute(rating_stmt)
    rating = rating_result.scalar_one_or_none()

    return rating_to_response(rating)


@router.delete(
    "/host/client-ratings/{rating_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_host_client_rating(
    rating_id: int,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """Delete a client rating created by the current host."""
    stmt = select(ClientRating).filter(
        ClientRating.id == rating_id,
        ClientRating.host_id == current_host.id,
    )
    result = await db.execute(stmt)
    rating = result.scalar_one_or_none()
    if not rating:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Rating not found"
        )

    await db.delete(rating)
    await db.commit()
    return None


@router.get(
    "/host/clients/{client_id}/profile", response_model=ClientProfileForHostResponse
)
async def get_client_profile_for_host(
    client_id: int,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Get client (renter) profile summary for hosts.

    Returns basic client info plus **trips_count** (number of completed bookings)
    and **average_rating** (from host ratings) so hosts can show "X trips" and
    rating on the renter's profile.
    """
    client_stmt = select(Client).filter(Client.id == client_id)
    client_result = await db.execute(client_stmt)
    client = client_result.scalar_one_or_none()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
        )

    trips_stmt = select(func.count(Booking.id)).filter(
        Booking.client_id == client_id,
        Booking.status == BookingStatus.COMPLETED,
    )
    trips_result = await db.execute(trips_stmt)
    trips_count = trips_result.scalar() or 0

    avg_stmt = select(func.avg(ClientRating.rating)).filter(
        ClientRating.client_id == client_id
    )
    avg_result = await db.execute(avg_stmt)
    avg_rating = avg_result.scalar()

    return ClientProfileForHostResponse(
        id=client.id,
        full_name=client.full_name,
        email=client.email,
        avatar_url=client.avatar_url,
        trips_count=trips_count,
        average_rating=round(float(avg_rating), 2) if avg_rating else None,
    )


@router.get("/clients/{client_id}/ratings", response_model=ClientRatingListResponse)
async def get_client_ratings_public(
    client_id: int,
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(
        20, ge=1, le=100, description="Maximum number of records to return"
    ),
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint: get ratings for a specific client (renter)."""
    client_stmt = select(Client).filter(Client.id == client_id)
    client_result = await db.execute(client_stmt)
    client = client_result.scalar_one_or_none()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
        )

    stmt = (
        select(ClientRating)
        .options(
            joinedload(ClientRating.client),
            joinedload(ClientRating.host),
        )
        .filter(ClientRating.client_id == client_id)
    )

    # Get total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    avg_stmt = select(func.avg(ClientRating.rating)).filter(
        ClientRating.client_id == client_id
    )
    avg_result = await db.execute(avg_stmt)
    avg = avg_result.scalar()

    stmt = stmt.order_by(ClientRating.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    ratings = result.scalars().all()

    return ClientRatingListResponse(
        ratings=[rating_to_response(r) for r in ratings],
        total=total,
        average_rating=round(float(avg), 2) if avg else None,
    )
