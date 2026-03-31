"""
Client-Host Messaging endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, or_, select
from datetime import datetime, timezone
from typing import Optional, List
from collections import defaultdict

from app.database import get_db
from app.models import ClientHostConversation, ClientHostMessage, Host, Client
from app.schemas import (
    ClientHostMessageRequest,
    ClientHostMessageResponse,
    ClientHostConversationResponse,
    ClientHostConversationListResponse
)
from app.auth import get_current_client, get_current_host

router = APIRouter()


def _message_to_response(db_message: ClientHostMessage, client: Client = None, host: Host = None) -> ClientHostMessageResponse:
    """Helper function to convert ClientHostMessage model to ClientHostMessageResponse"""
    sender_name = None
    sender_avatar_url = None
    
    if db_message.sender_type == "client" and client:
        sender_name = client.full_name
        sender_avatar_url = client.avatar_url
    elif db_message.sender_type == "host" and host:
        sender_name = host.full_name
        sender_avatar_url = host.avatar_url
    
    return ClientHostMessageResponse(
        id=db_message.id,
        conversation_id=db_message.conversation_id,
        sender_type=db_message.sender_type,
        sender_id=db_message.sender_id,
        sender_name=sender_name,
        sender_avatar_url=sender_avatar_url,
        message=db_message.message,
        is_read=db_message.is_read,
        created_at=db_message.created_at
    )


# ==================== CLIENT ENDPOINTS ====================

@router.post("/client/messages/host/{host_id}", response_model=ClientHostMessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message_to_host(
    host_id: int,
    request: ClientHostMessageRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db)
):
    """
    Send a message to a car host
    
    - **host_id**: ID of the host to message
    - **message**: Message content (1-2000 characters)
    
    Creates a conversation if it doesn't exist, or adds to existing conversation.
    Each client-host pair has one continuous conversation thread.
    """
    # Verify host exists
    host_stmt = select(Host).filter(Host.id == host_id)
    host_result = await db.execute(host_stmt)
    host = host_result.scalar_one_or_none()
    
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Host not found"
        )
    
    # Get or create conversation for this client-host pair
    conv_stmt = select(ClientHostConversation).filter(
        and_(
            ClientHostConversation.client_id == current_client.id,
            ClientHostConversation.host_id == host_id
        )
    )
    conv_result = await db.execute(conv_stmt)
    conversation = conv_result.scalar_one_or_none()
    
    if not conversation:
        # Create new conversation
        conversation = ClientHostConversation(
            client_id=current_client.id,
            host_id=host_id,
            is_read_by_client=True,  # Client just sent it, so they've read it
            is_read_by_host=False  # Host needs to read this
        )
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)
    
    # Create new message
    message = ClientHostMessage(
        conversation_id=conversation.id,
        sender_type="client",
        sender_id=current_client.id,
        message=request.message,
        is_read=False  # Host hasn't read it yet
    )
    
    db.add(message)
    
    # Update conversation
    conversation.is_read_by_host = False  # Host needs to read this
    conversation.is_read_by_client = True  # Client just sent it, so they've read it
    conversation.last_message_at = datetime.now(timezone.utc)
    conversation.updated_at = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(message)
    
    return _message_to_response(message, client=current_client, host=host)


@router.get("/client/messages/host/{host_id}", response_model=ClientHostConversationResponse)
async def get_conversation_with_host(
    host_id: int,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the conversation with a specific host
    
    Returns the conversation with all messages in chronological order.
    If no conversation exists, returns an empty conversation.
    """
    # Verify host exists
    host_stmt = select(Host).filter(Host.id == host_id)
    host_result = await db.execute(host_stmt)
    host = host_result.scalar_one_or_none()
    
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Host not found"
        )
    
    # Get conversation for this client-host pair
    conv_stmt = select(ClientHostConversation).filter(
        and_(
            ClientHostConversation.client_id == current_client.id,
            ClientHostConversation.host_id == host_id
        )
    )
    conv_result = await db.execute(conv_stmt)
    conversation = conv_result.scalar_one_or_none()
    
    if not conversation:
        # Return empty conversation
        return ClientHostConversationResponse(
            id=0,
            client_id=current_client.id,
            client_name=current_client.full_name,
            client_email=current_client.email,
            client_avatar_url=current_client.avatar_url,
            host_id=host_id,
            host_name=host.full_name,
            host_email=host.email,
            host_avatar_url=host.avatar_url,
            is_read_by_client=True,
            is_read_by_host=True,
            messages=[],
            created_at=datetime.now(timezone.utc),
            updated_at=None,
            last_message_at=None
        )
    
    # Get all messages in the conversation
    msg_stmt = select(ClientHostMessage).filter(
        ClientHostMessage.conversation_id == conversation.id
    ).order_by(ClientHostMessage.created_at.asc())
    msg_result = await db.execute(msg_stmt)
    messages = msg_result.scalars().all()
    
    # Mark host messages as read by client (since they're viewing the conversation)
    for msg in messages:
        if msg.sender_type == "host" and not msg.is_read:
            msg.is_read = True
    
    conversation.is_read_by_client = True
    await db.commit()
    
    # Build message responses
    message_list = []
    for msg in messages:
        message_list.append(_message_to_response(msg, client=current_client, host=host))
    
    return ClientHostConversationResponse(
        id=conversation.id,
        client_id=conversation.client_id,
        client_name=current_client.full_name,
        client_email=current_client.email,
        host_id=conversation.host_id,
        host_name=host.full_name,
        host_email=host.email,
        is_read_by_client=conversation.is_read_by_client,
        is_read_by_host=conversation.is_read_by_host,
        messages=message_list,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        last_message_at=conversation.last_message_at
    )


