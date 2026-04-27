from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional, Annotated
import os
from pathlib import Path
import logging
import json
from pydantic_settings import NoDecode

# Set up logging
logger = logging.getLogger(__name__)

# Get the project root directory (parent of app directory)
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Database configuration (PostgreSQL only)
    DATABASE_URL: Optional[str] = None
    
    # Test database configuration
    TEST_MODE: bool = False
    TEST_DATABASE_URL: Optional[str] = None
    
    # Supabase Storage configuration (for media uploads only)
    SUPABASE_URL: Optional[str] = None
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = None
    
    # Resend email API
    RESEND_API_KEY: Optional[str] = None
    
    # Google Auth
    GOOGLE_CLIENT_ID: Optional[str] = None
    
    # Security
    SECRET_KEY: str = "your-secret-key-change-in-production"  # Default for dev only
    ALGORITHM: str = "HS256"
    # ~30 days; JWT exp uses this value (override via ACCESS_TOKEN_EXPIRE_MINUTES in .env)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30 * 24 * 60  # 43200 ≈ one month
    # Must be longer than access token so /auth/refresh stays usable when access expires
    REFRESH_TOKEN_EXPIRE_DAYS: int = 90
    
    # CORS — must list every browser origin (scheme + host + port). localhost ≠ 127.0.0.1 to the browser.
    # VS Code Live Server often uses http://127.0.0.1:5500
    ALLOWED_ORIGINS: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://localhost:5500",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5500",
        "http://127.0.0.1:8000",
        "https://ardena.co.ke",
        "https://adminnn.ardena.xyz",
    ]
    
    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value):
        """
        Accept both JSON array strings and comma-separated origins from .env.
        Example valid values:
        - ["http://localhost:3000","https://ardena.co.ke"]
        - http://localhost:3000,https://ardena.co.ke
        """
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            if raw.startswith("[") and raw.endswith("]"):
                try:
                    parsed = json.loads(raw)
                    return parsed if isinstance(parsed, list) else []
                except json.JSONDecodeError:
                    return []
            return [origin.strip() for origin in raw.split(",") if origin.strip()]
        return value

    # Comma-separated list for client apps (city tabs, filters). Override in .env, e.g. OPERATING_CITIES=Nairobi,Nakuru,Mombasa,Kisumu
    OPERATING_CITIES: str = "Nairobi,Nakuru,Mombasa,Kisumu"

    # App version gates — set in .env to prompt users to update.
    # Leave empty (or unset) to not show the update modal.
    # Example: ANDROID_LATEST_VERSION=1.0.13  IOS_LATEST_VERSION=1.0.13
    ANDROID_LATEST_VERSION: Optional[str] = None
    IOS_LATEST_VERSION: Optional[str] = None
    ANDROID_STORE_URL: Optional[str] = "market://details?id=com.ardena.app"
    IOS_STORE_URL: Optional[str] = None

    FRONTEND_URL: Optional[str] = "https://ardena.co.ke"
    PASSWORD_RESET_LINK_BASE_URL: Optional[str] = None
    HOST_PASSWORD_RESET_WEB_URL: Optional[str] = None
    CLIENT_PASSWORD_RESET_WEB_URL: Optional[str] = "https://ardena.co.ke/reset-password.html"
    # Deep-link scheme for the host app (e.g. ardenahost:// or https://host.ardena.co.ke)
    # Paystack redirects hosts here after card checkout.
    HOST_FRONTEND_URL: Optional[str] = None

    # Paystack card payments (hosted page — no card data stored)
    PAYSTACK_SECRET_KEY: Optional[str] = None
    PAYSTACK_CALLBACK_BASE_URL: Optional[str] = None   # e.g. https://api.ardena.xyz/api/v1

    # Dojah KYC (host + client verification)
    DOJAH_APP_ID: Optional[str] = None           # App ID (used as AppId header)
    DOJAH_SECRET_KEY: Optional[str] = None       # Secret key (Authorization header)
    DOJAH_PUBLIC_KEY: Optional[str] = None       # Public/publishable key (sent to frontend for widget)
    DOJAH_WIDGET_ID: Optional[str] = None        # Pre-configured widget ID from Dojah dashboard
    DOJAH_BASE_URL: str = "https://api.dojah.io"
    DOJAH_WEBHOOK_SECRET: Optional[str] = None   # HMAC-SHA512 secret for webhook validation

    KYC_ALLOWED_RETURN_PREFIXES: str = "ardenahost://,ardena://,oparides://"

    # Gava Connect (Kenya e-Government PIN checker)
    GAVACONNECT_CONSUMER_KEY: Optional[str] = None
    GAVACONNECT_CONSUMER_SECRET: Optional[str] = None
    GAVACONNECT_BASE_URL: str = "https://developer.go.ke"  # UAT: https://uat.developer.go.ke

    class Config:
    
        env_file = str(BASE_DIR / ".env")
        env_file_encoding = 'utf-8'
        case_sensitive = True
        extra = "ignore"  


# Global settings instance
settings = Settings()


env_file_path = BASE_DIR / ".env"
if env_file_path.exists():
    logger.info(f"Found .env file at: {env_file_path}")
else:
    logger.warning(f".env file not found at: {env_file_path}")


if settings.RESEND_API_KEY:
    logger.info(f"RESEND_API_KEY loaded successfully (length: {len(settings.RESEND_API_KEY)})")
else:
    logger.warning("RESEND_API_KEY not found in settings, trying os.environ...")
    env_key = os.getenv("RESEND_API_KEY")
    if env_key:
        settings.RESEND_API_KEY = env_key
        logger.info(f"RESEND_API_KEY loaded from os.environ (length: {len(env_key)})")
    else:
        logger.error("RESEND_API_KEY not found in .env file or environment variables")
