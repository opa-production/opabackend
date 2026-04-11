"""
Admin Withdrawal Management endpoints.

Admins can list all withdrawal requests, view details, and mark as completed/rejected/cancelled.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query

from sqlalchemy.orm import Session, joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from app.database import get_db
from app.models import Withdrawal, WithdrawalStatus, Host, Admin
from app.auth import get_current_admin
from app.schemas import WithdrawalResponse, WithdrawalListResponse, WithdrawalUpdateRequest

router = APIRouter()


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


@router.get("/admin/withdrawals", response_model=WithdrawalListResponse)
async def list_withdrawals(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status: pending, completed, rejected, cancelled"),
    host_id: Optional[int] = Query(None, description="Filter by host ID"),
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    List all withdrawal requests. Filter by status or host.
    """
    stmt = (
        select(Withdrawal)
        .options(joinedload(Withdrawal.host))
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
    if host_id is not None:
        stmt = stmt.filter(Withdrawal.host_id == host_id)
        
    # Get total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0
    
    # Apply pagination
    stmt = stmt.order_by(Withdrawal.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().unique().all()
    
    return WithdrawalListResponse(
        withdrawals=[_withdrawal_to_response(w) for w in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/admin/withdrawals/{withdrawal_id}", response_model=WithdrawalResponse)
async def get_withdrawal(
    withdrawal_id: int,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single withdrawal by ID."""
    stmt = (
        select(Withdrawal)
        .options(joinedload(Withdrawal.host))
        .filter(Withdrawal.id == withdrawal_id)
    )
    result = await db.execute(stmt)
    w = result.scalar_one_or_none()
    
    if not w:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Withdrawal not found")
    return _withdrawal_to_response(w)


@router.patch("/admin/withdrawals/{withdrawal_id}", response_model=WithdrawalResponse)
async def update_withdrawal_status(
    withdrawal_id: int,
    request: WithdrawalUpdateRequest,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Update withdrawal status (e.g. mark as completed, rejected, or cancelled).
    Only pending withdrawals can be updated. Optionally set admin_notes.
    """
    from datetime import datetime, timezone

    stmt = (
        select(Withdrawal)
        .options(joinedload(Withdrawal.host))
        .filter(Withdrawal.id == withdrawal_id)
    )
    result = await db.execute(stmt)
    w = result.scalar_one_or_none()
    
    if not w:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Withdrawal not found")
    if w.status != WithdrawalStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Withdrawal is already {w.status.value}. Only pending withdrawals can be updated.",
        )
    new_status_str = request.status.strip().lower()
    try:
        new_status = WithdrawalStatus(new_status_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid status. Valid: pending, completed, rejected, cancelled, failed",
        )
    if new_status == WithdrawalStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use completed, rejected, or cancelled to update.",
        )
    w.status = new_status
    if request.admin_notes is not None:
        w.admin_notes = request.admin_notes[:2000] if len(request.admin_notes) > 2000 else request.admin_notes
    if new_status in (WithdrawalStatus.COMPLETED, WithdrawalStatus.REJECTED, WithdrawalStatus.CANCELLED):
        w.processed_at = datetime.now(timezone.utc)
        w.processed_by_admin_id = current_admin.id

    _host_id = w.host_id
    _amount = float(w.amount)

    await db.commit()
    await db.refresh(w)

    # Notify host of withdrawal decision (fire-and-forget)
    import asyncio as _asyncio
    from app.services.push_notifications import (
        notify_host_withdrawal_completed as _wd_ok,
        notify_host_withdrawal_rejected as _wd_reject,
    )
    if new_status == WithdrawalStatus.COMPLETED:
        _asyncio.ensure_future(_wd_ok(_host_id, _amount))
    elif new_status in (WithdrawalStatus.REJECTED, WithdrawalStatus.CANCELLED):
        _asyncio.ensure_future(_wd_reject(_host_id, _amount))

    return _withdrawal_to_response(w)
