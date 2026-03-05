from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Host, Client, Feedback, ClientFeedback
from app.schemas import (
    FeedbackCreateRequest,
    FeedbackResponse,
    FeedbackListResponse,
    ClientFeedbackCreateRequest,
    ClientFeedbackResponse,
    ClientFeedbackListResponse,
)
from app.auth import get_current_host, get_current_client

router = APIRouter()


# ==================== HOST FEEDBACK ====================


@router.post("/host/feedback", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
async def create_host_feedback(
    request: FeedbackCreateRequest,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db),
):
    """
    Create a new feedback entry for the authenticated host.
    
    - **content**: Feedback content (max 250 characters)
    
    Requires host Bearer token authentication.
    """
    db_feedback = Feedback(
        host_id=current_host.id,
        content=request.content.strip(),
    )

    db.add(db_feedback)
    db.commit()
    db.refresh(db_feedback)

    return db_feedback


@router.get("/host/feedback", response_model=FeedbackListResponse)
async def get_host_feedbacks(
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db),
):
    """
    Get all feedback entries submitted by the authenticated host.
    
    Requires host Bearer token authentication.
    """
    feedbacks = (
        db.query(Feedback)
        .filter(Feedback.host_id == current_host.id)
        .order_by(Feedback.created_at.desc())
        .all()
    )

    return FeedbackListResponse(feedbacks=feedbacks)


@router.get("/host/feedback/{feedback_id}", response_model=FeedbackResponse)
async def get_host_feedback(
    feedback_id: int,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db),
):
    """
    Get a specific feedback entry by ID for the authenticated host.
    """
    feedback = (
        db.query(Feedback)
        .filter(Feedback.id == feedback_id, Feedback.host_id == current_host.id)
        .first()
    )

    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found",
        )

    return feedback


@router.delete("/host/feedback/{feedback_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_host_feedback(
    feedback_id: int,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db),
):
    """
    Delete a feedback entry for the authenticated host.
    """
    feedback = (
        db.query(Feedback)
        .filter(Feedback.id == feedback_id, Feedback.host_id == current_host.id)
        .first()
    )

    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found",
        )

    db.delete(feedback)
    db.commit()

    return None


# ==================== CLIENT FEEDBACK ====================


@router.post(
    "/client/feedback",
    response_model=ClientFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_client_feedback(
    request: ClientFeedbackCreateRequest,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """
    Create a new feedback entry for the authenticated client.
    
    - **content**: Feedback content (max 250 characters)
    
    Requires client Bearer token authentication.
    """
    db_feedback = ClientFeedback(
        client_id=current_client.id,
        content=request.content.strip(),
    )

    db.add(db_feedback)
    db.commit()
    db.refresh(db_feedback)

    return db_feedback


@router.get(
    "/client/feedback",
    response_model=ClientFeedbackListResponse,
)
async def get_client_feedbacks(
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """
    Get all feedback entries submitted by the authenticated client.
    
    Requires client Bearer token authentication.
    """
    feedbacks = (
        db.query(ClientFeedback)
        .filter(ClientFeedback.client_id == current_client.id)
        .order_by(ClientFeedback.created_at.desc())
        .all()
    )

    return ClientFeedbackListResponse(feedbacks=feedbacks)


@router.get(
    "/client/feedback/{feedback_id}",
    response_model=ClientFeedbackResponse,
)
async def get_client_feedback(
    feedback_id: int,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """
    Get a specific feedback entry by ID for the authenticated client.
    """
    feedback = (
        db.query(ClientFeedback)
        .filter(
            ClientFeedback.id == feedback_id,
            ClientFeedback.client_id == current_client.id,
        )
        .first()
    )

    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found",
        )

    return feedback


@router.delete(
    "/client/feedback/{feedback_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_client_feedback(
    feedback_id: int,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """
    Delete a feedback entry for the authenticated client.
    """
    feedback = (
        db.query(ClientFeedback)
        .filter(
            ClientFeedback.id == feedback_id,
            ClientFeedback.client_id == current_client.id,
        )
        .first()
    )

    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found",
        )

    db.delete(feedback)
    db.commit()

    return None
