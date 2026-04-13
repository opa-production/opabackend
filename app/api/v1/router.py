"""
API v1 — master router.
All feature routers are registered here and included in main.py.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    bookings,
    cars,
    client_auth,
    client_emergency,
    client_kyc,
    client_ratings,
    client_refunds,
    feedback,
    host_auth,
    host_earnings,
    host_kyc,
    host_ratings,
    host_subscription,
    identity_verification,
    media,
    messages,
    payment_methods,
    payments,
    subscribers,
    support,
    veriff_webhook,
    wallet,
    wishlist,
)
from app.api.v1.endpoints.admin import (
    admins as admin_admins,
)
from app.api.v1.endpoints.admin import (
    auth as admin_auth,
)
from app.api.v1.endpoints.admin import (
    bookings as admin_bookings,
)
from app.api.v1.endpoints.admin import (
    cars as admin_cars,
)
from app.api.v1.endpoints.admin import (
    dashboard as admin_dashboard,
)
from app.api.v1.endpoints.admin import (
    feedback as admin_feedback,
)
from app.api.v1.endpoints.admin import (
    notifications as admin_notifications,
)
from app.api.v1.endpoints.admin import (
    payment_methods as admin_payment_methods,
)
from app.api.v1.endpoints.admin import (
    refunds as admin_refunds,
)
from app.api.v1.endpoints.admin import (
    subscribers as admin_subscribers,
)
from app.api.v1.endpoints.admin import (
    support as admin_support,
)
from app.api.v1.endpoints.admin import (
    users as admin_users,
)
from app.api.v1.endpoints.admin import (
    withdrawals as admin_withdrawals,
)

api_router = APIRouter()

# ── Client / Host routes ──────────────────────────────────────────────────────
api_router.include_router(host_auth.router, tags=["Host Auth"])
api_router.include_router(client_auth.router, tags=["Client Auth"])
api_router.include_router(cars.router, tags=["Car Management"])
api_router.include_router(payment_methods.router, tags=["Payment Methods"])
api_router.include_router(feedback.router, tags=["Feedback"])
api_router.include_router(support.router, tags=["Support Messages"])
api_router.include_router(messages.router, tags=["Client-Host Messages"])
api_router.include_router(bookings.router, tags=["Bookings"])
api_router.include_router(payments.router, tags=["Payments"])
api_router.include_router(media.router, tags=["Media Upload"])
api_router.include_router(host_ratings.router, tags=["Host Ratings"])
api_router.include_router(client_ratings.router, tags=["Client Ratings"])
api_router.include_router(host_earnings.router, tags=["Host Earnings"])
api_router.include_router(subscribers.router, tags=["Newsletter"])
api_router.include_router(host_kyc.router, tags=["Host KYC"])
api_router.include_router(client_kyc.router, tags=["Client KYC"])
api_router.include_router(veriff_webhook.router, tags=["Veriff Webhook"])
api_router.include_router(client_refunds.router, tags=["Client Refunds"])
api_router.include_router(client_emergency.router, tags=["Client Emergency"])
api_router.include_router(identity_verification.router, tags=["Identity Verification"])
api_router.include_router(wishlist.router, tags=["Client Wishlist"])
api_router.include_router(wallet.router, tags=["Wallet"])
api_router.include_router(host_subscription.router, tags=["Host Subscription"])

# ── Admin routes ──────────────────────────────────────────────────────────────
api_router.include_router(admin_auth.router, tags=["Admin Auth"])
api_router.include_router(admin_users.router, tags=["Admin User Management"])
api_router.include_router(admin_cars.router, tags=["Admin Car Management"])
api_router.include_router(admin_dashboard.router, tags=["Admin Dashboard"])
api_router.include_router(admin_feedback.router, tags=["Admin Feedback Management"])
api_router.include_router(admin_notifications.router, tags=["Admin Notifications"])
api_router.include_router(admin_admins.router, tags=["Admin Management"])
api_router.include_router(admin_payment_methods.router, tags=["Admin Payment Methods"])
api_router.include_router(admin_support.router, tags=["Admin Support"])
api_router.include_router(admin_bookings.router, tags=["Admin Bookings"])
api_router.include_router(admin_withdrawals.router, tags=["Admin Withdrawals"])
api_router.include_router(admin_subscribers.router, tags=["Admin Subscribers"])
api_router.include_router(admin_refunds.router, tags=["Admin Refunds"])
