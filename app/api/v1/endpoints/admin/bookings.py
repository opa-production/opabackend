"""
Admin Booking Management endpoints

These endpoints allow admins to view and manage all bookings in the system.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_admin
from app.api.v1.endpoints.bookings import booking_to_response, parse_image_urls
from app.db.session import get_db
from app.models import Admin, Booking, BookingStatus, Car, Client, Host
from app.schemas import BookingListResponse, BookingResponse

router = APIRouter()


# ==================== BOOKING LIST & SEARCH ====================


@router.get("/admin/bookings", response_model=BookingListResponse)
async def list_bookings(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by booking status"),
    client_id: Optional[int] = Query(None, description="Filter by client ID"),
    host_id: Optional[int] = Query(None, description="Filter by host ID"),
    car_id: Optional[int] = Query(None, description="Filter by car ID"),
    booking_id: Optional[str] = Query(None, description="Search by booking ID"),
    start_date_from: Optional[datetime] = Query(
        None, description="Filter bookings starting from this date"
    ),
    start_date_to: Optional[datetime] = Query(
        None, description="Filter bookings starting until this date"
    ),
    search: Optional[str] = Query(
        None, description="Search by client name, host name, or car name"
    ),
    sort_by: Optional[str] = Query(
        "created_at", description="Sort field: created_at, start_date, total_price"
    ),
    order: Optional[str] = Query("desc", description="Sort order: asc or desc"),
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    List all bookings with advanced filtering and search.

    - Supports pagination
    - Filter by status, client, host, car, date range
    - Search by booking ID, client name, host name, or car name
    - Sort by various fields
    - Requires admin authentication
    """
    # Build base statement with relationships
    stmt = select(Booking).options(
        joinedload(Booking.client), joinedload(Booking.car).joinedload(Car.host)
    )

    # Filter by status
    if status:
        try:
            status_enum = BookingStatus(status.lower())
            stmt = stmt.filter(Booking.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Valid values: {[s.value for s in BookingStatus]}",
            )

    # Filter by client_id
    if client_id:
        stmt = stmt.filter(Booking.client_id == client_id)

    # Filter by host_id (through car relationship)
    if host_id:
        stmt = stmt.join(Car).filter(Car.host_id == host_id)

    # Filter by car_id
    if car_id:
        stmt = stmt.filter(Booking.car_id == car_id)

    # Filter by booking_id (exact match)
    if booking_id:
        stmt = stmt.filter(Booking.booking_id.ilike(f"%{booking_id}%"))

    # Filter by date range
    if start_date_from:
        stmt = stmt.filter(Booking.start_date >= start_date_from)
    if start_date_to:
        stmt = stmt.filter(Booking.start_date <= start_date_to)

    # Search by client name, host name, or car name
    if search:
        search_term = f"%{search}%"
        stmt = (
            stmt.join(Client)
            .join(Car)
            .join(Host)
            .filter(
                or_(
                    Client.full_name.ilike(search_term),
                    Client.email.ilike(search_term),
                    Host.full_name.ilike(search_term),
                    Host.email.ilike(search_term),
                    Car.name.ilike(search_term),
                    Car.model.ilike(search_term),
                )
            )
        )

    # Get total count before pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # Apply sorting
    sort_field = sort_by.lower() if sort_by else "created_at"
    sort_order = order.lower() if order else "desc"

    if sort_field == "created_at":
        sort_column = Booking.created_at
    elif sort_field == "start_date":
        sort_column = Booking.start_date
    elif sort_field == "total_price":
        sort_column = Booking.total_price
    else:
        sort_column = Booking.created_at

    if sort_order == "asc":
        stmt = stmt.order_by(sort_column)
    else:
        stmt = stmt.order_by(desc(sort_column))

    # Apply pagination
    skip = (page - 1) * limit
    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    bookings = result.scalars().unique().all()

    # Convert to response format
    booking_responses = [booking_to_response(b) for b in bookings]

    return BookingListResponse(
        bookings=booking_responses, total=total, skip=skip, limit=limit
    )


# ==================== BOOKING DETAILS ====================


