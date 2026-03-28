import logging
import os
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


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
        response.headers["Strict-Transport-Security"] = (
            f"max-age={hsts_max_age}; includeSubDomains"
        )

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
            "frame-ancestors 'none'",
        )
        response.headers["Content-Security-Policy"] = csp_policy

        # Referrer Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions Policy (disable features not needed)
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )

        return response
