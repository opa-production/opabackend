from typing import Optional
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta

# Windows consoles often use cp1252; emoji/symbols in print() then raise UnicodeEncodeError on startup.
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except OSError:
        pass
from dotenv import load_dotenv
from app.config import settings

# Rate limiting
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

# Caching
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from fastapi_cache.backends.redis import RedisBackend
from fastapi_cache.decorator import cache

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

# Request logging - logs every API call with status code
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        # Log incoming request details
        origin = request.headers.get("origin", "none")
        client_host = request.client.host if request.client else "unknown"
        path = request.url.path
        method = request.method
        logging.info(f"[REQUEST] {method} {path} from {client_host} (origin: {origin})")
        
        response = await call_next(request)
        duration = (time.time() - start) * 1000
        status = response.status_code
        
        logging.info(f"{method} {path} -> {status} ({duration:.0f}ms)")
        return response


# Security Headers Middleware - adds all security headers to responses
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        
        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # XSS Protection (legacy but still useful for older browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Strict Transport Security (HSTS) - enforce HTTPS
        # Note: Enable in production with your actual domain
        hsts_max_age = os.getenv("HSTS_MAX_AGE", "31536000")  # 1 year default
        response.headers["Strict-Transport-Security"] = f"max-age={hsts_max_age}; includeSubDomains"
        
        # Content Security Policy
        # Swagger (/docs) and ReDoc (/redoc) load assets from cdn.jsdelivr.net; without this,
        # browsers block those scripts/styles and the UI spins forever.
        csp_policy = os.getenv(
            "CSP_POLICY",
            "default-src 'self'; "
            "img-src 'self' data: https:; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "font-src 'self' data: https://cdn.jsdelivr.net; "
            "connect-src 'self' https:; "
            "frame-ancestors 'none'"
        )
        response.headers["Content-Security-Policy"] = csp_policy
        
        # Referrer Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Permissions Policy (disable features not needed)
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        
        return response

# Load environment variables from .env file
load_dotenv()

from app.database import engine, Base, SessionLocal
from app import models  # Import models to ensure they're registered
from app.models import DrivingLicense  # Import DrivingLicense to ensure it's registered
from app.routers import (
    public_config as public_config_router,
    host_auth,
    client_auth,
    cars,
    payment_methods,
    feedback,
    support,
    media,
    bookings,
    messages,
    payments,
    host_ratings,
    client_ratings,
    car_ratings,
    agreements,
    host_earnings,
    host_subscription,
    wallet as wallet_router,
    subscribers as subscribers_router,
    host_kyc as host_kyc_router,
    client_kyc as client_kyc_router,
    veriff_webhook as veriff_webhook_router,
    client_refunds as client_refunds_router,
    client_emergency as client_emergency_router,
    wishlist as wishlist_router,
)
from app.admin import (
    auth as admin_auth,
    users as admin_users,
    cars as admin_cars,
    dashboard as admin_dashboard,
    feedback as admin_feedback,
    notifications as admin_notifications,
    admins as admin_admins,
    payment_methods as admin_payment_methods,
    support as admin_support,
    bookings as admin_bookings,
    withdrawals as admin_withdrawals,
    subscribers as admin_subscribers,
    refunds as admin_refunds,
)
from app.models import Admin
from app.auth import get_password_hash, get_admin_by_email
from sqlalchemy import inspect, select, text

app = FastAPI(
    title="Car Rental API",
    description="Backend API for car rental platform",
    version="1.0.0",
    docs_url="/docs",  # Explicitly enable Swagger UI
    redoc_url="/redoc",  # Explicitly enable ReDoc
    openapi_url="/openapi.json",  # Explicitly enable OpenAPI schema
    openapi_tags=[
        {"name": "Config", "description": "Public app configuration (no auth)"},
        {"name": "Host Auth", "description": "Host authentication endpoints"},
        {"name": "Client Auth", "description": "Client authentication endpoints"},
        {"name": "Car Management", "description": "Car listing and management"},
        {"name": "Payment Methods", "description": "Payment method management"},
        {"name": "Feedback", "description": "User feedback"},
        {"name": "Support Messages", "description": "Support messaging"},
        {"name": "Client-Host Messages", "description": "Client-Host messaging"},
        {"name": "Bookings", "description": "Booking management"},
        {"name": "Payments", "description": "Payment processing"},
        {"name": "Media Upload", "description": "File uploads"},
        {"name": "Host Ratings", "description": "Client ratings for hosts"},
        {"name": "Client Ratings", "description": "Host ratings for clients (renters)"},
        {"name": "Host Earnings", "description": "Host earnings summary, transactions, and withdrawal requests"},
        {"name": "Host Subscription", "description": "Host paid plans (M-Pesa) and subscription status"},
        {"name": "Client Refunds", "description": "Client‑visible refund records for bookings"},
        {"name": "Client Emergency", "description": "Emergency messages from clients with location"},
        {"name": "Client Wishlist", "description": "Client car wishlist (liked cars)"},
        {"name": "Ardena Pay", "description": "Client Stellar wallet: create, balances, incoming payments"},
        {"name": "Admin Auth", "description": "Admin authentication"},
        {"name": "Admin User Management", "description": "User management"},
        {"name": "Admin Car Management", "description": "Car verification"},
        {"name": "Admin Dashboard", "description": "Dashboard statistics"},
        {"name": "Admin Feedback Management", "description": "Feedback management"},
        {"name": "Admin Notifications", "description": "Notification broadcasting"},
        {"name": "Admin Management", "description": "Admin account management"},
        {"name": "Admin Payment Methods", "description": "Payment method oversight"},
        {"name": "Admin Support", "description": "Support conversation management"},
        {"name": "Admin Bookings", "description": "Booking management and oversight"},
        {"name": "Admin Withdrawals", "description": "View and process host withdrawal requests"},
        {"name": "Admin Refunds", "description": "Track and manage booking refunds for finance"},
        {"name": "Newsletter", "description": "Public subscribe / unsubscribe"},
        {"name": "Admin Subscribers", "description": "Newsletter subscriber list and send email to all"},
        {"name": "Host KYC", "description": "Host KYC verification (Veriff)"},
        {"name": "Veriff Webhook", "description": "Veriff decision webhook (do not call directly)"},
    ],
    servers=[{"url": "/", "description": "Current host"}],
)

