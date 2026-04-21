from typing import Optional
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.exceptions import RequestValidationError
from starlette.datastructures import MutableHeaders
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except OSError:
        pass

from dotenv import load_dotenv
from app.config import settings

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from fastapi_cache.backends.redis import RedisBackend
from fastapi_cache.decorator import cache

limiter = Limiter(key_func=get_remote_address)


# =============================================================================
# PURE ASGI MIDDLEWARE  (no BaseHTTPMiddleware — avoids response body buffering)
# =============================================================================

class SecurityHeadersMiddleware:
    """Injects security headers without buffering the response body."""

    _HEADERS = [
        ("X-Frame-Options", "DENY"),
        ("X-Content-Type-Options", "nosniff"),
        ("X-XSS-Protection", "1; mode=block"),
        ("Strict-Transport-Security", "max-age=31536000; includeSubDomains"),
        ("Referrer-Policy", "strict-origin-when-cross-origin"),
        ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
        (
            "Content-Security-Policy",
            (
                "default-src 'self'; "
                "img-src 'self' data: https:; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "font-src 'self' data: https://cdn.jsdelivr.net; "
                "connect-src 'self' https:; "
                "frame-ancestors 'none'"
            ),
        ),
    ]

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def patched_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in self._HEADERS:
                    headers.append(name, value)
            await send(message)

        await self.app(scope, receive, patched_send)


