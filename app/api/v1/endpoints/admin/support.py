from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_admin
from app.db.session import get_db
from app.models import Admin, Host, SupportConversation, SupportMessage
from app.schemas import (
    AdminResponseRequest,
    SupportConversationListResponse,
    SupportConversationResponse,
    SupportMessageResponse,
)

router = APIRouter()


def _message_to_response(
    db_message: SupportMessage, host: Host = None, admin: Admin = None
) -> SupportMessageResponse:
    """Helper function to convert SupportMessage model to SupportMessageResponse"""
    sender_name = None
    if db_message.sender_type == "host" and host:
        sender_name = host.full_name
    elif db_message.sender_type == "admin" and admin:
        sender_name = admin.full_name

    return SupportMessageResponse(
        id=db_message.id,
        conversation_id=db_message.conversation_id,
        sender_type=db_message.sender_type,
        sender_id=db_message.sender_id,
        sender_name=sender_name,
        message=db_message.message,
        is_read=db_message.is_read,
        created_at=db_message.created_at,
    )


def calculate_pagination(page: int, limit: int, total: int) -> dict:
    """Calculate pagination metadata"""
    total_pages = (total + limit - 1) // limit if limit > 0 else 0
    return {"total": total, "page": page, "limit": limit, "total_pages": total_pages}


@router.get(
    "/admin/support/conversations", response_model=SupportConversationListResponse
)
async def list_support_conversations(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    host_id: Optional[int] = Query(None, description="Filter by host ID"),
    status_filter: Optional[str] = Query(
        None, description="Filter by status (open, closed)"
    ),
    search: Optional[str] = Query(None, description="Search by host name or email"),
    sort_by: Optional[str] = Query(
        "last_message_at", description="Sort field (id, created_at, last_message_at)"
    ),
    order: Optional[str] = Query(
        "desc", regex="^(asc|desc)$", description="Sort order"
    ),
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    List all support conversations with filters and pagination

    - **page**: Page number (starts from 1)
    - **limit**: Number of items per page (1-100)
    - **host_id**: Filter by host ID
    - **status_filter**: Filter by status (open, closed)
    - **search**: Search by host name or email
    - **sort_by**: Field to sort by
    - **order**: Sort order (asc or desc)
    """
    # Build base statement
    stmt = select(SupportConversation).options(joinedload(SupportConversation.host))

    # Apply filters
    if host_id:
        stmt = stmt.filter(SupportConversation.host_id == host_id)

    if status_filter:
        stmt = stmt.filter(SupportConversation.status == status_filter)

    if search:
        search_filter = or_(
            Host.full_name.ilike(f"%{search}%"), Host.email.ilike(f"%{search}%")
        )
        stmt = stmt.join(Host).filter(search_filter)

    # Get total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # Get unread count
    unread_stmt = select(func.count(SupportConversation.id)).filter(
        SupportConversation.is_read_by_admin == False
    )
    unread_result = await db.execute(unread_stmt)
    unread_count = unread_result.scalar() or 0

    # Apply sorting
    sort_field = getattr(
        SupportConversation, sort_by, SupportConversation.last_message_at
    )
    if order == "asc":
        stmt = stmt.order_by(sort_field.asc())
    else:
        stmt = stmt.order_by(sort_field.desc())

    # Apply pagination
    skip = (page - 1) * limit
    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    conversations = result.scalars().unique().all()

    # Build response with messages
    conversation_list = []
    for conv in conversations:
        # Get all messages for this conversation
        msg_stmt = (
            select(SupportMessage)
            .filter(SupportMessage.conversation_id == conv.id)
            .order_by(SupportMessage.created_at.asc())
        )
        msg_result = await db.execute(msg_stmt)
        messages = msg_result.scalars().all()

        # Build message responses
        message_list = []
        for msg in messages:
            admin = None
            if msg.sender_type == "admin":
                admin_stmt = select(Admin).filter(Admin.id == msg.sender_id)
                admin_result = await db.execute(admin_stmt)
                admin = admin_result.scalar_one_or_none()

            message_list.append(_message_to_response(msg, host=conv.host, admin=admin))

        conversation_list.append(
            SupportConversationResponse(
                id=conv.id,
                host_id=conv.host_id,
                host_name=conv.host.full_name if conv.host else None,
                host_email=conv.host.email if conv.host else None,
                status=conv.status,
                is_read_by_host=conv.is_read_by_host,
                is_read_by_admin=conv.is_read_by_admin,
                messages=message_list,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
                last_message_at=conv.last_message_at,
            )
        )

    pagination = calculate_pagination(page, limit, total)

    return SupportConversationListResponse(
        conversations=conversation_list, unread_count=unread_count, **pagination
    )


@router.get(
    "/admin/support/conversations/{conversation_id}",
    response_model=SupportConversationResponse,
)
async def get_support_conversation_details(
    conversation_id: int,
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Get detailed information about a specific support conversation

    Includes all messages in chronological order.
    Marks the conversation as read by admin.
    """
    stmt = (
        select(SupportConversation)
        .options(joinedload(SupportConversation.host))
        .filter(SupportConversation.id == conversation_id)
    )
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Support conversation not found",
        )

    # Get all messages in the conversation
    msg_stmt = (
        select(SupportMessage)
        .filter(SupportMessage.conversation_id == conversation.id)
        .order_by(SupportMessage.created_at.asc())
    )
    msg_result = await db.execute(msg_stmt)
    messages = msg_result.scalars().all()

    # Mark host messages as read by admin (since they're viewing the conversation)
    for msg in messages:
        if msg.sender_type == "host" and not msg.is_read:
            msg.is_read = True

    # Mark conversation as read by admin
    conversation.is_read_by_admin = True
    await db.commit()

    # Build message responses
    message_list = []
    for msg in messages:
        admin = None
        if msg.sender_type == "admin":
            admin_stmt = select(Admin).filter(Admin.id == msg.sender_id)
            admin_result = await db.execute(admin_stmt)
            admin = admin_result.scalar_one_or_none()

        message_list.append(
            _message_to_response(msg, host=conversation.host, admin=admin)
        )

    return SupportConversationResponse(
        id=conversation.id,
        host_id=conversation.host_id,
        host_name=conversation.host.full_name if conversation.host else None,
        host_email=conversation.host.email if conversation.host else None,
        status=conversation.status,
        is_read_by_host=conversation.is_read_by_host,
        is_read_by_admin=conversation.is_read_by_admin,
        messages=message_list,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        last_message_at=conversation.last_message_at,
    )


