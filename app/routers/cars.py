"""
Car listing endpoints for clients (read-only browsing)
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_
from typing import Optional, List
from datetime import datetime, date
import json

from app.database import get_db
from app.models import Car, Host, Booking, BookingStatus, VerificationStatus
from app.auth import get_current_client, get_current_host
from app.schemas import (
    CarListingResponse,
    CarListResponse,
    CarAvailabilityResponse,
    CarResponse,
    CarStatusResponse,
    CarBasicsRequest,
    CarTechnicalSpecsRequest,
    CarPricingRulesRequest,
    CarLocationRequest,
)

router = APIRouter()


def parse_image_urls(image_urls_str: Optional[str]) -> List[str]:
    """Parse JSON image URLs string to list"""
    if not image_urls_str:
        return []
    try:
        urls = json.loads(image_urls_str)
        return urls if isinstance(urls, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def parse_features(features_str: Optional[str]) -> List[str]:
    """Parse JSON features string to list"""
    if not features_str:
        return []
    try:
        features = json.loads(features_str)
        return features if isinstance(features, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _car_to_response(db_car: Car) -> CarResponse:
    """Helper function to convert Car model to CarResponse"""
    features = None
    if db_car.features:
        try:
            features = json.loads(db_car.features)
        except (json.JSONDecodeError, TypeError):
            features = None
    
    return CarResponse(
        id=db_car.id,
        host_id=db_car.host_id,
        name=db_car.name,
        model=db_car.model,
        body_type=db_car.body_type,
        year=db_car.year,
        description=db_car.description,
        seats=db_car.seats,
        fuel_type=db_car.fuel_type,
        transmission=db_car.transmission,
        color=db_car.color,
        mileage=db_car.mileage,
        features=features,
        daily_rate=db_car.daily_rate,
        weekly_rate=db_car.weekly_rate,
        monthly_rate=db_car.monthly_rate,
        min_rental_days=db_car.min_rental_days,
        max_rental_days=db_car.max_rental_days,
        min_age_requirement=db_car.min_age_requirement,
        rules=db_car.rules,
        location_name=db_car.location_name,
        latitude=db_car.latitude,
        longitude=db_car.longitude,
        is_complete=db_car.is_complete,
        verification_status=VerificationStatus(db_car.verification_status).value if db_car.verification_status else VerificationStatus.AWAITING.value,
        is_hidden=db_car.is_hidden,
        created_at=db_car.created_at,
        updated_at=db_car.updated_at
    )


def car_to_listing_response(car: Car) -> dict:
    """Convert Car model to CarListingResponse dict"""
    return {
        "id": car.id,
        "host_id": car.host_id,
        "name": car.name,
        "model": car.model,
        "body_type": car.body_type,
        "year": car.year,
        "description": car.description,
        "seats": car.seats,
        "fuel_type": car.fuel_type,
        "transmission": car.transmission,
        "color": car.color,
        "mileage": car.mileage,
        "features": parse_features(car.features),
        "daily_rate": car.daily_rate,
        "weekly_rate": car.weekly_rate,
        "monthly_rate": car.monthly_rate,
        "min_rental_days": car.min_rental_days,
        "max_rental_days": car.max_rental_days,
        "min_age_requirement": car.min_age_requirement,
        "rules": car.rules,
        "location_name": car.location_name,
        "latitude": car.latitude,
        "longitude": car.longitude,
        "image_urls": parse_image_urls(car.image_urls),
        "video_url": car.video_url,
        "host_name": car.host.full_name if car.host else None,
        "host_avatar_url": car.host.avatar_url if car.host else None,
        "created_at": car.created_at,
    }


@router.get("/cars", response_model=CarListResponse)
async def get_car_listings(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    location: Optional[str] = Query(None, description="Filter by location name"),
    min_price: Optional[float] = Query(None, ge=0, description="Minimum daily rate"),
    max_price: Optional[float] = Query(None, ge=0, description="Maximum daily rate"),
    body_type: Optional[str] = Query(None, description="Filter by body type"),
    fuel_type: Optional[str] = Query(None, description="Filter by fuel type"),
    transmission: Optional[str] = Query(None, description="Filter by transmission"),
    min_seats: Optional[int] = Query(None, ge=1, description="Minimum number of seats"),
    start_date: Optional[datetime] = Query(None, description="Check availability from this date"),
    end_date: Optional[datetime] = Query(None, description="Check availability until this date"),
    db: Session = Depends(get_db)
):
    """
    Get list of available car listings for clients to browse.
    
    - Returns only complete listings (is_complete = True)
    - Supports filtering by location, price, car type, etc.
    - Supports availability filtering by date range
    - Results are paginated
    """
    # Base query: only complete listings with host data
    query = db.query(Car).options(joinedload(Car.host)).filter(Car.is_complete == True)
    
    # Apply filters
    if location:
        query = query.filter(Car.location_name.ilike(f"%{location}%"))
    
    if min_price is not None:
        query = query.filter(Car.daily_rate >= min_price)
    
    if max_price is not None:
        query = query.filter(Car.daily_rate <= max_price)
    
    if body_type:
        query = query.filter(Car.body_type.ilike(f"%{body_type}%"))
    
    if fuel_type:
        query = query.filter(Car.fuel_type.ilike(f"%{fuel_type}%"))
    
    if transmission:
        query = query.filter(Car.transmission.ilike(f"%{transmission}%"))
    
    if min_seats:
        query = query.filter(Car.seats >= min_seats)
    
    # Date availability filter
    if start_date and end_date:
        # Exclude cars that have overlapping bookings
        # A booking overlaps if: booking.start < requested.end AND booking.end > requested.start
        overlapping_bookings = db.query(Booking.car_id).filter(
            and_(
                Booking.start_date < end_date,
                Booking.end_date > start_date,
                Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.ACTIVE])
            )
        ).subquery()
        
        query = query.filter(~Car.id.in_(overlapping_bookings))
    
    # Get total count before pagination
    total = query.count()
    
    # Apply pagination and order by newest first
    cars = query.order_by(Car.created_at.desc()).offset(skip).limit(limit).all()
    
    # Convert to response format
    car_responses = [car_to_listing_response(car) for car in cars]
    
    return CarListResponse(
        cars=car_responses,
        total=total,
        skip=skip,
        limit=limit
    )


# ==================== HOST CAR CREATION & UPDATE ENDPOINTS ====================
# These must come before /cars/{car_id} to avoid route conflicts

@router.post("/cars/basics", response_model=CarResponse, status_code=status.HTTP_201_CREATED)
async def create_car_basics(
    request: CarBasicsRequest,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db)
):
    """
    Endpoint 1: Create car with basic information
    
    - **name**: Car name
    - **model**: Car model
    - **body_type**: Body type (e.g., Sedan, SUV, Hatchback)
    - **year**: Manufacturing year
    - **description**: Long-form description of the car
    
    Creates a new car listing in incomplete state, linked to the authenticated host.
    """
    # Create new car record
    db_car = Car(
        host_id=current_host.id,
        name=request.name,
        model=request.model,
        body_type=request.body_type,
        year=request.year,
        description=request.description,
        is_complete=False,
        verification_status=VerificationStatus.AWAITING.value
    )
    
    db.add(db_car)
    db.commit()
    db.refresh(db_car)
    
    return _car_to_response(db_car)


@router.put("/cars/{car_id}/specs", response_model=CarResponse)
async def update_car_specs(
    car_id: int,
    request: CarTechnicalSpecsRequest,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db)
):
    """
    Endpoint 2: Update car with technical specifications
    
    - **seats**: Number of seats (1-50)
    - **fuel_type**: Fuel type (e.g., Gasoline, Diesel, Electric)
    - **transmission**: Transmission type (e.g., Manual, Automatic)
    - **color**: Car color
    - **mileage**: Current mileage
    - **features**: List of up to 12 optional features
    
    Updates an existing car record with technical specifications.
    """
    # Get car and verify ownership
    db_car = db.query(Car).filter(Car.id == car_id).first()
    if not db_car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found"
        )
    
    if db_car.host_id != current_host.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to update this car"
        )
    
    # Update car specs
    db_car.seats = request.seats
    db_car.fuel_type = request.fuel_type
    db_car.transmission = request.transmission
    db_car.color = request.color
    db_car.mileage = request.mileage
    db_car.features = json.dumps(request.features) if request.features else None
    
    db.commit()
    db.refresh(db_car)
    
    return _car_to_response(db_car)


@router.put("/cars/{car_id}/pricing", response_model=CarResponse)
async def update_car_pricing(
    car_id: int,
    request: CarPricingRulesRequest,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db)
):
    """
    Endpoint 3: Update car with pricing and rules
    
    - **daily_rate**: Daily rental rate (required, > 0)
    - **weekly_rate**: Weekly rental rate (required, > 0)
    - **monthly_rate**: Monthly rental rate (required, > 0)
    - **min_rental_days**: Minimum rental days (required, >= 1)
    - **max_rental_days**: Maximum rental days (optional, >= 1)
    - **min_age_requirement**: Minimum age requirement (required, 18-100)
    - **rules**: Text-based car rules
    
    Updates an existing car record with pricing and rental rules.
    """
    # Get car and verify ownership
    db_car = db.query(Car).filter(Car.id == car_id).first()
    if not db_car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found"
        )
    
    if db_car.host_id != current_host.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to update this car"
        )
    
    # Update pricing and rules
    db_car.daily_rate = request.daily_rate
    db_car.weekly_rate = request.weekly_rate
    db_car.monthly_rate = request.monthly_rate
    db_car.min_rental_days = request.min_rental_days
    db_car.max_rental_days = request.max_rental_days
    db_car.min_age_requirement = request.min_age_requirement
    db_car.rules = request.rules
    
    db.commit()
    db.refresh(db_car)
    
    return _car_to_response(db_car)


@router.put("/cars/{car_id}/location", response_model=CarResponse)
async def update_car_location(
    car_id: int,
    request: CarLocationRequest,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db)
):
    """
    Endpoint 4: Update car location and mark as complete
    
    - **location_name**: Location name as string (e.g., "Downtown Parking")
    OR
    - **latitude**: Geographic latitude (-90 to 90)
    - **longitude**: Geographic longitude (-180 to 180)
    
    Updates an existing car record with location information and marks it as complete.
    """
    # Get car and verify ownership
    db_car = db.query(Car).filter(Car.id == car_id).first()
    if not db_car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found"
        )
    
    if db_car.host_id != current_host.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to update this car"
        )
    
    # Update location
    if request.location_name:
        db_car.location_name = request.location_name
        db_car.latitude = None
        db_car.longitude = None
    else:
        db_car.location_name = None
        db_car.latitude = request.latitude
        db_car.longitude = request.longitude
    
    # Mark car as complete
    db_car.is_complete = True
    
    db.commit()
    db.refresh(db_car)
    
    return _car_to_response(db_car)


@router.get("/cars/{car_id}", response_model=CarListingResponse)
async def get_car_details(
    car_id: int,
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific car listing.
    
    - **car_id**: The unique identifier of the car (listing_id)
    - Returns full car details including host information
    - Only returns complete listings
    """
    car = db.query(Car).options(joinedload(Car.host)).filter(
        Car.id == car_id,
        Car.is_complete == True
    ).first()
    
    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car listing not found"
        )
    
    return car_to_listing_response(car)