class RequestLoggingMiddleware:
    """Logs each request + status + duration without buffering the response body."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.monotonic()
        method = scope.get("method", "")
        path = scope.get("path", "")
        status_code = 500

        async def patched_send(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        await self.app(scope, receive, patched_send)
        duration_ms = (time.monotonic() - start) * 1000
        logging.info("%s %s -> %s (%.0fms)", method, path, status_code, duration_ms)


# =============================================================================
# LOAD ENV + DATABASE
# =============================================================================

load_dotenv()

from app.database import engine, Base, SessionLocal
from app import models  # noqa: F401 — registers all ORM models
from app.models import DrivingLicense  # noqa: F401
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
    push_tokens,
    host_earnings,
    host_subscription,
    wallet as wallet_router,
    subscribers as subscribers_router,
    host_kyc as host_kyc_router,
    client_kyc as client_kyc_router,
    dojah_webhook as dojah_webhook_router,
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
from app.models import Admin, Booking, BookingStatus
from app.auth import get_password_hash, get_admin_by_email
from sqlalchemy import select, text
from sqlalchemy.orm import joinedload

app = FastAPI(
    title="Car Rental API",
    description="Backend API for car rental platform",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
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
        {"name": "Client Refunds", "description": "Client-visible refund records for bookings"},
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
        {"name": "Host KYC", "description": "Host KYC verification (Dojah)"},
        {"name": "Dojah Webhook", "description": "Dojah decision webhook (do not call directly)"},
    ],
    servers=[{"url": "/", "description": "Current host"}],
)

# =============================================================================
# MIDDLEWARE  (outermost first)
# =============================================================================

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=os.getenv(
        "CORS_ALLOW_ORIGIN_REGEX",
        r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$|^https://([a-z0-9-]+\.)?ardena\.(xyz|co\.ke)(:\d+)?$",
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)

# =============================================================================
# ROUTERS
# =============================================================================

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
app.include_router(client_emergency_router.router, prefix="/api/v1", tags=["Client Emergency"])
app.include_router(wishlist_router.router, prefix="/api/v1", tags=["Client Wishlist"])
app.include_router(payments.router, prefix="/api/v1", tags=["Payments"])
app.include_router(wallet_router.router, prefix="/api/v1", tags=["Ardena Pay"])
app.include_router(media.router, prefix="/api/v1", tags=["Media Upload"])
app.include_router(car_ratings.router, prefix="/api/v1", tags=["Car Ratings"])
app.include_router(agreements.router, prefix="/api/v1", tags=["Rental Agreements"])
app.include_router(push_tokens.router, prefix="/api/v1", tags=["Push Notifications"])
app.include_router(host_ratings.router, prefix="/api/v1", tags=["Host Ratings"])
app.include_router(client_ratings.router, prefix="/api/v1", tags=["Client Ratings"])
app.include_router(host_earnings.router, prefix="/api/v1", tags=["Host Earnings"])
app.include_router(host_subscription.router, prefix="/api/v1", tags=["Host Subscription"])
app.include_router(subscribers_router.router, prefix="/api/v1", tags=["Newsletter"])
app.include_router(host_kyc_router.router, prefix="/api/v1", tags=["Host KYC"])
app.include_router(client_kyc_router.router, prefix="/api/v1", tags=["Client KYC"])
app.include_router(dojah_webhook_router.router, prefix="/api/v1", tags=["Dojah Webhook"])
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

# =============================================================================
# STARTUP
# =============================================================================

@app.on_event("startup")
async def startup_init_cache():
    """Connect to Redis (falls back to in-memory if Redis is unavailable)."""
    try:
        import redis.asyncio as redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        redis_client = redis.from_url(redis_url, decode_responses=False)
        await redis_client.ping()
        FastAPICache.init(RedisBackend(redis_client), prefix="opa-cache:", expire=300)
        logging.info("[CACHE] Redis cache initialized")
    except Exception as exc:
        logging.warning("[CACHE] Redis unavailable, using in-memory cache: %s", exc)
        FastAPICache.init(InMemoryBackend(), prefix="opa-cache:", expire=300)


@app.on_event("startup")
async def startup_database():
    """Create any missing tables and start background tasks."""
    import asyncio as _asyncio
    from app.services.booking_emails import set_main_loop
    set_main_loop(_asyncio.get_running_loop())

    # Create tables that don't exist yet (safe, never drops existing tables)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _ensure_default_super_admin()

    logging.info("Startup complete — workers ready")

    asyncio.create_task(_run_expire_pending_bookings_loop())
    asyncio.create_task(_run_pickup_reminder_loop())
    asyncio.create_task(_run_push_reminder_loop())


# =============================================================================
# DEFAULT SUPER ADMIN
# =============================================================================

async def _ensure_default_super_admin():
    from sqlalchemy.exc import IntegrityError
    async with SessionLocal() as db:
        try:
            default_email = "admin@carrental.com"
            if await get_admin_by_email(db, default_email):
                return
            hashed = get_password_hash("Admin123!")
            db.add(Admin(
                full_name="Super Admin",
                email=default_email,
                hashed_password=hashed,
                role="super_admin",
                is_active=True,
            ))
            try:
                await db.commit()
                logging.warning(
                    "Default super admin created (email=%s). Change this password immediately!",
                    default_email,
                )
            except IntegrityError:
                await db.rollback()
        except Exception:
            logging.exception("Error ensuring default super admin")
            await db.rollback()


# =============================================================================
# BACKGROUND LOOPS
# =============================================================================

async def _run_expire_pending_bookings_loop():
    from app.services.expire_pending_bookings import expire_pending_bookings, get_expire_minutes
    _log = logging.getLogger(__name__)
    interval = max(1, int(os.getenv("PENDING_BOOKING_EXPIRE_CHECK_INTERVAL_MINUTES", "1"))) * 60
    _log.info("[EXPIRE] Checking every %ds, expiring after %dmin", interval, get_expire_minutes())
    while True:
        await asyncio.sleep(interval)
        try:
            async with SessionLocal() as db:
                n = await expire_pending_bookings(db)
            if n:
                _log.info("[EXPIRE] Expired %d unpaid booking(s)", n)
        except Exception:
            _log.exception("[EXPIRE] Error")


async def _run_pickup_reminder_loop():
    from app.services.booking_emails import send_pickup_reminder_email
    _log = logging.getLogger(__name__)
    interval = max(15, int(os.getenv("PICKUP_REMINDER_CHECK_INTERVAL_MINUTES", "30"))) * 60
    _log.info("[PICKUP_REMINDER] Checking every %ds", interval)
    while True:
        await asyncio.sleep(interval)
        try:
            async with SessionLocal() as db:
                now = datetime.now(timezone.utc)
                result = await db.execute(
                    select(Booking).where(
                        Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.ACTIVE]),
                        Booking.start_date >= now + timedelta(hours=23),
                        Booking.start_date <= now + timedelta(hours=25),
                        Booking.pickup_reminder_sent_at.is_(None),
                    )
                )
                for b in result.scalars().all():
                    try:
                        ok = await asyncio.to_thread(send_pickup_reminder_email, b.id)
                        if ok:
                            b.pickup_reminder_sent_at = now
                            await db.commit()
                    except Exception:
                        _log.exception("[PICKUP_REMINDER] booking_id=%s", b.id)
        except Exception:
            _log.exception("[PICKUP_REMINDER] Loop error")


async def _run_push_reminder_loop():
    from app.services.push_notifications import push_client_standalone, CHANNEL_REMINDER
    _log = logging.getLogger(__name__)
    interval = 15 * 60
    half = timedelta(minutes=30)
    _log.info("[PUSH_REMINDER] Checking every 15min")
    while True:
        await asyncio.sleep(interval)
        try:
            async with SessionLocal() as db:
                now = datetime.now(timezone.utc)
                windows = [
                    (10, "push_reminder_10h_sent_at", "Pickup in 10 Hours",
                     "Your {car} pickup is in 10 hours. Head to {location} at {time}."),
                    (5,  "push_reminder_5h_sent_at",  "Pickup in 5 Hours",
                     "Reminder: {car} pickup in 5 hours at {location}."),
                    (1,  "push_reminder_1h_sent_at",  "Pickup in 1 Hour!",
                     "Almost time! Your {car} pickup is in 1 hour at {location}."),
                ]
                for hours, col, title, tpl in windows:
                    sent_col = getattr(Booking, col)
                    result = await db.execute(
                        select(Booking)
                        .options(joinedload(Booking.car))
                        .where(
                            Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.ACTIVE]),
                            Booking.start_date >= now + timedelta(hours=hours) - half,
                            Booking.start_date <= now + timedelta(hours=hours) + half,
                            sent_col.is_(None),
                        )
                    )
                    for b in result.scalars().all():
                        try:
                            car_name = (
                                f"{b.car.name} {b.car.model}".strip()
                                if b.car and b.car.model else
                                (b.car.name if b.car else "your car")
                            )
                            body = tpl.format(
                                car=car_name,
                                location=b.pickup_location or "the pickup point",
                                time=b.pickup_time or "your scheduled time",
                            )
                            await push_client_standalone(
                                client_id=b.client_id, title=title, body=body,
                                data={"type": "pickup_reminder", "booking_id": str(b.booking_id), "hours_before": hours},
                                channel=CHANNEL_REMINDER,
                            )
                            setattr(b, col, now)
                            await db.commit()
                            _log.info("[PUSH_REMINDER] %dh reminder sent booking=%s", hours, b.booking_id)
                        except Exception:
                            _log.exception("[PUSH_REMINDER] %dh booking=%s", hours, b.booking_id)
        except Exception:
            _log.exception("[PUSH_REMINDER] Loop error")


# =============================================================================
# EXCEPTION HANDLERS
# =============================================================================

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logging.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# =============================================================================
# MISC ENDPOINTS
# =============================================================================

@app.get("/host/kyc/redirect", response_class=HTMLResponse)
def kyc_redirect_callback(return_to: Optional[str] = Query(None)):
    from app.routers.host_kyc import build_kyc_redirect_response
    return build_kyc_redirect_response(return_to)


@app.get("/client/kyc/redirect", response_class=HTMLResponse)
def client_kyc_redirect_callback(return_to: Optional[str] = Query(None)):
    from app.routers.client_kyc import build_client_kyc_redirect_response
    return build_client_kyc_redirect_response(return_to)


@app.get("/")
async def root():
    return {"message": "Car Rental API", "version": "1.0.0", "docs": "/docs", "api_base": "/api/v1"}


@app.get("/api/v1/ping")
async def api_ping(request: Request):
    return {
        "ok": True, "api": "v1", "message": "pong",
        "server_host": str(request.url.hostname),
        "client_ip": request.client.host if request.client else "unknown",
        "origin": request.headers.get("origin", "none"),
    }


@app.get("/api")
async def api_info():
    return {"message": "Car Rental API v1", "base_url": "/api/v1", "docs": "/docs"}
