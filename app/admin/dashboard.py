from typing import List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, and_

from app.database import get_db
from app.models import Host, Client, Car, VerificationStatus
from app.schemas import (
    DashboardStatsResponse,
    ActivityItem,
    RecentActivityResponse,
    VerificationQueueStatsResponse
)
from app.auth import get_current_admin

router = APIRouter()


@router.get("/admin/dashboard/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    current_admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Get dashboard statistics
    
    Returns counts for:
    - Hosts (total, active, inactive)
    - Clients (total, active, inactive)
    - Cars (total, by verification status, hidden/visible)
    """
    # Host statistics
    total_hosts = db.query(func.count(Host.id)).scalar() or 0
    active_hosts = db.query(func.count(Host.id)).filter(Host.is_active == True).scalar() or 0
    inactive_hosts = total_hosts - active_hosts
    
    # Client statistics
    total_clients = db.query(func.count(Client.id)).scalar() or 0
    active_clients = db.query(func.count(Client.id)).filter(Client.is_active == True).scalar() or 0
    inactive_clients = total_clients - active_clients
    
    # Car statistics
    total_cars = db.query(func.count(Car.id)).scalar() or 0
    cars_awaiting = db.query(func.count(Car.id)).filter(
        Car.verification_status == VerificationStatus.AWAITING.value
    ).scalar() or 0
    verified_cars = db.query(func.count(Car.id)).filter(
        Car.verification_status == VerificationStatus.VERIFIED.value
    ).scalar() or 0
    rejected_cars = db.query(func.count(Car.id)).filter(
        Car.verification_status == VerificationStatus.DENIED.value
    ).scalar() or 0
    hidden_cars = db.query(func.count(Car.id)).filter(Car.is_hidden == True).scalar() or 0
    visible_cars = total_cars - hidden_cars
    
    return DashboardStatsResponse(
        total_hosts=total_hosts,
        active_hosts=active_hosts,
        inactive_hosts=inactive_hosts,
        total_clients=total_clients,
        active_clients=active_clients,
        inactive_clients=inactive_clients,
        total_cars=total_cars,
        cars_awaiting_verification=cars_awaiting,
        verified_cars=verified_cars,
        rejected_cars=rejected_cars,
        hidden_cars=hidden_cars,
        visible_cars=visible_cars
    )


@router.get("/admin/dashboard/activity", response_model=RecentActivityResponse)
async def get_recent_activity(
    limit: int = Query(20, ge=1, le=100, description="Number of activities to return"),
    current_admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Get recent activity across the platform
    
    Returns recent:
    - Host registrations
    - Client registrations
    - Car submissions
    - Car verification status changes
    
    Activities are sorted by timestamp (most recent first).
    """
    activities: List[ActivityItem] = []
    
    # Get recent host registrations
    recent_hosts = db.query(Host).order_by(Host.created_at.desc()).limit(limit).all()
    for host in recent_hosts:
        activities.append(ActivityItem(
            type="host_registration",
            entity_type="host",
            entity_id=host.id,
            entity_name=host.full_name,
            description=f"New host registered: {host.full_name} ({host.email})",
            timestamp=host.created_at
        ))
    
    # Get recent client registrations
    recent_clients = db.query(Client).order_by(Client.created_at.desc()).limit(limit).all()
    for client in recent_clients:
        activities.append(ActivityItem(
            type="client_registration",
            entity_type="client",
            entity_id=client.id,
            entity_name=client.full_name,
            description=f"New client registered: {client.full_name} ({client.email})",
            timestamp=client.created_at
        ))
    
    # Get recent car submissions
    recent_cars = db.query(Car).order_by(Car.created_at.desc()).limit(limit).all()
    for car in recent_cars:
        host = db.query(Host).filter(Host.id == car.host_id).first()
        host_name = host.full_name if host else "Unknown"
        activities.append(ActivityItem(
            type="car_submission",
            entity_type="car",
            entity_id=car.id,
            entity_name=car.name or f"{car.model or 'Car'}",
            description=f"New car submitted: {car.name or car.model} by {host_name}",
            timestamp=car.created_at
        ))
    
    # Get recent car status changes (when updated_at is different from created_at)
    # Only include cars that have been verified or rejected (status changed)
    recent_status_changes = db.query(Car).filter(
        Car.updated_at != None,
        Car.verification_status.in_([VerificationStatus.VERIFIED.value, VerificationStatus.DENIED.value])
    ).order_by(Car.updated_at.desc()).limit(limit).all()
    
    for car in recent_status_changes:
        host = db.query(Host).filter(Host.id == car.host_id).first()
        host_name = host.full_name if host else "Unknown"
        status_text = car.verification_status.replace("_", " ").title()
        activities.append(ActivityItem(
            type="car_status_change",
            entity_type="car",
            entity_id=car.id,
            entity_name=car.name or f"{car.model or 'Car'}",
            description=f"Car status changed to {status_text}: {car.name or car.model} by {host_name}",
            timestamp=car.updated_at or car.created_at
        ))
    
    # Sort all activities by timestamp (most recent first) and limit
    activities.sort(key=lambda x: x.timestamp, reverse=True)
    activities = activities[:limit]
    
    return RecentActivityResponse(
        activities=activities,
        total=len(activities)
    )


@router.get("/admin/dashboard/verification-queue", response_model=VerificationQueueStatsResponse)
async def get_verification_queue_stats(
    current_admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Get verification queue statistics
    
    Returns:
    - Count of cars awaiting verification
    - Average verification time (hours)
    - Rejection rate (percentage)
    - Total processed cars count
    """
    # Count cars awaiting verification
    cars_awaiting = db.query(func.count(Car.id)).filter(
        Car.verification_status == VerificationStatus.AWAITING.value
    ).scalar() or 0
    
    # Count verified and rejected cars
    verified_count = db.query(func.count(Car.id)).filter(
        Car.verification_status == VerificationStatus.VERIFIED.value
    ).scalar() or 0
    
    rejected_count = db.query(func.count(Car.id)).filter(
        Car.verification_status == VerificationStatus.DENIED.value
    ).scalar() or 0
    
    total_processed = verified_count + rejected_count
    
    # Calculate rejection rate
    rejection_rate = 0.0
    if total_processed > 0:
        rejection_rate = (rejected_count / total_processed) * 100
    
    # Calculate average verification time
    # Get cars that have been verified or rejected and have updated_at set
    processed_cars = db.query(Car).filter(
        Car.verification_status.in_([VerificationStatus.VERIFIED.value, VerificationStatus.DENIED.value]),
        Car.updated_at != None
    ).all()
    
    average_verification_time_hours = None
    if processed_cars:
        total_hours = 0
        count = 0
        for car in processed_cars:
            if car.updated_at and car.created_at:
                time_diff = car.updated_at - car.created_at
                hours = time_diff.total_seconds() / 3600
                total_hours += hours
                count += 1
        
        if count > 0:
            average_verification_time_hours = total_hours / count
    
    return VerificationQueueStatsResponse(
        cars_awaiting_verification=cars_awaiting,
        average_verification_time_hours=average_verification_time_hours,
        rejection_rate=round(rejection_rate, 2),
        total_processed=total_processed,
        verified_count=verified_count,
        rejected_count=rejected_count
    )
