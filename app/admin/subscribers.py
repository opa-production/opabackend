"""
Admin Newsletter Subscribers endpoints.

List subscribers, view count, trends for chart, and send newsletter email to all subscribed addresses.
"""
import logging
from datetime import datetime, timedelta, timezone, time as dt_time
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import Subscriber, Admin
from app.auth import get_current_admin
from app.schemas import (
    SubscriberListResponse,
    SubscriberItemResponse,
    AdminSendNewsletterRequest,
)
from app.config import settings
from app.services.email_welcome import send_email

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/admin/subscribers", response_model=SubscriberListResponse)
def list_subscribers(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    subscribed_only: bool = Query(True, description="If true, only list currently subscribed emails"),
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    List newsletter subscribers with pagination.
    Returns total count of subscribers (and total_pages) for the admin UI.
    """
    query = db.query(Subscriber)
    if subscribed_only:
        query = query.filter(Subscriber.is_subscribed.is_(True))
    total = query.count()
    total_pages = max(1, (total + limit - 1) // limit)
    skip = (page - 1) * limit
    subscribers = query.order_by(Subscriber.created_at.desc()).offset(skip).limit(limit).all()

    items = [
        SubscriberItemResponse(
            id=s.id,
            email=s.email,
            is_subscribed=s.is_subscribed,
            created_at=s.created_at,
            unsubscribed_at=s.unsubscribed_at,
        )
        for s in subscribers
    ]
    return SubscriberListResponse(
        subscribers=items,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )


@router.get("/admin/subscribers/trends")
def get_subscriber_trends(
    days: int = Query(30, ge=7, le=90),
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Return daily subscription and unsubscription counts for the last N days (for chart).
    """
    tz = timezone.utc
    today = datetime.now(tz).date()
    labels = []
    subscriptions = []
    unsubscriptions = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        labels.append(d.isoformat())
        subscriptions.append(0)
        unsubscriptions.append(0)

    since = datetime.combine(today - timedelta(days=days), dt_time(0, 0, 0), tzinfo=tz)
    # Subscriptions per day (created_at)
    sub_q = (
        db.query(func.date(Subscriber.created_at).label("d"), func.count(Subscriber.id).label("c"))
        .filter(Subscriber.created_at >= since)
        .group_by(func.date(Subscriber.created_at))
    )
    sub_map = {str(r.d): r.c for r in sub_q if r.d}
    unsub_q = (
        db.query(func.date(Subscriber.unsubscribed_at).label("d"), func.count(Subscriber.id).label("c"))
        .filter(Subscriber.unsubscribed_at.isnot(None), Subscriber.unsubscribed_at >= since)
        .group_by(func.date(Subscriber.unsubscribed_at))
    )
    unsub_map = {str(r.d): r.c for r in unsub_q if r.d}

    for i, label in enumerate(labels):
        subscriptions[i] = sub_map.get(label, 0)
        unsubscriptions[i] = unsub_map.get(label, 0)

    return {"labels": labels, "subscriptions": subscriptions, "unsubscriptions": unsubscriptions}


@router.get("/admin/subscribers/count")
def get_subscriber_count(
    subscribed_only: bool = Query(True, description="Count only currently subscribed"),
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Return total number of subscribers (for dashboard or header).
    """
    query = db.query(Subscriber)
    if subscribed_only:
        query = query.filter(Subscriber.is_subscribed.is_(True))
    count = query.count()
    return {"count": count, "subscribed_only": subscribed_only }


@router.post("/admin/subscribers/send")
def send_newsletter(
    request: AdminSendNewsletterRequest,
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Send a newsletter email to all currently subscribed addresses.
    Uses SendGrid; failures are logged per-recipient but do not fail the request.
    """
    if not settings.SENDGRID_API_KEY:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email service is not configured. Set SENDGRID_API_KEY.",
        )
    subscribers = db.query(Subscriber).filter(Subscriber.is_subscribed.is_(True)).all()
    if not subscribers:
        return {"message": "No subscribers to send to.", "sent": 0, "failed": 0 }
    sent = 0
    failed = 0
    for s in subscribers:
        ok = send_email(s.email, request.subject, request.body_html)
        if ok:
            sent += 1
        else:
            failed += 1
    return {
        "message": f"Newsletter sent to {sent} subscriber(s)." + (f" {failed} failed." if failed else ""),
        "sent": sent,
        "failed": failed,
        "total": len(subscribers),
    }
