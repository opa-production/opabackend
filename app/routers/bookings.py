"""
Booking endpoints for clients (and hosts)
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_
from typing import Optional, List
from datetime import datetime
import json
import uuid

from app.database import get_db
from app.models import Car, Client, Booking, BookingStatus, Host, VerificationStatus
from app.auth import get_current_client, get_current_host
from app.schemas import (
    BookingCreateRequest,
    BookingResponse,
    BookingListResponse,
    BookingCancelRequest,
    BookingStatusEnum,
)

router = APIRouter()

# Damage waiver price per day (KES)
DAMAGE_WAIVER_PRICE_PER_DAY = 250


def parse_image_urls(image_urls_str: Optional[str]) -> List[str]:
    """Parse JSON image URLs string to list"""
    if not image_urls_str:
        return []
    try:
        urls = json.loads(image_urls_str)
        return urls if isinstance(urls, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def generate_booking_id() -> str:
    """Generate a unique human-readable booking ID"""
    # Format: BK-XXXXXXXX (8 random characters)
    unique_part = uuid.uuid4().hex[:8].upper()
    return f"BK-{unique_part}"


def booking_to_response(booking: Booking) -> dict:
    """Convert Booking model to BookingResponse dict"""
    car = booking.car
    host = car.host if car else None
    
    client = getattr(booking, "client", None)
    return {
        "id": booking.id,
        "booking_id": booking.booking_id,
        "client_id": booking.client_id,
        "client_name": client.full_name if client else None,
        "client_email": client.email if client else None,
        "car_id": booking.car_id,
        
        # Car details
        "car_name": car.name if car else None,
        "car_model": car.model if car else None,
        "car_year": car.year if car else None,
        "car_make": car.name if car else None,  # Using name as make for now
        "car_image_urls": parse_image_urls(car.image_urls) if car else [],
        
        # Host details
        "host_id": host.id if host else None,
        "host_name": host.full_name if host else None,
        
        # Booking dates
        "start_date": booking.start_date,
        "end_date": booking.end_date,
        "pickup_time": booking.pickup_time,
        "return_time": booking.return_time,
        "pickup_location": booking.pickup_location,
        "return_location": booking.return_location,
        
        # Pricing
        "daily_rate": booking.daily_rate,
        "rental_days": booking.rental_days,
        "base_price": booking.base_price,
        "damage_waiver_fee": booking.damage_waiver_fee,
        "total_price": booking.total_price,
        
        # Options
        "damage_waiver_enabled": booking.damage_waiver_enabled,
        "drive_type": booking.drive_type,
        "check_in_preference": booking.check_in_preference,
        "special_requirements": booking.special_requirements,
        
        # Status
        "status": booking.status.value,
        "status_updated_at": booking.status_updated_at,
        "cancellation_reason": booking.cancellation_reason,
        
        # Timestamps
        "created_at": booking.created_at,
        "updated_at": booking.updated_at,
    }


def check_booking_overlap(db: Session, car_id: int, start_date: datetime, end_date: datetime, exclude_booking_id: Optional[int] = None) -> bool:
    """
    Check if there's an overlapping booking for the given car and date range.
    Returns True if there's an overlap (NOT available), False if available.
    """
    query = db.query(Booking).filter(
        Booking.car_id == car_id,
        Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.ACTIVE]),
        # Overlap condition: booking.start < requested.end AND booking.end > requested.start
        Booking.start_date < end_date,
        Booking.end_date > start_date
    )
    
    if exclude_booking_id:
        query = query.filter(Booking.id != exclude_booking_id)
    
    return query.first() is not None


@router.post("/client/bookings", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    request: BookingCreateRequest,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """
    Create a new car booking.
    
    - Validates car exists and is verified
    - Validates date range doesn't overlap with existing bookings
    - Validates minimum rental days requirement
    - Creates booking with 'pending' status
    - Returns full booking details
    
    Requires client authentication.
    """
    # Verify car exists and is verified
    car = db.query(Car).options(joinedload(Car.host)).filter(
        Car.id == request.car_id,
        Car.verification_status == VerificationStatus.VERIFIED.value
    ).first()
    
    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car listing not found or not verified"
        )
    
    # Calculate rental days
    rental_days = (request.end_date - request.start_date).days
    if rental_days < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rental period must be at least 1 day"
        )
    
    # Validate minimum rental days
    if car.min_rental_days and rental_days < car.min_rental_days:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Minimum rental period for this car is {car.min_rental_days} days"
        )
    
    # Validate maximum rental days
    if car.max_rental_days and rental_days > car.max_rental_days:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum rental period for this car is {car.max_rental_days} days"
        )
    
    # Check for overlapping bookings (prevents double booking)
    if check_booking_overlap(db, car.id, request.start_date, request.end_date):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Car is not available for the selected dates. Please choose different dates."
        )
    
    # Calculate pricing
    base_price = car.daily_rate * rental_days
    damage_waiver_fee = DAMAGE_WAIVER_PRICE_PER_DAY * rental_days if request.damage_waiver_enabled else 0
    total_price = base_price + damage_waiver_fee
    
    # Generate unique booking ID
    booking_id = generate_booking_id()
    
    # Ensure booking ID is unique
    while db.query(Booking).filter(Booking.booking_id == booking_id).first():
        booking_id = generate_booking_id()
    
    # Create booking
    booking = Booking(
        booking_id=booking_id,
        client_id=current_client.id,
        car_id=car.id,
        start_date=request.start_date,
        end_date=request.end_date,
        pickup_time=request.pickup_time,
        return_time=request.return_time,
        pickup_location=request.pickup_location or car.location_name,
        return_location=request.return_location or request.pickup_location or car.location_name,
        daily_rate=car.daily_rate,
        rental_days=rental_days,
        base_price=base_price,
        damage_waiver_fee=damage_waiver_fee,
        total_price=total_price,
        damage_waiver_enabled=request.damage_waiver_enabled,
        drive_type=request.drive_type,
        check_in_preference=request.check_in_preference,
        special_requirements=request.special_requirements,
        status=BookingStatus.PENDING
    )
    
    db.add(booking)
    db.commit()
    db.refresh(booking)
    
    # Load relationships for response
    booking = db.query(Booking).options(
        joinedload(Booking.car).joinedload(Car.host)
    ).filter(Booking.id == booking.id).first()
    
    return booking_to_response(booking)


@router.get("/client/bookings", response_model=BookingListResponse)
async def get_my_bookings(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    status: Optional[str] = Query(None, description="Filter by booking status"),
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """
    Get all bookings for the current authenticated client.
    
    - Returns bookings sorted by creation date (newest first)
    - Supports filtering by status
    - Results are paginated
    
    Requires client authentication.
    """
    query = db.query(Booking).options(
        joinedload(Booking.car).joinedload(Car.host)
    ).filter(Booking.client_id == current_client.id)
    
    # Filter by status if provided
    if status:
        try:
            status_enum = BookingStatus(status.lower())
            query = query.filter(Booking.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Valid values: {[s.value for s in BookingStatus]}"
            )
    
    # Get total count
    total = query.count()
    
    # Apply pagination and order by newest first
    bookings = query.order_by(Booking.created_at.desc()).offset(skip).limit(limit).all()
    
    # Convert to response format
    booking_responses = [booking_to_response(b) for b in bookings]
    
    return BookingListResponse(
        bookings=booking_responses,
        total=total,
        skip=skip,
        limit=limit
    )


def _client_booking_query(db: Session, booking_id_param: str, client_id: int):
    """Resolve booking by either numeric id or string booking_id (e.g. BK-ABC12345). Returns query with client filter."""
    base = db.query(Booking).options(
        joinedload(Booking.car).joinedload(Car.host)
    ).filter(Booking.client_id == client_id)
    if booking_id_param.isdigit():
        return base.filter(Booking.id == int(booking_id_param)).first()
    return base.filter(Booking.booking_id == booking_id_param).first()


@router.get("/client/bookings/{booking_id}", response_model=BookingResponse)
async def get_booking_details(
    booking_id: str,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific booking.

    - **booking_id**: The unique booking identifier (e.g. BK-12345678) **or** the numeric database id (e.g. 5)
    - Only returns bookings owned by the authenticated client

    Requires client authentication.
    """
    booking = _client_booking_query(db, booking_id, current_client.id)
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )
    return booking_to_response(booking)


