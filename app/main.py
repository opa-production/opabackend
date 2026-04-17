"""
Application entry-point — wiring only, no business logic.

Structure:
  Middleware  →  app/core/middleware.py
  Config      →  app/core/config.py
  Security    →  app/core/security.py  |  app/api/deps.py
  DB          →  app/db/session.py     |  app/db/init_db.py
  Cache       →  app/cache/redis.py
  Workers     →  app/workers/scheduler.py
  Routers     →  app/api/v1/router.py
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# ── Windows console encoding fix ──────────────────────────────────────────────
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except OSError:
        pass

load_dotenv()

from app.api.v1.router import api_router
from app.cache.redis import init_cache
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.middleware import RequestLoggingMiddleware, SecurityHeadersMiddleware
from app.core.rate_limit import limiter
from app.db.init_db import startup_database

setup_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_cache()
    await startup_database()
    yield

# ── App factory ───────────────────────────────────────────────────────────────
app = FastAPI(
    lifespan=lifespan,
    title="Car Rental API",
    description="Backend API for car rental platform",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=[
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
        {
            "name": "Host Earnings",
            "description": "Host earnings summary, transactions, and withdrawal requests",
        },
        {
            "name": "Host Subscription",
            "description": "Host paid plans (M-Pesa) and subscription status",
        },
        {
            "name": "Client Refunds",
            "description": "Client-visible refund records for bookings",
        },
        {
            "name": "Client Emergency",
            "description": "Emergency messages from clients with location",
        },
        {"name": "Client Wishlist", "description": "Client car wishlist (liked cars)"},
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
        {
            "name": "Admin Withdrawals",
            "description": "View and process host withdrawal requests",
        },
        {
            "name": "Admin Refunds",
            "description": "Track and manage booking refunds for finance",
        },
        {"name": "Newsletter", "description": "Public subscribe / unsubscribe"},
        {
            "name": "Admin Subscribers",
            "description": "Newsletter subscriber list and send email to all",
        },
        {"name": "Host KYC", "description": "Host KYC verification (Veriff)"},
        {"name": "Client KYC", "description": "Client KYC verification (Veriff)"},
        {
            "name": "Veriff Webhook",
            "description": "Veriff decision webhook (do not call directly)",
        },
    ],
    servers=[{"url": "/", "description": "Current host"}],
)

# ── Middleware (order matters — first added = outermost) ──────────────────────
# 1. Security headers (X-Frame-Options, CSP, HSTS …)
app.add_middleware(SecurityHeadersMiddleware)

# 2. Trusted host - Restrict to known domains for security
allowed_hosts = ["ardena.co.ke", "adminnn.ardena.xyz"]
# Add localhost variations for development
if os.getenv("ENVIRONMENT", "development").lower() in ["development", "dev", "local"]:
    allowed_hosts.extend(["localhost", "127.0.0.1"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

# 3. Rate-limiter state + error handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 4. Gzip compression
app.add_middleware(GZipMiddleware, minimum_size=1000)

# 5. CORS - Allow only explicitly configured origins for security
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=[
        "Accept",
        "Accept-Language", 
        "Content-Language",
        "Content-Type",
        "Authorization",
        "X-Requested-With",
    ],
    expose_headers=["X-Total-Count", "X-Rate-Limit-Remaining"],
)

# 6. Request logging (innermost — closest to handlers)
app.add_middleware(RequestLoggingMiddleware)


# ── API v1 ────────────────────────────────────────────────────────────────────
app.include_router(api_router, prefix="/api/v1")


# ── KYC redirect helpers (no /api/v1 prefix) ─────────────────────────────────
@app.get("/host/kyc/redirect", response_class=HTMLResponse, include_in_schema=False)
def kyc_redirect_callback(
    return_to: Optional[str] = Query(
        None, description="Deep link to open the app after KYC"
    ),
):
    """
    KYC callback without /api/v1 prefix.  Use when your proxy strips the path
    or Veriff is configured with https://your-domain/host/kyc/redirect.
    Delegates to the versioned handler.
    """
    from app.api.v1.endpoints.host_kyc import build_kyc_redirect_response

    return build_kyc_redirect_response(return_to)


@app.get("/client/kyc/redirect", response_class=HTMLResponse, include_in_schema=False)
def client_kyc_redirect_callback(
    return_to: Optional[str] = Query(
        None, description="Deep link to open the app after KYC"
    ),
):
    """Client KYC callback without /api/v1 prefix.  Delegates to the versioned handler."""
    from app.api.v1.endpoints.client_kyc import build_client_kyc_redirect_response

    return build_client_kyc_redirect_response(return_to)


# ── Exception handlers ────────────────────────────────────────────────────────
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


# ── Core routes ───────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def root():
    return {
        "message": "Car Rental API testing",
        "version": "1.0.0",
        "docs": "/docs",
        "api_base": "/api/v1",
    }


@app.get("/api/v1/ping", tags=["Health"])
async def api_ping(request: Request):
    """
    Simple liveness probe.  If this returns a non-JSON response your base URL
    is wrong (proxy is returning an HTML error page).
    """
    return {
        "ok": True,
        "api": "v1",
        "message": "pong",
        "server_host": str(request.url.hostname),
        "client_ip": request.client.host if request.client else "unknown",
        "origin": request.headers.get("origin", "none"),
    }


@app.get("/api", include_in_schema=False)
async def api_info():
    return {
        "message": "Car Rental API",
        "base_url": "/api/v1",
        "endpoints": {"docs": "/docs", "redoc": "/redoc"},
    }


@app.get("/api/v1", include_in_schema=False)
async def api_v1_info():
    return {
        "message": "Car Rental API v1",
        "version": "1.0.0",
        "endpoints": {
            "host_auth": "/api/v1/host/auth",
            "client_auth": "/api/v1/client/auth",
            "cars": "/api/v1/cars",
            "admin": "/api/v1/admin",
        },
    }
