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
from app.models import Car, Host, Booking, BookingStatus
from app.auth import get_current_client
from app.schemas import (
    CarListingResponse,
    CarListResponse,
    CarAvailabilityResponse,
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
