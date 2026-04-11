"""
Booking endpoints for clients (and hosts)
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, or_, func, select, update, delete
from typing import Optional, List
from datetime import datetime, timezone
import asyncio
import logging
import json
import uuid
from fastapi_cache.decorator import cache

from app.database import get_db
from app.models import (
    Car,
    Client,
    Booking,
    BookingStatus,
    Host,
    VerificationStatus,
    CarBlockedDate,
    BookingExtensionRequest,
    BookingIssue,
    Payment,
    PaymentStatus,
    Refund,
    RefundStatus,
    StellarPaymentTransaction,
    HostRating,
    ClientRating,
    CarRating,
    EmergencyReport,
)
from app.auth import get_current_client, get_current_host
from app.schemas import (
    BookingCreateRequest,
    BookingUpdateRequest,
    BookingResponse,
    BookingListResponse,
    BookingCancelRequest,
    BookingStatusEnum,
    BookingExtensionCreateRequest,
    BookingExtensionRequestResponse,
    BookingExtensionListResponse,
    BookingExtensionStatusEnum,
    DRIVE_SETTING_TO_ALLOWED,
    ReportIssueRequest,
    BookingIssueResponse,
    BookingIssueListResponse,
)
from app.services.receipt import build_receipt_pdf
from app.cache_utils import host_scoped_cache_key, invalidate_host_cache_namespaces
from app.services.push_notifications import (
    notify_booking_cancelled,
    notify_trip_started,
    notify_trip_completed,
    notify_host_new_booking,
    notify_host_booking_cancelled,
    notify_host_extension_requested,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Damage waiver price per day (KES)
DAMAGE_WAIVER_PRICE_PER_DAY = 250


_host_bookings_cache_key = host_scoped_cache_key


def _to_utc(dt: datetime) -> datetime:
    """Normalize datetime to timezone-aware UTC to avoid naive/aware comparison issues."""
    if dt is None:
        return dt  # type: ignore
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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


def _compute_refund_preview_for_cancellation(booking: Booking):
    """
    Compute refund preview (base trip only, excludes extension payments) for a booking
    that is currently in a cancellable state (pending or confirmed).
    Returns (refund_eligible, refund_amount, refund_percentage, refund_policy_code, refund_policy_reason).
    """
    refund_eligible = None
    refund_amount = None
    refund_percentage = None
    refund_policy_code = None
    refund_policy_reason = None

    try:
        # Only attempt refund preview for bookings that are not already cancelled or completed
        if booking.status in [BookingStatus.PENDING, BookingStatus.CONFIRMED]:
            completed_base_payments = [
                p
                for p in getattr(booking, "payments", []) or []
                if p.status == PaymentStatus.COMPLETED and p.extension_request_id is None
            ]
            total_paid = float(sum(p.amount for p in completed_base_payments))

            if total_paid <= 0:
                refund_eligible = False
                refund_amount = 0.0
                refund_percentage = 0.0
                refund_policy_code = "NO_PAYMENT"
                refund_policy_reason = "No completed payment found for this booking – nothing to refund."
            else:
                now = datetime.now(timezone.utc)
                start = booking.start_date
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                hours_to_pickup = (start - now).total_seconds() / 3600.0

                if hours_to_pickup > 24:
                    refund_percentage = 1.0
                    refund_policy_code = "FULL_BEFORE_24H"
                    refund_policy_reason = "Cancelled more than 24 hours before pickup – full refund of amounts paid."
                elif 0 <= hours_to_pickup <= 24:
                    refund_percentage = 0.5
                    refund_policy_code = "HALF_WITHIN_24H"
                    refund_policy_reason = "Cancelled within 24 hours before pickup – 50% refund of amounts paid."
                else:
                    refund_percentage = 0.0
                    refund_policy_code = "NO_REFUND_AFTER_START"
                    refund_policy_reason = "Pickup time has passed – no automatic refund, contact support for review."

                refund_amount = round(total_paid * refund_percentage, 2)
                refund_eligible = refund_percentage > 0

    except Exception:
        # Refund preview is best‑effort; never break booking serialization because of it.
        refund_eligible = None
        refund_amount = None
        refund_percentage = None
        refund_policy_code = None
        refund_policy_reason = None

    return refund_eligible, refund_amount, refund_percentage, refund_policy_code, refund_policy_reason


def booking_to_response(booking: Booking) -> dict:
    """Convert Booking model to BookingResponse dict"""
    car = booking.car
    host = car.host if car else None
    
    client = getattr(booking, "client", None)

    # ----- Refund preview (base trip only, excludes extension payments) -----
    if booking.status in [BookingStatus.PENDING, BookingStatus.CONFIRMED]:
        (
            refund_eligible,
            refund_amount,
            refund_percentage,
            refund_policy_code,
            refund_policy_reason,
        ) = _compute_refund_preview_for_cancellation(booking)
    elif booking.status == BookingStatus.CANCELLED:
        # For already cancelled bookings in generic responses, point to refunds history.
        refund_eligible = None
        refund_amount = None
        refund_percentage = None
        refund_policy_code = "ALREADY_CANCELLED"
        refund_policy_reason = "Booking is already cancelled – see finance/refunds history for actual refund details."
    else:
        refund_eligible = None
        refund_amount = None
        refund_percentage = None
        refund_policy_code = None
        refund_policy_reason = None

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
        "refund_eligible": refund_eligible,
        "refund_amount": refund_amount,
        "refund_percentage": refund_percentage,
        "refund_policy_code": refund_policy_code,
        "refund_policy_reason": refund_policy_reason,
        
        # Timestamps
        "created_at": booking.created_at,
        "updated_at": booking.updated_at,
    }


async def check_booking_overlap(db: AsyncSession, car_id: int, start_date: datetime, end_date: datetime, exclude_booking_id: Optional[int] = None) -> bool:
    """
    Check if there's an overlapping booking for the given car and date range.
    Returns True if there's an overlap (NOT available), False if available.
    """
    stmt = select(Booking).filter(
        Booking.car_id == car_id,
        Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.ACTIVE]),
        # Overlap condition: booking.start < requested.end AND booking.end > requested.start
        Booking.start_date < end_date,
        Booking.end_date > start_date
    )
    
    if exclude_booking_id:
        stmt = stmt.filter(Booking.id != exclude_booking_id)
    
    result = await db.execute(stmt)
    return result.first() is not None


async def check_blocked_date_overlap(db: AsyncSession, car_id: int, start_date: datetime, end_date: datetime) -> bool:
    """
    Check if the requested date range overlaps with any host-blocked dates.
    Returns True if there's an overlap (dates are blocked), False if clear.
    Checks both the start_date/end_date range columns and the legacy blocked_date column.
    """
    start_as_date = start_date.date() if isinstance(start_date, datetime) else start_date
    end_as_date = end_date.date() if isinstance(end_date, datetime) else end_date

    stmt = select(CarBlockedDate).filter(
        CarBlockedDate.car_id == car_id,
        or_(
            and_(
                CarBlockedDate.start_date < end_date,
                CarBlockedDate.end_date > start_date
            ),
            and_(
                CarBlockedDate.blocked_date.isnot(None),
                CarBlockedDate.blocked_date >= start_as_date,
                CarBlockedDate.blocked_date < end_as_date
            )
        )
    )
    result = await db.execute(stmt)
    return result.first() is not None


@router.post("/client/bookings", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    request: BookingCreateRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db)
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
    result = await db.execute(
        select(Car).options(joinedload(Car.host)).filter(
            Car.id == request.car_id,
            Car.verification_status == VerificationStatus.VERIFIED.value
        )
    )
    car = result.scalar_one_or_none()
    
    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car listing not found or not verified"
        )
    
    # ==================== PROFILE COMPLETION CHECKS ====================
    # Verify client has updated their profile
    if not (current_client.mobile_number and current_client.id_number and 
            current_client.date_of_birth and current_client.gender):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please complete your profile before making a booking. Required fields: mobile number, ID number, date of birth, and gender."
        )
    
    # Verify client has added driving license
    if not current_client.driving_license:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please add your driving license information before making a booking."
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
    
    # Validate drive_type is allowed by the car's drive setting
    drive_setting = getattr(car, "drive_setting", None) or "self_only"
    allowed_drive_types = DRIVE_SETTING_TO_ALLOWED.get(drive_setting, ["self"])
    requested_drive = (request.drive_type or "self").strip()
    allowed_lower = [a.lower() for a in allowed_drive_types]
    if requested_drive.lower() not in allowed_lower:
        allowed_str = ", ".join(allowed_drive_types)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This car only allows: {allowed_str}. You selected '{requested_drive}'."
        )
    
    # Check for overlapping bookings (prevents double booking)
    if await check_booking_overlap(db, car.id, request.start_date, request.end_date):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Car is not available for the selected dates. Please choose different dates."
        )
    
    # Check for host-blocked dates
    if await check_blocked_date_overlap(db, car.id, request.start_date, request.end_date):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The host has blocked some of the selected dates. Please choose different dates."
        )
    
    # Calculate pricing
    base_price = car.daily_rate * rental_days
    damage_waiver_fee = DAMAGE_WAIVER_PRICE_PER_DAY * rental_days if request.damage_waiver_enabled else 0
    total_price = base_price + damage_waiver_fee
    
    # Generate unique booking ID
    booking_id = generate_booking_id()
    
    # Ensure booking ID is unique
    while True:
        id_result = await db.execute(select(Booking).filter(Booking.booking_id == booking_id))
        if id_result.first() is None:
            break
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
    await db.commit()
    await db.refresh(booking)
    await invalidate_host_cache_namespaces(
        car.host_id,
        ["host-bookings-list"],
    )

    # Notify host of new booking (fire-and-forget)
    _client_name = current_client.full_name or "A client"
    _car_label = f"{car.name} {car.model or ''}".strip()
    _start = request.start_date.strftime("%d %b %Y")
    asyncio.ensure_future(notify_host_new_booking(
        car.host_id, booking_id, _client_name, _car_label, _start
    ))

    # Load relationships for response
    result = await db.execute(
        select(Booking).options(
            joinedload(Booking.car).joinedload(Car.host)
        ).filter(Booking.id == booking.id)
    )
    booking = result.scalar_one_or_none()

    return booking_to_response(booking)


@router.get("/client/bookings", response_model=BookingListResponse)
async def get_my_bookings(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    status: Optional[str] = Query(None, description="Filter by booking status"),
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all bookings for the current authenticated client.
    
    - Returns bookings sorted by creation date (newest first)
    - Supports filtering by status
    - Results are paginated
    
    Requires client authentication.
    """
    
    stmt = select(Booking).options(
        joinedload(Booking.car).joinedload(Car.host)
    ).filter(Booking.client_id == current_client.id)
    
    # Filter by status if provided
    if status:
        try:
            status_enum = BookingStatus(status.lower())
            stmt = stmt.filter(Booking.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Valid values: {[s.value for s in BookingStatus]}"
            )
    
    # Get total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0
    
    # Apply pagination and order by newest first
    stmt = stmt.order_by(Booking.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    bookings = result.scalars().all()
    
    # Convert to response format
    booking_responses = [booking_to_response(b) for b in bookings]
    
    return BookingListResponse(
        bookings=booking_responses,
        total=total,
        skip=skip,
        limit=limit
    )


async def _client_booking_query(db: AsyncSession, booking_id_param: str, client_id: int):
    """Resolve booking by either numeric id or string booking_id (e.g. BK-ABC12345). Returns booking with client filter."""
    stmt = select(Booking).options(
        joinedload(Booking.car).joinedload(Car.host)
    ).filter(Booking.client_id == client_id)
    
    if booking_id_param.isdigit():
        stmt = stmt.filter(Booking.id == int(booking_id_param))
    else:
        stmt = stmt.filter(Booking.booking_id == booking_id_param)
        
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _client_booking_for_receipt(db: AsyncSession, booking_id_param: str, client_id: int):
    """Resolve booking for client with car, host, payments loaded (for receipt)."""
    stmt = (
        select(Booking)
        .options(
            joinedload(Booking.car).joinedload(Car.host),
            joinedload(Booking.client),
            joinedload(Booking.payments),
        )
        .filter(Booking.client_id == client_id)
    )
    
    if booking_id_param.isdigit():
        stmt = stmt.filter(Booking.id == int(booking_id_param))
    else:
        stmt = stmt.filter(Booking.booking_id == booking_id_param)
        
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _host_booking_for_receipt(db: AsyncSession, booking_id_param: str, host_id: int):
    """Resolve booking by numeric id or booking_id string for host (car must belong to host). Loads car, client, payments."""
    stmt = (
        select(Booking)
        .options(
            joinedload(Booking.car).joinedload(Car.host),
            joinedload(Booking.client),
            joinedload(Booking.payments),
        )
        .join(Car)
        .filter(Car.host_id == host_id)
    )
    
    if booking_id_param.isdigit():
        stmt = stmt.filter(Booking.id == int(booking_id_param))
    else:
        stmt = stmt.filter(Booking.booking_id == booking_id_param)
        
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


@router.get("/client/bookings/{booking_id}", response_model=BookingResponse)
async def get_booking_details(
    booking_id: str,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed information about a specific booking.

    - **booking_id**: The unique booking identifier (e.g. BK-12345678) **or** the numeric database id (e.g. 5)
    - Only returns bookings owned by the authenticated client

    Requires client authentication.
    """
    booking = await _client_booking_query(db, booking_id, current_client.id)
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )
    return booking_to_response(booking)


@router.put("/client/bookings/{booking_id}", response_model=BookingResponse)
async def update_booking(
    booking_id: str,
    request: BookingUpdateRequest,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """
    Update a PENDING booking (e.g. change dates or details before paying).

    - Only **pending** bookings can be updated. After payment, cancel and rebook to change dates.
    - **booking_id**: The unique booking identifier (e.g. BK-12345678) or numeric id.
    - Send only the fields you want to change; omitted fields keep their current values.
    - If you change dates, availability is re-checked (other bookings and host-blocked dates).
    - Pricing is recalculated from the car's current daily rate when dates or damage waiver change.

    Requires client authentication.
    """
    booking = _client_booking_query(db, booking_id, current_client.id)
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )
    if booking.status != BookingStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only pending bookings can be updated. Current status: {booking.status.value}. Cancel and create a new booking to change after payment."
        )

    car = booking.car
    if not car:
        car = db.query(Car).options(joinedload(Car.host)).filter(Car.id == booking.car_id).first()
    if not car:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Car not found")

    # Resolve new dates: use request if provided, else keep existing
    new_start = request.start_date if request.start_date is not None else booking.start_date
    new_end = request.end_date if request.end_date is not None else booking.end_date
    new_start = _to_utc(new_start)
    new_end = _to_utc(new_end)
    if new_start >= new_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="End date must be after start date"
        )

    # If dates changed, run full availability and pricing validation
    dates_changed = new_start != _to_utc(booking.start_date) or new_end != _to_utc(booking.end_date)
    new_damage_waiver = request.damage_waiver_enabled if request.damage_waiver_enabled is not None else booking.damage_waiver_enabled

    if dates_changed:
        rental_days = (new_end - new_start).days
        if rental_days < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Rental period must be at least 1 day"
            )
        if car.min_rental_days and rental_days < car.min_rental_days:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Minimum rental period for this car is {car.min_rental_days} days"
            )
        if car.max_rental_days and rental_days > car.max_rental_days:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Maximum rental period for this car is {car.max_rental_days} days"
            )
        if check_booking_overlap(db, car.id, new_start, new_end, exclude_booking_id=booking.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Car is not available for the selected dates. Please choose different dates."
            )
        if check_blocked_date_overlap(db, car.id, new_start, new_end):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The host has blocked some of the selected dates. Please choose different dates."
            )
        booking.start_date = new_start
        booking.end_date = new_end
        booking.rental_days = rental_days
        base_price = car.daily_rate * rental_days
        damage_waiver_fee = DAMAGE_WAIVER_PRICE_PER_DAY * rental_days if new_damage_waiver else 0
        booking.base_price = base_price
        booking.damage_waiver_fee = damage_waiver_fee
        booking.damage_waiver_enabled = new_damage_waiver
        booking.total_price = base_price + damage_waiver_fee
    else:
        if request.damage_waiver_enabled is not None and request.damage_waiver_enabled != booking.damage_waiver_enabled:
            booking.damage_waiver_enabled = request.damage_waiver_enabled
            booking.damage_waiver_fee = DAMAGE_WAIVER_PRICE_PER_DAY * booking.rental_days if booking.damage_waiver_enabled else 0
            booking.total_price = booking.base_price + booking.damage_waiver_fee

    # Drive type: validate if changed
    new_drive = request.drive_type if request.drive_type is not None else booking.drive_type
    if new_drive is not None:
        drive_setting = getattr(car, "drive_setting", None) or "self_only"
        allowed = DRIVE_SETTING_TO_ALLOWED.get(drive_setting, ["self"])
        if new_drive.strip().lower() not in [a.lower() for a in allowed]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"This car only allows: {', '.join(allowed)}. You selected '{new_drive}'."
            )
        booking.drive_type = new_drive.strip()

    # Optional fields: apply if provided
    if request.pickup_time is not None:
        booking.pickup_time = request.pickup_time
    if request.return_time is not None:
        booking.return_time = request.return_time
    if request.pickup_location is not None:
        booking.pickup_location = request.pickup_location
    if request.return_location is not None:
        booking.return_location = request.return_location
    if request.check_in_preference is not None:
        booking.check_in_preference = request.check_in_preference
    if request.special_requirements is not None:
        booking.special_requirements = request.special_requirements

    db.commit()
    db.refresh(booking)
    booking = db.query(Booking).options(
        joinedload(Booking.car).joinedload(Car.host)
    ).filter(Booking.id == booking.id).first()
    return booking_to_response(booking)


@router.get("/client/bookings/{booking_id}/receipt")
async def get_client_booking_receipt(
    booking_id: str,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a PDF receipt for this booking. Only the client who made the booking can download.
    Receipt includes booking details, car, client, host, pricing, payment info (M-Pesa receipt), and host payout (after commission).
    """
    booking = await _client_booking_for_receipt(db, booking_id, current_client.id)
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )
    pdf_bytes = build_receipt_pdf(booking)
    bid = getattr(booking, "booking_id", None) or getattr(booking, "id", "receipt")
    filename = f"receipt-{bid}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/client/bookings/{booking_id}/cancel", response_model=BookingResponse)