@router.get("/admin/bookings/{booking_id}", response_model=BookingResponse)
async def get_booking_details(
    booking_id: str,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Get detailed information about a specific booking.

    - Returns full booking details including client, host, and car information
    - Requires admin authentication
    """
    stmt = (
        select(Booking)
        .options(
            joinedload(Booking.client), joinedload(Booking.car).joinedload(Car.host)
        )
        .filter(Booking.booking_id == booking_id)
    )
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found"
        )

    return booking_to_response(booking)


# ==================== BOOKING STATUS MANAGEMENT ====================


@router.put("/admin/bookings/{booking_id}/status")
async def update_booking_status(
    booking_id: str,
    new_status: str = Query(
        ...,
        description="New status: pending, confirmed, active, completed, cancelled, rejected",
    ),
    reason: Optional[str] = Query(
        None, description="Reason for status change (required for cancelled/rejected)"
    ),
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Update booking status.

    - Admins can change booking status to any valid status
    - Reason is required for cancelled/rejected statuses
    - Updates status_updated_at timestamp
    - Requires admin authentication
    """
    stmt = select(Booking).filter(Booking.booking_id == booking_id)
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found"
        )

    # Validate new status
    try:
        status_enum = BookingStatus(new_status.lower())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Valid values: {[s.value for s in BookingStatus]}",
        )

    # Validate reason for cancelled/rejected
    if status_enum in [BookingStatus.CANCELLED, BookingStatus.REJECTED] and not reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reason is required for cancelled or rejected status",
        )

    # Update booking status
    old_status = booking.status
    booking.status = status_enum
    booking.status_updated_at = datetime.now(timezone.utc)

    if status_enum in [BookingStatus.CANCELLED, BookingStatus.REJECTED]:
        booking.cancellation_reason = reason

    # Clear cancellation reason if status changed from cancelled/rejected
    if status_enum not in [BookingStatus.CANCELLED, BookingStatus.REJECTED]:
        booking.cancellation_reason = None

    await db.commit()
    await db.refresh(booking)

    # Reload with relationships for response
    load_stmt = (
        select(Booking)
        .options(
            joinedload(Booking.client), joinedload(Booking.car).joinedload(Car.host)
        )
        .filter(Booking.id == booking.id)
    )
    result = await db.execute(load_stmt)
    booking = result.scalar_one_or_none()

    return {
        "message": f"Booking status updated from {old_status.value} to {status_enum.value}",
        "booking": booking_to_response(booking),
    }


@router.post("/admin/bookings/{booking_id}/cancel")
async def cancel_booking(
    booking_id: str,
    reason: Optional[str] = Query(None, description="Cancellation reason"),
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Cancel a booking (convenience endpoint).

    - Sets booking status to 'cancelled'
    - Updates status_updated_at timestamp
    - Requires admin authentication
    """
    stmt = select(Booking).filter(Booking.booking_id == booking_id)
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found"
        )

    if booking.status == BookingStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Booking is already cancelled",
        )

    if booking.status == BookingStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot cancel a completed booking",
        )

    # Update booking
    booking.status = BookingStatus.CANCELLED
    booking.status_updated_at = datetime.now(timezone.utc)
    booking.cancellation_reason = reason or "Cancelled by admin"

    await db.commit()
    await db.refresh(booking)

    # Reload with relationships for response
    load_stmt = (
        select(Booking)
        .options(
            joinedload(Booking.client), joinedload(Booking.car).joinedload(Car.host)
        )
        .filter(Booking.id == booking.id)
    )
    result = await db.execute(load_stmt)
    booking = result.scalar_one_or_none()

    return {
        "message": "Booking cancelled successfully",
        "booking": booking_to_response(booking),
    }


@router.post("/admin/bookings/{booking_id}/confirm")
async def confirm_booking(
    booking_id: str,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Confirm a pending booking.

    - Sets booking status to 'confirmed'
    - Updates status_updated_at timestamp
    - Requires admin authentication
    """
    stmt = select(Booking).filter(Booking.booking_id == booking_id)
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found"
        )

    if booking.status != BookingStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot confirm booking with status: {booking.status.value}",
        )

    # Update booking
    booking.status = BookingStatus.CONFIRMED
    booking.status_updated_at = datetime.now(timezone.utc)
    booking.cancellation_reason = None

    await db.commit()
    await db.refresh(booking)

    # Reload with relationships for response
    load_stmt = (
        select(Booking)
        .options(
            joinedload(Booking.client), joinedload(Booking.car).joinedload(Car.host)
        )
        .filter(Booking.id == booking.id)
    )
    result = await db.execute(load_stmt)
    booking = result.scalar_one_or_none()

    return {
        "message": "Booking confirmed successfully",
        "booking": booking_to_response(booking),
    }


