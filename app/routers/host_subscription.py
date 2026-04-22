"""
Host subscription: M-Pesa checkout (Payhero STK), Paystack card checkout, and current plan APIs.
"""
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi_cache.decorator import cache
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth import get_current_host
from app.models import Host, HostSubscriptionPayment
from app.schemas import (
    HostSubscriptionCardCheckoutRequest,
    HostSubscriptionCardCheckoutResponse,
    HostSubscriptionCheckoutRequest,
    HostSubscriptionCheckoutResponse,
    HostSubscriptionMeResponse,
    HostSubscriptionPaymentStatusResponse,
    HostSubscriptionPaymentStatusEnum,
    HostSubscriptionPlansResponse,
    HostSubscriptionPlanPublic,
    HostTrialActivateResponse,
)
from app.services.host_subscription_payment import (
    activate_free_trial,
    activate_host_subscription_from_paystack,
    expire_stale_host_subscription_payments,
    free_trial_duration_days,
    get_active_pending_subscription_payment,
    get_paid_plan_details,
    get_pending_paystack_host_subscription,
    get_subscription_plan_catalog,
    host_is_on_trial,
    host_paid_subscription_active,
    host_trial_available,
    pending_subscription_seconds_remaining,
    stk_pending_window_seconds,
    sync_pending_host_subscription_from_payhero,
    CARD_REF_PREFIX,
)
from app.services.paystack_payment import (
    async_initialize_transaction as paystack_initialize,
    async_verify_transaction as paystack_verify,
)
from app.services.mpesa_stk_push import sendStkPush
from app.cache_utils import host_scoped_cache_key, invalidate_host_cache_namespaces

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
@cache(expire=120, namespace="host-subscription-me", key_builder=host_scoped_cache_key)
async def get_my_subscription(
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """Current host's subscription tier and expiry (free if never paid or expired)."""
    result = await db.execute(select(Host).where(Host.id == current_host.id))
    host = result.scalar_one_or_none()
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
    pending = await get_active_pending_subscription_payment(db, host.id)
    pending_secs = pending_subscription_seconds_remaining(pending) if pending else None
    pending_card = await get_pending_paystack_host_subscription(db, host.id)

    return HostSubscriptionMeResponse(
        plan=plan,
        expires_at=exp,
        is_paid_active=paid_active,
        is_trial=host_is_on_trial(host, now),
        trial_available=host_trial_available(host),
        days_remaining=days_remaining,
        has_pending_checkout=bool(pending),
        pending_plan=pending.plan if pending else None,
        pending_checkout_request_id=(pending.checkout_request_id if pending else None),
        pending_seconds_remaining=pending_secs,
        stk_pending_window_seconds=window_sec,
        pending_paystack_reference=(pending_card.paystack_reference if pending_card else None),
    )


@router.post(
    "/host/subscription/trial",
    response_model=HostTrialActivateResponse,
    status_code=status.HTTP_200_OK,
)
async def activate_host_free_trial(
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Activate the one-time 30-day free trial of the **starter** plan.

    - Only available to hosts who have never used the trial before.
    - Only available when currently on the **free** plan.
    - No payment required — activates immediately.
    - After the trial expires the host returns to the free plan unless they subscribe.
    """
    result = await db.execute(select(Host).where(Host.id == current_host.id))
    host = result.scalar_one_or_none()
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")

    try:
        expires_at, days = await activate_free_trial(db, host)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await invalidate_host_cache_namespaces(current_host.id, ["host-subscription-me"])

    return HostTrialActivateResponse(
        message=f"Your {days}-day free trial of the Starter plan is now active. Enjoy!",
        plan="starter",
        expires_at=expires_at,
        days_granted=days,
    )


@router.post(
    "/host/subscription/checkout",
    response_model=HostSubscriptionCheckoutResponse,
    status_code=status.HTTP_200_OK,
)
async def host_subscription_checkout(
    body: HostSubscriptionCheckoutRequest,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
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
    existing = await get_active_pending_subscription_payment(db, current_host.id)
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
    await db.flush()
    rec.external_reference = f"H-SUB-{rec.id}"
    await db.commit()
    await db.refresh(rec)

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

    mpesa_response = await sendStkPush(
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
        await db.commit()
        err = rec.result_desc or "M-Pesa STK failed"
        raise HTTPException(status_code=400, detail=err)

    checkout_id = mpesa_response.get("CheckoutRequestID")
    rec.checkout_request_id = checkout_id
    await db.commit()
    await invalidate_host_cache_namespaces(current_host.id, ["host-subscription-me"])

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
    db: AsyncSession = Depends(get_db),
):
    """Poll subscription payment status after STK (same idea as client booking payment status)."""
    await expire_stale_host_subscription_payments(db, current_host.id)
    lookup_id = (checkout_request_id or "").strip()
    result = await db.execute(
        select(HostSubscriptionPayment)
        .where(
            HostSubscriptionPayment.host_id == current_host.id,
            HostSubscriptionPayment.checkout_request_id == lookup_id,
        )
        .order_by(HostSubscriptionPayment.id.desc())
    )
    rec = result.scalars().first()
    if not rec:
        raise HTTPException(status_code=404, detail="No subscription payment found for this checkout id")

    # If webhook never reached us, refresh from Payhero (GET transaction-status) — same backup idea as Pesapal on client status.
    if rec.status == "pending":
        await sync_pending_host_subscription_from_payhero(db, rec)
        await db.refresh(rec)

    try:
        st = HostSubscriptionPaymentStatusEnum(rec.status)
    except ValueError:
        st = HostSubscriptionPaymentStatusEnum.failed

    msg = rec.result_desc
    if st == HostSubscriptionPaymentStatusEnum.pending:
        msg = msg or "Waiting for M-Pesa confirmation…"
    elif st == HostSubscriptionPaymentStatusEnum.expired:
        msg = msg or "Checkout timed out — you can start again."

    response = HostSubscriptionPaymentStatusResponse(
        checkout_request_id=rec.checkout_request_id,
        external_reference=rec.external_reference,
        plan=rec.plan,
        amount_kes=rec.amount_ksh,
        status=st,
        message=msg,
        mpesa_receipt_number=rec.mpesa_receipt_number,
    )
    if st != HostSubscriptionPaymentStatusEnum.pending:
        await invalidate_host_cache_namespaces(current_host.id, ["host-subscription-me"])
    return response


@router.post(
    "/host/subscription/checkout/card",
    response_model=HostSubscriptionCardCheckoutResponse,
    status_code=status.HTTP_200_OK,
)
async def host_subscription_card_checkout(
    body: HostSubscriptionCardCheckoutRequest,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Start a Paystack hosted card checkout for **starter** or **premium** subscription.

    No card details are collected or stored by us — the host is redirected to Paystack's
    secure hosted page.  After payment the host is returned to the host app via
    `HOST_FRONTEND_URL` (configured in server env).

    After calling this endpoint:
    1. Open `authorization_url` in a browser / in-app WebView.
    2. Poll `GET /host/subscription/card-status?paystack_reference=<ref>` until status is
       `completed` or `failed`.
    """
    callback_base = os.getenv("PAYSTACK_CALLBACK_BASE_URL", "").rstrip("/")
    if not callback_base:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Card payment is not configured on this server (PAYSTACK_CALLBACK_BASE_URL missing).",
        )

    plan = body.plan.value
    try:
        amount, duration_days = get_paid_plan_details(plan)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid plan price (check HOST_SUB_* env vars).")

    result = await db.execute(select(Host).where(Host.id == current_host.id))
    host = result.scalar_one_or_none()
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")

    # One pending card checkout at a time
    existing = await get_pending_paystack_host_subscription(db, host.id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "A card checkout is already in progress. "
                "Complete it or wait a moment, then try again."
            ),
        )

    # Create the payment record first so we have an id for the reference
    pending_ref = f"INIT-{secrets.token_hex(8)}"
    rec = HostSubscriptionPayment(
        host_id=host.id,
        plan=plan,
        amount_ksh=float(amount),
        duration_days=duration_days,
        payment_method="card",
        external_reference=pending_ref,
        status="pending",
    )
    db.add(rec)
    await db.flush()

    paystack_ref = f"{CARD_REF_PREFIX}{rec.id}-{secrets.token_hex(4)}"
    rec.external_reference = paystack_ref
    await db.commit()
    await db.refresh(rec)

    callback_url = f"{callback_base}/paystack/host-callback"
    ps_result = paystack_initialize(
        email=host.email,
        amount_kes=float(amount),
        reference=paystack_ref,
        callback_url=callback_url,
        metadata={
            "host_id": host.id,
            "plan": plan,
            "sub_payment_id": rec.id,
        },
    )

    if ps_result.get("status") != "success":
        rec.status = "failed"
        rec.result_desc = ps_result.get("message", "Paystack initialization failed")
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=ps_result.get("message", "Paystack initialization failed"),
        )

    rec.paystack_reference = ps_result["reference"]
    await db.commit()
    await invalidate_host_cache_namespaces(host.id, ["host-subscription-me"])

    logger.info(
        "[HOST SUB CARD] Initialized plan=%s amount=%s ref=%s host_id=%s",
        plan, amount, rec.paystack_reference, host.id,
    )

    return HostSubscriptionCardCheckoutResponse(
        message=(
            "Open the authorization_url to complete payment. "
            "Poll /host/subscription/card-status?paystack_reference=<ref> for status."
        ),
        plan=plan,
        amount_kes=int(amount),
        paystack_reference=rec.paystack_reference,
        authorization_url=ps_result["authorization_url"],
    )