async def cancel_booking(
    booking_id: str,
    request: Optional[BookingCancelRequest] = None,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db)
):
    """
    Cancel an existing booking and apply the platform refund policy.
    
    Policy (base trip payments only, extensions are handled separately):
    - If there is **no completed payment** for this booking yet, the booking is simply cancelled (no refund needed).
    - If cancelled **more than 24 hours before pickup**, the client is eligible for a **full refund** of amounts paid.
    - If cancelled **within 24 hours before pickup but before pickup time**, the client is eligible for a **50% refund**.
    - If pickup time has **already passed**, there is **no automatic refund**; support can review edge cases manually.
    
    The response includes `refund_eligible`, `refund_amount`, `refund_percentage`, and `refund_policy_code` so
    the app can show clear messaging to the client and route any manual refund handling to support/finance.
    
    - **booking_id**: The unique booking identifier (e.g. BK-12345678) or numeric id
    - Only pending or confirmed bookings can be cancelled
    - Only the booking owner can cancel
    
    Requires client authentication.
    """
    booking = await _client_booking_query(db, booking_id, current_client.id)
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
    
    # Compute refund preview BEFORE changing status so we know what policy applies right now
    (
        refund_eligible,
        refund_amount,
        refund_percentage,
        refund_policy_code,
        refund_policy_reason,
    ) = _compute_refund_preview_for_cancellation(booking)

    # Capture host_id before commit expires the relationship
    host_id = booking.car.host_id

    # Update booking status
    booking.status = BookingStatus.CANCELLED
    booking.status_updated_at = datetime.now(timezone.utc)
    if request and request.reason:
        booking.cancellation_reason = request.reason

    # Capture car info before commit expires the relationship
    _car_label = f"{booking.car.name} {getattr(booking.car, 'model', '') or ''}".strip() if booking.car else "car"
    _booking_ref = getattr(booking, "booking_id", str(booking.id))
    _cancel_reason = request.reason if request else None

    await db.commit()
    await db.refresh(booking)
    await invalidate_host_cache_namespaces(
        host_id,
        ["host-bookings-list"],
    )

    asyncio.ensure_future(notify_booking_cancelled(
        booking.client_id,
        _booking_ref,
        booking.cancellation_reason,
    ))
    asyncio.ensure_future(notify_host_booking_cancelled(
        host_id, _booking_ref, _car_label, _cancel_reason
    ))

    return booking_to_response(booking)


