"""
Host Rating endpoints for clients

These endpoints allow clients to rate hosts after completing bookings.
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, and_, select

from app.database import get_db
from app.models import HostRating, Host, Client, Booking, BookingStatus
from app.auth import get_current_client
from app.schemas import (
    HostRatingCreateRequest,
    HostRatingUpdateRequest,
    HostRatingResponse,
    HostRatingListResponse,
)

router = APIRouter()


def rating_to_response(rating: HostRating) -> dict:
    """Convert HostRating model to HostRatingResponse dict"""
    return {
        "id": rating.id,
        "host_id": rating.host_id,
        "client_id": rating.client_id,
        "booking_id": rating.booking_id,
        "rating": rating.rating,
        "review": rating.review,
        "created_at": rating.created_at,
        "updated_at": rating.updated_at,
        "client_name": rating.client.full_name if rating.client else None,
    }


# ==================== CLIENT RATING ENDPOINTS ====================

@router.post("/client/host-ratings", response_model=HostRatingResponse, status_code=status.HTTP_201_CREATED)
async def create_host_rating(
    request: HostRatingCreateRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a rating for a host.
    
    - **host_id**: ID of the host being rated
    - **rating**: Rating from 1 to 5 stars
    - **review**: Optional text review (max 1000 characters)
    - **booking_id**: Optional booking ID (if rating is for a specific completed booking)
    
    - Clients can rate a host multiple times (e.g., after different bookings)
    - If booking_id is provided, only one rating per booking is allowed
    - Requires client authentication
    """
    # Verify host exists
    host_stmt = select(Host).filter(Host.id == request.host_id)
    host_result = await db.execute(host_stmt)
    host = host_result.scalar_one_or_none()
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Host not found"
        )
    
    # If booking_id is provided, verify booking exists and belongs to client
    if request.booking_id:
        booking_stmt = select(Booking).options(joinedload(Booking.car)).filter(
            Booking.id == request.booking_id,
            Booking.client_id == current_client.id
        )
        booking_result = await db.execute(booking_stmt)
        booking = booking_result.scalar_one_or_none()
        
        if not booking:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Booking not found or you don't have access to it"
            )
        
        # Verify booking is completed
        if booking.status != BookingStatus.COMPLETED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You can only rate hosts for completed bookings"
            )
        
        # Verify booking's car belongs to the host being rated
        if booking.car.host_id != request.host_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The booking's car does not belong to the specified host"
            )
        
        # Check if rating already exists for this booking
        existing_stmt = select(HostRating).filter(
            HostRating.booking_id == request.booking_id,
            HostRating.client_id == current_client.id
        )
        existing_result = await db.execute(existing_stmt)
        existing_rating = existing_result.scalar_one_or_none()
        
        if existing_rating:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You have already rated this booking"
            )
    
    # Create rating
    rating = HostRating(
        host_id=request.host_id,
        client_id=current_client.id,
        booking_id=request.booking_id,
        rating=request.rating,
        review=request.review.strip() if request.review else None
    )
    
    db.add(rating)
    await db.commit()
    await db.refresh(rating)
    
    # Load relationships for response
    rating_stmt = select(HostRating).options(
        joinedload(HostRating.client)
    ).filter(HostRating.id == rating.id)
    rating_result = await db.execute(rating_stmt)
    rating = rating_result.scalar_one_or_none()
    
    return rating_to_response(rating)


