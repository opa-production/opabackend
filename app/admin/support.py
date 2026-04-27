from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_, func, select
from datetime import datetime, timezone

from app.database import get_db
from app.models import SupportConversation, SupportMessage, Host, Client, Admin
from app.schemas import (
    SupportConversationResponse,
    SupportMessageResponse,
    SupportConversationListResponse,
    AdminResponseRequest
)
from app.auth import get_current_admin

router = APIRouter()


def _message_to_response(
    db_message: SupportMessage,
    host: Host = None,
    client: Client = None,
    admin: Admin = None,
) -> SupportMessageResponse:
    sender_name = None
    if db_message.sender_type == "host" and host:
        sender_name = host.full_name
    elif db_message.sender_type == "client" and client:
        sender_name = client.full_name
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
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages
    }


@router.get("/admin/support/conversations", response_model=SupportConversationListResponse)
async def list_support_conversations(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    host_id: Optional[int] = Query(None, description="Filter by host ID"),
    client_id: Optional[int] = Query(None, description="Filter by client ID"),
    status_filter: Optional[str] = Query(None, description="Filter by status (open, closed)"),
    search: Optional[str] = Query(None, description="Search by host or client name/email"),
    sort_by: Optional[str] = Query("last_message_at", description="Sort field (id, created_at, last_message_at)"),
    order: Optional[str] = Query("desc", regex="^(asc|desc)$", description="Sort order"),
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
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
    stmt = select(SupportConversation).options(
        joinedload(SupportConversation.host),
        joinedload(SupportConversation.client),
    )

    if host_id:
        stmt = stmt.filter(SupportConversation.host_id == host_id)

    if client_id:
        stmt = stmt.filter(SupportConversation.client_id == client_id)

    if status_filter:
        stmt = stmt.filter(SupportConversation.status == status_filter)

    if search:
        search_filter = or_(
            Host.full_name.ilike(f"%{search}%"),
            Host.email.ilike(f"%{search}%"),
            Client.full_name.ilike(f"%{search}%"),
            Client.email.ilike(f"%{search}%"),
        )
        stmt = (
            stmt
            .outerjoin(Host, SupportConversation.host_id == Host.id)
            .outerjoin(Client, SupportConversation.client_id == Client.id)
            .filter(search_filter)
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    unread_stmt = select(func.count(SupportConversation.id)).filter(
        SupportConversation.is_read_by_admin == False
    )
    unread_result = await db.execute(unread_stmt)
    unread_count = unread_result.scalar() or 0

    sort_field = getattr(SupportConversation, sort_by, SupportConversation.last_message_at)
    if order == "asc":
        stmt = stmt.order_by(sort_field.asc())
    else:
        stmt = stmt.order_by(sort_field.desc())

    skip = (page - 1) * limit
    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    conversations = result.scalars().unique().all()

    conversation_list = []
    for conv in conversations:
        msg_stmt = select(SupportMessage).filter(
            SupportMessage.conversation_id == conv.id
        ).order_by(SupportMessage.created_at.asc())
        msg_result = await db.execute(msg_stmt)
        messages = msg_result.scalars().all()

        message_list = []
        for msg in messages:
            admin = None
            if msg.sender_type == "admin":
                admin_stmt = select(Admin).filter(Admin.id == msg.sender_id)
                admin_result = await db.execute(admin_stmt)
                admin = admin_result.scalar_one_or_none()

            message_list.append(
                _message_to_response(msg, host=conv.host, client=conv.client, admin=admin)
            )

        conversation_list.append(SupportConversationResponse(
            id=conv.id,
            host_id=conv.host_id,
            host_name=conv.host.full_name if conv.host else None,
            host_email=conv.host.email if conv.host else None,
            client_id=conv.client_id,
            client_name=conv.client.full_name if conv.client else None,
            client_email=conv.client.email if conv.client else None,
            status=conv.status,
            is_read_by_host=conv.is_read_by_host,
            is_read_by_admin=conv.is_read_by_admin,
            messages=message_list,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            last_message_at=conv.last_message_at,
        ))
    
    pagination = calculate_pagination(page, limit, total)
    
    return SupportConversationListResponse(
        conversations=conversation_list,
        unread_count=unread_count,
        **pagination
    )


@router.get("/admin/support/conversations/{conversation_id}", response_model=SupportConversationResponse)
async def get_support_conversation_details(
    conversation_id: int,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed information about a specific support conversation
    
    Includes all messages in chronological order.
    Marks the conversation as read by admin.
    """
    stmt = select(SupportConversation).options(
        joinedload(SupportConversation.host),
        joinedload(SupportConversation.client),
    ).filter(SupportConversation.id == conversation_id)
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Support conversation not found",
        )

    msg_stmt = select(SupportMessage).filter(
        SupportMessage.conversation_id == conversation.id
    ).order_by(SupportMessage.created_at.asc())
    msg_result = await db.execute(msg_stmt)
    messages = msg_result.scalars().all()

    for msg in messages:
        if msg.sender_type in ("host", "client") and not msg.is_read:
            msg.is_read = True

    conversation.is_read_by_admin = True
    await db.commit()

    message_list = []
    for msg in messages:
        admin = None
        if msg.sender_type == "admin":
            admin_stmt = select(Admin).filter(Admin.id == msg.sender_id)
            admin_result = await db.execute(admin_stmt)
            admin = admin_result.scalar_one_or_none()

        message_list.append(
            _message_to_response(msg, host=conversation.host, client=conversation.client, admin=admin)
        )

    return SupportConversationResponse(
        id=conversation.id,
        host_id=conversation.host_id,
        host_name=conversation.host.full_name if conversation.host else None,
        host_email=conversation.host.email if conversation.host else None,
        client_id=conversation.client_id,
        client_name=conversation.client.full_name if conversation.client else None,
        client_email=conversation.client.email if conversation.client else None,
        status=conversation.status,
        is_read_by_host=conversation.is_read_by_host,
        is_read_by_admin=conversation.is_read_by_admin,
        messages=message_list,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        last_message_at=conversation.last_message_at,
    )


@router.post("/admin/support/conversations/{conversation_id}/respond", response_model=SupportMessageResponse)
async def respond_to_support_conversation(
    conversation_id: int,
    request: AdminResponseRequest,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Respond to a support conversation
    
    - **message**: Admin response message (1-2000 characters)
    
    Admins can respond to support conversations. The response will be visible to the host.
    """
    stmt = select(SupportConversation).options(
        joinedload(SupportConversation.host),
        joinedload(SupportConversation.client),
    ).filter(SupportConversation.id == conversation_id)
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

    support_message = SupportMessage(
        conversation_id=conversation.id,
        sender_type="admin",
        sender_id=current_admin.id,
        message=request.message,
        is_read=False,
    )
    db.add(support_message)

    conversation.is_read_by_host = False
    conversation.is_read_by_admin = True
    conversation.last_message_at = datetime.now(timezone.utc)
    conversation.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(support_message)

    return _message_to_response(
        support_message, host=conversation.host, client=conversation.client, admin=current_admin
    )


@router.put("/admin/support/conversations/{conversation_id}/close")
async def close_support_conversation(
    conversation_id: int,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Close a support conversation
    
    Marks a support conversation as closed. Closed conversations cannot receive new messages.
    """
    stmt = select(SupportConversation).filter(
        SupportConversation.id == conversation_id
    )
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()
    
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Support conversation not found"
        )
    
    if conversation.status == "closed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Support conversation is already closed"
        )
    
    conversation.status = "closed"
    conversation.updated_at = datetime.now(timezone.utc)
    await db.commit()
    
    return {"message": "Support conversation closed successfully"}


@router.put("/admin/support/conversations/{conversation_id}/reopen")
async def reopen_support_conversation(
    conversation_id: int,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Reopen a closed support conversation
    
    Allows admins to reopen closed support conversations if needed.
    """
    stmt = select(SupportConversation).filter(
        SupportConversation.id == conversation_id
    )
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()
    
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Support conversation not found"
        )
    
    if conversation.status != "closed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Support conversation is not closed"
        )
    
    conversation.status = "open"
    conversation.updated_at = datetime.now(timezone.utc)
    await db.commit()
    
    return {"message": "Support conversation reopened successfully"}