@router.get("/client/bookings/{booking_id}/cancellation-preview", response_model=BookingResponse)
async def get_booking_cancellation_preview(
    booking_id: str,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """
    Get a live preview of what will happen if the client cancels this booking **right now**.

    The returned `BookingResponse` includes these fields populated:
    - **refund_eligible**: whether an automatic refund applies under the current policy.
    - **refund_amount**: estimated refund amount in KES (base trip only, excludes extensions).
    - **refund_percentage**: fraction between 0.0 and 1.0.
    - **refund_policy_code** and **refund_policy_reason**: explain which rule was applied.

    This endpoint **does not cancel** the booking; it is safe to call from the UI before showing the
    final "Confirm cancellation" dialog.
    """
    booking = _client_booking_query(db, booking_id, current_client.id)
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )
    return booking_to_response(booking)


# ==================== BOOKING EXTENSION REQUESTS ====================


@router.post(
    "/client/bookings/{booking_id}/extensions",
    response_model=BookingExtensionRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_booking_extension_request(
    booking_id: str,
    request: BookingExtensionCreateRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Request to extend an existing booking (same trip, later drop-off only).

    Flow:
    - Client proposes a new `end_date` and optionally a new drop-off location.
    - System checks availability (bookings + host blocked dates) for the **extra period only**.
    - Creates an extension request with status `pending_host_approval`.
    - Host then approves/rejects; on approval, client must pay for the extra days.

    Notes:
    - Only **confirmed** or **active** bookings can be extended (prevents extending unpaid bookings).
    - `new_end_date` must be strictly after the current booking `end_date`.
    """
    booking = await _client_booking_query(db, booking_id, current_client.id)
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    if booking.status not in [BookingStatus.CONFIRMED, BookingStatus.ACTIVE]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only confirmed or active bookings can be extended. "
                   "Complete payment for the current booking first.",
        )

    # Normalize datetimes to UTC to avoid naive/aware comparison errors
    new_end_utc = _to_utc(request.new_end_date)
    current_end_utc = _to_utc(booking.end_date)
    start_utc = _to_utc(booking.start_date)

    # Ensure client only extends the drop-off (new end must be after current end)
    if new_end_utc <= current_end_utc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New drop-off date must be after the current drop-off date.",
        )

    # Prevent multiple active extension requests for the same booking
    existing_stmt = select(BookingExtensionRequest).filter(
        BookingExtensionRequest.booking_id == booking.id,
        BookingExtensionRequest.status.in_(
            [
                BookingExtensionStatusEnum.PENDING_HOST_APPROVAL.value,
                BookingExtensionStatusEnum.HOST_APPROVED.value,
            ]
        ),
    )
    existing_active_result = await db.execute(existing_stmt)
    existing_active = existing_active_result.scalar_one_or_none()
    
    if existing_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="There is already a pending or approved extension request for this booking.",
        )

    # Extra period to validate: from current end to requested new end
    extra_start = current_end_utc
    extra_end = new_end_utc

    # Availability checks (other bookings + host blocked dates)
    if await check_booking_overlap(db, booking.car_id, extra_start, extra_end, exclude_booking_id=booking.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Car is not available for the requested extension period.",
        )

    if await check_blocked_date_overlap(db, booking.car_id, extra_start, extra_end):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The host has blocked some of the requested extension dates.",
        )

    # Calculate extra days and price (using same day-based logic as original booking)
    # Original rental_days = (end_date - start_date).days
    new_total_days = (new_end_utc - start_utc).days
    extra_days = new_total_days - booking.rental_days
    if extra_days < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Extension must add at least one extra day to the booking.",
        )

    extra_base_price = booking.daily_rate * extra_days
    extra_damage_waiver = (
        DAMAGE_WAIVER_PRICE_PER_DAY * extra_days if booking.damage_waiver_enabled else 0
    )
    extra_amount = extra_base_price + extra_damage_waiver

    car = booking.car
    if not car or not car.host:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Booking car or host information is missing.",
        )

    extension = BookingExtensionRequest(
        booking_id=booking.id,
        client_id=current_client.id,
        host_id=car.host.id,
        old_end_date=booking.end_date,
        requested_end_date=request.new_end_date,
        extra_days=extra_days,
        extra_amount=extra_amount,
        dropoff_same_as_previous=request.dropoff_same_as_previous,
        new_dropoff_location=request.new_dropoff_location.strip()
        if (request.new_dropoff_location and not request.dropoff_same_as_previous)
        else None,
        status=BookingExtensionStatusEnum.PENDING_HOST_APPROVAL.value,
    )

    db.add(extension)
    await db.commit()
    await db.refresh(extension)

    # Notify host of extension request (fire-and-forget)
    _car_label = f"{car.name} {getattr(car, 'model', '') or ''}".strip()
    _booking_ref = getattr(booking, "booking_id", str(booking.id))
    asyncio.ensure_future(notify_host_extension_requested(
        car.host.id, _booking_ref, _car_label, extra_days
    ))

    return extension

# ==================== CLIENT COMPLETED BOOKINGS ====================

@router.get("/client/bookings/completed", response_model=BookingListResponse)
async def get_my_completed_bookings(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db)
):
    """
    Convenience endpoint to get only **completed** bookings for the current client.

    - Uses the same shape as `/client/bookings`
    - Results are paginated and sorted by creation date (newest first)
    """
    stmt = select(Booking).options(
        joinedload(Booking.car).joinedload(Car.host)
    ).filter(
        Booking.client_id == current_client.id,
        Booking.status == BookingStatus.COMPLETED,
    )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0
    
    stmt = stmt.order_by(Booking.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    bookings = result.scalars().all()
    booking_responses = [booking_to_response(b) for b in bookings]

    return BookingListResponse(
        bookings=booking_responses,
        total=total,
        skip=skip,
        limit=limit,
    )


# ==================== HOST BOOKINGS ====================

@router.get("/host/bookings", response_model=BookingListResponse)
@cache(expire=60, namespace="host-bookings-list", key_builder=_host_bookings_cache_key)
async def get_host_bookings(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    status: Optional[str] = Query(None, description="Filter by booking status"),
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Get bookings for the current authenticated host.

    - Returns bookings where the car belongs to the host
    - Supports filtering by status
    - Results are paginated and sorted by creation date (newest first)
    """
    stmt = (
        select(Booking)
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
            stmt = stmt.filter(Booking.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Valid values: {[s.value for s in BookingStatus]}",
            )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0
    
    stmt = stmt.order_by(Booking.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    bookings = result.scalars().all()
    booking_responses = [booking_to_response(b) for b in bookings]

    return BookingListResponse(
        bookings=booking_responses,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/host/bookings/completed", response_model=BookingListResponse)
@cache(expire=120, namespace="host-bookings-completed", key_builder=_host_bookings_cache_key)
async def get_host_completed_bookings(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Convenience endpoint to get only **completed** bookings for the current host.

    - Returns bookings where the car belongs to the host
    - Results are paginated and sorted by creation date (newest first)
    """
    stmt = (
        select(Booking)
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

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0
    
    stmt = stmt.order_by(Booking.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    bookings = result.scalars().all()
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
    db: AsyncSession = Depends(get_db),
):
    """
    Get detailed information about a specific booking for a host.

    - Only returns bookings where the car belongs to the authenticated host
    - Not cached — hosts actively manage bookings from this view (pickup / dropoff)
    """
    stmt = (
        select(Booking)
        .options(
            joinedload(Booking.car).joinedload(Car.host),
            joinedload(Booking.client),
        )
        .join(Car)
        .filter(
            Booking.booking_id == booking_id,
            Car.host_id == current_host.id,
        )
    )
    
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    return booking_to_response(booking)


@router.get("/host/bookings/{booking_id}/receipt")
async def get_host_booking_receipt(
    booking_id: str,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a PDF receipt for this booking. Only the host who owns the car can download.
    Receipt includes booking details, car, client, host, pricing, payment info (M-Pesa receipt), and host payout (after commission).
    """
    booking = await _host_booking_for_receipt(db, booking_id, current_host.id)
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )
    pdf_bytes = build_receipt_pdf(booking)
    bid = getattr(booking, "booking_id", None) or getattr(booking, "id", "receipt")
    filename = f"receipt-{bid}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/host/bookings/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_host_booking(
    booking_id: str,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Permanently delete a completed or cancelled booking for the current host.

    - Only deletes bookings where the car belongs to the authenticated host.
    - Only bookings with status `completed` or `cancelled` can be deleted.
    - This is a hard delete – booking and related payments are removed from the database.
    """
    stmt = (
        select(Booking)
        .join(Car)
        .filter(
            Booking.booking_id == booking_id,
            Car.host_id == current_host.id,
        )
    )
    
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    if booking.status not in (BookingStatus.COMPLETED, BookingStatus.CANCELLED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only completed or cancelled bookings can be deleted.",
        )

    bid = booking.id

    # --- 1. Null out nullable FK columns that point at this booking ---
    await db.execute(update(HostRating).where(HostRating.booking_id == bid).values(booking_id=None))
    await db.execute(update(ClientRating).where(ClientRating.booking_id == bid).values(booking_id=None))
    await db.execute(update(CarRating).where(CarRating.booking_id == bid).values(booking_id=None))
    await db.execute(update(EmergencyReport).where(EmergencyReport.booking_id == bid).values(booking_id=None))

    # --- 2. Null Payment.extension_request_id so extension requests can be deleted ---
    await db.execute(update(Payment).where(Payment.booking_id == bid).values(extension_request_id=None))

    # --- 3. Delete child records with NOT NULL FK ---
    await db.execute(delete(BookingIssue).where(BookingIssue.booking_id == bid))
    await db.execute(delete(Refund).where(Refund.booking_id == bid))
    await db.execute(delete(BookingExtensionRequest).where(BookingExtensionRequest.booking_id == bid))
    await db.execute(delete(StellarPaymentTransaction).where(StellarPaymentTransaction.booking_id == bid))
    await db.execute(delete(Payment).where(Payment.booking_id == bid))

    # --- 4. Now the booking has no dependents — safe to delete ---
    await db.delete(booking)
    await db.commit()
    await invalidate_host_cache_namespaces(
        current_host.id,
        ["host-bookings-list", "host-bookings-completed", "host-earnings-summary"],
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/host/bookings/{booking_id}/confirm-pickup", response_model=BookingResponse)
async def confirm_pickup_as_host(
    booking_id: str,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Confirm that the client has picked up the car (host side). Moves booking from **confirmed** to **active**.

    - Only the host who owns the car can confirm pickup
    - Only `confirmed` bookings can be moved to active
    """
    stmt = (
        select(Booking)
        .options(
            joinedload(Booking.car).joinedload(Car.host),
            joinedload(Booking.client),
        )
        .join(Car)
        .filter(
            Booking.booking_id == booking_id,
            Car.host_id == current_host.id,
        )
    )
    
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()

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

    today_utc = datetime.now(timezone.utc).date()
    pickup_date = (
        booking.start_date.astimezone(timezone.utc).date()
        if booking.start_date.tzinfo
        else booking.start_date.date()
    )
    if today_utc < pickup_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pickup can only be confirmed on or after the pickup date.",
        )

    booking.status = BookingStatus.ACTIVE
    booking.status_updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(booking)
    await invalidate_host_cache_namespaces(
        current_host.id,
        ["host-bookings-list", "host-bookings-completed", "host-earnings-summary"],
    )

    car = booking.car if hasattr(booking, "car") and booking.car else None
    car_name = f"{getattr(car, 'name', '')} {getattr(car, 'model', '')}".strip() if car else "your car"
    asyncio.ensure_future(notify_trip_started(
        booking.client_id,
        getattr(booking, "booking_id", str(booking.id)),
        car_name,
    ))

    return booking_to_response(booking)


@router.put("/host/bookings/{booking_id}/confirm-dropoff", response_model=BookingResponse)
async def confirm_dropoff_as_host(
    booking_id: str,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Confirm that the client has returned the car (host side). Marks booking as **completed**.

    - Only the host who owns the car can confirm dropoff
    - Only `confirmed` or `active` bookings can be marked completed
    """
    stmt = (
        select(Booking)
        .options(
            joinedload(Booking.car).joinedload(Car.host),
            joinedload(Booking.client),
        )
        .join(Car)
        .filter(
            Booking.booking_id == booking_id,
            Car.host_id == current_host.id,
        )
    )
    
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    if booking.status not in [BookingStatus.CONFIRMED, BookingStatus.ACTIVE]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Only confirmed or active bookings can have dropoff confirmed. "
                f"Current status is '{booking.status.value}'."
            ),
        )

    booking.status = BookingStatus.COMPLETED
    booking.status_updated_at = datetime.now(timezone.utc)
    booking.cancellation_reason = None

    await db.commit()
    await db.refresh(booking)
    await invalidate_host_cache_namespaces(
        current_host.id,
        ["host-bookings-list", "host-bookings-completed", "host-earnings-summary"],
    )

    _car = booking.car if hasattr(booking, "car") and booking.car else None
    _car_name = f"{getattr(_car, 'name', '')} {getattr(_car, 'model', '')}".strip() if _car else "your car"
    asyncio.ensure_future(notify_trip_completed(
        booking.client_id,
        getattr(booking, "booking_id", str(booking.id)),
        _car_name,
    ))

    return booking_to_response(booking)


def _issue_to_response(issue: BookingIssue) -> dict:
    """Convert BookingIssue to response dict."""
    booking = getattr(issue, "booking", None)
    booking_id_display = booking.booking_id if booking else f"BK-{issue.booking_id}"
    return {
        "id": issue.id,
        "booking_id": issue.booking_id,
        "booking_id_display": booking_id_display,
        "host_id": issue.host_id,
        "issue_type": issue.issue_type,
        "description": issue.description,
        "status": issue.status,
        "created_at": issue.created_at,
        "updated_at": issue.updated_at,
    }


@router.post("/host/bookings/{booking_id}/report-issue", response_model=BookingIssueResponse, status_code=status.HTTP_201_CREATED)
async def report_booking_issue(
    booking_id: str,
    request: ReportIssueRequest,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Report an issue concerning an active (or past) booking.

    - Only the host who owns the car can report issues
    - Booking must be confirmed, active, or completed
    - **issue_type**: damage, late_return, no_show, misconduct, other
    """
    stmt = (
        select(Booking)
        .options(joinedload(Booking.car))
        .join(Car)
        .filter(
            Booking.booking_id == booking_id,
            Car.host_id == current_host.id,
        )
    )
    
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    if booking.status not in [BookingStatus.CONFIRMED, BookingStatus.ACTIVE, BookingStatus.COMPLETED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Issues can only be reported for confirmed, active, or completed bookings. "
                f"Current status is '{booking.status.value}'."
            ),
        )

    issue = BookingIssue(
        booking_id=booking.id,
        host_id=current_host.id,
        issue_type=request.issue_type,
        description=request.description,
        status="open",
    )
    db.add(issue)
    await db.commit()
    await db.refresh(issue)
    await db.refresh(issue.booking)

    return _issue_to_response(issue)


@router.get("/host/issues", response_model=BookingIssueListResponse)
async def list_host_issues(
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None, description="Filter by status: open, in_review, resolved, closed"),
):
    """
    List all issues reported by the host, with optional status filter.
    """
    stmt = (
        select(BookingIssue)
        .options(joinedload(BookingIssue.booking))
        .filter(BookingIssue.host_id == current_host.id)
    )
    if status:
        stmt = stmt.filter(BookingIssue.status == status)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0
    
    stmt = stmt.order_by(BookingIssue.created_at.desc()).offset((page - 1) * limit).limit(limit)
    result = await db.execute(stmt)
    issues = result.scalars().all()

    return BookingIssueListResponse(
        issues=[_issue_to_response(i) for i in issues],
        total=total,
        page=page,
        limit=limit,
    )


@router.post("/host/bookings/{booking_id}/complete", response_model=BookingResponse)
async def complete_booking_as_host(
    booking_id: str,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Mark a booking as **completed** from the host side (e.g., after drop‑off confirmation).

    - Only the host who owns the car can complete the booking
    - Only `confirmed` or `active` bookings can be completed
    """
    stmt = (
        select(Booking)
        .options(
            joinedload(Booking.car).joinedload(Car.host),
            joinedload(Booking.client),
        )
        .join(Car)
        .filter(
            Booking.booking_id == booking_id,
            Car.host_id == current_host.id,
        )
    )
    
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()

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
    booking.status_updated_at = datetime.now(timezone.utc)
    booking.cancellation_reason = None

    await db.commit()
    await db.refresh(booking)
    await invalidate_host_cache_namespaces(
        current_host.id,
        ["host-bookings-list", "host-bookings-completed", "host-earnings-summary"],
    )

    _car2 = booking.car if hasattr(booking, "car") and booking.car else None
    _car2_name = f"{getattr(_car2, 'name', '')} {getattr(_car2, 'model', '')}".strip() if _car2 else "your car"
    asyncio.ensure_future(notify_trip_completed(
        booking.client_id,
        getattr(booking, "booking_id", str(booking.id)),
        _car2_name,
    ))

    return booking_to_response(booking)


@router.delete("/client/bookings/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_booking(
    booking_id: str,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a booking (soft delete by cancelling).

    **booking_id** can be the string (e.g. BK-12345678) or numeric id.
    Use POST /bookings/{booking_id}/cancel for more control.

    Requires client authentication.
    """
    booking = await _client_booking_query(db, booking_id, current_client.id)
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
    
    # Capture host_id and car info before commit expires the relationship
    host_id = booking.car.host_id
    _booking_ref = getattr(booking, "booking_id", str(booking.id))
    _car_label = f"{booking.car.name} {getattr(booking.car, 'model', '') or ''}".strip() if booking.car else "car"

    # Soft delete by cancelling
    booking.status = BookingStatus.CANCELLED
    booking.status_updated_at = datetime.now(timezone.utc)
    booking.cancellation_reason = "Deleted by client"

    await db.commit()
    await invalidate_host_cache_namespaces(
        host_id,
        ["host-bookings-list"],
    )
    asyncio.ensure_future(notify_host_booking_cancelled(host_id, _booking_ref, _car_label))

    return None


@router.delete("/client/bookings/{booking_id}/completed", status_code=status.HTTP_204_NO_CONTENT)
async def delete_completed_booking(
    booking_id: str,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Hide/delete a **completed or cancelled** booking from the client's view.

    - Does **not** delete the booking from the database; it sets `client_deleted_at`
      so the client no longer sees it in their bookings list.
    - Only bookings owned by the current client and with status `completed` or
      `cancelled` are allowed.
    """
    booking = await _client_booking_query(db, booking_id, current_client.id)
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    if booking.status not in [BookingStatus.COMPLETED, BookingStatus.CANCELLED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only completed or cancelled bookings can be deleted from your history.",
        )

    if booking.client_deleted_at is not None:
        # Already hidden; treat as success
        return None

    booking.client_deleted_at = datetime.utcnow()
    await db.commit()

    return None


@router.get(
    "/client/bookings/{booking_id}/extensions",
    response_model=BookingExtensionListResponse,
)
async def get_client_booking_extensions(
    booking_id: str,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all extension requests for a specific booking (client view).

    - Only returns extensions for bookings owned by the authenticated client.
    """
    booking = await _client_booking_query(db, booking_id, current_client.id)
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    stmt = select(BookingExtensionRequest).filter(
        BookingExtensionRequest.booking_id == booking.id
    ).order_by(BookingExtensionRequest.created_at.desc())
    
    result = await db.execute(stmt)
    extensions = result.scalars().all()

    return BookingExtensionListResponse(extensions=extensions)


@router.get(
    "/host/bookings/{booking_id}/extensions",
    response_model=BookingExtensionListResponse,
)
async def get_host_booking_extensions(
    booking_id: str,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all extension requests for a specific booking (host view).

    - Only returns extensions where the car belongs to the authenticated host.
    """
    stmt = (
        select(Booking)
        .join(Car)
        .filter(
            Booking.booking_id == booking_id,
            Car.host_id == current_host.id,
        )
    )
    
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()
    
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    stmt = select(BookingExtensionRequest).filter(
        BookingExtensionRequest.booking_id == booking.id
    ).order_by(BookingExtensionRequest.created_at.desc())
    
    result = await db.execute(stmt)
    extensions = result.scalars().all()

    return BookingExtensionListResponse(extensions=extensions)


@router.post(
    "/host/bookings/{booking_id}/extensions/{extension_id}/approve",
    response_model=BookingExtensionRequestResponse,
)
async def approve_booking_extension(
    booking_id: str,
    extension_id: int,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Approve a client's booking extension request.

    - Verifies the booking belongs to the host.
    - Ensures the extension is still pending.
    - Re-checks availability before approval.
    """
    stmt = (
        select(Booking)
        .join(Car)
        .filter(
            Booking.booking_id == booking_id,
            Car.host_id == current_host.id,
        )
    )
    
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()
    
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    stmt = select(BookingExtensionRequest).filter(
        BookingExtensionRequest.id == extension_id,
        BookingExtensionRequest.booking_id == booking.id,
    )
    
    result = await db.execute(stmt)
    extension = result.scalar_one_or_none()
    
    if not extension:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Extension request not found",
        )

    if extension.status != BookingExtensionStatusEnum.PENDING_HOST_APPROVAL.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve an extension in status '{extension.status}'.",
        )

    # Re-check availability in case something changed since the request was created
    extra_start = extension.old_end_date
    extra_end = extension.requested_end_date

    if await check_booking_overlap(db, booking.car_id, extra_start, extra_end, exclude_booking_id=booking.id):
        # Mark as rejected so client sees it's no longer possible
        extension.status = BookingExtensionStatusEnum.REJECTED.value
        extension.host_note = "Car is no longer available for the requested extension period."
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Car is no longer available for the requested extension period.",
        )

    if await check_blocked_date_overlap(db, booking.car_id, extra_start, extra_end):
        extension.status = BookingExtensionStatusEnum.REJECTED.value
        extension.host_note = "Some of the requested extension dates are now blocked."
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Some of the requested extension dates are now blocked.",
        )

    extension.status = BookingExtensionStatusEnum.HOST_APPROVED.value
    await db.commit()
    await db.refresh(extension)

    return extension


@router.post(
    "/host/bookings/{booking_id}/extensions/{extension_id}/reject",
    response_model=BookingExtensionRequestResponse,
)
async def reject_booking_extension(
    booking_id: str,
    extension_id: int,
    reason: Optional[str] = Body(None, embed=True, description="Optional reason for rejecting the extension"),
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Reject a client's booking extension request.

    - Verifies the booking belongs to the host.
    - Sets extension status to `rejected` and optionally stores a reason.
    """
    stmt = (
        select(Booking)
        .join(Car)
        .filter(
            Booking.booking_id == booking_id,
            Car.host_id == current_host.id,
        )
    )
    
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()
    
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    stmt = select(BookingExtensionRequest).filter(
        BookingExtensionRequest.id == extension_id,
        BookingExtensionRequest.booking_id == booking.id,
    )
    
    result = await db.execute(stmt)
    extension = result.scalar_one_or_none()
    
    if not extension:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Extension request not found",
        )

    if extension.status in [
        BookingExtensionStatusEnum.PAID.value,
        BookingExtensionStatusEnum.EXPIRED.value,
        BookingExtensionStatusEnum.REJECTED.value,
    ]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reject an extension in status '{extension.status}'.",
        )

    extension.status = BookingExtensionStatusEnum.REJECTED.value
    if reason:
        extension.host_note = reason.strip()

    await db.commit()
    await db.refresh(extension)

    return extension