# ==================== BOOKING DELETION ====================


@router.delete("/admin/bookings/{booking_id}")
async def delete_booking(
    booking_id: str,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a booking (permanent deletion).

    - Permanently removes booking from database
    - Use with caution - consider cancelling instead
    - Requires admin authentication
    """
    stmt = select(Booking).filter(Booking.booking_id == booking_id)
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found"
        )

    # Prevent deletion of active or completed bookings
    if booking.status in [BookingStatus.ACTIVE, BookingStatus.COMPLETED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete booking with status: {booking.status.value}",
        )

    await db.delete(booking)
    await db.commit()

    return {"message": "Booking deleted successfully"}


# ==================== BOOKING STATISTICS ====================


@router.get("/admin/bookings/stats")
async def get_booking_stats(
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Get booking statistics for the admin dashboard.

    - Total bookings count
    - Counts by status
    - Revenue statistics
    - Recent booking trends
    - Requires admin authentication
    """
    # Total bookings
    count_stmt = select(func.count(Booking.id))
    total_result = await db.execute(count_stmt)
    total_bookings = total_result.scalar() or 0

    # Bookings by status
    status_counts_stmt = select(
        Booking.status, func.count(Booking.id).label("count")
    ).group_by(Booking.status)
    status_counts_result = await db.execute(status_counts_stmt)
    status_counts = status_counts_result.all()

    status_breakdown = {status.value: 0 for status in BookingStatus}
    for status, count in status_counts:
        status_breakdown[status.value] = count

    # Revenue statistics
    rev_stmt = select(func.sum(Booking.total_price)).filter(
        Booking.status.in_(
            [BookingStatus.CONFIRMED, BookingStatus.ACTIVE, BookingStatus.COMPLETED]
        )
    )
    rev_result = await db.execute(rev_stmt)
    total_revenue = rev_result.scalar() or 0

    comp_rev_stmt = select(func.sum(Booking.total_price)).filter(
        Booking.status == BookingStatus.COMPLETED
    )
    comp_rev_result = await db.execute(comp_rev_stmt)
    completed_revenue = comp_rev_result.scalar() or 0

    # Average booking value
    avg_stmt = select(func.avg(Booking.total_price)).filter(
        Booking.status.in_(
            [BookingStatus.CONFIRMED, BookingStatus.ACTIVE, BookingStatus.COMPLETED]
        )
    )
    avg_result = await db.execute(avg_stmt)
    avg_booking_value = avg_result.scalar() or 0

    # Bookings in date ranges
    now = datetime.now(timezone.utc)
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)

    today_stmt = select(func.count(Booking.id)).filter(
        func.date(Booking.created_at) == func.date(today_start)
    )
    today_result = await db.execute(today_stmt)
    today_bookings = today_result.scalar() or 0

    # This week (last 7 days)
    week_ago = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=7
    )
    week_stmt = select(func.count(Booking.id)).filter(Booking.created_at >= week_ago)
    week_result = await db.execute(week_stmt)
    week_bookings = week_result.scalar() or 0

    # This month
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    month_stmt = select(func.count(Booking.id)).filter(
        Booking.created_at >= month_start
    )
    month_result = await db.execute(month_stmt)
    month_bookings = month_result.scalar() or 0

    return {
        "total_bookings": total_bookings,
        "status_breakdown": status_breakdown,
        "revenue": {
            "total": float(total_revenue),
            "completed": float(completed_revenue),
            "average_booking_value": float(avg_booking_value)
            if avg_booking_value
            else 0,
        },
        "recent_trends": {
            "today": today_bookings,
            "this_week": week_bookings,
            "this_month": month_bookings,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
