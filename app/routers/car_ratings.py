"""
Car Rating endpoints (primary rating)

Clients rate individual cars after completing a booking.
The host's overall rating is derived from their cars' ratings (see host_ratings.py).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi_cache.decorator import cache
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

import asyncio

from app.auth import get_current_client
from app.database import get_db
from app.models import Booking, BookingStatus, Car, CarRating, Client
from app.services.push_notifications import notify_host_new_rating
from app.schemas import (
    CarRatingCreateRequest,
    CarRatingListResponse,
    CarRatingResponse,
    CarRatingUpdateRequest,
)

router = APIRouter()


def rating_to_response(rating: CarRating) -> dict:
    """Convert CarRating model to CarRatingResponse dict"""
    return {
        "id": rating.id,
        "car_id": rating.car_id,
        "client_id": rating.client_id,
        "booking_id": rating.booking_id,
        "rating": rating.rating,
        "review": rating.review,
        "created_at": rating.created_at,
        "updated_at": rating.updated_at,
        "client_name": rating.client.full_name if rating.client else None,
        "car_name": rating.car.name if rating.car else None,
    }


# ==================== CLIENT CAR RATING ENDPOINTS ====================

@router.post("/client/car-ratings", response_model=CarRatingResponse, status_code=status.HTTP_201_CREATED)
async def create_car_rating(
    request: CarRatingCreateRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Rate a car after a completed booking (primary rating).

    - **car_id**: ID of the car being rated
    - **rating**: 1 to 5 stars
    - **review**: Optional text review (max 1000 characters)
    - **booking_id**: Required — the completed booking this rating belongs to
    - Only one rating is allowed per booking
    - The booking must be completed and belong to the current client
    """
    # Verify car exists
    car_stmt = select(Car).filter(Car.id == request.car_id)
    car_result = await db.execute(car_stmt)
    car = car_result.scalar_one_or_none()
    if not car:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Car not found")

    if request.booking_id:
        booking_stmt = select(Booking).filter(
            Booking.id == request.booking_id,
            Booking.client_id == current_client.id,
            Booking.car_id == request.car_id,
        )
        booking_result = await db.execute(booking_stmt)
        booking = booking_result.scalar_one_or_none()

        if not booking:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Booking not found or does not belong to this client and car",
            )
        if booking.status != BookingStatus.COMPLETED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You can only rate cars for completed bookings",
            )

        # One rating per booking (enforced by unique constraint + API check)
        existing_stmt = select(CarRating).filter(CarRating.booking_id == request.booking_id)
        existing_result = await db.execute(existing_stmt)
        if existing_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This booking has already been rated",
            )

    rating = CarRating(
        car_id=request.car_id,
        client_id=current_client.id,
        booking_id=request.booking_id,
        rating=request.rating,
        review=request.review.strip() if request.review else None,
    )
    db.add(rating)
    await db.commit()
    await db.refresh(rating)

    # Reload with relationships
    stmt = select(CarRating).options(
        joinedload(CarRating.client),
        joinedload(CarRating.car),
    ).filter(CarRating.id == rating.id)
    result = await db.execute(stmt)
    rating = result.scalar_one_or_none()

    # Notify host of new car rating (fire-and-forget)
    if rating and rating.car:
        _client_name = rating.client.full_name if rating.client else "A renter"
        _car_label = f"{rating.car.name} {getattr(rating.car, 'model', '') or ''}".strip()
        asyncio.ensure_future(notify_host_new_rating(
            rating.car.host_id, _client_name, rating.rating, _car_label
        ))

    return rating_to_response(rating)


@router.get("/client/car-ratings", response_model=CarRatingListResponse)
async def get_my_car_ratings(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    car_id: Optional[int] = Query(None, description="Filter by car ID"),
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Get all car ratings submitted by the current client."""
    stmt = select(CarRating).options(
        joinedload(CarRating.client),
        joinedload(CarRating.car),
    ).filter(CarRating.client_id == current_client.id)

    if car_id:
        stmt = stmt.filter(CarRating.car_id == car_id)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    stmt = stmt.order_by(CarRating.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    ratings = result.scalars().all()

    return CarRatingListResponse(
        ratings=[rating_to_response(r) for r in ratings],
        total=total,
        average_rating=None,
    )


@router.get("/client/car-ratings/{rating_id}", response_model=CarRatingResponse)
async def get_car_rating_details(
    rating_id: int,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific car rating submitted by the current client."""
    stmt = select(CarRating).options(
        joinedload(CarRating.client),
        joinedload(CarRating.car),
    ).filter(
        CarRating.id == rating_id,
        CarRating.client_id == current_client.id,
    )
    result = await db.execute(stmt)
    rating = result.scalar_one_or_none()

    if not rating:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rating not found")

    return rating_to_response(rating)


@router.put("/client/car-ratings/{rating_id}", response_model=CarRatingResponse)
async def update_car_rating(
    rating_id: int,
    request: CarRatingUpdateRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing car rating."""
    stmt = select(CarRating).filter(
        CarRating.id == rating_id,
        CarRating.client_id == current_client.id,
    )
    result = await db.execute(stmt)
    rating = result.scalar_one_or_none()

    if not rating:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rating not found")

    rating.rating = request.rating
    rating.review = request.review.strip() if request.review else None
    await db.commit()
    await db.refresh(rating)

    stmt = select(CarRating).options(
        joinedload(CarRating.client),
        joinedload(CarRating.car),
    ).filter(CarRating.id == rating.id)
    result = await db.execute(stmt)
    rating = result.scalar_one_or_none()

    return rating_to_response(rating)


@router.delete("/client/car-ratings/{rating_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_car_rating(
    rating_id: int,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Delete a car rating."""
    stmt = select(CarRating).filter(
        CarRating.id == rating_id,
        CarRating.client_id == current_client.id,
    )
    result = await db.execute(stmt)
    rating = result.scalar_one_or_none()

    if not rating:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rating not found")

    await db.delete(rating)
    await db.commit()
    return None


# ==================== PUBLIC CAR RATING ENDPOINTS ====================

@router.get("/cars/{car_id}/ratings", response_model=CarRatingListResponse)
@cache(expire=120)  # Cache for 2 minutes — public, read-only
async def get_car_ratings(
    car_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all ratings for a specific car (public endpoint).

    - Returns ratings sorted by newest first
    - Includes average rating for this car only
    - No authentication required
    """
    car_stmt = select(Car).filter(Car.id == car_id)
    car_result = await db.execute(car_stmt)
    if not car_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Car not found")

    stmt = select(CarRating).options(
        joinedload(CarRating.client),
        joinedload(CarRating.car),
    ).filter(CarRating.car_id == car_id)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    avg_stmt = select(func.avg(CarRating.rating)).filter(CarRating.car_id == car_id)
    avg_result = await db.execute(avg_stmt)
    average_rating = avg_result.scalar()

    stmt = stmt.order_by(CarRating.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    ratings = result.scalars().all()

    return CarRatingListResponse(
        ratings=[rating_to_response(r) for r in ratings],
        total=total,
        average_rating=round(float(average_rating), 2) if average_rating else None,
    )
