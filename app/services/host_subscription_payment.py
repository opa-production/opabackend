"""
Host subscription M-Pesa (Payhero) — pricing config and callback handling.
Uses same /payments/mpesa/callback as booking STK; external_reference prefix H-SUB-.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Host, HostSubscriptionPayment
from app.services.mpesa_callback_utils import infer_insufficient_funds, normalize_stk_result_code

logger = logging.getLogger(__name__)

REF_PREFIX = "H-SUB-"


def stk_pending_window_seconds() -> int:
    """How long an STK push stays 'pending' before auto-expiring (no PIN / abandoned)."""
    return max(30, min(600, _int_env("HOST_SUB_STK_PENDING_WINDOW_SECONDS", 90)))


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


def _ensure_aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def get_subscription_plan_catalog() -> list[dict[str, Any]]:
    """Public catalog: free + paid tiers (prices from env)."""
    starter_price = _int_env("HOST_SUB_STARTER_PRICE_KES", 3500)
    premium_price = _int_env("HOST_SUB_PREMIUM_PRICE_KES", 6500)
    starter_days = _int_env("HOST_SUB_STARTER_DURATION_DAYS", 30)
    premium_days = _int_env("HOST_SUB_PREMIUM_DURATION_DAYS", 30)

    return [
        {
            "code": "free",
            "name": "Free",
            "description": "Default plan — list and operate with standard limits.",
            "price_kes": 0,
            "duration_days": 0,
            "features": [
                "No monthly fee",
                "Standard host features",
            ],
        },
        {
            "code": "starter",
            "name": "Starter",
            "description": "Paid starter tier for growing hosts.",
            "price_kes": starter_price,
            "duration_days": starter_days,
            "features": [
                f"KES {starter_price:,} per {starter_days} days",
                "Unlock starter benefits in app",
            ],
        },
        {
            "code": "premium",
            "name": "Premium",
            "description": "Full premium host subscription.",
            "price_kes": premium_price,
            "duration_days": premium_days,
            "features": [
                f"KES {premium_price:,} per {premium_days} days",
                "Unlock premium benefits in app",
            ],
        },
    ]


async def expire_stale_host_subscription_payments(
    db: AsyncSession, host_id: Optional[int] = None
) -> int:
    """
    Mark subscription STK rows stuck in `pending` longer than stk_pending_window_seconds() as `expired`.
    Host can start a new checkout after that (no more "wait 15 minutes" lockout).
    """
    window_sec = stk_pending_window_seconds()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=window_sec)

    stmt = select(HostSubscriptionPayment).where(HostSubscriptionPayment.status == "pending")
    if host_id is not None:
        stmt = stmt.where(HostSubscriptionPayment.host_id == host_id)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    updated = 0
    for row in rows:
        ca = _ensure_aware_utc(row.created_at)
        if ca is None or ca >= cutoff:
            continue
        row.status = "expired"
        row.result_desc = (
            f"No PIN entered within {window_sec} seconds — you can start checkout again."
        )
        updated += 1

    if updated:
        await db.commit()
    return updated


async def get_active_pending_subscription_payment(
    db: AsyncSession, host_id: int
) -> Optional[HostSubscriptionPayment]:
    """After expiring stale rows, return the host's current in-window pending STK, if any."""
    await expire_stale_host_subscription_payments(db, host_id)
    window_sec = stk_pending_window_seconds()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=window_sec)

    result = await db.execute(
        select(HostSubscriptionPayment)
        .where(
            HostSubscriptionPayment.host_id == host_id,
            HostSubscriptionPayment.status == "pending",
        )
        .order_by(HostSubscriptionPayment.id.desc())
    )
    pendings = list(result.scalars().all())
    for p in pendings:
        ca = _ensure_aware_utc(p.created_at)
        if ca is not None and ca >= cutoff:
            return p
    return None


def pending_subscription_seconds_remaining(payment: HostSubscriptionPayment) -> int:
    """Seconds left in the STK window (0 if past window — caller should expire first)."""
    window_sec = stk_pending_window_seconds()
    now = datetime.now(timezone.utc)
    ca = _ensure_aware_utc(payment.created_at)
    if ca is None:
        return 0
    end = ca + timedelta(seconds=window_sec)
    return max(0, int((end - now).total_seconds()))


