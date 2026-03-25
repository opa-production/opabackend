"""
Host earnings, transactions, and withdrawal endpoints.

Powers the host app home/dashboard: net earnings, commission, withdrawable amount,
transactions list, and withdrawal requests.
"""
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from app.database import get_db
from app.models import Booking, Car, Payment, PaymentStatus, BookingStatus, Withdrawal, WithdrawalStatus
from app.auth import get_current_host
from app.models import Host
from app.schemas import (
    HostEarningsSummaryResponse,
    HostTransactionItem,
    HostTransactionListResponse,
    WithdrawalCreateRequest,
    WithdrawalResponse,
    WithdrawalListResponse,
)

router = APIRouter()

COMMISSION_RATE = 0.15  # 15% platform commission (same as admin dashboard)


async def _withdrawable_for_host(db: AsyncSession, host_id: int) -> float:
    """Compute withdrawable balance for host (net earnings minus pending+completed withdrawals)."""
    paid_statuses = [BookingStatus.CONFIRMED.value, BookingStatus.ACTIVE.value, BookingStatus.COMPLETED.value]
    
    total_gross_stmt = (
        select(func.coalesce(func.sum(Booking.total_price), 0))
        .join(Car)
        .filter(Car.host_id == host_id, Booking.status.in_(paid_statuses))
    )
    total_gross_result = await db.execute(total_gross_stmt)
    total_gross = total_gross_result.scalar()
    
    net = float(total_gross or 0) * (1 - COMMISSION_RATE)
    
    withdrawn_stmt = (
        select(func.coalesce(func.sum(Withdrawal.amount), 0))
        .filter(
            Withdrawal.host_id == host_id,
            Withdrawal.status.in_([WithdrawalStatus.PENDING, WithdrawalStatus.COMPLETED]),
        )
    )
    withdrawn_result = await db.execute(withdrawn_stmt)
    withdrawn = withdrawn_result.scalar()
    
    return max(0, round(net - float(withdrawn or 0), 2))


def _withdrawal_to_response(w: Withdrawal) -> WithdrawalResponse:
    return WithdrawalResponse(
        id=w.id,
        host_id=w.host_id,
        host_name=w.host.full_name if w.host else None,
        host_email=w.host.email if w.host else None,
        amount=w.amount,
        status=w.status.value,
        payment_method_type=w.payment_method_type,
        payment_details=w.payment_details,
        processed_at=w.processed_at,
        processed_by_admin_id=w.processed_by_admin_id,
        admin_notes=w.admin_notes,
        created_at=w.created_at,
        updated_at=w.updated_at,
    )