@router.get("/client/messages", response_model=ClientHostConversationListResponse)
async def get_client_conversations(
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all conversations for the authenticated client
    
    Returns a list of all conversations with hosts, ordered by last message time.
    """
    # Get all conversations for this client
    stmt = select(ClientHostConversation).filter(
        ClientHostConversation.client_id == current_client.id
    ).order_by(ClientHostConversation.last_message_at.desc())
    result = await db.execute(stmt)
    conversations = result.scalars().all()
    
    # Build conversation responses
    conversation_list = []
    unread_count = 0
    
    for conv in conversations:
        # Get host info
        host_stmt = select(Host).filter(Host.id == conv.host_id)
        host_result = await db.execute(host_stmt)
        host = host_result.scalar_one_or_none()
        
        # Get all messages
        msg_stmt = select(ClientHostMessage).filter(
            ClientHostMessage.conversation_id == conv.id
        ).order_by(ClientHostMessage.created_at.asc())
        msg_result = await db.execute(msg_stmt)
        messages = msg_result.scalars().all()
        
        # Build message responses
        message_list = []
        for msg in messages:
            message_list.append(_message_to_response(msg, client=current_client, host=host))
        
        # Count unread (messages from host that client hasn't read)
        if not conv.is_read_by_client:
            unread_count += 1
        
        conversation_list.append(ClientHostConversationResponse(
            id=conv.id,
            client_id=conv.client_id,
            client_name=current_client.full_name,
            client_email=current_client.email,
            client_avatar_url=current_client.avatar_url,
            host_id=conv.host_id,
            host_name=host.full_name if host else None,
            host_email=host.email if host else None,
            host_avatar_url=host.avatar_url if host else None,
            is_read_by_client=conv.is_read_by_client,
            is_read_by_host=conv.is_read_by_host,
            messages=message_list,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            last_message_at=conv.last_message_at
        ))
    
    return ClientHostConversationListResponse(
        conversations=conversation_list,
        total=len(conversation_list),
        unread_count=unread_count
    )


# ==================== HOST ENDPOINTS ====================

@router.post("/host/messages/client/{client_id}", response_model=ClientHostMessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message_to_client(
    client_id: int,
    request: ClientHostMessageRequest,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db)
):
    """
    Send a message to a client
    
    - **client_id**: ID of the client to message
    - **message**: Message content (1-2000 characters)
    
    Creates a conversation if it doesn't exist, or adds to existing conversation.
    """
    # Verify client exists
    client_stmt = select(Client).filter(Client.id == client_id)
    client_result = await db.execute(client_stmt)
    client = client_result.scalar_one_or_none()
    
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )
    
    # Get or create conversation for this client-host pair
    conv_stmt = select(ClientHostConversation).filter(
        and_(
            ClientHostConversation.client_id == client_id,
            ClientHostConversation.host_id == current_host.id
        )
    )
    conv_result = await db.execute(conv_stmt)
    conversation = conv_result.scalar_one_or_none()
    
    if not conversation:
        # Create new conversation
        conversation = ClientHostConversation(
            client_id=client_id,
            host_id=current_host.id,
            is_read_by_client=False,  # Client needs to read this
            is_read_by_host=True  # Host just sent it, so they've read it
        )
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)
    
    # Create new message
    message = ClientHostMessage(
        conversation_id=conversation.id,
        sender_type="host",
        sender_id=current_host.id,
        message=request.message,
        is_read=False  # Client hasn't read it yet
    )
    
    db.add(message)
    
    # Update conversation
    conversation.is_read_by_client = False  # Client needs to read this
    conversation.is_read_by_host = True  # Host just sent it, so they've read it
    conversation.last_message_at = datetime.now(timezone.utc)
    conversation.updated_at = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(message)
    
    return _message_to_response(message, client=client, host=current_host)


@router.get("/host/messages/client/{client_id}", response_model=ClientHostConversationResponse)
async def get_conversation_with_client(
    client_id: int,
    skip: int = Query(0, ge=0, description="Number of messages to skip (oldest-first pagination)"),
    limit: int = Query(50, ge=1, le=200, description="Maximum messages to return"),
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the conversation with a specific client
    
    Returns the conversation messages in chronological order.
    If no conversation exists, returns an empty conversation.
    """
    # Verify client exists
    client_stmt = select(Client).filter(Client.id == client_id)
    client_result = await db.execute(client_stmt)
    client = client_result.scalar_one_or_none()
    
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )
    
    # Get conversation for this client-host pair
    conv_stmt = select(ClientHostConversation).filter(
        and_(
            ClientHostConversation.client_id == client_id,
            ClientHostConversation.host_id == current_host.id
        )
    )
    conv_result = await db.execute(conv_stmt)
    conversation = conv_result.scalar_one_or_none()
    
    if not conversation:
        # Return empty conversation
        return ClientHostConversationResponse(
            id=0,
            client_id=client_id,
            client_name=client.full_name,
            client_email=client.email,
            client_avatar_url=client.avatar_url,
            host_id=current_host.id,
            host_name=current_host.full_name,
            host_email=current_host.email,
            host_avatar_url=current_host.avatar_url,
            is_read_by_client=True,
            is_read_by_host=True,
            messages=[],
            created_at=datetime.now(timezone.utc),
            updated_at=None,
            last_message_at=None
        )
    
    # Get paginated messages in the conversation
    msg_stmt = select(ClientHostMessage).filter(
        ClientHostMessage.conversation_id == conversation.id
    ).order_by(ClientHostMessage.created_at.asc()).offset(skip).limit(limit)
    msg_result = await db.execute(msg_stmt)
    messages = msg_result.scalars().all()
    
    # Mark client messages as read by host (since they're viewing the conversation)
    for msg in messages:
        if msg.sender_type == "client" and not msg.is_read:
            msg.is_read = True
    
    conversation.is_read_by_host = True
    await db.commit()
    
    # Build message responses
    message_list = []
    for msg in messages:
        message_list.append(_message_to_response(msg, client=client, host=current_host))
    
    return ClientHostConversationResponse(
        id=conversation.id,
        client_id=conversation.client_id,
        client_name=client.full_name,
        client_email=client.email,
        host_id=conversation.host_id,
        host_name=current_host.full_name,
        host_email=current_host.email,
        is_read_by_client=conversation.is_read_by_client,
        is_read_by_host=conversation.is_read_by_host,
        messages=message_list,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        last_message_at=conversation.last_message_at
    )


