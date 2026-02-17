"""
Payment processing endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timezone
from typing import Optional
import logging

from app.database import get_db
from app.models import Booking, PaymentMethod, Client, BookingStatus, PaymentMethodType, Payment, PaymentStatus
from app.auth import get_current_client
from app.schemas import PaymentRequest, PaymentResponse, PaymentStatusResponse, PaymentStatusEnum
from app.services.mpesa_stk_push import sendStkPush

router = APIRouter()
logger = logging.getLogger(__name__)


def _payment_to_status_response(payment: Payment) -> PaymentStatusResponse:
    """Build PaymentStatusResponse from Payment model."""
    status_enum = PaymentStatusEnum(payment.status.value)
    message = payment.result_desc if payment.status != PaymentStatus.PENDING else None
    return PaymentStatusResponse(
        checkout_request_id=payment.checkout_request_id or "",
        booking_id=payment.booking.booking_id,
        status=status_enum,
        message=message,
        amount=payment.amount,
        paid_at=payment.updated_at if payment.status == PaymentStatus.COMPLETED else None,
        mpesa_receipt_number=payment.mpesa_receipt_number,
    )


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
    # Accept both string booking_id (e.g. "BK-ABC12345") and numeric id
    booking_query = db.query(Booking).options(joinedload(Booking.car)).filter(
        Booking.client_id == current_client.id
    )
    if isinstance(request.booking_id, int):
        booking = booking_query.filter(Booking.id == request.booking_id).first()
    else:
        booking = booking_query.filter(Booking.booking_id == request.booking_id).first()
    
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
    
    # ACTUAL PAYMENT PROCESSING
    try:
        # Double-check booking is still available (prevent double payment)
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

        transaction_id = f"TXN-{booking.booking_id}"
        payment_message = "Payment processed successfully. Your booking is now confirmed."

        # If payment method is M-Pesa, call STK Push and create pending payment (do not confirm booking yet)
        if payment_method.method_type == PaymentMethodType.MPESA:
            if not payment_method.mpesa_number:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="M-Pesa number is missing for this payment method"
                )
            
            # Format amount to integer string
            amount_str = str(int(float(booking.total_price))) # type: ignore
            
            logger.info(f" [MPESA STK PUSH] Initiating for booking={booking.booking_id}, "
                       f"number={payment_method.mpesa_number}, amount={amount_str}")
            
            # Ensure M-Pesa number has country code (254 for Kenya) if missing
            mpesa_phone = str(payment_method.mpesa_number).strip()
            if mpesa_phone.startswith("0"):
                mpesa_phone = "254" + mpesa_phone[1:]
            elif not mpesa_phone.startswith("254"):
                mpesa_phone = "254" + mpesa_phone

            mpesa_response = sendStkPush(
                amount=amount_str,
                PhoneNumber=mpesa_phone,
                AccountReference=str(booking.booking_id),
                TransactionDesc=f"Payment for booking {booking.booking_id}"
            )
            
            if mpesa_response is None or mpesa_response.get("ResponseCode") != "0":
                logger.error(f"[MPESA STK PUSH] Failed: {mpesa_response}")
                error_desc = mpesa_response.get('ResponseDescription', 'Unknown error') if mpesa_response else 'No response from M-Pesa'
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"M-Pesa STK Push failed: {error_desc}"
                )
            
            checkout_request_id = mpesa_response.get("CheckoutRequestID")
            transaction_id = checkout_request_id or transaction_id
            
            # Create pending payment so callback (and UI polling) can update status
            payment = Payment(
                booking_id=booking.id,
                client_id=current_client.id,
                checkout_request_id=checkout_request_id,
                amount=float(booking.total_price),
                status=PaymentStatus.PENDING,
            )
            db.add(payment)
            db.commit()
            db.refresh(payment)
            
            payment_message = "M-Pesa STK Push initiated. Please check your phone to complete the payment. You can poll GET /client/payments/status?checkout_request_id=... for status."
            # Do NOT set booking to CONFIRMED here; callback will do it when payment succeeds.
        else:
            # Non-M-Pesa (e.g. card): confirm booking immediately
            booking.status = BookingStatus.CONFIRMED # type: ignore
            booking.status_updated_at = datetime.now(timezone.utc) # type: ignore
        
        db.commit()
        db.refresh(booking)
        
        logger.info(f"💳 [PROCESS PAYMENT] ✅ Request processed: booking_id={request.booking_id}, "
                   f"amount={booking.total_price}, status={booking.status.value}")
        
        # Reload booking with relationships for response
        from app.models import Car
        final_booking = db.query(Booking).options(
            joinedload(Booking.car).joinedload(Car.host)
        ).filter(Booking.id == booking.id).first()
        
        if not final_booking:
             raise HTTPException(status_code=404, detail="Booking lost during processing")

        # Import here to avoid circular import
        from app.routers.bookings import booking_to_response
        from app.schemas import BookingResponse
        
        # Return payment confirmation with booking details
        return PaymentResponse(
            success=True,
            booking_id=str(final_booking.booking_id),
            amount_paid=float(final_booking.total_price), # type: ignore
            payment_method_type=str(payment_method.method_type.value),
            payment_method_name=str(payment_method.name),
            transaction_id=str(transaction_id),
            message=payment_message,
            paid_at=datetime.now(timezone.utc),
            booking=BookingResponse(**booking_to_response(final_booking))  # Include full booking details
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


@router.get("/client/payments/status", response_model=PaymentStatusResponse)
async def get_payment_status(
    checkout_request_id: Optional[str] = Query(None, description="M-Pesa CheckoutRequestID returned from process payment"),
    booking_id: Optional[str] = Query(None, description="Booking ID (e.g. BK-ABC12345); returns latest payment for this booking"),
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """
    Get status of an M-Pesa STK push payment. Poll this after initiating payment to detect:
    - **pending**: User has not yet completed or cancelled.
    - **completed**: Payment successful; booking is confirmed.
    - **cancelled**: User cancelled on phone (ResultCode 1032).
    - **failed**: e.g. insufficient funds, timeout (see `message` for reason).
    
    Provide either `checkout_request_id` (from the process payment response) or `booking_id`.
    """
    if not checkout_request_id and not booking_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either checkout_request_id or booking_id",
        )
    
    if checkout_request_id:
        payment = (
            db.query(Payment)
            .options(joinedload(Payment.booking))
            .filter(
                Payment.checkout_request_id == checkout_request_id,
                Payment.client_id == current_client.id,
            )
            .first()
        )
    else:
        booking = (
            db.query(Booking)
            .filter(
                Booking.client_id == current_client.id,
                Booking.booking_id == booking_id,
            )
            .first()
        )
        if not booking:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
        payment = (
            db.query(Payment)
            .options(joinedload(Payment.booking))
            .filter(Payment.booking_id == booking.id, Payment.client_id == current_client.id)
            .order_by(Payment.created_at.desc())
            .first()
        )
    
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No payment found for this request or booking",
        )
    
    return _payment_to_status_response(payment)


def parse_mpesa_metadata(metadata_items):
    """Parse M-Pesa callback metadata into a dictionary"""
    parsed = {}
    for item in metadata_items:
        name = item.get("Name")
        value = item.get("Value")
        parsed[name] = value
    return parsed


@router.post("/mpesa/callback")
async def mpesa_callback(request: Request, db: Session = Depends(get_db)):
    """
    M-Pesa STK Push Callback URL.
    Called by Safaricom after the user completes, cancels, or fails (e.g. insufficient funds) the STK push.
    Updates the Payment record and, on success, confirms the booking.
    """
    try:
        data = await request.json()
        logger.info(f"[MPESA CALLBACK] Received: {data}")
        
        stk_callback = data.get("Body", {}).get("stkCallback", {})
        result_code = stk_callback.get("ResultCode")
        result_desc = stk_callback.get("ResultDesc")
        checkout_request_id = stk_callback.get("CheckoutRequestID")
        
        if not checkout_request_id:
            logger.warning("[MPESA CALLBACK] No CheckoutRequestID in callback")
            return {"ResultCode": 0, "ResultDesc": "Success"}
        
        payment = db.query(Payment).filter(
            Payment.checkout_request_id == checkout_request_id,
            Payment.status == PaymentStatus.PENDING,
        ).first()
        
        if not payment:
            logger.warning(f"[MPESA CALLBACK] No pending payment for CheckoutRequestID={checkout_request_id}")
            return {"ResultCode": 0, "ResultDesc": "Success"}
        
        if result_code == 0:
            metadata = stk_callback.get("CallbackMetadata", {}).get("Item", [])
            parsed_metadata = parse_mpesa_metadata(metadata)
            receipt = parsed_metadata.get("MpesaReceiptNumber")
            phone = parsed_metadata.get("PhoneNumber")
            transaction_date = parsed_metadata.get("TransactionDate")
            
            payment.status = PaymentStatus.COMPLETED
            payment.result_code = result_code
            payment.result_desc = result_desc
            payment.mpesa_receipt_number = str(receipt) if receipt else None
            payment.mpesa_phone = str(phone) if phone else None
            payment.mpesa_transaction_date = str(transaction_date) if transaction_date else None
            
            booking = db.query(Booking).filter(Booking.id == payment.booking_id).first()
            if booking and booking.status == BookingStatus.PENDING:
                booking.status = BookingStatus.CONFIRMED
                booking.status_updated_at = datetime.now(timezone.utc)
            
            db.commit()
            logger.info(f"[MPESA CALLBACK] ✅ Payment Successful: Receipt={receipt}, CheckoutRequestID={checkout_request_id}, booking_id={booking.booking_id if booking else None}")
        else:
            # User cancelled, insufficient funds, or other failure
            payment.status = PaymentStatus.CANCELLED if result_code == 1032 else PaymentStatus.FAILED
            payment.result_code = result_code
            payment.result_desc = result_desc
            db.commit()
            logger.warning(f"[MPESA CALLBACK] ❌ Payment Failed/Cancelled: {result_desc} (Code: {result_code}, CheckoutRequestID: {checkout_request_id})")
            
        return {"ResultCode": 0, "ResultDesc": "Success"}
    except Exception as e:
        db.rollback()
        logger.error(f"[MPESA CALLBACK] ❌ Error processing callback: {str(e)}", exc_info=True)
        return {"ResultCode": 0, "ResultDesc": "Success"}