def get_paid_plan_details(plan: str) -> Tuple[int, int]:
    """Return (price_kes, duration_days) for starter or premium."""
    plan = (plan or "").lower().strip()
    if plan == "starter":
        return (
            _int_env("HOST_SUB_STARTER_PRICE_KES", 3500),
            _int_env("HOST_SUB_STARTER_DURATION_DAYS", 30),
        )
    if plan == "premium":
        return (
            _int_env("HOST_SUB_PREMIUM_PRICE_KES", 6500),
            _int_env("HOST_SUB_PREMIUM_DURATION_DAYS", 30),
        )
    raise ValueError(f"Unknown paid plan: {plan}")


def _parse_h_sub_ref(external_reference: Optional[str]) -> Optional[int]:
    if not external_reference:
        return None
    s = str(external_reference).strip()
    if not s.startswith(REF_PREFIX):
        return None
    m = re.match(rf"^{re.escape(REF_PREFIX)}(\d+)$", s)
    if not m:
        return None
    return int(m.group(1))


def host_paid_subscription_active(host: Host, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if (host.subscription_plan or "free").lower() == "free":
        return False
    exp = _ensure_aware_utc(host.subscription_expires_at)
    if not exp:
        return False
    return exp > now


def _payhero_subscription_sync_enabled() -> bool:
    """Poll Payhero GET transaction-status when host app polls payment-status (callback backup)."""
    v = os.getenv("HOST_SUB_SYNC_PAYHERO_STATUS", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


async def _host_subscription_mark_success(
    db: AsyncSession,
    sub: HostSubscriptionPayment,
    *,
    result_code_str: str,
    result_desc: Optional[str],
    receipt: Any,
    phone: Any,
    transaction_date: Any,
) -> None:
    sub.status = "completed"
    sub.result_code = result_code_str
    sub.result_desc = str(result_desc).strip() if result_desc else None
    sub.mpesa_receipt_number = str(receipt) if receipt else None
    sub.mpesa_phone = str(phone) if phone else None
    sub.mpesa_transaction_date = str(transaction_date) if transaction_date else None

    h_result = await db.execute(select(Host).where(Host.id == sub.host_id))
    host = h_result.scalar_one_or_none()
    if host:
        now = datetime.now(timezone.utc)
        duration = timedelta(days=int(sub.duration_days))
        current_end = _ensure_aware_utc(host.subscription_expires_at)
        base = now
        if current_end and current_end > base:
            base = current_end
        new_end = base + duration
        host.subscription_plan = sub.plan
        host.subscription_expires_at = new_end
        logger.info(
            "[HOST SUB] Activated plan=%s for host_id=%s until %s (payment id=%s)",
            sub.plan,
            host.id,
            new_end.isoformat(),
            sub.id,
        )
    else:
        logger.error("[HOST SUB] Host %s missing for subscription payment %s", sub.host_id, sub.id)


def _host_subscription_mark_failure(
    sub: HostSubscriptionPayment,
    *,
    result_code_str: str,
    result_desc: str,
) -> None:
    rc = normalize_stk_result_code(result_code_str) if result_code_str else ""
    rd = str(result_desc or "")
    if rc == "1032":
        sub.status = "cancelled"
        sub.result_desc = "Payment cancelled."
    elif infer_insufficient_funds(rc, rd):
        sub.status = "failed"
        sub.result_desc = "Insufficient funds. Please top up your M-Pesa and try again."
    elif rc == "2029":
        sub.status = "failed"
        sub.result_desc = "Payment timed out or failed."
    else:
        sub.status = "failed"
        sub.result_desc = rd.strip() if rd.strip() else "Payment failed."
    sub.result_code = rc or (str(result_code_str) if result_code_str else "")


async def process_host_subscription_mpesa_callback(
    db: AsyncSession, payload: Dict[str, Any]
) -> bool:
    """
    If this callback belongs to a host subscription payment, update row and host plan.
    Returns True if handled (subscription), False if not a subscription payment.
    """
    checkout_request_id = payload.get("CheckoutRequestID")
    external_reference = payload.get("ExternalReference")
    result_code = payload.get("ResultCode")
    result_desc = payload.get("ResultDesc") or ""
    status_str = payload.get("Status")

    sub: Optional[HostSubscriptionPayment] = None
    if checkout_request_id:
        r1 = await db.execute(
            select(HostSubscriptionPayment).where(
                HostSubscriptionPayment.checkout_request_id == str(checkout_request_id),
                HostSubscriptionPayment.status == "pending",
            )
        )
        sub = r1.scalar_one_or_none()
    if not sub and external_reference:
        pid = _parse_h_sub_ref(external_reference)
        if pid is not None:
            r2 = await db.execute(
                select(HostSubscriptionPayment).where(
                    HostSubscriptionPayment.id == pid,
                    HostSubscriptionPayment.status == "pending",
                )
            )
            sub = r2.scalar_one_or_none()
        if not sub:
            r3 = await db.execute(
                select(HostSubscriptionPayment).where(
                    HostSubscriptionPayment.external_reference == str(external_reference),
                    HostSubscriptionPayment.status == "pending",
                )
            )
            sub = r3.scalar_one_or_none()

    if not sub:
        return False

    if checkout_request_id and not sub.checkout_request_id:
        sub.checkout_request_id = str(checkout_request_id)

    result_code_str = normalize_stk_result_code(result_code)
    is_success = result_code_str == "0" or (status_str and str(status_str).lower() == "success")

    receipt = payload.get("MpesaReceiptNumber")
    phone = payload.get("PhoneNumber")
    transaction_date = payload.get("TransactionDate")

    if is_success:
        await _host_subscription_mark_success(
            db,
            sub,
            result_code_str=result_code_str,
            result_desc=str(result_desc).strip() if result_desc else None,
            receipt=receipt,
            phone=phone,
            transaction_date=transaction_date,
        )
    else:
        _host_subscription_mark_failure(
            sub,
            result_code_str=result_code_str,
            result_desc=str(result_desc) if result_desc else "",
        )

    await db.commit()
    return True


async def sync_pending_host_subscription_from_payhero(
    db: AsyncSession, rec: HostSubscriptionPayment
) -> None:
    """
    If still pending, ask Payhero for final status (SUCCESS/FAILED). Same idea as Pesapal sync on
    GET /client/payments/status — fixes cases where PAYHERO_CALLBACK_URL is wrong or webhook drops.
    """
    if not _payhero_subscription_sync_enabled():
        return
    await db.refresh(rec)
    if rec.status != "pending":
        return

    from app.services.mpesa_stk_push import fetch_payhero_transaction_status

    refs: list[str] = []
    if rec.checkout_request_id:
        refs.append(str(rec.checkout_request_id).strip())
    if rec.external_reference:
        er = str(rec.external_reference).strip()
        if er not in refs:
            refs.append(er)
    if not refs:
        return

    for ref in refs:
        data = fetch_payhero_transaction_status(ref)
        if not data or not isinstance(data, dict):
            continue

        st = (data.get("status") or data.get("Status") or "").strip().upper()
        success_flag = data.get("success")

        if success_flag is True or st == "SUCCESS":
            await db.refresh(rec)
            if rec.status != "pending":
                return
            rc = normalize_stk_result_code(data.get("ResultCode", data.get("result_code", 0)))
            rd = (
                data.get("ResultDesc")
                or data.get("result_desc")
                or data.get("message")
                or ""
            )
            receipt = (
                data.get("MpesaReceiptNumber")
                or data.get("mpesa_receipt_number")
                or data.get("provider_reference")
                or data.get("third_party_reference")
            )
            phone = data.get("PhoneNumber") or data.get("phone_number") or data.get("Phone")
            td = data.get("TransactionDate") or data.get("transaction_date")
            await _host_subscription_mark_success(
                db,
                rec,
                result_code_str=rc or "0",
                result_desc=str(rd).strip() if rd else None,
                receipt=receipt,
                phone=phone,
                transaction_date=td,
            )
            await db.commit()
            logger.info("[HOST SUB] Payhero status API → completed (ref tail=%s)", ref[-20:])
            return

        if st == "FAILED" or (success_flag is False and st not in ("QUEUED", "PENDING", "")):
            await db.refresh(rec)
            if rec.status != "pending":
                return
            rd = (
                data.get("ResultDesc")
                or data.get("result_desc")
                or data.get("message")
                or data.get("error_message")
                or "Payment failed."
            )
            rc_raw = data.get("ResultCode", data.get("result_code", ""))
            rc_str = str(rc_raw) if rc_raw is not None and str(rc_raw).strip() != "" else ""
            _host_subscription_mark_failure(rec, result_code_str=rc_str, result_desc=str(rd))
            await db.commit()
            logger.info("[HOST SUB] Payhero status API → %s (ref tail=%s)", rec.status, ref[-20:])
            return

        # Still in flight at Payhero
        if st in ("QUEUED", "PENDING") or (success_flag is None and st == ""):
            return
