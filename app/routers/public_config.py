"""
Public configuration for client apps (no authentication).
"""
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import settings

router = APIRouter()


def _operating_cities_list() -> List[str]:
    raw = (settings.OPERATING_CITIES or "").strip()
    if not raw:
        return []
    return [c.strip() for c in raw.split(",") if c.strip()]


class PublicConfigResponse(BaseModel):
    """Safe, non-secret values the mobile/web client may need at startup."""

    api_version: str = Field("1.0.0", description="Backend API version")
    google_sign_in_enabled: bool = Field(
        ..., description="True when Google OAuth client ID is configured"
    )
    frontend_url: Optional[str] = Field(None, description="Primary marketing / web app URL")
    operating_cities: List[str] = Field(
        ...,
        description="Canonical city names for browse tabs / filters (matches host operating city)",
    )
    android_version: Optional[str] = Field(
        None, description="Latest required Android app version. Omitted when no update is needed."
    )
    ios_version: Optional[str] = Field(
        None, description="Latest required iOS app version. Omitted when no update is needed."
    )
    android_store_url: Optional[str] = Field(
        None, description="Play Store URL or market:// deep-link for the Android update."
    )
    ios_store_url: Optional[str] = Field(
        None, description="App Store URL for the iOS update."
    )


@router.get("/config", response_model=PublicConfigResponse)
async def get_public_config():
    return PublicConfigResponse(
        google_sign_in_enabled=bool(
            settings.GOOGLE_CLIENT_ID and str(settings.GOOGLE_CLIENT_ID).strip()
        ),
        frontend_url=settings.FRONTEND_URL,
        operating_cities=_operating_cities_list(),
        android_version=settings.ANDROID_LATEST_VERSION or None,
        ios_version=settings.IOS_LATEST_VERSION or None,
        android_store_url=settings.ANDROID_STORE_URL or None,
        ios_store_url=settings.IOS_STORE_URL or None,
    )