@router.post(
    "/admin/support/conversations/{conversation_id}/respond",
    response_model=SupportMessageResponse,
)
async def respond_to_support_conversation(
    conversation_id: int,
    request: AdminResponseRequest,
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Respond to a support conversation

    - **message**: Admin response message (1-2000 characters)

    Admins can respond to support conversations. The response will be visible to the host.
    """
    stmt = select(SupportConversation).filter(SupportConversation.id == conversation_id)
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Support conversation not found",
        )

    if conversation.status == "closed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot respond to a closed conversation",
        )

    # Create new message
    support_message = SupportMessage(
        conversation_id=conversation.id,
        sender_type="admin",
        sender_id=current_admin.id,
        message=request.message,
        is_read=False,  # Host hasn't read it yet
    )

    db.add(support_message)

    # Update conversation
    conversation.is_read_by_host = False  # Host needs to read the response
    conversation.is_read_by_admin = True  # Admin just sent it
    conversation.last_message_at = datetime.now(timezone.utc)
    conversation.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(support_message)

    return _message_to_response(
        support_message, host=conversation.host, admin=current_admin
    )


@router.put("/admin/support/conversations/{conversation_id}/close")
async def close_support_conversation(
    conversation_id: int,
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Close a support conversation

    Marks a support conversation as closed. Closed conversations cannot receive new messages.
    """
    stmt = select(SupportConversation).filter(SupportConversation.id == conversation_id)
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Support conversation not found",
        )

    if conversation.status == "closed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Support conversation is already closed",
        )

    conversation.status = "closed"
    conversation.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return {"message": "Support conversation closed successfully"}


@router.put("/admin/support/conversations/{conversation_id}/reopen")
async def reopen_support_conversation(
    conversation_id: int,
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Reopen a closed support conversation

    Allows admins to reopen closed support conversations if needed.
    """
    stmt = select(SupportConversation).filter(SupportConversation.id == conversation_id)
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Support conversation not found",
        )

    if conversation.status != "closed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Support conversation is not closed",
        )

    conversation.status = "open"
    conversation.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return {"message": "Support conversation reopened successfully"}
