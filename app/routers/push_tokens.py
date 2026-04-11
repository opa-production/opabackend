"""
Expo push token registration endpoints for clients and hosts.

The React Native / Expo app calls POST /client/push-token (or /host/push-token)
right after login (or whenever Expo gives a new token). On logout it calls DELETE
to unregister.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.auth import get_current_client, get_current_host
from app.database import get_db
from app.models import Client, Host, ClientPushToken, HostPushToken

router = APIRouter()


class RegisterPushTokenRequest(BaseModel):
    token: str = Field(..., description="Expo push token, e.g. ExponentPushToken[xxx]")
    platform: Optional[str] = Field(None, description="'ios' or 'android'")


class PushTokenResponse(BaseModel):
    message: str


@router.post(
    "/client/push-token",
    response_model=PushTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Register Expo push token",
    tags=["Push Notifications"],
)
async def register_push_token(
    request: RegisterPushTokenRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Register (or refresh) an Expo push token for the current client.

    Call this on every app launch after requesting notification permission.
    If the token already exists for this client it is a no-op (idempotent).
    If the same token was previously registered to a different client (e.g. after
    re-install and new login), it is reassigned to the current client.
    """
    token = request.token.strip()

    if not token.startswith("ExponentPushToken"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Expo push token format. Must start with 'ExponentPushToken'.",
        )

    # Check if token already exists
    result = await db.execute(
        select(ClientPushToken).filter(ClientPushToken.token == token)
    )
    existing = result.scalar_one_or_none()

    if existing:
        if existing.client_id == current_client.id:
            # Already registered for this client — update platform if provided
            if request.platform:
                existing.platform = request.platform
                await db.commit()
            return PushTokenResponse(message="Push token already registered.")
        else:
            # Token belongs to a different client (device reuse / re-install)
            existing.client_id = current_client.id
            existing.platform = request.platform
            await db.commit()
            return PushTokenResponse(message="Push token updated.")

    # New token — insert
    push_token = ClientPushToken(
        client_id=current_client.id,
        token=token,
        platform=request.platform,
    )
    db.add(push_token)
    await db.commit()
    return PushTokenResponse(message="Push token registered successfully.")


@router.delete(
    "/client/push-token",
    response_model=PushTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Unregister Expo push token",
    tags=["Push Notifications"],
)
async def unregister_push_token(
    request: RegisterPushTokenRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Unregister an Expo push token (call on logout or notification opt-out).
    """
    token = request.token.strip()

    result = await db.execute(
        select(ClientPushToken).filter(
            ClientPushToken.token == token,
            ClientPushToken.client_id == current_client.id,
        )
    )
    existing = result.scalar_one_or_none()

    if not existing:
        return PushTokenResponse(message="Token not found — nothing to remove.")

    await db.delete(existing)
    await db.commit()
    return PushTokenResponse(message="Push token unregistered.")


# ── Host push token endpoints ─────────────────────────────────────────────────

@router.post(
    "/host/push-token",
    response_model=PushTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Register Expo push token (host)",
    tags=["Push Notifications"],
)
async def register_host_push_token(
    request: RegisterPushTokenRequest,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Register (or refresh) an Expo push token for the current host.

    Call this on every app launch after requesting notification permission.
    If the token already exists for this host it is a no-op (idempotent).
    If the same token was previously registered to a different host it is reassigned.
    """
    token = request.token.strip()

    if not token.startswith("ExponentPushToken"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Expo push token format. Must start with 'ExponentPushToken'.",
        )

    result = await db.execute(
        select(HostPushToken).filter(HostPushToken.token == token)
    )
    existing = result.scalar_one_or_none()

    if existing:
        if existing.host_id == current_host.id:
            if request.platform:
                existing.platform = request.platform
                await db.commit()
            return PushTokenResponse(message="Push token already registered.")
        else:
            existing.host_id = current_host.id
            existing.platform = request.platform
            await db.commit()
            return PushTokenResponse(message="Push token updated.")

    push_token = HostPushToken(
        host_id=current_host.id,
        token=token,
        platform=request.platform,
    )
    db.add(push_token)
    await db.commit()
    return PushTokenResponse(message="Push token registered successfully.")


@router.delete(
    "/host/push-token",
    response_model=PushTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Unregister Expo push token (host)",
    tags=["Push Notifications"],
)
async def unregister_host_push_token(
    request: RegisterPushTokenRequest,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """Unregister an Expo push token (call on logout or notification opt-out)."""
    token = request.token.strip()

    result = await db.execute(
        select(HostPushToken).filter(
            HostPushToken.token == token,
            HostPushToken.host_id == current_host.id,
        )
    )
    existing = result.scalar_one_or_none()

    if not existing:
        return PushTokenResponse(message="Token not found — nothing to remove.")

    await db.delete(existing)
    await db.commit()
    return PushTokenResponse(message="Push token unregistered.")
