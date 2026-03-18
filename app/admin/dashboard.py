"""
Admin Dashboard endpoints

These endpoints power the admin web dashboard (`admin-web/`).
"""
from datetime import datetime, timezone
from typing import Dict, Any, List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from app.database import get_db
from app.models import Host, Client, Car, Booking, VerificationStatus, BookingStatus

router = APIRouter()
ACTIVITY_LIMIT = 30


@router.get("/admin/dashboard/stats")
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """
    High‑level statistics for the admin dashboard.

    Matches the fields expected by `admin-web/dashboard.js`:
    - total_hosts, active_hosts, inactive_hosts
    - total_clients, active_clients, inactive_clients
    - total_cars, visible_cars, hidden_cars
    - cars_awaiting_verification, verified_cars, rejected_cars
    """
    # Hosts
    total_hosts_result = await db.execute(select(func.count(Host.id)))
    total_hosts = total_hosts_result.scalar() or 0
    
    active_hosts_result = await db.execute(select(func.count(Host.id)).filter(Host.is_active.is_(True)))
    active_hosts = active_hosts_result.scalar() or 0
    
    inactive_hosts = total_hosts - active_hosts

    # Clients
    total_clients_result = await db.execute(select(func.count(Client.id)))
    total_clients = total_clients_result.scalar() or 0
    
    active_clients_result = await db.execute(select(func.count(Client.id)).filter(Client.is_active.is_(True)))
    active_clients = active_clients_result.scalar() or 0
    
    inactive_clients = total_clients - active_clients

    # Cars
    total_cars_result = await db.execute(select(func.count(Car.id)))
    total_cars = total_cars_result.scalar() or 0
    
    visible_cars_result = await db.execute(select(func.count(Car.id)).filter(Car.is_hidden.is_(False)))
    visible_cars = visible_cars_result.scalar() or 0
    
    hidden_cars = total_cars - visible_cars

    cars_awaiting_result = await db.execute(
        select(func.count(Car.id))
        .filter(Car.verification_status == VerificationStatus.AWAITING.value)
    )
    cars_awaiting_verification = cars_awaiting_result.scalar() or 0
    
    verified_cars_result = await db.execute(
        select(func.count(Car.id))
        .filter(Car.verification_status == VerificationStatus.VERIFIED.value)
    )
    verified_cars = verified_cars_result.scalar() or 0
    
    rejected_cars_result = await db.execute(
        select(func.count(Car.id))
        .filter(Car.verification_status == VerificationStatus.DENIED.value)
    )
    rejected_cars = rejected_cars_result.scalar() or 0

    return {
        "total_hosts": total_hosts,
        "active_hosts": active_hosts,
        "inactive_hosts": inactive_hosts,
        "total_clients": total_clients,
        "active_clients": active_clients,
        "inactive_clients": inactive_clients,
        "total_cars": total_cars,
        "visible_cars": visible_cars,
        "hidden_cars": hidden_cars,
        "cars_awaiting_verification": cars_awaiting_verification,
        "verified_cars": verified_cars,
        "rejected_cars": rejected_cars,
    }