@router.get("/cars/{car_id}/availability", response_model=CarAvailabilityResponse)
async def get_car_availability(
    car_id: int,
    start_date: Optional[datetime] = Query(None, description="Check availability from this date"),
    end_date: Optional[datetime] = Query(None, description="Check availability until this date"),
    db: Session = Depends(get_db)
):
    """
    Check availability of a specific car.
    
    - **car_id**: The unique identifier of the car
    - **start_date**: Optional start date to check specific range
    - **end_date**: Optional end date to check specific range
    - Returns list of booked date ranges and availability status
    """
    # Verify car exists
    car = db.query(Car).filter(Car.id == car_id, Car.is_complete == True).first()
    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car listing not found"
        )
    
    # Get all active bookings for this car
    bookings_query = db.query(Booking).filter(
        Booking.car_id == car_id,
        Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.ACTIVE])
    )
    
    # If checking specific date range, filter to relevant bookings
    if start_date and end_date:
        bookings_query = bookings_query.filter(
            and_(
                Booking.start_date < end_date,
                Booking.end_date > start_date
            )
        )
    
    bookings = bookings_query.order_by(Booking.start_date).all()
    
    # Build booked dates list
    booked_dates = [
        {
            "start_date": booking.start_date.isoformat(),
            "end_date": booking.end_date.isoformat(),
            "status": booking.status.value
        }
        for booking in bookings
    ]
    
    # Check if specific range is available
    available = True
    message = "Car is available"
    
    if start_date and end_date:
        if len(booked_dates) > 0:
            available = False
            message = "Car is not available for the selected dates"
        else:
            message = "Car is available for the selected dates"
    elif len(booked_dates) > 0:
        message = f"Car has {len(booked_dates)} upcoming booking(s)"
    
    return CarAvailabilityResponse(
        car_id=car_id,
        available=available,
        booked_dates=booked_dates,
        message=message
    )