# =============================================================================
# MIDDLEWARE CONFIGURATION (order matters - first added = outermost)
# =============================================================================

# 1. Security Headers Middleware (adds X-Frame-Options, CSP, HSTS, etc.)
# Must be added first so it runs first on request, last on response
app.add_middleware(SecurityHeadersMiddleware)

# 2. Trusted Host Middleware
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"]  # Change this in production!
)

# Add rate limiter state to app
app.state.limiter = limiter

# Add rate limit exceeded handler
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 3. Gzip compression for faster responses 
app.add_middleware(GZipMiddleware, minimum_size=1000)

# 4. CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],  # settings.ALLOWED_ORIGINS,
    # "Forever" CORS:
    # - Local dev may use different hostnames and ports (e.g. 127.0.0.1:5500 vs localhost:5500)
    # - Frontend/admin are on ardena subdomains.
    # If ALLOWED_ORIGINS doesn't include a specific origin, this regex can still allow it.
    allow_origin_regex=os.getenv(
        "CORS_ALLOW_ORIGIN_REGEX",
        r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$|^https://([a-z0-9-]+\.)?ardena\.(xyz|co\.ke)(:\d+)?$",
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# 4. Request logging (add last so it runs closest to handler)
app.add_middleware(RequestLoggingMiddleware)

# =============================================================================
# CACHE CONFIGURATION
# =============================================================================

# Initialize cache with Redis backend
# Note: Cache will only work if Redis is available; graceful fallback if not
@app.on_event("startup")
async def startup_init_cache():
    try:
        import redis.asyncio as redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        # fastapi-cache coder expects bytes from backend; decode_responses=True returns str
        # and causes: AttributeError: 'str' object has no attribute 'decode'
        redis_client = redis.from_url(redis_url, decode_responses=False)
        # Force a real connection test at startup; from_url alone does not verify availability.
        await redis_client.ping()
        FastAPICache.init(
            RedisBackend(redis_client),
            prefix="opa-cache:",
            expire=300  # Default cache expiration: 5 minutes
        )
        logging.info("[CACHE] Redis cache initialized successfully")
    except Exception as e:
        logging.warning(f"[CACHE] Redis not available, using in-memory cache: {e}")
        # In-memory fallback avoids Redis connection errors on every request.
        FastAPICache.init(
            InMemoryBackend(),
            prefix="opa-cache:",
            expire=300
        )

# Include routers
app.include_router(public_config_router.router, prefix="/api/v1", tags=["Config"])
app.include_router(host_auth.router, prefix="/api/v1", tags=["Host Auth"])
app.include_router(client_auth.router, prefix="/api/v1", tags=["Client Auth"])
app.include_router(cars.router, prefix="/api/v1", tags=["Car Management"])
app.include_router(payment_methods.router, prefix="/api/v1", tags=["Payment Methods"])
app.include_router(feedback.router, prefix="/api/v1", tags=["Feedback"])
app.include_router(support.router, prefix="/api/v1", tags=["Support Messages"])
app.include_router(messages.router, prefix="/api/v1", tags=["Client-Host Messages"])
app.include_router(bookings.router, prefix="/api/v1", tags=["Bookings"])
app.include_router(client_refunds_router.router, prefix="/api/v1", tags=["Client Refunds"])
app.include_router(wishlist_router.router, prefix="/api/v1", tags=["Client Wishlist"])
app.include_router(payments.router, prefix="/api/v1", tags=["Payments"])
app.include_router(wallet_router.router, prefix="/api/v1", tags=["Ardena Pay"])
app.include_router(media.router, prefix="/api/v1", tags=["Media Upload"])
app.include_router(car_ratings.router, prefix="/api/v1", tags=["Car Ratings"])
app.include_router(agreements.router, prefix="/api/v1", tags=["Rental Agreements"])
app.include_router(host_ratings.router, prefix="/api/v1", tags=["Host Ratings"])
app.include_router(client_ratings.router, prefix="/api/v1", tags=["Client Ratings"])
app.include_router(host_earnings.router, prefix="/api/v1", tags=["Host Earnings"])
app.include_router(host_subscription.router, prefix="/api/v1", tags=["Host Subscription"])
app.include_router(subscribers_router.router, prefix="/api/v1", tags=["Newsletter"])
app.include_router(host_kyc_router.router, prefix="/api/v1", tags=["Host KYC"])
app.include_router(client_kyc_router.router, prefix="/api/v1", tags=["Client KYC"])
app.include_router(veriff_webhook_router.router, prefix="/api/v1", tags=["Veriff Webhook"])
app.include_router(admin_auth.router, prefix="/api/v1", tags=["Admin Auth"])
app.include_router(admin_users.router, prefix="/api/v1", tags=["Admin User Management"])
app.include_router(admin_cars.router, prefix="/api/v1", tags=["Admin Car Management"])
app.include_router(admin_dashboard.router, prefix="/api/v1", tags=["Admin Dashboard"])
app.include_router(admin_feedback.router, prefix="/api/v1", tags=["Admin Feedback Management"])
app.include_router(admin_notifications.router, prefix="/api/v1", tags=["Admin Notifications"])
app.include_router(admin_admins.router, prefix="/api/v1", tags=["Admin Management"])
app.include_router(admin_payment_methods.router, prefix="/api/v1", tags=["Admin Payment Methods"])
app.include_router(admin_support.router, prefix="/api/v1", tags=["Admin Support"])
app.include_router(admin_bookings.router, prefix="/api/v1", tags=["Admin Bookings"])
app.include_router(admin_withdrawals.router, prefix="/api/v1", tags=["Admin Withdrawals"])
app.include_router(admin_subscribers.router, prefix="/api/v1", tags=["Admin Subscribers"])


async def _async_insp_table_names(conn) -> set:
    """Table names via sync inspector inside greenlet (required for async SQLAlchemy)."""

    def _f(sync_conn):
        return set(inspect(sync_conn).get_table_names())

    for attempt in range(3):
        try:
            return await conn.run_sync(_f)
        except Exception as e:
            if attempt == 2:
                raise
            print(f"Attempt {attempt + 1} failed: {e}, retrying...")
            await asyncio.sleep(0.1)


async def _async_insp_column_names(conn, table: str) -> list:
    def _f(sync_conn):
        insp = inspect(sync_conn)
        if table not in insp.get_table_names():
            return []
        return [c["name"] for c in insp.get_columns(table)]

    for attempt in range(3):
        try:
            return await conn.run_sync(_f)
        except Exception as e:
            if attempt == 2:
                raise
            print(f"Attempt {attempt + 1} failed: {e}, retrying...")
            await asyncio.sleep(0.1)


async def _async_insp_column_info(conn, table: str) -> dict:
    def _f(sync_conn):
        insp = inspect(sync_conn)
        if table not in insp.get_table_names():
            return {}
        return {c["name"]: c for c in insp.get_columns(table)}

    for attempt in range(3):
        try:
            return await conn.run_sync(_f)
        except Exception as e:
            if attempt == 2:
                raise
            print(f"Attempt {attempt + 1} failed: {e}, retrying...")
            await asyncio.sleep(0.1)


async def run_migrations():
    """Run idempotent schema/data patches on every startup.

    Previously migrations ran only once (guarded by cwd/migration.lock), so new
    ALTERs (e.g. cars draft columns DROP NOT NULL) never ran after the first boot.
    """
    import sys

    if sys.platform == "win32":
        # No fcntl; avoid import error noise in tracebacks on Windows dev.
        await migrate_database()
        async with engine.connect() as conn:
            await migrate_car_media_data(conn)
        return

    import fcntl

    lock_file = "/tmp/fastapi_migration.lock"
    with open(lock_file, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            await migrate_database()
            async with engine.connect() as conn:
                await migrate_car_media_data(conn)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


async def migrate_database():
    """Add missing columns to existing tables"""
    async with engine.connect() as conn:
        table_names = await _async_insp_table_names(conn)

        # Check and add missing columns to hosts table
        if "hosts" in table_names:
            columns = await _async_insp_column_names(conn, "hosts")
            if 'is_active' not in columns:
                await conn.execute(text("ALTER TABLE hosts ADD COLUMN is_active INTEGER DEFAULT 1 NOT NULL"))
                await conn.commit()
                print("✓ Added is_active column to hosts table")
            if 'avatar_url' not in columns:
                await conn.execute(text("ALTER TABLE hosts ADD COLUMN avatar_url VARCHAR(500)"))
                await conn.commit()
                print("✓ Added avatar_url column to hosts table")
            if 'cover_image_url' not in columns:
                await conn.execute(text("ALTER TABLE hosts ADD COLUMN cover_image_url VARCHAR(500)"))
                await conn.commit()
                print("✓ Added cover_image_url column to hosts table")
            if 'id_document_url' not in columns:
                await conn.execute(text("ALTER TABLE hosts ADD COLUMN id_document_url VARCHAR(500)"))
                await conn.commit()
                print("✓ Added id_document_url column to hosts table")
            if 'license_document_url' not in columns:
                await conn.execute(text("ALTER TABLE hosts ADD COLUMN license_document_url VARCHAR(500)"))
                await conn.commit()
                print("✓ Added license_document_url column to hosts table")
            if 'google_id' not in columns:
                await conn.execute(text("ALTER TABLE hosts ADD COLUMN google_id VARCHAR(255)"))
                await conn.commit()
                print("✓ Added google_id column to hosts table")
            if 'terms_accepted_at' not in columns:
                await conn.execute(text("ALTER TABLE hosts ADD COLUMN terms_accepted_at TIMESTAMP WITH TIME ZONE"))
                await conn.commit()
                print("✓ Added terms_accepted_at column to hosts table")
        
        # Check and add missing columns to clients table
        if "clients" in table_names:
            columns = await _async_insp_column_names(conn, "clients")
            if 'is_active' not in columns:
                await conn.execute(text("ALTER TABLE clients ADD COLUMN is_active INTEGER DEFAULT 1 NOT NULL"))
                await conn.commit()
                print("✓ Added is_active column to clients table")
            if 'avatar_url' not in columns:
                await conn.execute(text("ALTER TABLE clients ADD COLUMN avatar_url VARCHAR(500)"))
                await conn.commit()
                print("✓ Added avatar_url column to clients table")
            if 'id_document_url' not in columns:
                await conn.execute(text("ALTER TABLE clients ADD COLUMN id_document_url VARCHAR(500)"))
                await conn.commit()
                print("✓ Added id_document_url column to clients table")
            if 'license_document_url' not in columns:
                await conn.execute(text("ALTER TABLE clients ADD COLUMN license_document_url VARCHAR(500)"))
                await conn.commit()
                print("✓ Added license_document_url column to clients table")
            if 'date_of_birth' not in columns:
                await conn.execute(text("ALTER TABLE clients ADD COLUMN date_of_birth DATE"))
                await conn.commit()
                print("✓ Added date_of_birth column to clients table")
            if 'gender' not in columns:
                await conn.execute(text("ALTER TABLE clients ADD COLUMN gender VARCHAR(20)"))
                await conn.commit()
                print("✓ Added gender column to clients table")
            if 'google_id' not in columns:
                await conn.execute(text("ALTER TABLE clients ADD COLUMN google_id VARCHAR(255)"))
                await conn.commit()
                print("✓ Added google_id column to clients table")
            if 'terms_accepted_at' not in columns:
                await conn.execute(text("ALTER TABLE clients ADD COLUMN terms_accepted_at TIMESTAMP WITH TIME ZONE"))
                await conn.commit()
                print("✓ Added terms_accepted_at column to clients table")
            if 'email_notifications_enabled' not in columns:
                await conn.execute(text("ALTER TABLE clients ADD COLUMN email_notifications_enabled INTEGER DEFAULT 1 NOT NULL"))
                await conn.commit()
                print("✓ Added email_notifications_enabled column to clients table")
            if 'sms_notifications_enabled' not in columns:
                await conn.execute(text("ALTER TABLE clients ADD COLUMN sms_notifications_enabled INTEGER DEFAULT 1 NOT NULL"))
                await conn.commit()
                print("✓ Added sms_notifications_enabled column to clients table")
            if 'in_app_notifications_enabled' not in columns:
                await conn.execute(text("ALTER TABLE clients ADD COLUMN in_app_notifications_enabled INTEGER DEFAULT 1 NOT NULL"))
                await conn.commit()
                print("✓ Added in_app_notifications_enabled column to clients table")
        
        # Check and add missing columns to cars table
        if "cars" in table_names:
            columns = await _async_insp_column_names(conn, "cars")
            if 'rejection_reason' not in columns:
                await conn.execute(text("ALTER TABLE cars ADD COLUMN rejection_reason TEXT"))
                await conn.commit()
                print("✓ Added rejection_reason column to cars table")
            if 'is_hidden' not in columns:
                await conn.execute(text("ALTER TABLE cars ADD COLUMN is_hidden INTEGER DEFAULT 0 NOT NULL"))
                await conn.commit()
                print("✓ Added is_hidden column to cars table")
            if 'image_urls' not in columns:
                await conn.execute(text("ALTER TABLE cars ADD COLUMN image_urls TEXT"))
                await conn.commit()
                print("✓ Added image_urls column to cars table")
            if 'video_url' not in columns:
                await conn.execute(text("ALTER TABLE cars ADD COLUMN video_url VARCHAR(500)"))
                await conn.commit()
                print("✓ Added video_url column to cars table")
            if 'cover_image' not in columns:
                await conn.execute(text("ALTER TABLE cars ADD COLUMN cover_image VARCHAR(500)"))
                await conn.commit()
                print("✓ Added cover_image column to cars table")
            if 'car_images' not in columns:
                await conn.execute(text("ALTER TABLE cars ADD COLUMN car_images TEXT"))
                await conn.commit()
                print("✓ Added car_images column to cars table")
            if 'car_video' not in columns:
                await conn.execute(text("ALTER TABLE cars ADD COLUMN car_video VARCHAR(500)"))
                await conn.commit()
                print("✓ Added car_video column to cars table")
            if 'drive_setting' not in columns:
                await conn.execute(text("ALTER TABLE cars ADD COLUMN drive_setting VARCHAR(30) DEFAULT 'self_only' NOT NULL"))
                await conn.commit()
                print("✓ Added drive_setting column to cars table")

            # Multi-step listing: POST /cars/basics inserts before specs/pricing — these columns must allow NULL.
            # PostgreSQL: always run DROP NOT NULL (idempotent if already nullable). Inspector .get("nullable")
            # was unreliable here and skipped migration, leaving NOT NULL and breaking basics.
            # Any column the ORM inserts as NULL on POST /cars/basics must not be NOT NULL in DB.
            # Includes step 2–4 + media + rejection_reason for older schemas.
            _draft_car_nullable = [
                "seats",
                "fuel_type",
                "transmission",
                "color",
                "mileage",
                "features",
                "daily_rate",
                "weekly_rate",
                "monthly_rate",
                "min_rental_days",
                "max_rental_days",
                "min_age_requirement",
                "rules",
                "location_name",
                "latitude",
                "longitude",
                "image_urls",
                "video_url",
                "cover_image",
                "car_images",
                "car_video",
                "rejection_reason",
                "updated_at",
            ]
            if engine.dialect.name == "postgresql":
                for col in _draft_car_nullable:
                    try:
                        await conn.execute(text(f"ALTER TABLE cars ALTER COLUMN {col} DROP NOT NULL"))
                        await conn.commit()
                        print(f"✓ cars.{col}: nullable for draft listing (PostgreSQL)")
                    except Exception as e:
                        try:
                            await conn.rollback()
                        except Exception:
                            pass
                        print(f"⚠️  cars.{col} DROP NOT NULL: {e}")
            else:
                car_col_info = await _async_insp_column_info(conn, "cars")
                for col in _draft_car_nullable:
                    if col not in car_col_info:
                        continue
                    # Only skip when reflection explicitly says nullable
                    if car_col_info[col].get("nullable") is True:
                        continue
                    try:
                        await conn.execute(text(f"ALTER TABLE cars ALTER COLUMN {col} DROP NOT NULL"))
                        await conn.commit()
                        print(f"✓ Made cars.{col} nullable (draft listing after basics)")
                    except Exception as e:
                        try:
                            await conn.rollback()
                        except Exception:
                            pass
                        print(f"⚠️  Could not make cars.{col} nullable: {e}")
        
        # Check and add is_flagged to feedbacks table
        if "feedbacks" in table_names:
            columns = await _async_insp_column_names(conn, "feedbacks")
            if 'is_flagged' not in columns:
                await conn.execute(text("ALTER TABLE feedbacks ADD COLUMN is_flagged INTEGER DEFAULT 0 NOT NULL"))
                await conn.commit()
                print("✓ Added is_flagged column to feedbacks table")

        # Check and add extension_request_id to payments table (for booking extensions)
        if "payments" in table_names:
            columns = await _async_insp_column_names(conn, "payments")
            if 'extension_request_id' not in columns:
                await conn.execute(text("ALTER TABLE payments ADD COLUMN extension_request_id INTEGER"))
                await conn.commit()
                print("✓ Added extension_request_id column to payments table")
        
        # Check and add client_id to payment_methods table, and make host_id nullable
        if "payment_methods" in table_names:
            columns = await _async_insp_column_names(conn, "payment_methods")
            column_info = await _async_insp_column_info(conn, "payment_methods")
            
            # Add client_id if missing
            if 'client_id' not in columns:
                try:
                    await conn.execute(text("ALTER TABLE payment_methods ADD COLUMN client_id INTEGER"))
                    await conn.commit()
                    print("✓ Added client_id column to payment_methods table")
                except Exception as e:
                    print(f"⚠️  Error adding client_id to payment_methods: {e}")
            
            # PostgreSQL can handle ALTER COLUMN directly
            if 'host_id' in column_info:
                host_id_nullable = column_info['host_id'].get('nullable', False)
                if not host_id_nullable:
                    print("⚠️  payment_methods.host_id is NOT NULL, altering to nullable...")
                    try:
                        await conn.execute(text("ALTER TABLE payment_methods ALTER COLUMN host_id DROP NOT NULL"))
                        await conn.commit()
                        print("✓ Made payment_methods.host_id nullable")
                    except Exception as e:
                        print(f"⚠️  Error altering payment_methods table: {e}")
        
        # Create notifications table if it doesn't exist
        if 'notifications' not in table_names:
            print("✓ Notifications table will be created")
        
        # Migrate support_messages table to new conversation-based schema
        if "support_messages" in table_names:
            columns = await _async_insp_column_names(conn, "support_messages")
            if 'conversation_id' not in columns and 'host_id' in columns:
                print("⚠️  Migrating support_messages table to new conversation-based schema...")
                await conn.execute(text("DROP TABLE support_messages"))
                await conn.commit()
                print("✓ Dropped old support_messages table (will be recreated with new schema)")
        
        # Ensure support_conversations table exists
        if 'support_conversations' not in table_names:
            print("✓ Support conversations table will be created")


async def migrate_car_media_data(conn):
    """Migrate existing car media data from legacy fields to new fields"""
    import json
    
    # Check if cars table exists
    table_names = await _async_insp_table_names(conn)
    if 'cars' not in table_names:
        return
    
    # Get all cars with legacy media data
    result = await conn.execute(text("SELECT id, image_urls, video_url, car_images, cover_image, car_video FROM cars"))
    cars = result.fetchall()
    
    migrated_count = 0
    for car in cars:
        car_id, image_urls, video_url, car_images, cover_image, car_video = car
        
        updates = {}
        
        # Migrate image_urls to car_images if car_images is empty
        if image_urls and not car_images:
            try:
                # image_urls should already be JSON, but let's ensure it's valid
                parsed_urls = json.loads(image_urls) if isinstance(image_urls, str) else image_urls
                if isinstance(parsed_urls, list) and parsed_urls:
                    updates['car_images'] = json.dumps(parsed_urls)
                    # Set cover_image to first image if not set
                    if not cover_image and parsed_urls:
                        updates['cover_image'] = parsed_urls[0]
            except (json.JSONDecodeError, TypeError):
                # If image_urls is not valid JSON, try to treat it as a single URL
                if image_urls and isinstance(image_urls, str):
                    updates['car_images'] = json.dumps([image_urls])
                    if not cover_image:
                        updates['cover_image'] = image_urls
        
        # Migrate video_url to car_video if car_video is empty
        if video_url and not car_video:
            updates['car_video'] = video_url
        
        # Apply updates if any
        if updates:
            set_parts = []
            params = {'car_id': car_id}
            
            for field, value in updates.items():
                set_parts.append(f"{field} = :{field}")
                params[field] = value
            
            if set_parts:
                query = f"UPDATE cars SET {', '.join(set_parts)} WHERE id = :car_id"
                await conn.execute(text(query), params)
                migrated_count += 1
    
    if migrated_count > 0:
        await conn.commit()
        print(f"✓ Migrated media data for {migrated_count} cars from legacy to new fields")


@app.on_event("startup")
async def startup_database():
    """Create database tables on startup and create default super admin"""
    print("🚀 Starting up...")

    # Store the running event loop so background threads can schedule DB-backed
    # coroutines on it via run_coroutine_threadsafe (booking emails, agreements).
    import asyncio as _asyncio
    from app.services.booking_emails import set_main_loop
    set_main_loop(_asyncio.get_running_loop())

    # Run migrations first
    await run_migrations()
    
    # Then create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with engine.connect() as conn:
        table_names = await _async_insp_table_names(conn)

        # Double-check that support_messages table exists, create if missing
        if 'support_messages' not in table_names:
            print("⚠️  support_messages table missing, creating...")
            from app.models import SupportMessage
            def create_table(sync_conn):
                SupportMessage.__table__.create(sync_conn, checkfirst=True)
            await conn.run_sync(create_table)
            print("✓ Created support_messages table")
        
        # Double-check that client_host_conversations and client_host_messages tables exist
        if 'client_host_conversations' not in table_names:
            print("⚠️  client_host_conversations table missing, creating...")
            from app.models import ClientHostConversation
            def create_table(sync_conn):
                ClientHostConversation.__table__.create(sync_conn, checkfirst=True)
            await conn.run_sync(create_table)
            print("✓ Created client_host_conversations table")
        
        if 'client_host_messages' not in table_names:
            print("⚠️  client_host_messages table missing, creating...")
            from app.models import ClientHostMessage
            def create_table(sync_conn):
                ClientHostMessage.__table__.create(sync_conn, checkfirst=True)
            await conn.run_sync(create_table)
            print("✓ Created client_host_messages table")
        
        # Double-check that car_blocked_dates table exists
        if 'car_blocked_dates' not in table_names:
            print("⚠️  car_blocked_dates table missing, creating...")
            from app.models import CarBlockedDate
            def create_table(sync_conn):
                CarBlockedDate.__table__.create(sync_conn, checkfirst=True)
            await conn.run_sync(create_table)
            print("✓ Created car_blocked_dates table")
        else:
            columns = await _async_insp_column_names(conn, "car_blocked_dates")
            if 'start_date' in columns and 'blocked_date' not in columns:
                await conn.execute(text("ALTER TABLE car_blocked_dates ADD COLUMN blocked_date DATE"))
                await conn.execute(text("UPDATE car_blocked_dates SET blocked_date = DATE(start_date) WHERE blocked_date IS NULL"))
                await conn.commit()
                print("✓ Migrated start_date to blocked_date in car_blocked_dates table")
            elif 'blocked_date' not in columns:
                await conn.execute(text("ALTER TABLE car_blocked_dates ADD COLUMN blocked_date DATE"))
                await conn.commit()
                print("✓ Added blocked_date column to car_blocked_dates table")
            
            if 'reason' not in columns:
                await conn.execute(text("ALTER TABLE car_blocked_dates ADD COLUMN reason TEXT"))
                await conn.commit()
                print("✓ Added reason column to car_blocked_dates table")
            if 'created_at' not in columns:
                await conn.execute(text("ALTER TABLE car_blocked_dates ADD COLUMN created_at TIMESTAMP WITH TIME ZONE"))
                await conn.commit()
                print("✓ Added created_at column to car_blocked_dates table")
        
        # Ensure client_kycs table exists
        if 'client_kycs' not in table_names:
            print("⚠️  client_kycs table missing, creating...")
            from app.models import ClientKyc
            def create_table(sync_conn):
                ClientKyc.__table__.create(sync_conn, checkfirst=True)
            await conn.run_sync(create_table)
            print("✓ Created client_kycs table")

        # Ensure client_wallets table exists (Ardena Pay / Stellar)
        if 'client_wallets' not in table_names:
            print("⚠️  client_wallets table missing, creating...")
            from app.models import ClientWallet
            await conn.run_sync(lambda sync_conn: ClientWallet.__table__.create(sync_conn, checkfirst=True))
            print("✓ Created client_wallets table")
        else:
            # Add balance cache columns if missing (stored in DB for easier retrieval)
            cw_columns = await conn.run_sync(
                lambda sync_conn: [col['name'] for col in inspect(sync_conn).get_columns('client_wallets')]
            )
            if 'balance_xlm' not in cw_columns:
                await conn.execute(text("ALTER TABLE client_wallets ADD COLUMN balance_xlm VARCHAR(50) DEFAULT '0'"))
                await conn.commit()
                print("✓ Added balance_xlm column to client_wallets table")
            if 'balance_usdc' not in cw_columns:
                await conn.execute(text("ALTER TABLE client_wallets ADD COLUMN balance_usdc VARCHAR(50) DEFAULT '0'"))
                await conn.commit()
                print("✓ Added balance_usdc column to client_wallets table")
            if 'balance_updated_at' not in cw_columns:
                await conn.execute(text("ALTER TABLE client_wallets ADD COLUMN balance_updated_at TIMESTAMP WITH TIME ZONE"))
                await conn.commit()
                print("✓ Added balance_updated_at column to client_wallets table")

        # Ensure host_booking_issues table exists
        if 'host_booking_issues' not in table_names:
            print("⚠️  host_booking_issues table missing, creating...")
            from app.models import BookingIssue
            def create_table(sync_conn):
                BookingIssue.__table__.create(sync_conn, checkfirst=True)
            await conn.run_sync(create_table)
            print("✓ Created host_booking_issues table")

        # Check and add missing columns to bookings table
        if "bookings" in table_names:
            columns = await _async_insp_column_names(conn, "bookings")
            if 'dropoff_same_as_pickup' not in columns:
                await conn.execute(text("ALTER TABLE bookings ADD COLUMN dropoff_same_as_pickup INTEGER DEFAULT 1 NOT NULL"))
                await conn.commit()
                print("✓ Added dropoff_same_as_pickup column to bookings table")
            if 'pickup_confirmed_at' not in columns:
                await conn.execute(text("ALTER TABLE bookings ADD COLUMN pickup_confirmed_at TIMESTAMP WITH TIME ZONE"))
                await conn.commit()
                print("✓ Added pickup_confirmed_at column to bookings table")
            if 'dropoff_confirmed_at' not in columns:
                await conn.execute(text("ALTER TABLE bookings ADD COLUMN dropoff_confirmed_at TIMESTAMP WITH TIME ZONE"))
                await conn.commit()
                print("✓ Added dropoff_confirmed_at column to bookings table")

        # Check and add missing columns to withdrawals table
        if "withdrawals" in table_names:
            columns = await _async_insp_column_names(conn, "withdrawals")
            if 'checkout_request_id' not in columns:
                await conn.execute(text("ALTER TABLE withdrawals ADD COLUMN checkout_request_id VARCHAR(255)"))
                await conn.commit()
                print("✓ Added checkout_request_id column to withdrawals table")
            if 'result_code' not in columns:
                await conn.execute(text("ALTER TABLE withdrawals ADD COLUMN result_code INTEGER"))
                await conn.commit()
                print("✓ Added result_code column to withdrawals table")
            if 'result_desc' not in columns:
                await conn.execute(text("ALTER TABLE withdrawals ADD COLUMN result_desc VARCHAR(500)"))
                await conn.commit()
                print("✓ Added result_desc column to withdrawals table")
            if 'mpesa_receipt_number' not in columns:
                await conn.execute(text("ALTER TABLE withdrawals ADD COLUMN mpesa_receipt_number VARCHAR(100)"))
                await conn.commit()
                print("✓ Added mpesa_receipt_number column to withdrawals table")
            if 'mpesa_phone' not in columns:
                await conn.execute(text("ALTER TABLE withdrawals ADD COLUMN mpesa_phone VARCHAR(20)"))
                await conn.commit()
                print("✓ Added mpesa_phone column to withdrawals table")
            if 'mpesa_transaction_date' not in columns:
                await conn.execute(text("ALTER TABLE withdrawals ADD COLUMN mpesa_transaction_date VARCHAR(50)"))
                await conn.commit()
                print("✓ Added mpesa_transaction_date column to withdrawals table")
    
        # Migrate existing car media data from legacy to new fields
        await migrate_car_media_data(conn)
    
    # Create default super admin if it doesn't exist
    await _ensure_default_super_admin()
    
    print("✅ Startup complete!")
    asyncio.create_task(_run_expire_pending_bookings_loop())
    asyncio.create_task(_run_pickup_reminder_loop())


async def _ensure_default_super_admin():
    """Ensure the default super admin exists, handling race conditions from multiple workers."""
    from sqlalchemy.exc import IntegrityError
    async with SessionLocal() as db:
        try:
            default_admin_email = "admin@carrental.com"
            existing_admin = await get_admin_by_email(db, default_admin_email)
            
            if not existing_admin:
                # Default super admin password: Admin123!
                # ⚠️ SECURITY WARNING: This default password is for development only.
                # In production, use a strong password or environment variable.
                default_password = "Admin123!"
                hashed_password = get_password_hash(default_password)
                
                super_admin = Admin(
                    full_name="Super Admin",
                    email=default_admin_email,
                    hashed_password=hashed_password,
                    role="super_admin",
                    is_active=True
                )
                
                db.add(super_admin)
                try:
                    await db.commit()
                    await db.refresh(super_admin)
                    
                    print("=" * 60)
                    print("DEFAULT SUPER ADMIN CREATED")
                    print("=" * 60)
                    print(f"Email: {default_admin_email}")
                    print(f"Password: {default_password}")
                    print("=" * 60)
                    print("⚠️  IMPORTANT: Change this password after first login!")
                    print("=" * 60)
                except IntegrityError:
                    await db.rollback()
                    # Someone else created it in the meantime
                    print(f"Super admin already exists (created by another worker): {default_admin_email}")
            else:
                print(f"Super admin already exists: {default_admin_email}")
        except Exception as e:
            print(f"Error creating default super admin: {e}")
            await db.rollback()


async def _run_expire_pending_bookings_loop():
    """Every N minutes, cancel PENDING bookings older than PENDING_BOOKING_EXPIRE_MINUTES with no completed payment."""
    from app.services.expire_pending_bookings import expire_pending_bookings, get_expire_minutes
    _log = logging.getLogger(__name__)
    interval_minutes = max(1, int(os.getenv("PENDING_BOOKING_EXPIRE_CHECK_INTERVAL_MINUTES", "1")))
    interval_seconds = interval_minutes * 60
    expire_mins = get_expire_minutes()
    _log.info(
        "[EXPIRE] Pending booking expiry: expire after %s min, check every %s min",
        expire_mins,
        interval_minutes,
    )
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with SessionLocal() as db:
                n = await expire_pending_bookings(db)
            if n:
                _log.info("[EXPIRE] Expired %s unpaid pending booking(s)", n)
        except Exception as e:
            _log.exception("[EXPIRE] Error expiring pending bookings: %s", e)


async def _run_pickup_reminder_loop():
    """Every 30–60 min, send pickup reminder emails for bookings whose start_date is in ~24 hours."""
    from app.models import Booking, BookingStatus
    from app.services.booking_emails import send_pickup_reminder_email

    _log = logging.getLogger(__name__)
    interval_minutes = max(15, int(os.getenv("PICKUP_REMINDER_CHECK_INTERVAL_MINUTES", "30")))
    interval_seconds = interval_minutes * 60
    _log.info("[PICKUP_REMINDER] Loop started, check every %s min", interval_minutes)
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with SessionLocal() as db:
                now = datetime.now(timezone.utc)
                window_start = now + timedelta(hours=23)
                window_end = now + timedelta(hours=25)
                result = await db.execute(
                    select(Booking).where(
                        Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.ACTIVE]),
                        Booking.start_date >= window_start,
                        Booking.start_date <= window_end,
                        Booking.pickup_reminder_sent_at.is_(None),
                    )
                )
                bookings = result.scalars().all()
                for b in bookings:
                    try:
                        ok = await asyncio.to_thread(send_pickup_reminder_email, b.id)
                        if ok:
                            b.pickup_reminder_sent_at = now
                            await db.commit()
                    except Exception as e:
                        _log.exception("[PICKUP_REMINDER] Failed for booking_id=%s: %s", b.id, e)
        except Exception as e:
            _log.exception("[PICKUP_REMINDER] Loop error: %s", e)