@router.post("/client/bookings/{booking_id}/cancel", response_model=BookingResponse)
async def cancel_booking(
    booking_id: str,
    request: Optional[BookingCancelRequest] = None,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """
    Cancel an existing booking.

    - **booking_id**: The unique booking identifier (e.g. BK-12345678) or numeric id
    - Only pending or confirmed bookings can be cancelled
    - Only the booking owner can cancel

    Requires client authentication.
    """
    booking = _client_booking_query(db, booking_id, current_client.id)
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )
    
    # Check if booking can be cancelled
    if booking.status not in [BookingStatus.PENDING, BookingStatus.CONFIRMED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel booking with status '{booking.status.value}'. Only pending or confirmed bookings can be cancelled."
        )
    
    # Update booking status
    booking.status = BookingStatus.CANCELLED
    booking.status_updated_at = datetime.utcnow()
    if request and request.reason:
        booking.cancellation_reason = request.reason
    
    db.commit()
    db.refresh(booking)
    
    return booking_to_response(booking)


# ==================== CLIENT COMPLETED BOOKINGS ====================

@router.get("/client/bookings/completed", response_model=BookingListResponse)
async def get_my_completed_bookings(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """
    Convenience endpoint to get only **completed** bookings for the current client.

    - Uses the same shape as `/client/bookings`
    - Results are paginated and sorted by creation date (newest first)
    """
    query = db.query(Booking).options(
        joinedload(Booking.car).joinedload(Car.host)
    ).filter(
        Booking.client_id == current_client.id,
        Booking.status == BookingStatus.COMPLETED,
    )

    total = query.count()
    bookings = query.order_by(Booking.created_at.desc()).offset(skip).limit(limit).all()
    booking_responses = [booking_to_response(b) for b in bookings]

    return BookingListResponse(
        bookings=booking_responses,
        total=total,
        skip=skip,
        limit=limit,
    )


# ==================== HOST BOOKINGS ====================

@router.get("/host/bookings", response_model=BookingListResponse)
async def get_host_bookings(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    status: Optional[str] = Query(None, description="Filter by booking status"),
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db),
):
    """
    Get bookings for the current authenticated host.

    - Returns bookings where the car belongs to the host
    - Supports filtering by status
    - Results are paginated and sorted by creation date (newest first)
    """
    query = (
        db.query(Booking)
        .options(
            joinedload(Booking.car).joinedload(Car.host),
            joinedload(Booking.client),
        )
        .join(Car)
        .filter(Car.host_id == current_host.id)
    )

    if status:
        try:
            status_enum = BookingStatus(status.lower())
            query = query.filter(Booking.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Valid values: {[s.value for s in BookingStatus]}",
            )

    total = query.count()
    bookings = query.order_by(Booking.created_at.desc()).offset(skip).limit(limit).all()
    booking_responses = [booking_to_response(b) for b in bookings]

    return BookingListResponse(
        bookings=booking_responses,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/host/bookings/completed", response_model=BookingListResponse)
async def get_host_completed_bookings(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db),
):
    """
    Convenience endpoint to get only **completed** bookings for the current host.

    - Returns bookings where the car belongs to the host
    - Results are paginated and sorted by creation date (newest first)
    """
    query = (
        db.query(Booking)
        .options(
            joinedload(Booking.car).joinedload(Car.host),
            joinedload(Booking.client),
        )
        .join(Car)
        .filter(
            Car.host_id == current_host.id,
            Booking.status == BookingStatus.COMPLETED,
        )
    )

    total = query.count()
    bookings = query.order_by(Booking.created_at.desc()).offset(skip).limit(limit).all()
    booking_responses = [booking_to_response(b) for b in bookings]

    return BookingListResponse(
        bookings=booking_responses,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/host/bookings/{booking_id}", response_model=BookingResponse)
async def get_host_booking_details(
    booking_id: str,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db),
):
    """
    Get detailed information about a specific booking for a host.

    - Only returns bookings where the car belongs to the authenticated host
    """
    booking = (
        db.query(Booking)
        .options(
            joinedload(Booking.car).joinedload(Car.host),
            joinedload(Booking.client),
        )
        .join(Car)
        .filter(
            Booking.booking_id == booking_id,
            Car.host_id == current_host.id,
        )
        .first()
    )

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    return booking_to_response(booking)


