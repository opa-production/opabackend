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
    
    # Database configuration
    DATABASE_URL: Optional[str] = None
    
    # SendGrid API configuration
    SENDGRID_API_KEY: Optional[str] = None
    
    # Email from address (verified sender in SendGrid, e.g. hello@ardena.xyz)
    SENDGRID_FROM_EMAIL: Optional[str] = "Ardena Group Team <hello@ardena.xyz>"
    
    # Google Auth
    GOOGLE_CLIENT_ID: Optional[str] = None
    
    # Security
    SECRET_KEY: str = "your-secret-key-change-in-production"  # Default for dev only
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # CORS
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8000", "https://ardena.co.ke"]

    FRONTEND_URL: Optional[str] = "https://ardena.co.ke"  
    PASSWORD_RESET_LINK_BASE_URL: Optional[str] = None  
    HOST_PASSWORD_RESET_WEB_URL: Optional[str] = None  
    CLIENT_PASSWORD_RESET_WEB_URL: Optional[str] = "https://ardena.co.ke/reset-password.html" 

    # Veriff KYC (host + client verification)
    VERIFF_API_KEY: Optional[str] = None
    VERIFF_BASE_URL: Optional[str] = "https://stationapi.veriff.com"  
   
    VERIFF_CALLBACK_URL: Optional[str] = None
    
    KYC_ALLOWED_RETURN_PREFIXES: str = "ardenahost://,ardena://,oparides://"
   
    VERIFF_WEBHOOK_SECRET: Optional[str] = None
    SHARED_SECRET_KEY: Optional[str] = None   
    MASTER_SECRET_KEY: Optional[str] = None   

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
