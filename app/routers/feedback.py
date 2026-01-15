from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Host, Feedback
from app.schemas import (
    FeedbackCreateRequest,
    FeedbackResponse,
    FeedbackListResponse
)
from app.auth import get_current_host

router = APIRouter()


@router.post("/host/feedback", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
async def create_feedback(
    request: FeedbackCreateRequest,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db)
):
    """
    Create a new feedback for the authenticated host
    
    - **content**: Feedback content (max 250 characters)
    
    Requires Bearer token authentication.
    """
    # Create feedback
    db_feedback = Feedback(
        host_id=current_host.id,
        content=request.content.strip()  # Remove leading/trailing whitespace
    )
    
    db.add(db_feedback)
    db.commit()
    db.refresh(db_feedback)
    
    return db_feedback


@router.get("/host/feedback", response_model=FeedbackListResponse)
async def get_host_feedbacks(
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db)
):
    """
    Get all feedbacks submitted by the authenticated host
    
    Requires Bearer token authentication.
    Returns list of feedbacks ordered by creation date (newest first).
    """
    feedbacks = db.query(Feedback).filter(
        Feedback.host_id == current_host.id
    ).order_by(Feedback.created_at.desc()).all()
    
    return FeedbackListResponse(feedbacks=feedbacks)


@router.get("/host/feedback/{feedback_id}", response_model=FeedbackResponse)
async def get_feedback(
    feedback_id: int,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db)
):
    """
    Get a specific feedback by ID
    
    Requires Bearer token authentication.
    Returns the feedback if it belongs to the authenticated host.
    """
    feedback = db.query(Feedback).filter(
        Feedback.id == feedback_id,
        Feedback.host_id == current_host.id
    ).first()
    
    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found"
        )
    
    return feedback


@router.delete("/host/feedback/{feedback_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feedback(
    feedback_id: int,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db)
):
    """
    Delete a feedback
    
    Requires Bearer token authentication.
    Only the owner of the feedback can delete it.
    """
    feedback = db.query(Feedback).filter(
        Feedback.id == feedback_id,
        Feedback.host_id == current_host.id
    ).first()
    
    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found"
        )
    
    db.delete(feedback)
    db.commit()
    
    return None
