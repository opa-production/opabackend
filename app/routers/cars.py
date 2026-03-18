"""
Car listing endpoints for clients (read-only browsing)
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, or_, func, select
from typing import Optional, List
from datetime import datetime, date, timedelta
import json
import logging

logger = logging.getLogger(__name__)

from app.database import get_db
from app.models import Car, Host, Booking, BookingStatus, VerificationStatus, CarBlockedDate
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
    CarMediaRequest,
    CarMediaUrlsRequest,
    CarExploreItemResponse,
    CarExploreListResponse,
    CarBlockedDateRequest,
    DriveSettingsRequest,
    DriveSettingsResponse,
    DRIVE_SETTING_TO_ALLOWED,
)

router = APIRouter()


def parse_image_urls(image_urls_str: Optional[str]) -> List[str]:
    """Parse JSON image URLs string to list"""
    if not image_urls_str:
        logger.debug(f"🖼️ [PARSE IMAGE URLS] Input is None or empty")
        return []
    try:
        urls = json.loads(image_urls_str)
        if isinstance(urls, list):
            logger.debug(f"🖼️ [PARSE IMAGE URLS] Successfully parsed {len(urls)} URLs from JSON string")
            return urls
        logger.warning(f"🖼️ [PARSE IMAGE URLS] Parsed JSON is not a list: {type(urls)}")
        return []
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"🖼️ [PARSE IMAGE URLS] Failed to parse JSON: {str(e)}, input={image_urls_str[:100] if image_urls_str else None}")
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


def _get_allowed_drive_types(drive_setting: Optional[str]) -> List[str]:
    """Derive allowed drive types from car's drive_setting."""
    setting = (drive_setting or "self_only").strip()
    return DRIVE_SETTING_TO_ALLOWED.get(setting, ["self"])


def _car_to_response(db_car: Car) -> CarResponse:
    """Helper function to convert Car model to CarResponse"""
    features = None
    if db_car.features:
        try:
            features = json.loads(db_car.features)
        except (json.JSONDecodeError, TypeError):
            features = None
    
    # car_images: Return as JSON string (frontend expects string, not parsed array)
    # Frontend will parse the JSON string itself
    car_images_str = db_car.car_images  # Already a JSON string in database
    
    # Parse car_images for legacy image_urls fallback (for backward compatibility)
    car_images_parsed = None
    if db_car.car_images:
        try:
            car_images_parsed = json.loads(db_car.car_images)
            if not isinstance(car_images_parsed, list):
                car_images_parsed = None
        except (json.JSONDecodeError, TypeError):
            car_images_parsed = None
    
    # Parse image_urls (legacy)
    image_urls = None
    if db_car.image_urls:
        try:
            image_urls = json.loads(db_car.image_urls)
            if not isinstance(image_urls, list):
                image_urls = None
        except (json.JSONDecodeError, TypeError):
            image_urls = None
    
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
        drive_setting=getattr(db_car, "drive_setting", None) or "self_only",
        allowed_drive_types=_get_allowed_drive_types(getattr(db_car, "drive_setting", None)),
        cover_image=db_car.cover_image,
        car_images=car_images_str,  # JSON string (frontend expects string, not array)
        car_video=db_car.car_video,
        image_urls=car_images_parsed if car_images_parsed else image_urls,  # Legacy - parsed array for backward compatibility
        video_url=db_car.video_url,  # Legacy
        created_at=db_car.created_at,
        updated_at=db_car.updated_at
    )


