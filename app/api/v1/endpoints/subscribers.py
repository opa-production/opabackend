"""
Public newsletter subscribe / unsubscribe endpoints.
Used by the website "Subscribe" form; no auth required.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Subscriber
from app.schemas import SubscribeRequest, UnsubscribeRequest

router = APIRouter()


@router.post("/subscribe")
async def subscribe(request: SubscribeRequest, db: AsyncSession = Depends(get_db)):
    """
    Subscribe an email to the newsletter.
    Idempotent: if already subscribed, returns success. If previously unsubscribed, re-subscribes.
    """
    email = request.email.strip().lower()
    stmt = select(Subscriber).filter(Subscriber.email == email)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        if not existing.is_subscribed:
            existing.is_subscribed = True
            existing.unsubscribed_at = None
            await db.commit()
            await db.refresh(existing)
        return {"message": "You are subscribed to our newsletter.", "subscribed": True}
    sub = Subscriber(email=email, is_subscribed=True)
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return {"message": "You are subscribed to our newsletter.", "subscribed": True}


@router.post("/unsubscribe")
async def unsubscribe(request: UnsubscribeRequest, db: AsyncSession = Depends(get_db)):
    """
    Unsubscribe an email from the newsletter.
    Idempotent: if not found or already unsubscribed, returns success (no info leak).
    """
    from datetime import datetime, timezone

    email = request.email.strip().lower()
    stmt = select(Subscriber).filter(Subscriber.email == email)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing and existing.is_subscribed:
        existing.is_subscribed = False
        existing.unsubscribed_at = datetime.now(timezone.utc)
        await db.commit()
    return {"message": "You have been unsubscribed.", "subscribed": False}