@router.get("/host/messages", response_model=ClientHostConversationListResponse)
async def get_host_conversations(
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all conversations for the authenticated host
    
    Returns a list of all conversations with clients, ordered by last message time.
    """
    # Get all conversations for this host
    stmt = select(ClientHostConversation).filter(
        ClientHostConversation.host_id == current_host.id
    ).order_by(ClientHostConversation.last_message_at.desc())
    result = await db.execute(stmt)
    conversations = result.scalars().all()
    
    # Bulk-load related clients and messages to avoid N+1 query overhead.
    conversation_ids = [conv.id for conv in conversations]
    client_ids = list({conv.client_id for conv in conversations})

    clients_by_id = {}
    if client_ids:
        clients_result = await db.execute(select(Client).filter(Client.id.in_(client_ids)))
        clients = clients_result.scalars().all()
        clients_by_id = {client.id: client for client in clients}

    messages_by_conversation_id = defaultdict(list)
    if conversation_ids:
        messages_result = await db.execute(
            select(ClientHostMessage)
            .filter(ClientHostMessage.conversation_id.in_(conversation_ids))
            .order_by(ClientHostMessage.created_at.asc())
        )
        all_messages = messages_result.scalars().all()
        for msg in all_messages:
            messages_by_conversation_id[msg.conversation_id].append(msg)

    # Build conversation responses
    conversation_list = []
    unread_count = 0
    
    for conv in conversations:
        client = clients_by_id.get(conv.client_id)
        messages = messages_by_conversation_id.get(conv.id, [])
        
        # Build message responses
        message_list = []
        for msg in messages:
            message_list.append(_message_to_response(msg, client=client, host=current_host))
        
        # Count unread (messages from client that host hasn't read)
        if not conv.is_read_by_host:
            unread_count += 1
        
        conversation_list.append(ClientHostConversationResponse(
            id=conv.id,
            client_id=conv.client_id,
            client_name=client.full_name if client else None,
            client_email=client.email if client else None,
            client_avatar_url=client.avatar_url if client else None,
            host_id=conv.host_id,
            host_name=current_host.full_name,
            host_email=current_host.email,
            host_avatar_url=current_host.avatar_url,
            is_read_by_client=conv.is_read_by_client,
            is_read_by_host=conv.is_read_by_host,
            messages=message_list,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            last_message_at=conv.last_message_at
        ))
    
    return ClientHostConversationListResponse(
        conversations=conversation_list,
        total=len(conversation_list),
        unread_count=unread_count
    )