# Ensure all error responses are valid JSON (avoids "JSON parse error" in production)
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logging.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

@app.get("/host/kyc/redirect", response_class=HTMLResponse)
def kyc_redirect_callback(
    return_to: Optional[str] = Query(None, description="Deep link to open the app after KYC"),
):
    """
    KYC callback without /api/v1 prefix. Use this URL if your proxy strips the path
    or you configured Veriff with https://your-domain/host/kyc/redirect.
    Same behavior as GET /api/v1/host/kyc/redirect.
    """
    from app.routers.host_kyc import build_kyc_redirect_response
    return build_kyc_redirect_response(return_to)


@app.get("/client/kyc/redirect", response_class=HTMLResponse)
def client_kyc_redirect_callback(
    return_to: Optional[str] = Query(None, description="Deep link to open the app after KYC"),
):
    """
    Client KYC callback without /api/v1 prefix.
    Same behavior as GET /api/v1/client/kyc/redirect.
    """
    from app.routers.client_kyc import build_client_kyc_redirect_response
    return build_client_kyc_redirect_response(return_to)


@app.get("/")
async def root():
    """Root endpoint - API information"""
    return {
        "message": "Car Rental API",
        "version": "1.0.0",
        "docs": "/docs",
        "api_base": "/api/v1"
    }