@router.get(
    "/host/subscription/card-status",
    response_model=HostSubscriptionPaymentStatusResponse,
)
async def host_subscription_card_status(
    paystack_reference: str = Query(..., description="paystack_reference from card checkout response"),
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Poll the status of a Paystack card subscription payment.

    Returns `pending` while the host is on the Paystack page.
    Returns `completed` once payment is confirmed via webhook.
    Returns `failed` if the card was declined or the payment was abandoned.
    """
    result = await db.execute(
        select(HostSubscriptionPayment)
        .where(
            HostSubscriptionPayment.host_id == current_host.id,
            HostSubscriptionPayment.paystack_reference == paystack_reference.strip(),
        )
        .order_by(HostSubscriptionPayment.id.desc())
    )
    rec = result.scalars().first()
    if not rec:
        raise HTTPException(status_code=404, detail="No card subscription payment found for this reference")

    # Fallback: if still pending, verify directly with Paystack (handles missed webhooks)
    if rec.status == "pending":
        ps = paystack_verify(paystack_reference.strip())
        if ps.get("status") == "success":
            ps_payment_status = ps.get("payment_status", "")
            if ps_payment_status == "success":
                await activate_host_subscription_from_paystack(db, rec, ps)
                await db.refresh(rec)
            elif ps_payment_status in ("failed", "abandoned"):
                rec.status = "failed"
                rec.result_desc = f"Card payment {ps_payment_status}"
                await db.commit()
                await db.refresh(rec)

    try:
        st = HostSubscriptionPaymentStatusEnum(rec.status)
    except ValueError:
        st = HostSubscriptionPaymentStatusEnum.failed

    msg = rec.result_desc
    if st == HostSubscriptionPaymentStatusEnum.pending:
        msg = msg or "Waiting for card payment confirmation…"

    if st != HostSubscriptionPaymentStatusEnum.pending:
        await invalidate_host_cache_namespaces(current_host.id, ["host-subscription-me"])

    return HostSubscriptionPaymentStatusResponse(
        checkout_request_id=None,
        external_reference=rec.external_reference,
        plan=rec.plan,
        amount_kes=rec.amount_ksh,
        status=st,
        message=msg,
        mpesa_receipt_number=None,
        paystack_reference=rec.paystack_reference,
        paystack_card_last4=rec.paystack_card_last4,
        paystack_card_brand=rec.paystack_card_brand,
    )
