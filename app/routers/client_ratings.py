"""
Client (renter) rating endpoints

These endpoints allow hosts to rate clients after completing bookings.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_host
from app.database import get_db
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


@router.post("/host/client-ratings", response_model=ClientRatingResponse, status_code=status.HTTP_201_CREATED)
async def create_client_rating(
    request: ClientRatingCreateRequest,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db),
):
    """
    Create a rating for a client (renter).

    - Only authenticated hosts can create ratings
    - If booking_id is provided, booking must belong to this host and be completed
    - Only one host rating per booking is allowed
    """
    client = db.query(Client).filter(Client.id == request.client_id).first()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    if request.booking_id:
        booking = (
            db.query(Booking)
            .options(joinedload(Booking.car))
            .join(Car)
            .filter(
                Booking.id == request.booking_id,
                Booking.client_id == request.client_id,
                Car.host_id == current_host.id,
            )
            .first()
        )
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

        existing = db.query(ClientRating).filter(
            ClientRating.booking_id == request.booking_id,
            ClientRating.host_id == current_host.id,
        ).first()
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
    db.commit()
    db.refresh(rating)

    rating = db.query(ClientRating).options(
        joinedload(ClientRating.client),
        joinedload(ClientRating.host),
    ).filter(ClientRating.id == rating.id).first()
    return rating_to_response(rating)


@router.get("/host/client-ratings", response_model=ClientRatingListResponse)
async def get_host_submitted_client_ratings(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    client_id: Optional[int] = Query(None, description="Filter by client ID"),
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db),
):
    """Get ratings submitted by the current host."""
    query = db.query(ClientRating).options(
        joinedload(ClientRating.client),
        joinedload(ClientRating.host),
    ).filter(ClientRating.host_id == current_host.id)

    if client_id:
        query = query.filter(ClientRating.client_id == client_id)

    total = query.count()
    ratings = query.order_by(ClientRating.created_at.desc()).offset(skip).limit(limit).all()

    return ClientRatingListResponse(
        ratings=[rating_to_response(r) for r in ratings],
        total=total,
        average_rating=None,
    )


@router.get("/host/client-ratings/{rating_id}", response_model=ClientRatingResponse)
async def get_host_client_rating_details(
    rating_id: int,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db),
):
    """Get one client rating created by the current host."""
    rating = db.query(ClientRating).options(
        joinedload(ClientRating.client),
        joinedload(ClientRating.host),
    ).filter(
        ClientRating.id == rating_id,
        ClientRating.host_id == current_host.id,
    ).first()

    if not rating:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rating not found")
    return rating_to_response(rating)


@router.put("/host/client-ratings/{rating_id}", response_model=ClientRatingResponse)
async def update_host_client_rating(
    rating_id: int,
    request: ClientRatingUpdateRequest,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db),
):
    """Update a client rating created by the current host."""
    rating = db.query(ClientRating).filter(
        ClientRating.id == rating_id,
        ClientRating.host_id == current_host.id,
    ).first()
    if not rating:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rating not found")

    rating.rating = request.rating
    rating.review = request.review.strip() if request.review else None
    db.commit()
    db.refresh(rating)

    rating = db.query(ClientRating).options(
        joinedload(ClientRating.client),
        joinedload(ClientRating.host),
    ).filter(ClientRating.id == rating.id).first()
    return rating_to_response(rating)


@router.delete("/host/client-ratings/{rating_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_host_client_rating(
    rating_id: int,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db),
):
    """Delete a client rating created by the current host."""
    rating = db.query(ClientRating).filter(
        ClientRating.id == rating_id,
        ClientRating.host_id == current_host.id,
    ).first()
    if not rating:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rating not found")

    db.delete(rating)
    db.commit()
    return None


@router.get("/host/clients/{client_id}/profile", response_model=ClientProfileForHostResponse)
async def get_client_profile_for_host(
    client_id: int,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db),
):
    """
    Get client (renter) profile summary for hosts.

    Returns basic client info plus **trips_count** (number of completed bookings)
    and **average_rating** (from host ratings) so hosts can show "X trips" and
    rating on the renter's profile.
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    trips_count = db.query(Booking).filter(
        Booking.client_id == client_id,
        Booking.status == BookingStatus.COMPLETED,
    ).count()

    avg_rating = db.query(func.avg(ClientRating.rating)).filter(
        ClientRating.client_id == client_id
    ).scalar()

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
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    db: Session = Depends(get_db),
):
    """Public endpoint: get ratings for a specific client (renter)."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    query = db.query(ClientRating).options(
        joinedload(ClientRating.client),
        joinedload(ClientRating.host),
    ).filter(ClientRating.client_id == client_id)
    total = query.count()
    avg = db.query(func.avg(ClientRating.rating)).filter(
        ClientRating.client_id == client_id
    ).scalar()
    ratings = query.order_by(ClientRating.created_at.desc()).offset(skip).limit(limit).all()

    return ClientRatingListResponse(
        ratings=[rating_to_response(r) for r in ratings],
        total=total,
        average_rating=round(float(avg), 2) if avg else None,
    )

