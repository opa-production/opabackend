from pydantic_settings import BaseSettings
from typing import Optional
import os
from pathlib import Path
import logging

# Set up logging
logger = logging.getLogger(__name__)

# Get the project root directory (parent of app directory)
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # SendGrid API configuration
    SENDGRID_API_KEY: Optional[str] = None
    
    # Email from address (verified sender in SendGrid, e.g. hello@ardena.xyz)
    SENDGRID_FROM_EMAIL: Optional[str] = "Ardena Group Team <hello@ardena.xyz>"
    
    # Google Auth
    GOOGLE_CLIENT_ID: Optional[str] = None
    
    # Frontend URL for password reset links
    FRONTEND_URL: Optional[str] = "https://yourapp.com"  # Base URL for reset password links
    
    class Config:
        # Use absolute path to .env file in project root
        env_file = str(BASE_DIR / ".env")
        env_file_encoding = 'utf-8'
        case_sensitive = True
        extra = "ignore"  # Ignore extra env vars (DATABASE_URL, etc. used elsewhere)


# Global settings instance
settings = Settings()

# Debug logging for environment variables (only in development)
# Check if .env file exists
env_file_path = BASE_DIR / ".env"
if env_file_path.exists():
    logger.info(f"Found .env file at: {env_file_path}")
else:
    logger.warning(f".env file not found at: {env_file_path}")

# Log environment variable loading status (without exposing the actual key)
if settings.SENDGRID_API_KEY:
    logger.info(f"SENDGRID_API_KEY loaded successfully (length: {len(settings.SENDGRID_API_KEY)})")
else:
    logger.warning("SENDGRID_API_KEY not found in settings, trying os.environ...")
    env_key = os.getenv("SENDGRID_API_KEY")
    if env_key:
        settings.SENDGRID_API_KEY = env_key
        logger.info(f"SENDGRID_API_KEY loaded from os.environ (length: {len(env_key)})")
    else:
        logger.error("SENDGRID_API_KEY not found in .env file or environment variables")