@router.get("/cars/{car_id}/status", response_model=CarStatusResponse)
async def get_car_status(
    car_id: int,
    db: Session = Depends(get_db)
):
    """
    Get car verification status
    
    Returns the verification status of a car (awaiting, verified, or denied).
    This endpoint is used by the UI to monitor the verification status.
    
    - **car_id**: The unique identifier of the car
    """
    db_car = db.query(Car).filter(Car.id == car_id).first()
    if not db_car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found"
        )
    
    # Convert string value to enum
    # db_car.verification_status is now a string, so we convert it to the enum
    try:
        verification_status = VerificationStatus(db_car.verification_status)
    except (ValueError, AttributeError):
        verification_status = VerificationStatus.AWAITING
    
    return CarStatusResponse(
        car_id=db_car.id,
        verification_status=verification_status.value
    )


# ==================== HOST CAR MANAGEMENT ENDPOINTS ====================

@router.get("/host/cars", response_model=List[CarResponse])
async def list_my_cars(
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db)
):
    """
    List all cars belonging to the authenticated host
    
    Returns all cars owned by the currently authenticated host, regardless of verification status.
    """
    cars = db.query(Car).filter(Car.host_id == current_host.id).order_by(Car.created_at.desc()).all()
    return [_car_to_response(car) for car in cars]


@router.put("/host/cars/{car_id}/toggle-visibility", response_model=CarResponse)
async def toggle_car_visibility(
    car_id: int,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db)
):
    """
    Toggle car visibility (show/hide) for verified cars
    
    This endpoint allows hosts to make their verified cars available or hidden from public listings.
    Only verified cars can have their visibility toggled.
    
    - **car_id**: ID of the car to toggle visibility
    """
    # Get car and verify ownership
    db_car = db.query(Car).filter(Car.id == car_id).first()
    if not db_car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found"
        )
    
    if db_car.host_id != current_host.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to modify this car"
        )
    
    # Check if car is verified
    if db_car.verification_status != VerificationStatus.VERIFIED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only verified cars can have their visibility toggled"
        )
    
    # Toggle visibility
    db_car.is_hidden = not db_car.is_hidden
    
    db.commit()
    db.refresh(db_car)
    
    return _car_to_response(db_car)