@router.get("/client/host-ratings", response_model=HostRatingListResponse)
async def get_my_host_ratings(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    host_id: Optional[int] = Query(None, description="Filter by host ID"),
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all ratings submitted by the current client.
    
    - Returns ratings sorted by creation date (newest first)
    - Supports filtering by host_id
    - Results are paginated
    - Requires client authentication
    """
    stmt = select(HostRating).options(
        joinedload(HostRating.client)
    ).filter(HostRating.client_id == current_client.id)
    
    # Filter by host_id if provided
    if host_id:
        stmt = stmt.filter(HostRating.host_id == host_id)
    
    # Get total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0
    
    # Apply pagination and order by newest first
    stmt = stmt.order_by(HostRating.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    ratings = result.scalars().all()
    
    # Convert to response format
    rating_responses = [rating_to_response(r) for r in ratings]
    
    return HostRatingListResponse(
        ratings=rating_responses,
        total=total,
        average_rating=None  # Not applicable for client's own ratings
    )


@router.get("/client/host-ratings/{rating_id}", response_model=HostRatingResponse)
async def get_host_rating_details(
    rating_id: int,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed information about a specific rating.
    
    - Only returns ratings owned by the authenticated client
    - Requires client authentication
    """
    stmt = select(HostRating).options(
        joinedload(HostRating.client)
    ).filter(
        HostRating.id == rating_id,
        HostRating.client_id == current_client.id
    )
    result = await db.execute(stmt)
    rating = result.scalar_one_or_none()
    
    if not rating:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rating not found"
        )
    
    return rating_to_response(rating)


@router.put("/client/host-ratings/{rating_id}", response_model=HostRatingResponse)
async def update_host_rating(
    rating_id: int,
    request: HostRatingUpdateRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db)
):
    """
    Update an existing rating.
    
    - Only the client who created the rating can update it
    - Can update both rating and review
    - Requires client authentication
    """
    stmt = select(HostRating).filter(
        HostRating.id == rating_id,
        HostRating.client_id == current_client.id
    )
    result = await db.execute(stmt)
    rating = result.scalar_one_or_none()
    
    if not rating:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rating not found"
        )
    
    # Update rating
    rating.rating = request.rating
    rating.review = request.review.strip() if request.review else None
    
    await db.commit()
    await db.refresh(rating)
    
    # Load relationships for response
    rating_stmt = select(HostRating).options(
        joinedload(HostRating.client)
    ).filter(HostRating.id == rating.id)
    rating_result = await db.execute(rating_stmt)
    rating = rating_result.scalar_one_or_none()
    
    return rating_to_response(rating)


@router.delete("/client/host-ratings/{rating_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_host_rating(
    rating_id: int,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a rating.
    
    - Only the client who created the rating can delete it
    - Requires client authentication
    """
    stmt = select(HostRating).filter(
        HostRating.id == rating_id,
        HostRating.client_id == current_client.id
    )
    result = await db.execute(stmt)
    rating = result.scalar_one_or_none()
    
    if not rating:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rating not found"
        )
    
    await db.delete(rating)
    await db.commit()
    
    return None


# ==================== PUBLIC HOST RATING ENDPOINTS ====================

@router.get("/hosts/{host_id}/ratings", response_model=HostRatingListResponse)
async def get_host_ratings(
    host_id: int,
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all ratings for a specific host (public endpoint).
    
    - Returns ratings sorted by creation date (newest first)
    - Includes average rating calculation
    - Results are paginated
    - No authentication required (public endpoint)
    """
    # Verify host exists
    host_stmt = select(Host).filter(Host.id == host_id)
    host_result = await db.execute(host_stmt)
    host = host_result.scalar_one_or_none()
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Host not found"
        )
    
    stmt = select(HostRating).options(
        joinedload(HostRating.client)
    ).filter(HostRating.host_id == host_id)
    
    # Get total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0
    
    # Calculate average rating
    avg_stmt = select(func.avg(HostRating.rating)).filter(HostRating.host_id == host_id)
    avg_result = await db.execute(avg_stmt)
    average_rating = avg_result.scalar()
    
    # Apply pagination and order by newest first
    stmt = stmt.order_by(HostRating.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    ratings = result.scalars().all()
    
    # Convert to response format
    rating_responses = [rating_to_response(r) for r in ratings]
    
    return HostRatingListResponse(
        ratings=rating_responses,
        total=total,
        average_rating=round(float(average_rating), 2) if average_rating else None
    )
