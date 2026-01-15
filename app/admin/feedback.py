from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.database import get_db
from app.models import Feedback, Host
from app.schemas import (
    AdminFeedbackListResponse,
    AdminFeedbackDetailResponse,
    PaginatedFeedbackListResponse
)
from app.auth import get_current_admin

router = APIRouter()


# Helper function for pagination
def calculate_pagination(page: int, limit: int, total: int) -> dict:
    """Calculate pagination metadata"""
    total_pages = (total + limit - 1) // limit if limit > 0 else 0
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages
    }


@router.get("/admin/feedback", response_model=PaginatedFeedbackListResponse)
async def list_feedback(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    host_id: Optional[int] = Query(None, description="Filter by host ID"),
    is_flagged: Optional[bool] = Query(None, description="Filter by flagged status"),
    sort_by: Optional[str] = Query("created_at", description="Sort field (id, created_at)"),
    order: Optional[str] = Query("desc", regex="^(asc|desc)$", description="Sort order"),
    current_admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    List all feedback with pagination and filtering
    
    - **page**: Page number (starts from 1)
    - **limit**: Number of items per page (1-100)
    - **host_id**: Filter by host ID
    - **is_flagged**: Filter by flagged status
    - **sort_by**: Field to sort by (id, created_at)
    - **order**: Sort order (asc or desc)
    """
    # Build query with join to host
    query = db.query(Feedback).join(Host)
    
    # Apply filters
    if host_id:
        query = query.filter(Feedback.host_id == host_id)
    
    if is_flagged is not None:
        query = query.filter(Feedback.is_flagged == is_flagged)
    
    # Get total count
    total = query.count()
    
    # Apply sorting
    sort_field = getattr(Feedback, sort_by, Feedback.created_at)
    if order == "asc":
        query = query.order_by(sort_field.asc())
    else:
        query = query.order_by(sort_field.desc())
    
    # Apply pagination
    skip = (page - 1) * limit
    feedbacks = query.offset(skip).limit(limit).all()
    
    # Build response
    feedback_list = []
    for feedback in feedbacks:
        feedback_list.append(AdminFeedbackListResponse(
            id=feedback.id,
            host_id=feedback.host_id,
            host_name=feedback.host.full_name,
            host_email=feedback.host.email,
            content=feedback.content,
            is_flagged=feedback.is_flagged,
            created_at=feedback.created_at,
            updated_at=feedback.updated_at
        ))
    
    pagination = calculate_pagination(page, limit, total)
    
    return PaginatedFeedbackListResponse(
        feedbacks=feedback_list,
        **pagination
    )


@router.get("/admin/feedback/{feedback_id}", response_model=AdminFeedbackDetailResponse)
async def get_feedback_details(
    feedback_id: int,
    current_admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get detailed information about a specific feedback including host information"""
    feedback = db.query(Feedback).join(Host).filter(Feedback.id == feedback_id).first()
    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found"
        )
    
    return AdminFeedbackDetailResponse(
        id=feedback.id,
        host_id=feedback.host_id,
        host_name=feedback.host.full_name,
        host_email=feedback.host.email,
        host_mobile_number=feedback.host.mobile_number,
        content=feedback.content,
        is_flagged=feedback.is_flagged,
        created_at=feedback.created_at,
        updated_at=feedback.updated_at
    )


@router.delete("/admin/feedback/{feedback_id}")
async def delete_feedback(
    feedback_id: int,
    current_admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Delete inappropriate feedback
    
    This action cannot be undone.
    """
    feedback = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found"
        )
    
    db.delete(feedback)
    db.commit()
    
    return {"message": "Feedback deleted successfully"}


@router.put("/admin/feedback/{feedback_id}/flag")
async def flag_feedback(
    feedback_id: int,
    current_admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Flag feedback for review"""
    feedback = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found"
        )
    
    if feedback.is_flagged:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Feedback is already flagged"
        )
    
    feedback.is_flagged = True
    db.commit()
    
    return {"message": "Feedback flagged for review successfully"}


@router.put("/admin/feedback/{feedback_id}/unflag")
async def unflag_feedback(
    feedback_id: int,
    current_admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Unflag feedback (remove flag)"""
    feedback = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found"
        )
    
    if not feedback.is_flagged:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Feedback is not flagged"
        )
    
    feedback.is_flagged = False
    db.commit()
    
    return {"message": "Feedback unflagged successfully"}