def car_to_listing_response(car: Car) -> dict:
    """Convert Car model to CarListingResponse dict - full car details for details page"""
    # Parse car_images from JSON string to array (for carousel)
    car_images_array = None
    if car.car_images:
        car_images_array = parse_image_urls(car.car_images)
    
    # Fallback to legacy image_urls if car_images is empty
    legacy_image_urls = parse_image_urls(car.image_urls)
    if not car_images_array and legacy_image_urls:
        car_images_array = legacy_image_urls
    
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
        # New media fields (preferred)
        "cover_image": car.cover_image,
        "car_images": car_images_array,  # Array for carousel
        "car_video": car.car_video,
        # Legacy fields (for backward compatibility)
        "image_urls": legacy_image_urls,
        "video_url": car.video_url,
        # Drive options (for client car details + booking)
        "drive_setting": getattr(car, "drive_setting", None) or "self_only",
        "allowed_drive_types": _get_allowed_drive_types(getattr(car, "drive_setting", None)),
        # Host information
        "host_name": car.host.full_name if car.host else None,
        "host_avatar_url": car.host.avatar_url if car.host else None,
        "host_created_at": car.host.created_at if car.host else None,
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
    db: AsyncSession = Depends(get_db)
):
    """
    Get list of available car listings for clients to browse.
    
    - Returns only complete listings (is_complete = True)
    - Supports filtering by location, price, car type, etc.
    - When start_date and end_date (pickup and return dates) are provided, returns only cars
      that are available for that period: no overlapping booking (pending/confirmed/active)
      and no overlapping host-blocked dates.
    - Results are paginated
    """
    # Base query: only complete listings with host data
    stmt = select(Car).options(joinedload(Car.host)).filter(Car.is_complete == True)
    
    # Apply filters
    if location:
        stmt = stmt.filter(Car.location_name.ilike(f"%{location}%"))
    
    if min_price is not None:
        stmt = stmt.filter(Car.daily_rate >= min_price)
    
    if max_price is not None:
        stmt = stmt.filter(Car.daily_rate <= max_price)
    
    if body_type:
        stmt = stmt.filter(Car.body_type.ilike(f"%{body_type}%"))
    
    if fuel_type:
        stmt = stmt.filter(Car.fuel_type.ilike(f"%{fuel_type}%"))
    
    if transmission:
        stmt = stmt.filter(Car.transmission.ilike(f"%{transmission}%"))
    
    if min_seats:
        stmt = stmt.filter(Car.seats >= min_seats)
    
    # Date availability filter (start_date = pickup, end_date = return)
    if start_date and end_date:
        # Exclude cars that have overlapping bookings
        # A booking overlaps if: booking.start < requested.end AND booking.end > requested.start
        overlapping_bookings = select(Booking.car_id).filter(
            and_(
                Booking.start_date < end_date,
                Booking.end_date > start_date,
                Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.ACTIVE])
            )
        )
        stmt = stmt.filter(~Car.id.in_(overlapping_bookings))

        # Exclude cars that have host-blocked dates overlapping the requested range
        # Blocked range overlaps if: blocked.start < requested.end AND blocked.end > requested.start
        overlapping_blocked = select(CarBlockedDate.car_id).filter(
            and_(
                CarBlockedDate.start_date < end_date,
                CarBlockedDate.end_date > start_date
            )
        ).distinct()
        stmt = stmt.filter(~Car.id.in_(overlapping_blocked))
    
    # Get total count before pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0
    
    # Apply pagination and order by newest first
    stmt = stmt.order_by(Car.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    cars = result.scalars().all()
    
    # Convert to response format
    car_responses = [car_to_listing_response(car) for car in cars]
    
    return CarListResponse(
        cars=car_responses,
        total=total,
        skip=skip,
        limit=limit
    )


@router.get("/client/cars/explore", response_model=CarExploreListResponse)
async def explore_cars(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by car name, model, or location"),
    location: Optional[str] = Query(None, description="Filter by location name"),
    min_price: Optional[float] = Query(None, ge=0, description="Minimum daily rate"),
    max_price: Optional[float] = Query(None, ge=0, description="Maximum daily rate"),
    body_type: Optional[str] = Query(None, description="Filter by body type"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get cars for explore page - simplified listing for clients
    
    Returns only verified and visible cars with essential information:
    - cover_image: First image from image_urls
    - car_name: Car name
    - price_per_day: Daily rental rate
    - rating: Car rating (placeholder for future)
    - is_renters_favourite: Whether car is marked as favourite (placeholder)
    - is_wishlisted: Whether car is in user's wishlist (placeholder)
    - location_name: Car location
    
    Filters:
    - Only shows verified cars (verification_status = 'verified')
    - Only shows visible cars (is_hidden = False)
    - Supports search by name, model, or location
    - Supports filtering by location, price range, body type
    """
    logger.info(f"🖼️ [EXPLORE CARS] Request received: page={page}, limit={limit}, "
               f"search={search}, location={location}, min_price={min_price}, "
               f"max_price={max_price}, body_type={body_type}")
    
    # Base query: only verified and visible listings (is_complete not required for explore)
    stmt = select(Car).options(joinedload(Car.host)).filter(
        Car.verification_status == VerificationStatus.VERIFIED.value,
        Car.is_hidden == False
    )
    
    # Apply search filter
    if search:
        search_filter = or_(
            Car.name.ilike(f"%{search}%"),
            Car.model.ilike(f"%{search}%"),
            Car.location_name.ilike(f"%{search}%")
        )
        stmt = stmt.filter(search_filter)
    
    # Apply location filter
    if location:
        stmt = stmt.filter(Car.location_name.ilike(f"%{location}%"))
    
    # Apply price filters
    if min_price is not None:
        stmt = stmt.filter(Car.daily_rate >= min_price)
    
    if max_price is not None:
        stmt = stmt.filter(Car.daily_rate <= max_price)
    
    # Apply body type filter
    if body_type:
        stmt = stmt.filter(Car.body_type.ilike(f"%{body_type}%"))
    
    # Get total count before pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0
    
    # Calculate pagination
    skip = (page - 1) * limit
    total_pages = (total + limit - 1) // limit if limit > 0 else 0
    
    # Apply pagination and order by newest first
    stmt = stmt.order_by(Car.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    cars = result.scalars().all()
    
    # Convert to explore response format
    car_responses = []
    logger.info(f"🖼️ [EXPLORE CARS] Processing {len(cars)} cars for explore page")
    
    for car in cars:
        # Get cover image - prefer cover_image, fallback to first image from car_images or image_urls
        cover_image = None
        cover_image_source = None
        
        if car.cover_image:
            cover_image = car.cover_image
            cover_image_source = "cover_image_field"
            logger.debug(f"🖼️ [EXPLORE CARS] Car {car.id}: Using cover_image field: {cover_image}")
        elif car.car_images:
            car_images = parse_image_urls(car.car_images)
            logger.debug(f"🖼️ [EXPLORE CARS] Car {car.id}: Parsed car_images: {car_images}")
            if car_images and len(car_images) > 0:
                cover_image = car_images[0]
                cover_image_source = "car_images_first"
                logger.debug(f"🖼️ [EXPLORE CARS] Car {car.id}: Using first from car_images: {cover_image}")
            else:
                logger.warning(f"🖼️ [EXPLORE CARS] Car {car.id}: car_images exists but parsed to empty list")
        elif car.image_urls:
            # Legacy fallback
            image_urls = parse_image_urls(car.image_urls)
            logger.debug(f"🖼️ [EXPLORE CARS] Car {car.id}: Parsed legacy image_urls: {image_urls}")
            if image_urls and len(image_urls) > 0:
                cover_image = image_urls[0]
                cover_image_source = "image_urls_legacy"
                logger.debug(f"🖼️ [EXPLORE CARS] Car {car.id}: Using first from legacy image_urls: {cover_image}")
            else:
                logger.warning(f"🖼️ [EXPLORE CARS] Car {car.id}: image_urls exists but parsed to empty list")
        
        if not cover_image:
            logger.warning(f"🖼️ [EXPLORE CARS] Car {car.id}: No cover image found. "
                          f"cover_image={car.cover_image}, car_images={car.car_images}, "
                          f"image_urls={car.image_urls}")
        
        # Build car name (name + model if available)
        car_name = car.name
        if car.model:
            car_name = f"{car.name} {car.model}".strip() if car.name else car.model
        
        car_responses.append(CarExploreItemResponse(
            id=car.id,
            cover_image=cover_image,
            car_name=car_name,
            price_per_day=car.daily_rate,
            rating=None,  # Placeholder for future rating system
            is_renters_favourite=False,  # Placeholder for future favourite system
            is_wishlisted=False,  # Placeholder for future wishlist system
            location_name=car.location_name
        ))
        
        logger.debug(f"🖼️ [EXPLORE CARS] Car {car.id}: Added to response. cover_image={cover_image} "
                    f"(source={cover_image_source}), car_name={car_name}")
    
    logger.info(f"🖼️ [EXPLORE CARS] ✅ Returning {len(car_responses)} cars. "
               f"Total matching: {total}, Page: {page}/{total_pages}")
    
    return CarExploreListResponse(
        cars=car_responses,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages
    )


# ==================== HOST CAR CREATION & UPDATE ENDPOINTS ====================
# These must come before /cars/{car_id} to avoid route conflicts

@router.post("/cars/basics", response_model=CarResponse, status_code=status.HTTP_201_CREATED)
async def create_car_basics(
    request: CarBasicsRequest,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db)
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
    await db.commit()
    await db.refresh(db_car)
    
    return _car_to_response(db_car)


@router.put("/cars/{car_id}/specs", response_model=CarResponse)
async def update_car_specs(
    car_id: int,
    request: CarTechnicalSpecsRequest,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db)
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
    result = await db.execute(select(Car).filter(Car.id == car_id))
    db_car = result.scalar_one_or_none()
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
    
    await db.commit()
    await db.refresh(db_car)
    
    return _car_to_response(db_car)


@router.put("/cars/{car_id}/pricing", response_model=CarResponse)
async def update_car_pricing(
    car_id: int,
    request: CarPricingRulesRequest,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db)
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
    result = await db.execute(select(Car).filter(Car.id == car_id))
    db_car = result.scalar_one_or_none()
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
    
    await db.commit()
    await db.refresh(db_car)
    
    return _car_to_response(db_car)


@router.put("/cars/{car_id}/location", response_model=CarResponse)
async def update_car_location(
    car_id: int,
    request: CarLocationRequest,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db)
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
    result = await db.execute(select(Car).filter(Car.id == car_id))
    db_car = result.scalar_one_or_none()
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
    
    await db.commit()
    await db.refresh(db_car)
    
    return _car_to_response(db_car)



@router.put("/host/cars/{car_id}/media", response_model=CarResponse)
async def update_car_media(
    car_id: int,
    request: CarMediaRequest,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db)
):
    """
    Update car media URLs after uploading to Supabase
    
    Frontend sends URLs (already uploaded to Supabase), not file uploads.
    
    Request body:
    - **files**: REQUIRED - Array of image URLs (max 12 items)
    - **cover_image**: OPTIONAL - Cover image URL
    - **car_video**: OPTIONAL - Video URL
    
    Response:
    - **car_images**: JSON string (e.g., '["url1", "url2"]') - frontend parses this
    """
    logger.info(f"🖼️ [UPDATE CAR MEDIA] Request received for car_id={car_id}, host_id={current_host.id}")
    logger.info(f"🖼️ [UPDATE CAR MEDIA] Request body: files={request.files} ({len(request.files)} images), "
                f"cover_image={request.cover_image}, car_video={request.car_video}")
    
    # Get car and verify ownership
    result = await db.execute(select(Car).filter(Car.id == car_id))
    db_car = result.scalar_one_or_none()
    if not db_car:
        logger.error(f"🖼️ [UPDATE CAR MEDIA] Car not found: car_id={car_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found"
        )
    
    logger.info(f"🖼️ [UPDATE CAR MEDIA] Car found: car_id={db_car.id}, owner_host_id={db_car.host_id}, "
                f"current_cover={db_car.cover_image}, current_car_images={db_car.car_images}, "
                f"current_video={db_car.car_video}")
    
    if db_car.host_id != current_host.id:
        logger.warning(f"🖼️ [UPDATE CAR MEDIA] Permission denied: car owner={db_car.host_id}, "
                      f"requesting host={current_host.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to update this car"
        )
    
    # Track what will be updated
    updates = {}
    
    # Store files as JSON string in car_images
    old_car_images = db_car.car_images
    db_car.car_images = json.dumps(request.files)
    updates['car_images'] = {'old': old_car_images, 'new': db_car.car_images, 'count': len(request.files)}
    logger.info(f"🖼️ [UPDATE CAR MEDIA] Updating car_images: {len(request.files)} images")
    logger.info(f"🖼️ [UPDATE CAR MEDIA] Image URLs: {request.files}")
    logger.info(f"🖼️ [UPDATE CAR MEDIA] Stored as JSON string: {db_car.car_images}")
    
    # Update cover_image if provided, otherwise use first image from files
    if request.cover_image:
        old_cover = db_car.cover_image
        db_car.cover_image = request.cover_image
        updates['cover_image'] = {'old': old_cover, 'new': request.cover_image, 'source': 'provided'}
        logger.info(f"🖼️ [UPDATE CAR MEDIA] Updating cover_image (provided): {old_cover} -> {request.cover_image}")
    elif len(request.files) > 0:
        old_cover = db_car.cover_image
        db_car.cover_image = request.files[0]
        updates['cover_image'] = {'old': old_cover, 'new': request.files[0], 'source': 'auto_from_first_file'}
        logger.info(f"🖼️ [UPDATE CAR MEDIA] Auto-setting cover_image to first file: {request.files[0]}")
    
    # Update car_video if provided
    if request.car_video is not None:
        old_video = db_car.car_video
        db_car.car_video = request.car_video
        updates['car_video'] = {'old': old_video, 'new': request.car_video}
        logger.info(f"🖼️ [UPDATE CAR MEDIA] Updating car_video: {old_video} -> {request.car_video}")
    
    logger.info(f"🖼️ [UPDATE CAR MEDIA] Prepared updates: {updates}")
    
    try:
        await db.commit()
        await db.refresh(db_car)
        logger.info(f"🖼️ [UPDATE CAR MEDIA] ✅ Successfully updated car media for car_id={car_id}. "
                   f"Updates: {updates}")
        logger.info(f"🖼️ [UPDATE CAR MEDIA] Final state: cover_image={db_car.cover_image}, "
                   f"car_images={db_car.car_images}, car_video={db_car.car_video}")
    except Exception as e:
        logger.error(f"🖼️ [UPDATE CAR MEDIA] ❌ Database commit failed: {str(e)}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update car media: {str(e)}"
        )
    
    return _car_to_response(db_car)


@router.post("/host/cars/{car_id}/media/urls", response_model=CarResponse)
async def save_car_media_urls(
    car_id: int,
    request: CarMediaUrlsRequest,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db)
):
    """
    Save car media URLs after app uploads directly to Supabase
    
    This endpoint accepts the 'files' field (for app compatibility).
    The app uploads images/video directly to Supabase, then sends the URLs here.
    
    - **files**: List of image URLs (optional, will be stored in car_images)
    - **cover_image**: Cover image URL (optional, defaults to first image in files if not provided)
    - **car_video**: Car video URL (optional)
    
    At least one of: files, cover_image, or car_video must be provided.
    """
    logger.info(f"🖼️ [SAVE IMAGE URLS API] Request received for car_id={car_id}, host_id={current_host.id}")
    logger.info(f"🖼️ [SAVE IMAGE URLS API] Request body: files={request.files}, "
                f"cover_image={request.cover_image}, car_video={request.car_video}")
    logger.info(f"🖼️ [SAVE IMAGE URLS API] Request body types: files_type={type(request.files)}, "
                f"files_is_none={request.files is None}, files_length={len(request.files) if request.files else 'N/A'}")
    
    # Get car and verify ownership
    result = await db.execute(select(Car).filter(Car.id == car_id))
    db_car = result.scalar_one_or_none()
    if not db_car:
        logger.error(f"🖼️ [SAVE IMAGE URLS API] Car not found: car_id={car_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found"
        )
    
    logger.info(f"🖼️ [SAVE IMAGE URLS API] Car found: car_id={db_car.id}, owner_host_id={db_car.host_id}, "
                f"current_cover={db_car.cover_image}, current_car_images={db_car.car_images}, "
                f"current_video={db_car.car_video}")
    
    if db_car.host_id != current_host.id:
        logger.warning(f"🖼️ [SAVE IMAGE URLS API] Permission denied: car owner={db_car.host_id}, "
                      f"requesting host={current_host.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to update this car"
        )
    
    # Validate that at least one field is provided
    has_files = request.files is not None and len(request.files) > 0
    has_cover = request.cover_image is not None and request.cover_image.strip() != ""
    has_video = request.car_video is not None and request.car_video.strip() != ""
    
    logger.info(f"🖼️ [SAVE IMAGE URLS API] Field validation: has_files={has_files}, "
                f"has_cover={has_cover}, has_video={has_video}")
    
    if not has_files and not has_cover and not has_video:
        logger.error(f"🖼️ [SAVE IMAGE URLS API] Validation failed: All fields are empty/null. "
                    f"files={request.files}, cover_image={request.cover_image}, car_video={request.car_video}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one of: files, cover_image, or car_video must be provided"
        )
    
    # Track what will be updated
    updates = {}
    
    # Store images as JSON string
    if request.files is not None:
        old_car_images = db_car.car_images
        if request.files:
            db_car.car_images = json.dumps(request.files)
            updates['car_images'] = {'old': old_car_images, 'new': db_car.car_images, 'count': len(request.files)}
            logger.info(f"🖼️ [SAVE IMAGE URLS API] Updating car_images: {len(request.files)} images")
            logger.info(f"🖼️ [SAVE IMAGE URLS API] Image URLs: {request.files}")
            logger.info(f"🖼️ [SAVE IMAGE URLS API] Stored as JSON: {db_car.car_images}")
        else:
            logger.warning(f"🖼️ [SAVE IMAGE URLS API] files array is empty, setting car_images to None")
            db_car.car_images = None
            updates['car_images'] = {'old': old_car_images, 'new': None, 'count': 0}
    
    # Set cover_image (use provided one, or default to first image)
    if request.cover_image:
        old_cover = db_car.cover_image
        db_car.cover_image = request.cover_image
        updates['cover_image'] = {'old': old_cover, 'new': request.cover_image, 'source': 'provided'}
        logger.info(f"🖼️ [SAVE IMAGE URLS API] Updating cover_image (provided): {old_cover} -> {request.cover_image}")
    elif request.files and len(request.files) > 0:
        old_cover = db_car.cover_image
        db_car.cover_image = request.files[0]
        updates['cover_image'] = {'old': old_cover, 'new': request.files[0], 'source': 'auto_from_first_file'}
        logger.info(f"🖼️ [SAVE IMAGE URLS API] Auto-setting cover_image to first file: {request.files[0]}")
    
    if request.car_video is not None:
        old_video = db_car.car_video
        db_car.car_video = request.car_video
        updates['car_video'] = {'old': old_video, 'new': request.car_video}
        logger.info(f"🖼️ [SAVE IMAGE URLS API] Updating car_video: {old_video} -> {request.car_video}")
    
    logger.info(f"🖼️ [SAVE IMAGE URLS API] Prepared updates: {updates}")
    
    try:
        await db.commit()
        await db.refresh(db_car)
        logger.info(f"🖼️ [SAVE IMAGE URLS API] ✅ Successfully saved car media URLs for car_id={car_id}")
        logger.info(f"🖼️ [SAVE IMAGE URLS API] Final state: cover_image={db_car.cover_image}, "
                   f"car_images={db_car.car_images}, car_video={db_car.car_video}")
        logger.info(f"🖼️ [SAVE IMAGE URLS API] Response data: {updates}")
    except Exception as e:
        logger.error(f"🖼️ [SAVE IMAGE URLS API] ❌ Database commit failed: {str(e)}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save car media URLs: {str(e)}"
        )
    
    return _car_to_response(db_car)


@router.get("/cars/{car_id}", response_model=CarListingResponse)
async def get_car_details(
    car_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed information about a specific car for car details page.
    
    Returns all car information including:
    - Car images (car_images array for carousel)
    - Cover image
    - Video
    - Name, model, location
    - All technical specs (seats, fuel_type, transmission, color, mileage, year, body_type)
    - Features list
    - Pricing (daily_rate, weekly_rate, monthly_rate)
    - Rental rules (min_rental_days, max_rental_days, min_age_requirement, rules)
    - Description
    - Host information (name, avatar)
    
    Only returns verified and visible cars (verification_status = 'verified', is_hidden = False).
    """
    logger.info(f"🚗 [CAR DETAILS] Request received for car_id={car_id}")
    
    result = await db.execute(
        select(Car).options(joinedload(Car.host)).filter(
            Car.id == car_id,
            Car.verification_status == VerificationStatus.VERIFIED.value,
            Car.is_hidden == False
        )
    )
    car = result.scalar_one_or_none()
    
    if not car:
        logger.warning(f"🚗 [CAR DETAILS] Car not found or not available: car_id={car_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found or not available"
        )
    
    car_images_count = len(parse_image_urls(car.car_images)) if car.car_images else 0
    logger.info(f"🚗 [CAR DETAILS] ✅ Returning car details for car_id={car_id}, "
               f"name={car.name}, model={car.model}, images_count={car_images_count}")
    
    return car_to_listing_response(car)



@router.get("/client/cars/{car_id}", response_model=CarListingResponse)
async def get_car_details_client(
    car_id: int,
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific car for car details page (client endpoint).
    
    Alias for GET /cars/{car_id} - provides consistent API path structure for clients.
    
    Returns all car information including:
    - Car images (car_images array for carousel)
    - Cover image
    - Video
    - Name, model, location
    - All technical specs (seats, fuel_type, transmission, color, mileage, year, body_type)
    - Features list
    - Pricing (daily_rate, weekly_rate, monthly_rate)
    - Rental rules (min_rental_days, max_rental_days, min_age_requirement, rules)
    - Description
    - Host information (name, avatar)
    
    Only returns verified and visible cars (verification_status = 'verified', is_hidden = False).
    """
    # Delegate to the main endpoint
    return await get_car_details(car_id, db)


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
    # Verify car exists and is verified
    car = db.query(Car).filter(
        Car.id == car_id,
        Car.verification_status == VerificationStatus.VERIFIED.value,
        Car.is_hidden == False
    ).first()
    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car listing not found or not available"
        )
    
    # Get current date (date only, no time)
    today = date.today()
    today_datetime = datetime.combine(today, datetime.min.time())
    
    # Get all active bookings for this car that haven't ended yet
    bookings_query = db.query(Booking).filter(
        Booking.car_id == car_id,
        Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.ACTIVE]),
        Booking.end_date >= today_datetime
    )
    
    if start_date and end_date:
        bookings_query = bookings_query.filter(
            and_(
                Booking.start_date < end_date,
                Booking.end_date > start_date
            )
        )
    
    bookings = bookings_query.order_by(Booking.start_date).all()
    
    # Get host-blocked dates for this car (only future/current ones)
    blocked_query = db.query(CarBlockedDate).filter(
        CarBlockedDate.car_id == car_id,
        CarBlockedDate.end_date >= today_datetime
    )
    
    if start_date and end_date:
        blocked_query = blocked_query.filter(
            and_(
                CarBlockedDate.start_date < end_date,
                CarBlockedDate.end_date > start_date
            )
        )
    
    blocked_entries = blocked_query.order_by(CarBlockedDate.start_date).all()
    
    # Build booked dates list
    booked_dates = [
        {
            "start_date": booking.start_date.isoformat(),
            "end_date": booking.end_date.isoformat(),
            "status": booking.status.value
        }
        for booking in bookings
    ]
    
    # Build blocked dates list (host-blocked periods visible to clients)
    blocked_dates = [
        {
            "start_date": (bd.start_date.isoformat() if bd.start_date
                           else datetime.combine(bd.blocked_date, datetime.min.time()).isoformat()),
            "end_date": (bd.end_date.isoformat() if bd.end_date
                         else datetime.combine(bd.blocked_date, datetime.min.time()).isoformat()),
            "reason": bd.reason or "Unavailable"
        }
        for bd in blocked_entries
    ]
    
    # Combined list for easy calendar rendering on the client
    unavailable_dates = [
        {"start_date": d["start_date"], "end_date": d["end_date"], "type": "booked"}
        for d in booked_dates
    ] + [
        {"start_date": d["start_date"], "end_date": d["end_date"], "type": "blocked"}
        for d in blocked_dates
    ]
    
    # Check if today is booked or blocked
    today_is_booked = any(
        booking.start_date.date() <= today <= booking.end_date.date()
        for booking in bookings
    )
    today_is_blocked = any(
        (bd.start_date.date() if bd.start_date else bd.blocked_date) <= today <=
        (bd.end_date.date() if bd.end_date else bd.blocked_date)
        for bd in blocked_entries
    )
    today_unavailable = today_is_booked or today_is_blocked
    
    # Calculate next available date considering both bookings and blocked dates
    all_end_dates = (
        [booking.end_date.date() for booking in bookings]
        + [(bd.end_date.date() if bd.end_date else bd.blocked_date) for bd in blocked_entries]
    )
    
    next_available_date = None
    if not all_end_dates:
        next_available_date = today.isoformat()
    else:
        latest_end_date = max(all_end_dates)
        if today_unavailable:
            next_available_date = (latest_end_date + timedelta(days=1)).isoformat()
        else:
            next_available_date = today.isoformat()
    
    # Check if specific range is available (against both bookings AND blocked dates)
    available = True
    message = "Car is available"
    
    if start_date and end_date:
        booking_overlap = any(
            booking.start_date < end_date and booking.end_date > start_date
            for booking in bookings
        )
        blocked_overlap = any(
            (bd.start_date or datetime.combine(bd.blocked_date, datetime.min.time())) < end_date
            and (bd.end_date or datetime.combine(bd.blocked_date, datetime.min.time())) > start_date
            for bd in blocked_entries
        )
        if booking_overlap or blocked_overlap:
            available = False
            message = "Car is not available for the selected dates"
        else:
            message = "Car is available for the selected dates"
    else:
        if today_unavailable:
            available = False
            reasons = []
            if today_is_booked:
                reasons.append(f"{len(booked_dates)} active booking(s)")
            if today_is_blocked:
                reasons.append("host has blocked today")
            message = f"Car is currently unavailable. {', '.join(reasons)}"
        elif len(booked_dates) > 0 or len(blocked_dates) > 0:
            available = True
            message = (f"Car is available today. {len(booked_dates)} upcoming booking(s), "
                       f"{len(blocked_dates)} blocked period(s)")
        else:
            available = True
            message = "Car is available"
    
    return CarAvailabilityResponse(
        car_id=car_id,
        available=available,
        booked_dates=booked_dates,
        blocked_dates=blocked_dates,
        unavailable_dates=unavailable_dates,
        next_available_date=next_available_date,
        message=message
    )


@router.get("/cars/{car_id}/status", response_model=CarStatusResponse)
async def get_car_status(
    car_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Get car verification status
    
    Returns the verification status of a car (awaiting, verified, or denied).
    This endpoint is used by the UI to monitor the verification status.
    
    - **car_id**: The unique identifier of the car
    """
    result = await db.execute(select(Car).filter(Car.id == car_id))
    db_car = result.scalar_one_or_none()
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
    db: AsyncSession = Depends(get_db)
):
    """
    List all cars belonging to the authenticated host
    
    Returns all cars owned by the currently authenticated host, regardless of verification status.
    """
    result = await db.execute(
        select(Car).filter(Car.host_id == current_host.id).order_by(Car.created_at.desc())
    )
    cars = result.scalars().all()
    return [_car_to_response(car) for car in cars]



@router.put("/host/cars/{car_id}/toggle-visibility", response_model=CarResponse)
async def toggle_car_visibility(
    car_id: int,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db)
):
    """
    Toggle car visibility (show/hide) for verified cars
    
    This endpoint allows hosts to make their verified cars available or hidden from public listings.
    Only verified cars can have their visibility toggled.
    
    - **car_id**: ID of the car to toggle visibility
    """
    # Get car and verify ownership
    result = await db.execute(select(Car).filter(Car.id == car_id))
    db_car = result.scalar_one_or_none()
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
    
    await db.commit()
    await db.refresh(db_car)
    
    return _car_to_response(db_car)


@router.get("/host/cars/{car_id}/drive-settings", response_model=DriveSettingsResponse)
async def get_car_drive_settings(
    car_id: int,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the drive setting for a car.

    - **drive_setting**: self_only | self_and_chauffeur | chauffeur_only
    - **allowed_drive_types**: Drive types the client can choose when booking
    """
    result = await db.execute(
        select(Car).filter(
            Car.id == car_id,
            Car.host_id == current_host.id,
        )
    )
    car = result.scalar_one_or_none()

    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found or you don't have permission to access it",
        )

    drive_setting = getattr(car, "drive_setting", None) or "self_only"
    return DriveSettingsResponse(
        drive_setting=drive_setting,
        allowed_drive_types=_get_allowed_drive_types(drive_setting),
    )


@router.put("/host/cars/{car_id}/drive-settings", response_model=DriveSettingsResponse)
async def update_car_drive_settings(
    car_id: int,
    request: DriveSettingsRequest,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Update the drive setting for a car.

    - **self_only**: Client can only choose self drive
    - **self_and_chauffeur**: Client can choose self drive or with chauffeur
    - **chauffeur_only**: Client can only choose with chauffeur
    """
    result = await db.execute(
        select(Car).filter(
            Car.id == car_id,
            Car.host_id == current_host.id,
        )
    )
    car = result.scalar_one_or_none()

    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found or you don't have permission to modify it",
        )

    car.drive_setting = request.drive_setting.value
    await db.commit()
    await db.refresh(car)

    return DriveSettingsResponse(
        drive_setting=car.drive_setting,
        allowed_drive_types=_get_allowed_drive_types(car.drive_setting),
    )


@router.delete("/host/cars/{car_id}", status_code=status.HTTP_200_OK)
async def delete_my_car(
    car_id: int,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a car listing. Only the car owner (host) can delete it.

    - Cannot delete if the car has any pending, confirmed, or active bookings.
    - Returns 400 in that case; cancel or complete those bookings first.
    """
    result = await db.execute(
        select(Car).filter(
            Car.id == car_id,
            Car.host_id == current_host.id
        )
    )
    car = result.scalar_one_or_none()

    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found or you don't have permission to delete it",
        )

    # Block delete if there are non-finished bookings
    booking_result = await db.execute(
        select(Booking)
        .filter(
            Booking.car_id == car_id,
            Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.ACTIVE]),
        )
    )
    active_booking = booking_result.scalar_one_or_none()
    if active_booking:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Cannot delete car with pending, confirmed, or active bookings. "
                "Cancel or complete them first."
            ),
        )

    await db.delete(car)
    await db.commit()
    return {"message": "Car deleted successfully"}


# ==================== BLOCKED DATES MANAGEMENT ====================

# Helper function to add blocked date (shared by both endpoints)
async def _add_blocked_date_internal(
    car_id: int,
    blocked_date: date,
    reason: Optional[str],
    current_host: Host,
    db: AsyncSession
):
    """Internal helper to add a blocked date"""
    # Verify car exists and belongs to host
    result = await db.execute(
        select(Car).filter(
            Car.id == car_id,
            Car.host_id == current_host.id
        )
    )
    car = result.scalar_one_or_none()
    
    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found or you don't have permission to access it"
        )
    
    # Check if date is already blocked (check both blocked_date and start_date)
    existing_result = await db.execute(
        select(CarBlockedDate).filter(
            CarBlockedDate.car_id == car_id,
            or_(
                CarBlockedDate.blocked_date == blocked_date,
                and_(
                    func.date(CarBlockedDate.start_date) <= blocked_date,
                    func.date(CarBlockedDate.end_date) >= blocked_date
                )
            )
        )
    )
    existing = existing_result.scalar_one_or_none()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Date {blocked_date.isoformat()} is already blocked"
        )
    
    # Check if date is in the past
    if blocked_date < date.today():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot block dates in the past"
        )
    
    # Create blocked date
    # Convert date to datetime for start_date and end_date (table requires them)
    blocked_datetime = datetime.combine(blocked_date, datetime.min.time())
    blocked_date_obj = CarBlockedDate(
        car_id=car_id,
        start_date=blocked_datetime,
        end_date=blocked_datetime,
        blocked_date=blocked_date,  # Also store as date for compatibility
        reason=reason.strip() if reason else None
    )
    
    db.add(blocked_date_obj)
    await db.commit()
    await db.refresh(blocked_date_obj)
    
    return {
        "message": f"Date {blocked_date.isoformat()} blocked successfully",
        "blocked_date": {
            "id": blocked_date_obj.id,
            "blocked_date": blocked_date_obj.blocked_date.isoformat(),
            "reason": blocked_date_obj.reason,
            "created_at": blocked_date_obj.created_at.isoformat() if blocked_date_obj.created_at else None
        }
    }


@router.get("/host/cars/{car_id}/blocked-dates")
async def get_car_blocked_dates(
    car_id: int,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all blocked dates for a car.
    
    - Only the car owner (host) can view blocked dates
    - Returns list of blocked dates with reasons
    """
    # Verify car exists and belongs to host
    result = await db.execute(
        select(Car).filter(
            Car.id == car_id,
            Car.host_id == current_host.id
        )
    )
    car = result.scalar_one_or_none()
    
    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found or you don't have permission to access it"
        )
    
    # Get all blocked dates for this car
    result = await db.execute(
        select(CarBlockedDate).filter(
            CarBlockedDate.car_id == car_id
        ).order_by(CarBlockedDate.start_date)
    )
    blocked_dates = result.scalars().all()
    
    return {
        "car_id": car_id,
        "blocked_dates": [
            {
                "id": bd.id,
                "blocked_date": bd.blocked_date.isoformat() if bd.blocked_date else bd.start_date.date().isoformat(),
                "start_date": bd.start_date.isoformat() if bd.start_date else None,
                "end_date": bd.end_date.isoformat() if bd.end_date else None,
                "reason": bd.reason,
                "created_at": bd.created_at.isoformat() if bd.created_at else None
            }
            for bd in blocked_dates
        ],
        "total": len(blocked_dates)
    }


@router.post("/host/cars/{car_id}/blocked-dates")
async def add_car_blocked_date(
    car_id: int,
    request: CarBlockedDateRequest,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db)
):
    """
    Add a blocked date for a car.
    
    - Only the car owner (host) can add blocked dates
    - Prevents bookings on this date
    - Can specify optional reason (e.g., "Maintenance", "Unavailable")
    """
    return await _add_blocked_date_internal(car_id, request.blocked_date, request.reason, current_host, db)


# Alias endpoint for client compatibility (block-dates vs blocked-dates)
@router.post("/host/cars/{car_id}/block-dates")
async def add_car_blocked_date_alias(
    car_id: int,
    request: CarBlockedDateRequest,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db)
):
    """Alias for /blocked-dates endpoint for client compatibility"""
    return await _add_blocked_date_internal(car_id, request.blocked_date, request.reason, current_host, db)


@router.delete("/host/cars/{car_id}/blocked-dates/{blocked_date_id}")
async def remove_car_blocked_date(
    car_id: int,
    blocked_date_id: int,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db)
):
    """
    Remove a blocked date for a car.
    
    - Only the car owner (host) can remove blocked dates
    """
    # Verify car exists and belongs to host
    result = await db.execute(
        select(Car).filter(
            Car.id == car_id,
            Car.host_id == current_host.id
        )
    )
    car = result.scalar_one_or_none()
    
    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found or you don't have permission to access it"
        )
    
    # Find the blocked date
    result = await db.execute(
        select(CarBlockedDate).filter(
            CarBlockedDate.id == blocked_date_id,
            CarBlockedDate.car_id == car_id
        )
    )
    blocked_date_obj = result.scalar_one_or_none()
    
    if not blocked_date_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blocked date not found"
        )
    
    await db.delete(blocked_date_obj)
    await db.commit()
    
    return {
        "message": f"Blocked date {blocked_date_obj.blocked_date.isoformat()} removed successfully"
    }

