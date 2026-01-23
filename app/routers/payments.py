"""
Payment processing endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timezone
import logging

from app.database import get_db
from app.models import Booking, PaymentMethod, Client, BookingStatus
from app.auth import get_current_client
from app.schemas import PaymentRequest, PaymentResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/client/payments/process", response_model=PaymentResponse, status_code=status.HTTP_200_OK)
async def process_payment(
    request: PaymentRequest,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """
    Process payment for a booking (simulated payment gateway).
    
    This endpoint simulates payment processing. In production, this would integrate
    with real payment gateways (M-Pesa, Stripe, etc.).
    
    Flow:
    1. Validates booking exists and belongs to client
    2. Validates payment method exists and belongs to client
    3. Validates booking is in PENDING status (not already paid)
    4. Simulates payment processing
    5. Updates booking status to CONFIRMED
    6. Returns payment confirmation
    
    - **booking_id**: The booking ID to pay for (e.g., "BK-12345678")
    - **payment_method_id**: ID of the payment method to use
    
    Requires client authentication.
    """
    logger.info(f"💳 [PROCESS PAYMENT] Request received: client_id={current_client.id}, "
               f"booking_id={request.booking_id}, payment_method_id={request.payment_method_id}")
    
    # Verify booking exists and belongs to client
    booking = db.query(Booking).options(
        joinedload(Booking.car)
    ).filter(
        Booking.booking_id == request.booking_id,
        Booking.client_id == current_client.id
    ).first()
    
    if not booking:
        logger.warning(f"💳 [PROCESS PAYMENT] Booking not found: booking_id={request.booking_id}, client_id={current_client.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )
    
    # Verify booking is in PENDING status (not already paid/confirmed)
    if booking.status != BookingStatus.PENDING:
        logger.warning(f"💳 [PROCESS PAYMENT] Booking already processed: booking_id={request.booking_id}, status={booking.status.value}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Booking has already been processed. Current status: {booking.status.value}"
        )
    
    # Verify payment method exists and belongs to client
    payment_method = db.query(PaymentMethod).filter(
        PaymentMethod.id == request.payment_method_id,
        PaymentMethod.client_id == current_client.id
    ).first()
    
    if not payment_method:
        logger.warning(f"💳 [PROCESS PAYMENT] Payment method not found: payment_method_id={request.payment_method_id}, client_id={current_client.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment method not found or does not belong to you"
        )
    
    logger.info(f"💳 [PROCESS PAYMENT] Validations passed. Processing payment for booking_id={request.booking_id}, "
               f"amount={booking.total_price}, payment_method={payment_method.method_type.value}")
    
    # SIMULATE PAYMENT PROCESSING
    # In production, this would call actual payment gateway APIs
    try:
        # Simulate payment processing delay (in real implementation, this would be async)
        # For now, we just validate and confirm
        
        # Double-check booking is still available (prevent double payment)
        # Re-query to ensure no race condition
        booking_check = db.query(Booking).filter(
            Booking.id == booking.id,
            Booking.status == BookingStatus.PENDING
        ).first()
        
        if not booking_check:
            logger.warning(f"💳 [PROCESS PAYMENT] Booking status changed during payment: booking_id={request.booking_id}")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Booking status has changed. Please refresh and try again."
            )
        
        # Update booking status to CONFIRMED
        booking.status = BookingStatus.CONFIRMED
        booking.status_updated_at = datetime.now(timezone.utc)
        
        db.commit()
        db.refresh(booking)
        
        logger.info(f"💳 [PROCESS PAYMENT] ✅ Payment processed successfully: booking_id={request.booking_id}, "
                   f"amount={booking.total_price}, status={booking.status.value}")
        
        # Reload booking with relationships for response
        from app.models import Car
        booking = db.query(Booking).options(
            joinedload(Booking.car).joinedload(Car.host)
        ).filter(Booking.id == booking.id).first()
        
        # Import here to avoid circular import
        from app.routers.bookings import booking_to_response
        
        # Return payment confirmation with booking details
        return PaymentResponse(
            success=True,
            booking_id=booking.booking_id,
            amount_paid=booking.total_price,
            payment_method_type=payment_method.method_type.value,
            payment_method_name=payment_method.name,
            transaction_id=f"TXN-{booking.booking_id}",  # Simulated transaction ID
            message="Payment processed successfully. Your booking is now confirmed.",
            paid_at=datetime.now(timezone.utc),
            booking=booking_to_response(booking)  # Include full booking details
        )
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"💳 [PROCESS PAYMENT] ❌ Payment processing failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Payment processing failed: {str(e)}"
        )
