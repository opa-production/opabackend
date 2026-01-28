"""
Admin Dashboard endpoints

These endpoints power the admin web dashboard (`admin-web/`).
"""
from datetime import datetime
from typing import Dict, Any, List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import Host, Client, Car, VerificationStatus

router = APIRouter()


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
def get_recent_activity() -> Dict[str, List[Dict[str, Any]]]:
    """
    Recent platform activity for the dashboard.

    For now this returns an empty list so the UI shows
    “No recent activity” instead of a 404 error.
    """
    return {"activities": []}


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