@router.get("/admin/dashboard/activity")
async def get_recent_activity(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """
    Recent platform activity for the dashboard.

    For now this returns an empty list so the UI shows
    “No recent activity” instead of a 404 error.
    """
    activities: List[Dict[str, Any]] = []

    # Recent host registrations
    hosts_result = await db.execute(select(Host).order_by(Host.created_at.desc()).limit(10))
    hosts = hosts_result.scalars().all()
    for h in hosts:
        activities.append({
            "type": "host_registration",
            "entity_type": "host",
            "entity_id": h.id,
            "entity_name": h.full_name,
            "description": f"Host {h.full_name} registered",
            "timestamp": h.created_at.isoformat() if h.created_at else "",
        })

    # Recent client registrations
    clients_result = await db.execute(select(Client).order_by(Client.created_at.desc()).limit(10))
    clients = clients_result.scalars().all()
    for c in clients:
        activities.append({
            "type": "client_registration",
            "entity_type": "client",
            "entity_id": c.id,
            "entity_name": c.full_name,
            "description": f"Client {c.full_name} registered",
            "timestamp": c.created_at.isoformat() if c.created_at else "",
        })

    # Recent car submissions
    cars_result = await db.execute(select(Car).order_by(Car.created_at.desc()).limit(10))
    cars = cars_result.scalars().all()
    for car in cars:
        activities.append({
            "type": "car_submission",
            "entity_type": "car",
            "entity_id": car.id,
            "entity_name": car.name or f"Car #{car.id}",
            "description": f"Car '{car.name or 'Untitled'}' submitted for verification",
            "timestamp": car.created_at.isoformat() if car.created_at else "",
        })

    # Car status changes (verified/rejected)
    cars_updated_result = await db.execute(
        select(Car)
        .filter(Car.updated_at.isnot(None))
        .order_by(Car.updated_at.desc())
        .limit(10)
    )
    cars_updated = cars_updated_result.scalars().all()
    for car in cars_updated:
        status = car.verification_status or "awaiting"
        activities.append({
            "type": "car_status_change",
            "entity_type": "car",
            "entity_id": car.id,
            "entity_name": car.name or f"Car #{car.id}",
            "description": f"Car '{car.name or 'Untitled'}' {status}",
            "timestamp": car.updated_at.isoformat() if car.updated_at else "",
        })

    # Recent bookings
    bookings_result = await db.execute(
        select(Booking)
        .options(joinedload(Booking.car))
        .order_by(Booking.created_at.desc())
        .limit(10)
    )
    bookings = bookings_result.scalars().all()
    for b in bookings:
        car_name = b.car.name if b.car else f"Car #{b.car_id}"
        activities.append({
            "type": "booking_created",
            "entity_type": "car",
            "entity_id": b.id,
            "entity_name": car_name,
            "description": f"New booking {b.booking_id} created",
            "timestamp": b.created_at.isoformat() if b.created_at else "",
        })

    # Sort by timestamp descending and take top N
    activities.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    activities = activities[:ACTIVITY_LIMIT]

    return {"activities": activities, "total": len(activities)}


@router.get("/admin/dashboard/verification-queue")
async def get_verification_queue_stats(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """
    Basic stats for the car verification queue.

    Useful for future widgets; safe no-op for now.
    """
    awaiting_result = await db.execute(
        select(func.count(Car.id))
        .filter(Car.verification_status == VerificationStatus.AWAITING.value)
    )
    awaiting = awaiting_result.scalar() or 0
    
    verified_result = await db.execute(
        select(func.count(Car.id))
        .filter(Car.verification_status == VerificationStatus.VERIFIED.value)
    )
    verified = verified_result.scalar() or 0
    
    denied_result = await db.execute(
        select(func.count(Car.id))
        .filter(Car.verification_status == VerificationStatus.DENIED.value)
    )
    denied = denied_result.scalar() or 0

    return {
        "cars_awaiting_verification": awaiting,
        "verified_cars": verified,
        "rejected_cars": denied,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


COMMISSION_RATE = 0.15  # 15% platform commission


@router.get("/admin/dashboard/revenue")
async def get_revenue_stats(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """
    Revenue statistics for admin dashboard.
    - money_in: Total from confirmed/active/completed bookings
    - commission: Platform commission (15%)
    - host_payout: Money paid to hosts
    - monthly_breakdown: Revenue by month for charts
    """
    from datetime import timedelta

    paid_statuses = [BookingStatus.CONFIRMED.value, BookingStatus.ACTIVE.value, BookingStatus.COMPLETED.value]
    result = await db.execute(
        select(func.sum(Booking.total_price))
        .filter(Booking.status.in_(paid_statuses))
    )
    money_in_val = result.scalar()
    money_in = float(money_in_val or 0)
    
    paid_count_result = await db.execute(
        select(func.count(Booking.id))
        .filter(Booking.status.in_(paid_statuses))
    )
    paid_bookings_count = paid_count_result.scalar() or 0
    
    commission_amount = round(money_in * COMMISSION_RATE, 2)
    host_payout = round(money_in - commission_amount, 2)

    # Monthly breakdown (last 6 months)
    now = datetime.now(timezone.utc)
    monthly_data = []
    for i in range(5, -1, -1):
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        for _ in range(i):
            if month_start.month == 1:
                month_start = month_start.replace(year=month_start.year - 1, month=12)
            else:
                month_start = month_start.replace(month=month_start.month - 1)
        month_end = month_start + timedelta(days=32)
        month_end = month_end.replace(day=1) - timedelta(seconds=1)

        month_total_result = await db.execute(
            select(func.coalesce(func.sum(Booking.total_price), 0))
            .filter(
                Booking.status.in_(paid_statuses),
                Booking.created_at >= month_start,
                Booking.created_at <= month_end,
            )
        )
        month_total = month_total_result.scalar()
        
        month_count_result = await db.execute(
            select(func.count(Booking.id))
            .filter(
                Booking.status.in_(paid_statuses),
                Booking.created_at >= month_start,
                Booking.created_at <= month_end,
            )
        )
        month_count = month_count_result.scalar() or 0
        
        monthly_data.append({
            "month": month_start.strftime("%b %Y"),
            "label": month_start.strftime("%b"),
            "revenue": float(month_total or 0),
            "booking_count": int(month_count),
        })

    return {
        "money_in": round(money_in, 2),
        "paid_bookings_count": int(paid_bookings_count),
        "commission_rate": COMMISSION_RATE,
        "commission": commission_amount,
        "host_payout": host_payout,
        "monthly_breakdown": monthly_data,
    }
