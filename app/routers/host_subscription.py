"""
Host subscription: M-Pesa checkout (Payhero STK) and current plan APIs.
"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import get_current_host
from app.models import Host, HostSubscriptionPayment
from app.schemas import (
    HostSubscriptionCheckoutRequest,
    HostSubscriptionCheckoutResponse,
    HostSubscriptionMeResponse,
    HostSubscriptionPaymentStatusResponse,
    HostSubscriptionPaymentStatusEnum,
    HostSubscriptionPlansResponse,
    HostSubscriptionPlanPublic,
)
from app.services.host_subscription_payment import (
    expire_stale_host_subscription_payments,
    get_active_pending_subscription_payment,
    get_paid_plan_details,
    get_subscription_plan_catalog,
    host_paid_subscription_active,
    pending_subscription_seconds_remaining,
    stk_pending_window_seconds,
    sync_pending_host_subscription_from_payhero,
)
from app.services.mpesa_stk_push import sendStkPush

logger = logging.getLogger(__name__)

router = APIRouter()


def _normalize_mpesa_phone(raw: str) -> str:
    mpesa_phone = str(raw).strip().replace(" ", "")
    if mpesa_phone.startswith("0"):
        mpesa_phone = "254" + mpesa_phone[1:]
    elif not mpesa_phone.startswith("254"):
        mpesa_phone = "254" + mpesa_phone
    return mpesa_phone


@router.get("/host/subscription/plans", response_model=HostSubscriptionPlansResponse)
async def list_host_subscription_plans():
    """
    Public catalog of host subscription plans (free, starter, premium) and KES prices.
    Prices/durations are driven by env: HOST_SUB_* (see .env.example).
    """
    rows = get_subscription_plan_catalog()
    return HostSubscriptionPlansResponse(
        plans=[HostSubscriptionPlanPublic(**r) for r in rows]
    )


@router.get("/host/subscription/me", response_model=HostSubscriptionMeResponse)
async def get_my_subscription(
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db),
):
    """Current host's subscription tier and expiry (free if never paid or expired)."""
    host = db.query(Host).filter(Host.id == current_host.id).first()
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")

    plan = (host.subscription_plan or "free").lower()
    exp = host.subscription_expires_at
    if exp and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    paid_active = host_paid_subscription_active(host, now)
    days_remaining = None
    if exp and paid_active:
        days_remaining = max(0, (exp - now).days)

    window_sec = stk_pending_window_seconds()
    pending = get_active_pending_subscription_payment(db, host.id)
    pending_secs = pending_subscription_seconds_remaining(pending) if pending else None

    return HostSubscriptionMeResponse(
        plan=plan,
        expires_at=exp,
        is_paid_active=paid_active,
        days_remaining=days_remaining,
        has_pending_checkout=bool(pending),
        pending_plan=pending.plan if pending else None,
        pending_checkout_request_id=(pending.checkout_request_id if pending else None),
        pending_seconds_remaining=pending_secs,
        stk_pending_window_seconds=window_sec,
    )


@router.post(
    "/host/subscription/checkout",
    response_model=HostSubscriptionCheckoutResponse,
    status_code=status.HTTP_200_OK,
)
async def host_subscription_checkout(
    body: HostSubscriptionCheckoutRequest,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db),
):
    """
    Start M-Pesa STK Push for **starter** or **premium** subscription (Payhero, same as bookings).

    After success, poll:
    `GET /api/v1/host/subscription/payment-status?checkout_request_id=<CheckoutRequestID>`
    """
    plan = body.plan.value
    try:
        amount, duration_days = get_paid_plan_details(plan)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="Invalid plan price (check HOST_SUB_* env vars).",
        )

    # One in-window pending STK per host (server auto-expires after HOST_SUB_STK_PENDING_WINDOW_SECONDS)
    existing = get_active_pending_subscription_payment(db, current_host.id)
    if existing:
        sec = pending_subscription_seconds_remaining(existing)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "A subscription payment is already in progress. Approve on your phone, "
                f"or wait about {sec} second(s) to try again."
            ),
        )

    pending_ref = f"PENDING-{uuid.uuid4().hex}"
    rec = HostSubscriptionPayment(
        host_id=current_host.id,
        plan=plan,
        amount_ksh=float(amount),
        duration_days=duration_days,
        external_reference=pending_ref,
        status="pending",
    )
    db.add(rec)
    db.flush()
    rec.external_reference = f"H-SUB-{rec.id}"
    db.commit()
    db.refresh(rec)

    phone = _normalize_mpesa_phone(body.phone_number)
    amount_str = str(int(amount))

    logger.info(
        "[HOST SUB STK] host_id=%s plan=%s amount=%s ref=%s phone=%s",
        current_host.id,
        plan,
        amount_str,
        rec.external_reference,
        phone[:5] + "***",
    )

    mpesa_response = sendStkPush(
        amount=amount_str,
        PhoneNumber=phone,
        AccountReference=rec.external_reference,
    )

    if mpesa_response is None or mpesa_response.get("ResponseCode") != "0":
        rec.status = "failed"
        rec.result_desc = (
            (mpesa_response or {}).get("ResponseDescription", "STK failed")
            if mpesa_response
            else "No response from M-Pesa"
        )
        db.commit()
        err = rec.result_desc or "M-Pesa STK failed"
        raise HTTPException(status_code=400, detail=err)

    checkout_id = mpesa_response.get("CheckoutRequestID")
    rec.checkout_request_id = checkout_id
    db.commit()

    return HostSubscriptionCheckoutResponse(
        message="M-Pesa STK Push sent. Approve on your phone to activate your subscription.",
        plan=plan,
        amount_kes=int(amount),
        checkout_request_id=checkout_id,
        external_reference=rec.external_reference,
        stk_pending_window_seconds=stk_pending_window_seconds(),
    )


@router.get("/host/subscription/payment-status", response_model=HostSubscriptionPaymentStatusResponse)
async def host_subscription_payment_status(
    checkout_request_id: str = Query(..., description="CheckoutRequestID from checkout response"),
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db),
):
    """Poll subscription payment status after STK (same idea as client booking payment status)."""
    expire_stale_host_subscription_payments(db, current_host.id)
    lookup_id = (checkout_request_id or "").strip()
    rec = (
        db.query(HostSubscriptionPayment)
        .filter(
            HostSubscriptionPayment.host_id == current_host.id,
            HostSubscriptionPayment.checkout_request_id == lookup_id,
        )
        .order_by(HostSubscriptionPayment.id.desc())
        .first()
    )
    if not rec:
        raise HTTPException(status_code=404, detail="No subscription payment found for this checkout id")

    # If webhook never reached us, refresh from Payhero (GET transaction-status) — same backup idea as Pesapal on client status.
    if rec.status == "pending":
        sync_pending_host_subscription_from_payhero(db, rec)
        db.refresh(rec)

    try:
        st = HostSubscriptionPaymentStatusEnum(rec.status)
    except ValueError:
        st = HostSubscriptionPaymentStatusEnum.failed

    msg = rec.result_desc
    if st == HostSubscriptionPaymentStatusEnum.pending:
        msg = msg or "Waiting for M-Pesa confirmation…"
    elif st == HostSubscriptionPaymentStatusEnum.expired:
        msg = msg or "Checkout timed out — you can start again."

    return HostSubscriptionPaymentStatusResponse(
        checkout_request_id=rec.checkout_request_id,
        external_reference=rec.external_reference,
        plan=rec.plan,
        amount_kes=rec.amount_ksh,
        status=st,
        message=msg,
        mpesa_receipt_number=rec.mpesa_receipt_number,
    )
