from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models import Host, PaymentMethod, PaymentMethodType
from app.schemas import (
    MpesaPaymentMethodAddRequest,
    CardPaymentMethodAddRequest,
    PaymentMethodResponse,
    PaymentMethodListResponse
)
from app.auth import get_current_host, get_password_hash

router = APIRouter()


def hash_card_number(card_number: str) -> str:
    """Hash card number using bcrypt"""
    return get_password_hash(card_number)


def hash_cvc(cvc: str) -> str:
    """Hash CVC/CVV using bcrypt"""
    return get_password_hash(cvc)


@router.post("/host/payment-methods/mpesa", response_model=PaymentMethodResponse, status_code=status.HTTP_201_CREATED)
async def add_mpesa_payment_method(
    request: MpesaPaymentMethodAddRequest,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db)
):
    """
    Add a new M-Pesa payment method for the authenticated host
    
    - **name**: Name for this M-Pesa payment method (e.g., "John's M-Pesa")
    - **mpesa_number**: M-Pesa phone number (9-15 digits, e.g., 254712345678)
    - **is_default**: Set as default payment method
    
    Requires Bearer token authentication.
    """
    # If setting as default, unset other default payment methods
    if request.is_default:
        existing_defaults = db.query(PaymentMethod).filter(
            PaymentMethod.host_id == current_host.id,
            PaymentMethod.is_default == True
        ).all()
        for pm in existing_defaults:
            pm.is_default = False
    
    # Create M-Pesa payment method
    db_payment_method = PaymentMethod(
        host_id=current_host.id,
        name=request.name,
        method_type=PaymentMethodType.MPESA,
        mpesa_number=request.mpesa_number,
        is_default=request.is_default
    )
    
    db.add(db_payment_method)
    db.commit()
    db.refresh(db_payment_method)
    
    return db_payment_method


@router.post("/host/payment-methods/card", response_model=PaymentMethodResponse, status_code=status.HTTP_201_CREATED)
async def add_card_payment_method(
    request: CardPaymentMethodAddRequest,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db)
):
    """
    Add a new card payment method (Visa or Mastercard) for the authenticated host
    
    - **name**: Name for this card payment method (e.g., "My Visa Card")
    - **card_number**: 16-digit card number (Visa must start with 4, Mastercard with 5)
    - **expiry_date**: Expiry date in MM/YY format (e.g., "08/30")
    - **cvc**: 3-4 digit CVC/CVV code
    - **card_type**: Card type ("visa" or "mastercard")
    - **is_default**: Set as default payment method
    
    Requires Bearer token authentication.
    """
    # If setting as default, unset other default payment methods
    if request.is_default:
        existing_defaults = db.query(PaymentMethod).filter(
            PaymentMethod.host_id == current_host.id,
            PaymentMethod.is_default == True
        ).all()
        for pm in existing_defaults:
            pm.is_default = False
    
    # Extract last 4 digits for display
    card_last_four = request.card_number[-4:]
    
    # Map card_type string to PaymentMethodType enum
    method_type_map = {
        "visa": PaymentMethodType.VISA,
        "mastercard": PaymentMethodType.MASTERCARD
    }
    
    # Get parsed expiry month and year from validation
    expiry_month = request._expiry_month
    expiry_year = request._expiry_year
    
    db_payment_method = PaymentMethod(
        host_id=current_host.id,
        name=request.name,
        method_type=method_type_map[request.card_type],
        card_number_hash=hash_card_number(request.card_number),
        card_last_four=card_last_four,
        card_type=request.card_type,
        expiry_month=expiry_month,
        expiry_year=expiry_year,
        cvc_hash=hash_cvc(request.cvc),
        is_default=request.is_default
    )
    
    db.add(db_payment_method)
    db.commit()
    db.refresh(db_payment_method)
    
    return db_payment_method


@router.get("/host/payment-methods", response_model=PaymentMethodListResponse)
async def get_payment_methods(
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db)
):
    """
    Get all payment methods for the authenticated host
    
    Requires Bearer token authentication.
    Returns list of payment methods (sensitive data like full card numbers and CVC are not included).
    """
    payment_methods = db.query(PaymentMethod).filter(
        PaymentMethod.host_id == current_host.id
    ).order_by(PaymentMethod.is_default.desc(), PaymentMethod.created_at.desc()).all()
    
    return PaymentMethodListResponse(payment_methods=payment_methods)


@router.get("/host/payment-methods/{payment_method_id}", response_model=PaymentMethodResponse)
async def get_payment_method(
    payment_method_id: int,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db)
):
    """
    Get a specific payment method by ID
    
    Requires Bearer token authentication.
    Returns the payment method if it belongs to the authenticated host.
    """
    payment_method = db.query(PaymentMethod).filter(
        PaymentMethod.id == payment_method_id,
        PaymentMethod.host_id == current_host.id
    ).first()
    
    if not payment_method:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment method not found"
        )
    
    return payment_method


@router.delete("/host/payment-methods/{payment_method_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_payment_method(
    payment_method_id: int,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db)
):
    """
    Delete a payment method
    
    Requires Bearer token authentication.
    Only the owner of the payment method can delete it.
    """
    payment_method = db.query(PaymentMethod).filter(
        PaymentMethod.id == payment_method_id,
        PaymentMethod.host_id == current_host.id
    ).first()
    
    if not payment_method:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment method not found"
        )
    
    db.delete(payment_method)
    db.commit()
    
    return None


@router.put("/host/payment-methods/{payment_method_id}/default", response_model=PaymentMethodResponse)
async def set_default_payment_method(
    payment_method_id: int,
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db)
):
    """
    Set a payment method as default
    
    Requires Bearer token authentication.
    Sets the specified payment method as default and unsets all other default payment methods for the host.
    """
    payment_method = db.query(PaymentMethod).filter(
        PaymentMethod.id == payment_method_id,
        PaymentMethod.host_id == current_host.id
    ).first()
    
    if not payment_method:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment method not found"
        )
    
    # Unset other default payment methods
    existing_defaults = db.query(PaymentMethod).filter(
        PaymentMethod.host_id == current_host.id,
        PaymentMethod.is_default == True,
        PaymentMethod.id != payment_method_id
    ).all()
    
    for pm in existing_defaults:
        pm.is_default = False
    
    # Set this one as default
    payment_method.is_default = True
    
    db.commit()
    db.refresh(payment_method)
    
    return payment_method

