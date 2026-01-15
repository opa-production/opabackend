from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.database import get_db
from app.models import PaymentMethod, Host
from app.schemas import (
    PaymentMethodResponse,
    PaymentMethodListResponse
)
from app.auth import get_current_admin

router = APIRouter()


# Helper function for pagination
def calculate_pagination(page: int, limit: int, total: int) -> dict:
    """Calculate pagination metadata"""
    total_pages = (total + limit - 1) // limit if limit > 0 else 0
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages
    }


def _format_payment_method_response(payment_method: PaymentMethod) -> dict:
    """Format payment method response with expiry date"""
    response_data = {
        "id": payment_method.id,
        "host_id": payment_method.host_id,
        "name": payment_method.name,
        "method_type": payment_method.method_type.value if payment_method.method_type else None,
        "mpesa_number": payment_method.mpesa_number,
        "card_last_four": payment_method.card_last_four,
        "card_type": payment_method.card_type,
        "expiry_month": payment_method.expiry_month,
        "expiry_year": payment_method.expiry_year,
        "is_default": payment_method.is_default,
        "created_at": payment_method.created_at,
        "updated_at": payment_method.updated_at
    }
    
    # Format expiry date if card payment method
    if payment_method.expiry_month and payment_method.expiry_year:
        year_short = payment_method.expiry_year % 100
        response_data["expiry_date"] = f"{payment_method.expiry_month:02d}/{year_short:02d}"
    else:
        response_data["expiry_date"] = None
    
    return response_data


@router.get("/admin/payment-methods", response_model=dict)
async def list_payment_methods(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    host_id: Optional[int] = Query(None, description="Filter by host ID"),
    method_type: Optional[str] = Query(None, description="Filter by method type (mpesa, visa, mastercard)"),
    search: Optional[str] = Query(None, description="Search by payment method name or host name/email"),
    sort_by: Optional[str] = Query("created_at", description="Sort field (id, created_at, name)"),
    order: Optional[str] = Query("desc", regex="^(asc|desc)$", description="Sort order"),
    current_admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    List all payment methods with host information
    
    - **page**: Page number (starts from 1)
    - **limit**: Number of items per page (1-100)
    - **host_id**: Filter by host ID
    - **method_type**: Filter by method type
    - **search**: Search by payment method name or host name/email
    - **sort_by**: Field to sort by
    - **order**: Sort order (asc or desc)
    """
    # Build query with join to host
    query = db.query(PaymentMethod).join(Host)
    
    # Apply filters
    if host_id:
        query = query.filter(PaymentMethod.host_id == host_id)
    
    if method_type:
        query = query.filter(PaymentMethod.method_type == method_type)
    
    if search:
        search_filter = or_(
            PaymentMethod.name.ilike(f"%{search}%"),
            Host.full_name.ilike(f"%{search}%"),
            Host.email.ilike(f"%{search}%")
        )
        query = query.filter(search_filter)
    
    # Get total count
    total = query.count()
    
    # Apply sorting
    sort_field = getattr(PaymentMethod, sort_by, PaymentMethod.created_at)
    if order == "asc":
        query = query.order_by(sort_field.asc())
    else:
        query = query.order_by(sort_field.desc())
    
    # Apply pagination
    skip = (page - 1) * limit
    payment_methods = query.offset(skip).limit(limit).all()
    
    # Build response with host information
    payment_method_list = []
    for pm in payment_methods:
        pm_data = _format_payment_method_response(pm)
        pm_data["host_name"] = pm.host.full_name if pm.host else None
        pm_data["host_email"] = pm.host.email if pm.host else None
        payment_method_list.append(pm_data)
    
    pagination = calculate_pagination(page, limit, total)
    
    return {
        "payment_methods": payment_method_list,
        **pagination
    }


@router.get("/admin/payment-methods/{payment_method_id}", response_model=dict)
async def get_payment_method_details(
    payment_method_id: int,
    current_admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific payment method including host information
    """
    payment_method = db.query(PaymentMethod).join(Host).filter(
        PaymentMethod.id == payment_method_id
    ).first()
    
    if not payment_method:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment method not found"
        )
    
    pm_data = _format_payment_method_response(payment_method)
    pm_data["host_name"] = payment_method.host.full_name if payment_method.host else None
    pm_data["host_email"] = payment_method.host.email if payment_method.host else None
    pm_data["host_id"] = payment_method.host_id
    
    return pm_data


@router.delete("/admin/payment-methods/{payment_method_id}")
async def delete_payment_method(
    payment_method_id: int,
    current_admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Delete a payment method (admin only)
    """
    payment_method = db.query(PaymentMethod).filter(
        PaymentMethod.id == payment_method_id
    ).first()
    
    if not payment_method:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment method not found"
        )
    
    db.delete(payment_method)
    db.commit()
    
    return {"message": "Payment method deleted successfully"}