@router.get("/host/earnings/summary", response_model=HostEarningsSummaryResponse)
async def get_host_earnings_summary(
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Get earnings summary for the authenticated host (home/dashboard).

    - **total_gross**: Total from paid bookings (confirmed/active/completed) on this host's cars.
    - **commission_rate**: Platform commission rate (0.15 = 15%).
    - **commission_amount**: Total commission deducted.
    - **net_earnings**: total_gross - commission_amount.
    - **withdrawable**: Amount available to withdraw (currently same as net_earnings).
    - **paid_bookings_count**: Number of paid bookings.
    """
    paid_statuses = [
        BookingStatus.CONFIRMED.value,
        BookingStatus.ACTIVE.value,
        BookingStatus.COMPLETED.value,
    ]
    
    base_stmt = (
        select(Booking)
        .join(Car)
        .filter(Car.host_id == current_host.id, Booking.status.in_(paid_statuses))
    )
    
    total_gross_stmt = (
        select(func.coalesce(func.sum(Booking.total_price), 0))
        .join(Car)
        .filter(Car.host_id == current_host.id, Booking.status.in_(paid_statuses))
    )
    total_gross_result = await db.execute(total_gross_stmt)
    total_gross_val = total_gross_result.scalar()
    total_gross = float(total_gross_val or 0)
    
    # Get paid count
    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    count_result = await db.execute(count_stmt)
    paid_count = count_result.scalar() or 0
    
    commission_amount = round(total_gross * COMMISSION_RATE, 2)
    net_earnings = round(total_gross - commission_amount, 2)
    
    # Withdrawable = net minus amounts already in pending or completed withdrawals
    withdrawn_stmt = (
        select(func.coalesce(func.sum(Withdrawal.amount), 0))
        .filter(
            Withdrawal.host_id == current_host.id,
            Withdrawal.status.in_([WithdrawalStatus.PENDING, WithdrawalStatus.COMPLETED]),
        )
    )
    withdrawn_result = await db.execute(withdrawn_stmt)
    withdrawn_sum = withdrawn_result.scalar()
    
    withdrawable = max(0, round(net_earnings - float(withdrawn_sum or 0), 2))

    return HostEarningsSummaryResponse(
        total_gross=round(total_gross, 2),
        commission_rate=COMMISSION_RATE,
        commission_amount=commission_amount,
        net_earnings=net_earnings,
        withdrawable=withdrawable,
        paid_bookings_count=paid_count,
    )


@router.get("/host/earnings/transactions", response_model=HostTransactionListResponse)
async def get_host_transactions(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    List all transactions (paid bookings) for the authenticated host.

    Each transaction is a paid booking on one of the host's cars, with amount,
    commission, net amount, paid_at, and optional M-Pesa receipt number.
    """
    paid_statuses = [
        BookingStatus.CONFIRMED.value,
        BookingStatus.ACTIVE.value,
        BookingStatus.COMPLETED.value,
    ]
    
    stmt = (
        select(Booking)
        .options(
            joinedload(Booking.car),
            joinedload(Booking.client),
            joinedload(Booking.payments),
        )
        .join(Car)
        .filter(Car.host_id == current_host.id, Booking.status.in_(paid_statuses))
    )
    
    # Get total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0
    
    # Apply pagination
    stmt = stmt.order_by(Booking.id.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    bookings = result.scalars().unique().all()

    transactions = []
    for b in bookings:
        amount = float(b.total_price)
        commission_amount = round(amount * COMMISSION_RATE, 2)
        net_amount = round(amount - commission_amount, 2)
        paid_at = b.status_updated_at
        mpesa_receipt = None
        for p in (b.payments or []):
            if p.status == PaymentStatus.COMPLETED:
                if p.updated_at and (paid_at is None or p.updated_at > paid_at):
                    paid_at = p.updated_at
                if p.mpesa_receipt_number:
                    mpesa_receipt = p.mpesa_receipt_number
                break
        if mpesa_receipt is None and (b.payments or []):
            for p in b.payments:
                if p.status == PaymentStatus.COMPLETED and p.mpesa_receipt_number:
                    mpesa_receipt = p.mpesa_receipt_number
                    break

        transactions.append(
            HostTransactionItem(
                booking_id=b.booking_id,
                car_name=b.car.name if b.car else None,
                client_name=b.client.full_name if b.client else None,
                amount=amount,
                commission_amount=commission_amount,
                net_amount=net_amount,
                paid_at=paid_at,
                mpesa_receipt_number=mpesa_receipt,
            )
        )

    return HostTransactionListResponse(
        transactions=transactions,
        total=total,
        skip=skip,
        limit=limit,
    )


# ==================== HOST WITHDRAWALS (same router so they appear under Host Earnings in Swagger) ====================


@router.post("/host/withdrawals", response_model=WithdrawalResponse, status_code=status.HTTP_201_CREATED)
async def host_create_withdrawal(
    request: WithdrawalCreateRequest,
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Submit a withdrawal request. Amount is validated against your current withdrawable balance.

    - **amount**: Amount to withdraw (must be <= withdrawable).
    - **payment_method_type**: `mpesa` or `bank`.
    - **mpesa_number**: Required when payment_method_type is mpesa (e.g. 254712345678).
    - **bank_name**, **account_number**: Required when payment_method_type is bank.
    """
    withdrawable = await _withdrawable_for_host(db, current_host.id)
    amount = round(float(request.amount), 2)
    if amount > withdrawable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Amount exceeds withdrawable balance. Withdrawable: {withdrawable}",
        )
    payment_type = request.payment_method_type.strip().lower()
    details = {}
    if payment_type == "mpesa":
        details["mpesa_number"] = (request.mpesa_number or "").strip()
    elif payment_type == "bank":
        details["bank_name"] = (request.bank_name or "").strip()
        details["account_number"] = (request.account_number or "").strip()
        if request.account_name:
            details["account_name"] = request.account_name.strip()
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="payment_method_type must be mpesa or bank",
        )
    withdrawal = Withdrawal(
        host_id=current_host.id,
        amount=amount,
        status=WithdrawalStatus.PENDING,
        payment_method_type=payment_type,
        payment_details=json.dumps(details),
    )
    db.add(withdrawal)
    await db.commit()
    await db.refresh(withdrawal)
    
    # Reload with host for response
    stmt = select(Withdrawal).options(joinedload(Withdrawal.host)).filter(Withdrawal.id == withdrawal.id)
    result = await db.execute(stmt)
    withdrawal = result.scalar_one_or_none()
    
    return _withdrawal_to_response(withdrawal)


@router.get("/host/withdrawals", response_model=WithdrawalListResponse)
async def host_list_my_withdrawals(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status: pending, completed, rejected, cancelled"),
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """List withdrawal requests for the authenticated host."""
    stmt = (
        select(Withdrawal)
        .options(joinedload(Withdrawal.host))
        .filter(Withdrawal.host_id == current_host.id)
    )
    if status_filter:
        try:
            status_enum = WithdrawalStatus(status_filter.lower())
            stmt = stmt.filter(Withdrawal.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid status. Valid: pending, completed, rejected, cancelled, failed",
            )
            
    # Get total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0
    
    # Apply pagination
    stmt = stmt.order_by(Withdrawal.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    
    return WithdrawalListResponse(
        withdrawals=[_withdrawal_to_response(w) for w in rows],
        total=total,
        skip=skip,
        limit=limit,
    )