@app.get("/api/v1/ping")
async def api_ping(request: Request):
    """
    Simple JSON ping. Use this to verify the app is hitting the correct API.
    If you get a JSON parse error when calling this, the base URL is wrong
    or a proxy is returning HTML (e.g. 404/502 page). Correct base URL
    should be the host that serves this response, e.g. https://api.yourdomain.com
    """
    origin = request.headers.get("origin", "none")
    client_host = request.client.host if request.client else "unknown"
    return {
        "ok": True,
        "api": "v1",
        "message": "pong",
        "server_host": str(request.url.hostname),
        "client_ip": client_host,
        "origin": origin
    }


@app.get("/api")
async def api_info():
    """API information endpoint"""
    return {
        "message": "Car Rental API v1",
        "base_url": "/api/v1",
        "endpoints": {
            "docs": "/docs",
            "redoc": "/redoc",
            "health": "/health"
        }
    }


@app.get("/api/v1")
async def api_v1_info():
    """API v1 information endpoint"""
    return {
        "message": "Car Rental API v1",
        "version": "1.0.0",
        "endpoints": {
            "host_auth": "/api/v1/host/auth",
            "client_auth": "/api/v1/client/auth",
            "cars": "/api/v1/cars",
            "admin": "/api/v1/admin"
        }
    }