@router.put("/host/bookings/{booking_id}/confirm-pickup", response_model=BookingResponse)
async def confirm_pickup_as_host(
    booking_id: str,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db),
):
    """
    Confirm that the client has picked up the car (host side). Moves booking from **confirmed** to **active**.

    - Only the host who owns the car can confirm pickup
    - Only `confirmed` bookings can be moved to active
    """
    booking = (
        db.query(Booking)
        .options(
            joinedload(Booking.car).joinedload(Car.host),
            joinedload(Booking.client),
        )
        .join(Car)
        .filter(
            Booking.booking_id == booking_id,
            Car.host_id == current_host.id,
        )
        .first()
    )

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    if booking.status != BookingStatus.CONFIRMED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Only confirmed bookings can have pickup confirmed. "
                f"Current status is '{booking.status.value}'."
            ),
        )

    booking.status = BookingStatus.ACTIVE
    booking.status_updated_at = datetime.utcnow()

    db.commit()
    db.refresh(booking)

    return booking_to_response(booking)


@router.post("/host/bookings/{booking_id}/complete", response_model=BookingResponse)
async def complete_booking_as_host(
    booking_id: str,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db),
):
    """
    Mark a booking as **completed** from the host side (e.g., after drop‑off confirmation).

    - Only the host who owns the car can complete the booking
    - Only `confirmed` or `active` bookings can be completed
    """
    booking = (
        db.query(Booking)
        .options(
            joinedload(Booking.car).joinedload(Car.host),
            joinedload(Booking.client),
        )
        .join(Car)
        .filter(
            Booking.booking_id == booking_id,
            Car.host_id == current_host.id,
        )
        .first()
    )

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    if booking.status not in [BookingStatus.CONFIRMED, BookingStatus.ACTIVE]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Only confirmed or active bookings can be marked as completed by the host. "
                f"Current status is '{booking.status.value}'."
            ),
        )

    booking.status = BookingStatus.COMPLETED
    booking.status_updated_at = datetime.utcnow()
    booking.cancellation_reason = None

    db.commit()
    db.refresh(booking)

    return booking_to_response(booking)


@router.delete("/client/bookings/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_booking(
    booking_id: str,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """
    Delete a booking (soft delete by cancelling).

    **booking_id** can be the string (e.g. BK-12345678) or numeric id.
    Use POST /bookings/{booking_id}/cancel for more control.

    Requires client authentication.
    """
    booking = _client_booking_query(db, booking_id, current_client.id)
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )
    
    # Check if booking can be cancelled
    if booking.status not in [BookingStatus.PENDING, BookingStatus.CONFIRMED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete booking with status '{booking.status.value}'"
        )
    
    # Soft delete by cancelling
    booking.status = BookingStatus.CANCELLED
    booking.status_updated_at = datetime.utcnow()
    booking.cancellation_reason = "Deleted by client"
    
    db.commit()
    
    return None
