from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from app.database import get_db
from app.models import SupportConversation, SupportMessage, Host
from app.schemas import (
    SupportMessageRequest,
    SupportConversationResponse,
    SupportMessageResponse
)
from app.auth import get_current_host

router = APIRouter()


def _message_to_response(db_message: SupportMessage, host: Host = None, admin_name: str = None) -> SupportMessageResponse:
    """Helper function to convert SupportMessage model to SupportMessageResponse"""
    sender_name = None
    if db_message.sender_type == "host" and host:
        sender_name = host.full_name
    elif db_message.sender_type == "admin" and admin_name:
        sender_name = admin_name
    
    return SupportMessageResponse(
        id=db_message.id,
        conversation_id=db_message.conversation_id,
        sender_type=db_message.sender_type,
        sender_id=db_message.sender_id,
        sender_name=sender_name,
        message=db_message.message,
        is_read=db_message.is_read,
        created_at=db_message.created_at
    )


@router.post("/host/support/messages", response_model=SupportMessageResponse, status_code=status.HTTP_201_CREATED)
async def send_support_message(
    request: SupportMessageRequest,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db)
):
    """
    Send a message in the support conversation
    
    - **message**: Message content (1-2000 characters)
    
    Creates a conversation if it doesn't exist, or adds to existing conversation.
    Each host has only one continuous conversation thread.
    """
    # Get or create conversation for this host
    stmt = select(SupportConversation).filter(
        SupportConversation.host_id == current_host.id
    )
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()
    
    if not conversation:
        # Create new conversation
        conversation = SupportConversation(
            host_id=current_host.id,
            status="open",
            is_read_by_host=False,
            is_read_by_admin=False
        )
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)
    
    # Check if conversation is closed
    if conversation.status == "closed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot send messages to a closed conversation. Please contact support to reopen."
        )
    
    # Create new message
    support_message = SupportMessage(
        conversation_id=conversation.id,
        sender_type="host",
        sender_id=current_host.id,
        message=request.message,
        is_read=False  # Admin hasn't read it yet
    )
    
    db.add(support_message)
    
    # Update conversation
    conversation.is_read_by_admin = False  # Admin needs to read this
    conversation.is_read_by_host = True  # Host just sent it, so they've read it
    conversation.last_message_at = datetime.now(timezone.utc)
    conversation.updated_at = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(support_message)
    
    return _message_to_response(support_message, host=current_host)


@router.get("/host/support/conversation", response_model=SupportConversationResponse)
async def get_support_conversation(
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the support conversation for the authenticated host
    
    Returns the conversation with all messages in chronological order.
    If no conversation exists, returns an empty conversation.
    """
    # Get conversation for this host
    stmt = select(SupportConversation).filter(
        SupportConversation.host_id == current_host.id
    )
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()
    
    if not conversation:
        # Return empty conversation
        return SupportConversationResponse(
            id=0,
            host_id=current_host.id,
            host_name=current_host.full_name,
            host_email=current_host.email,
            status="open",
            is_read_by_host=True,
            is_read_by_admin=True,
            messages=[],
            created_at=datetime.now(timezone.utc),
            updated_at=None,
            last_message_at=None
        )
    
    # Get all messages in the conversation
    msg_stmt = select(SupportMessage).filter(
        SupportMessage.conversation_id == conversation.id
    ).order_by(SupportMessage.created_at.asc())
    msg_result = await db.execute(msg_stmt)
    messages = msg_result.scalars().all()
    
    # Mark admin messages as read by host (since they're viewing the conversation)
    for msg in messages:
        if msg.sender_type == "admin" and not msg.is_read:
            msg.is_read = True
    
    conversation.is_read_by_host = True
    await db.commit()
    
    # Build message responses
    message_list = []
    for msg in messages:
        admin_name = None
        if msg.sender_type == "admin":
            # Get admin name if available
            from app.models import Admin
            admin_stmt = select(Admin).filter(Admin.id == msg.sender_id)
            admin_result = await db.execute(admin_stmt)
            admin = admin_result.scalar_one_or_none()
            admin_name = admin.full_name if admin else None
        
        message_list.append(_message_to_response(msg, host=current_host, admin_name=admin_name))
    
    return SupportConversationResponse(
        id=conversation.id,
        host_id=conversation.host_id,
        host_name=current_host.full_name,
        host_email=current_host.email,
        status=conversation.status,
        is_read_by_host=conversation.is_read_by_host,
        is_read_by_admin=conversation.is_read_by_admin,
        messages=message_list,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        last_message_at=conversation.last_message_at
    )
