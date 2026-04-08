from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.config import settings
from app.db.session import get_db
from app.models import Client, Host, Notification
from app.schemas import (
    AdminMultiChannelBroadcastToClientsRequest,
    BroadcastNotificationRequest,
    NotificationResponse,
    UserNotificationRequest,
)
from app.services.email_welcome import send_email

router = APIRouter()

# Default sender name for admin notifications
ADMIN_SENDER_NAME = "[Deon,CEO ardena]"


@router.post(
    "/admin/notifications/broadcast-hosts", response_model=NotificationResponse
)
async def broadcast_notification_to_hosts(
    request: BroadcastNotificationRequest,
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Send notification to all active hosts

    - **title**: Notification title
    - **message**: Notification message
    - **type**: Notification type (info, warning, success, error)

    Note: This is a placeholder implementation. In production, you would:
    - Store notifications in a database
    - Send push notifications via FCM/APNS
    - Send email notifications
    - Integrate with a notification service
    """
    try:
        # Get all active hosts
        stmt = select(Host).filter(Host.is_active == True)
        result = await db.execute(stmt)
        active_hosts = result.scalars().all()

        if not active_hosts:
            return NotificationResponse(
                message="No active hosts found. Notification not sent.", sent_count=0
            )

        sent_count = 0

        # Create notifications for each host
        for host in active_hosts:
            try:
                notification = Notification(
                    recipient_type="host",
                    recipient_id=host.id,
                    title=request.title,
                    message=request.message,
                    notification_type=request.type or "info",
                    sender_name=ADMIN_SENDER_NAME,
                )
                db.add(notification)
                sent_count += 1
            except Exception as e:
                # Log error but continue with other hosts
                print(f"Error creating notification for host {host.id}: {e}")
                continue

        # Commit all notifications
        await db.commit()

        return NotificationResponse(
            message=f"Notification sent to {sent_count} active host(s)",
            sent_count=sent_count,
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error sending notifications: {str(e)}",
        )


@router.post(
    "/admin/notifications/broadcast-clients", response_model=NotificationResponse
)
async def broadcast_notification_to_clients(
    request: BroadcastNotificationRequest,
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Send notification to all active clients

    - **title**: Notification title
    - **message**: Notification message
    - **type**: Notification type (info, warning, success, error)

    Note: This is a placeholder implementation. In production, you would:
    - Store notifications in a database
    - Send push notifications via FCM/APNS
    - Send email notifications
    - Integrate with a notification service
    """
    try:
        # Get all active clients
        stmt = select(Client).filter(Client.is_active == True)
        result = await db.execute(stmt)
        active_clients = result.scalars().all()

        if not active_clients:
            return NotificationResponse(
                message="No active clients found. Notification not sent.", sent_count=0
            )

        sent_count = 0

        # Create notifications for each client
        for client in active_clients:
            try:
                notification = Notification(
                    recipient_type="client",
                    recipient_id=client.id,
                    title=request.title,
                    message=request.message,
                    notification_type=request.type or "info",
                    sender_name=ADMIN_SENDER_NAME,
                )
                db.add(notification)
                sent_count += 1
            except Exception as e:
                # Log error but continue with other clients
                print(f"Error creating notification for client {client.id}: {e}")
                continue

        # Commit all notifications
        await db.commit()

        return NotificationResponse(
            message=f"Notification sent to {sent_count} active client(s)",
            sent_count=sent_count,
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error sending notifications: {str(e)}",
        )


@router.post("/admin/notifications/send", response_model=NotificationResponse)
async def send_notification_to_user(
    request: UserNotificationRequest,
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Send notification to a specific user (host or client)

    - **user_type**: User type (host or client)
    - **user_id**: User ID
    - **title**: Notification title
    - **message**: Notification message
    - **type**: Notification type (info, warning, success, error)

    Note: This is a placeholder implementation. In production, you would:
    - Store notification in a database
    - Send push notifications via FCM/APNS
    - Send email notifications
    - Integrate with a notification service
    """
    try:
        user = None

        if request.user_type == "host":
            stmt = select(Host).filter(Host.id == request.user_id)
            result = await db.execute(stmt)
            user = result.scalar_one_or_none()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Host not found"
                )
            if not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Host account is inactive",
                )
        elif request.user_type == "client":
            stmt = select(Client).filter(Client.id == request.user_id)
            result = await db.execute(stmt)
            user = result.scalar_one_or_none()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
                )
            if not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Client account is inactive",
                )

        # Create notification
        notification = Notification(
            recipient_type=request.user_type,
            recipient_id=request.user_id,
            title=request.title,
            message=request.message,
            notification_type=request.type or "info",
            sender_name=ADMIN_SENDER_NAME,
        )

        db.add(notification)
        await db.commit()

        return NotificationResponse(
            message=f"Notification sent successfully",
            sent_count=1,
            user_id=request.user_id,
            user_type=request.user_type,
        )
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error sending notification: {str(e)}",
        )


@router.post(
    "/admin/notifications/broadcast-clients-preferences",
    response_model=NotificationResponse,
)
async def broadcast_to_clients_respecting_preferences(
    request: AdminMultiChannelBroadcastToClientsRequest,
    background_tasks: BackgroundTasks,
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Broadcast a message to all active clients, sending it only through the
    channels they have enabled in their notification preferences.

    - In-app notification is created when `in_app_notifications_enabled` is true.
    - Email is sent when `email_notifications_enabled` is true and email service is configured.
    """
    try:
        # Fetch all active clients who have at least one of the channels enabled
        stmt = select(Client).filter(
            Client.is_active == True,
            or_(
                Client.email_notifications_enabled == True,
                Client.in_app_notifications_enabled == True,
            ),
        )
        result = await db.execute(stmt)
        clients = result.scalars().all()

        if not clients:
            return NotificationResponse(
                message="No active clients with notifications enabled were found.",
                sent_count=0,
            )

        notif_type = request.type or "info"
        sent_in_app = 0
        scheduled_emails = 0

        # Prepare email template pieces
        email_subject = request.email_subject or request.title

        for client in clients:
            # In‑app notification
            if getattr(client, "in_app_notifications_enabled", True):
                try:
                    notification = Notification(
                        recipient_type="client",
                        recipient_id=client.id,
                        title=request.title,
                        message=request.message,
                        notification_type=notif_type,
                        sender_name=ADMIN_SENDER_NAME,
                    )
                    db.add(notification)
                    sent_in_app += 1
                except Exception as e:
                    print(
                        f"Error creating in-app notification for client {client.id}: {e}"
                    )

            # Email notification
            if (
                getattr(client, "email_notifications_enabled", True)
                and settings.SENDGRID_API_KEY
            ):
                try:
                    if request.email_body_html:
                        body_html = request.email_body_html
                    else:
                        # Simple default HTML wrapper around the plain-text message
                        body_html = f"""
                        <div style="font-family: sans-serif; max-width: 560px; margin: 0 auto;">
                          <p>{request.message}</p>
                          <p style="margin-top: 24px;">— The Ardena Group Team</p>
                        </div>
                        """
                    background_tasks.add_task(
                        send_email,
                        client.email,
                        email_subject,
                        body_html,
                    )
                    scheduled_emails += 1
                except Exception as e:
                    print(f"Error scheduling email for client {client.id}: {e}")

        # Persist in‑app notifications
        await db.commit()

        total_channels = sent_in_app + scheduled_emails
        return NotificationResponse(
            message=(
                f"Broadcast queued to {len(clients)} client(s) "
                f"({sent_in_app} in-app, {scheduled_emails} email)."
            ),
            sent_count=total_channels,
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error broadcasting notifications: {str(e)}",
        )
