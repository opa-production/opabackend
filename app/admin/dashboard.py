"""
Admin Dashboard endpoints

These endpoints power the admin web dashboard (`admin-web/`).
"""
from datetime import datetime
from typing import Dict, Any, List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.database import get_db
from app.models import Host, Client, Car, Booking, VerificationStatus

router = APIRouter()
ACTIVITY_LIMIT = 30


@router.get("/admin/dashboard/stats")
def get_dashboard_stats(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    High‑level statistics for the admin dashboard.

    Matches the fields expected by `admin-web/dashboard.js`:
    - total_hosts, active_hosts, inactive_hosts
    - total_clients, active_clients, inactive_clients
    - total_cars, visible_cars, hidden_cars
    - cars_awaiting_verification, verified_cars, rejected_cars
    """
    # Hosts
    total_hosts = db.query(func.count(Host.id)).scalar() or 0
    active_hosts = db.query(func.count(Host.id)).filter(Host.is_active.is_(True)).scalar() or 0
    inactive_hosts = total_hosts - active_hosts

    # Clients
    total_clients = db.query(func.count(Client.id)).scalar() or 0
    active_clients = db.query(func.count(Client.id)).filter(Client.is_active.is_(True)).scalar() or 0
    inactive_clients = total_clients - active_clients

    # Cars
    total_cars = db.query(func.count(Car.id)).scalar() or 0
    visible_cars = db.query(func.count(Car.id)).filter(Car.is_hidden.is_(False)).scalar() or 0
    hidden_cars = total_cars - visible_cars

    cars_awaiting_verification = (
        db.query(func.count(Car.id))
        .filter(Car.verification_status == VerificationStatus.AWAITING.value)
        .scalar()
        or 0
    )
    verified_cars = (
        db.query(func.count(Car.id))
        .filter(Car.verification_status == VerificationStatus.VERIFIED.value)
        .scalar()
        or 0
    )
    rejected_cars = (
        db.query(func.count(Car.id))
        .filter(Car.verification_status == VerificationStatus.DENIED.value)
        .scalar()
        or 0
    )

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
def get_recent_activity(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Recent platform activity for the dashboard.

    For now this returns an empty list so the UI shows
    “No recent activity” instead of a 404 error.
    """
    activities: List[Dict[str, Any]] = []

    # Recent host registrations
    hosts = db.query(Host).order_by(Host.created_at.desc()).limit(10).all()
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
    clients = db.query(Client).order_by(Client.created_at.desc()).limit(10).all()
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
    cars = db.query(Car).order_by(Car.created_at.desc()).limit(10).all()
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
    cars_updated = (
        db.query(Car)
        .filter(Car.updated_at.isnot(None))
        .order_by(Car.updated_at.desc())
        .limit(10)
        .all()
    )
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
    bookings = (
        db.query(Booking)
        .options(joinedload(Booking.car))
        .order_by(Booking.created_at.desc())
        .limit(10)
        .all()
    )
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
def get_verification_queue_stats(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Basic stats for the car verification queue.

    Useful for future widgets; safe no-op for now.
    """
    awaiting = (
        db.query(func.count(Car.id))
        .filter(Car.verification_status == VerificationStatus.AWAITING.value)
        .scalar()
        or 0
    )
    verified = (
        db.query(func.count(Car.id))
        .filter(Car.verification_status == VerificationStatus.VERIFIED.value)
        .scalar()
        or 0
    )
    denied = (
        db.query(func.count(Car.id))
        .filter(Car.verification_status == VerificationStatus.DENIED.value)
        .scalar()
        or 0
    )

    return {
        "cars_awaiting_verification": awaiting,
        "verified_cars": verified,
        "rejected_cars": denied,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }
