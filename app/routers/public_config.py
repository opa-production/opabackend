"""
Public configuration for client apps (no authentication).
"""
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import settings

router = APIRouter()


class PublicConfigResponse(BaseModel):
    """Safe, non-secret values the mobile/web client may need at startup."""

    api_version: str = Field("1.0.0", description="Backend API version")
    google_sign_in_enabled: bool = Field(
        ..., description="True when Google OAuth client ID is configured"
    )
    frontend_url: Optional[str] = Field(None, description="Primary marketing / web app URL")


@router.get("/config", response_model=PublicConfigResponse)
async def get_public_config():
    return PublicConfigResponse(
        google_sign_in_enabled=bool(
            settings.GOOGLE_CLIENT_ID and str(settings.GOOGLE_CLIENT_ID).strip()
        ),
        frontend_url=settings.FRONTEND_URL,
    )
