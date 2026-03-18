"""
Payment processing endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, and_, or_
from datetime import datetime, timezone, timedelta
from typing import Optional
import json
import logging

from app.database import get_db
from app.models import Booking, PaymentMethod, Client, BookingStatus, PaymentMethodType, Payment, PaymentStatus, Withdrawal, WithdrawalStatus, BookingExtensionRequest
from app.auth import get_current_client
from app.schemas import (
    PaymentRequest,
    PaymentResponse,
    PaymentStatusResponse,
    PaymentStatusEnum,
    BookingExtensionPaymentRequest,
)
from app.services.mpesa_stk_push import sendStkPush

router = APIRouter()
logger = logging.getLogger(__name__)


def _payment_to_status_response(payment: Payment) -> PaymentStatusResponse:
    """Build PaymentStatusResponse from Payment model."""
    status_enum = PaymentStatusEnum(payment.status)
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
    db: AsyncSession = Depends(get_db)
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
    stmt = select(Booking).options(joinedload(Booking.car)).filter(
        Booking.client_id == current_client.id
    )
    if isinstance(request.booking_id, int) or (isinstance(request.booking_id, str) and request.booking_id.isdigit()):
        stmt = stmt.filter(Booking.id == int(request.booking_id))
    else:
        stmt = stmt.filter(Booking.booking_id == request.booking_id)
    
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()
    
    if not booking:
        logger.warning(f"💳 [PROCESS PAYMENT] Booking not found: booking_id={request.booking_id}, client_id={current_client.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )
    
    # Verify booking is in PENDING status (not already paid/confirmed)
    if booking.status != BookingStatus.PENDING:
        logger.warning(f"💳 [PROCESS PAYMENT] Booking already processed: booking_id={request.booking_id}, status={booking.status}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Booking has already been processed. Current status: {booking.status}"
        )
    
    # Verify payment method exists and belongs to client
    pm_stmt = select(PaymentMethod).filter(
        PaymentMethod.id == request.payment_method_id,
        PaymentMethod.client_id == current_client.id
    )
    pm_result = await db.execute(pm_stmt)
    payment_method = pm_result.scalar_one_or_none()
    
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
        booking_check_stmt = select(Booking).filter(
            Booking.id == booking.id,
            Booking.status == BookingStatus.PENDING
        )
        booking_check_result = await db.execute(booking_check_stmt)
        booking_check = booking_check_result.scalar_one_or_none()
        
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

            mpesa_response = await sendStkPush(
                amount=amount_str,
                PhoneNumber=mpesa_phone,
                AccountReference=str(booking.booking_id),
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
            await db.commit()
            await db.refresh(payment)
            
            payment_message = "M-Pesa STK Push initiated. Please check your phone to complete the payment. You can poll GET /client/payments/status?checkout_request_id=... for status."
            # Do NOT set booking to CONFIRMED here; callback will do it when payment succeeds.
        else:
            # Non-M-Pesa (e.g. card): confirm booking immediately
            booking.status = BookingStatus.CONFIRMED # type: ignore
            booking.status_updated_at = datetime.now(timezone.utc) # type: ignore
        
        await db.commit()
        await db.refresh(booking)
        
        logger.info(f"💳 [PROCESS PAYMENT] ✅ Request processed: booking_id={request.booking_id}, "
                   f"amount={booking.total_price}, status={booking.status}")
        
        # Reload booking with relationships for response
        from app.models import Car
        final_booking_stmt = select(Booking).options(
            joinedload(Booking.car).joinedload(Car.host)
        ).filter(Booking.id == booking.id)
        final_booking_result = await db.execute(final_booking_stmt)
        final_booking = final_booking_result.scalar_one_or_none()
        
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
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"💳 [PROCESS PAYMENT] ❌ Payment processing failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Payment processing failed: {str(e)}"
        )


@router.post(
    "/client/bookings/{booking_id}/extensions/{extension_id}/pay",
    response_model=PaymentResponse,
    status_code=status.HTTP_200_OK,
)
async def process_extension_payment(
    booking_id: str,
    extension_id: int,
    request: BookingExtensionPaymentRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Start payment for an **approved** booking extension.

    Flow:
    - Verifies booking belongs to client and is confirmed/active.
    - Verifies extension exists, belongs to this booking, and is host-approved.
    - Ensures payment is started at least 24 hours before the current drop-off time.
    - Initiates M-Pesa STK push for the extension amount and creates a pending Payment.
    - Booking dates and price are updated by the M-Pesa callback when payment succeeds.
    """
    logger.info(
        "💳 [EXTENSION PAYMENT] Request: client_id=%s, booking_id=%s, extension_id=%s, payment_method_id=%s",
        current_client.id,
        booking_id,
        extension_id,
        request.payment_method_id,
    )

    # Resolve booking by booking_id (string) for this client
    booking_stmt = (
        select(Booking)
        .options(joinedload(Booking.car))
        .filter(
            Booking.client_id == current_client.id,
            Booking.booking_id == booking_id,
        )
    )
    booking_result = await db.execute(booking_stmt)
    booking = booking_result.scalar_one_or_none()
    
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    if booking.status not in [BookingStatus.CONFIRMED, BookingStatus.ACTIVE]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only confirmed or active bookings can be extended.",
        )

    # Find extension request
    ext_stmt = (
        select(BookingExtensionRequest)
        .filter(
            BookingExtensionRequest.id == extension_id,
            BookingExtensionRequest.booking_id == booking.id,
            BookingExtensionRequest.client_id == current_client.id,
        )
    )
    ext_result = await db.execute(ext_stmt)
    extension = ext_result.scalar_one_or_none()
    
    if not extension:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Extension request not found",
        )

    if extension.status != "host_approved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Extension must be host-approved before payment. Current status: {extension.status}",
        )

    # Enforce 24-hour rule: payment must be started at least 24h before the current end date
    now = datetime.now(timezone.utc)
    end = booking.end_date
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if end - now < timedelta(hours=24):
        extension.status = "expired"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Extension payment must be made at least 24 hours before the current drop-off time.",
        )

    # Verify payment method exists and belongs to client
    pm_stmt = (
        select(PaymentMethod)
        .filter(
            PaymentMethod.id == request.payment_method_id,
            PaymentMethod.client_id == current_client.id,
        )
    )
    pm_result = await db.execute(pm_stmt)
    payment_method = pm_result.scalar_one_or_none()
    
    if not payment_method:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment method not found or does not belong to you",
        )

    if payment_method.method_type != PaymentMethodType.MPESA:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only M-Pesa payment is supported for booking extensions at the moment.",
        )

    if not payment_method.mpesa_number:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="M-Pesa number is missing for this payment method",
        )

    amount_str = str(int(float(extension.extra_amount)))

    logger.info(
        " [MPESA STK PUSH EXT] Initiating for booking=%s, extension_id=%s, number=%s, amount=%s",
        booking.booking_id,
        extension.id,
        payment_method.mpesa_number,
        amount_str,
    )

    # Ensure M-Pesa number has country code (254 for Kenya) if missing
    mpesa_phone = str(payment_method.mpesa_number).strip()
    if mpesa_phone.startswith("0"):
        mpesa_phone = "254" + mpesa_phone[1:]
    elif not mpesa_phone.startswith("254"):
        mpesa_phone = "254" + mpesa_phone

    mpesa_response = await sendStkPush(
        amount=amount_str,
        PhoneNumber=mpesa_phone,
        AccountReference=str(booking.booking_id),
    )

    if mpesa_response is None or mpesa_response.get("ResponseCode") != "0":
        logger.error("[MPESA STK PUSH EXT] Failed: %s", mpesa_response)
        error_desc = (
            mpesa_response.get("ResponseDescription", "Unknown error")
            if mpesa_response
            else "No response from M-Pesa"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"M-Pesa STK Push failed: {error_desc}",
        )

    checkout_request_id = mpesa_response.get("CheckoutRequestID")
    transaction_id = checkout_request_id or f"TXN-EXT-{booking.booking_id}-{extension.id}"

    payment = Payment(
        booking_id=booking.id,
        client_id=current_client.id,
        checkout_request_id=checkout_request_id,
        amount=float(extension.extra_amount),
        status=PaymentStatus.PENDING,
        extension_request_id=extension.id,
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    # Reload booking with relationships for response
    from app.models import Car  # local import to avoid circular

    final_booking_stmt = (
        select(Booking)
        .options(joinedload(Booking.car).joinedload(Car.host))
        .filter(Booking.id == booking.id)
    )
    final_booking_result = await db.execute(final_booking_stmt)
    final_booking = final_booking_result.scalar_one_or_none()
    
    if not final_booking:
        raise HTTPException(status_code=404, detail="Booking lost during processing")

    from app.routers.bookings import booking_to_response
    from app.schemas import BookingResponse

    message = (
        "M-Pesa STK Push initiated for extension. "
        "Please check your phone to complete the payment. "
        "You can poll GET /client/payments/status?checkout_request_id=... for status."
    )

    return PaymentResponse(
        success=True,
        booking_id=str(final_booking.booking_id),
        amount_paid=float(extension.extra_amount),  # type: ignore
        payment_method_type=str(payment_method.method_type.value),
        payment_method_name=str(payment_method.name),
        transaction_id=str(transaction_id),
        message=message,
        paid_at=datetime.now(timezone.utc),
        booking=BookingResponse(**booking_to_response(final_booking)),
    )

@router.get("/client/payments/status", response_model=PaymentStatusResponse)
async def get_payment_status(
    checkout_request_id: Optional[str] = Query(None, description="M-Pesa CheckoutRequestID returned from process payment"),
    booking_id: Optional[str] = Query(None, description="Booking ID (e.g. BK-ABC12345); returns latest payment for this booking"),
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
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
    
    payment = None
    if checkout_request_id:
        stmt = (
            select(Payment)
            .options(joinedload(Payment.booking))
            .filter(
                Payment.checkout_request_id == checkout_request_id,
                Payment.client_id == current_client.id,
            )
        )
        result = await db.execute(stmt)
        payment = result.scalar_one_or_none()
    else:
        booking_stmt = (
            select(Booking)
            .filter(
                Booking.client_id == current_client.id,
                Booking.booking_id == booking_id,
            )
        )
        booking_result = await db.execute(booking_stmt)
        booking = booking_result.scalar_one_or_none()
        
        if not booking:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
        
        stmt = (
            select(Payment)
            .options(joinedload(Payment.booking))
            .filter(Payment.booking_id == booking.id, Payment.client_id == current_client.id)
            .order_by(Payment.created_at.desc())
        )
        result = await db.execute(stmt)
        payment = result.scalars().first()
    
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No payment found for this request or booking",
        )
    
    return _payment_to_status_response(payment)


def _normalize_callback_payload(data: dict) -> dict:
    """Extract and normalize callback payload; Payhero may nest under 'response' or use different casing."""
    payload = data.get("response", data)
    if not payload and isinstance(data.get("Body"), dict):
        # Safaricom-style nesting
        payload = data.get("Body", {}).get("stkCallback", data)
    # Normalize keys: prefer PascalCase from Payhero, fall back to snake_case
    def get_val(p: dict, *keys: str):
        for k in keys:
            if k in p and p[k] is not None:
                return p[k]
        return None
    # ExternalReference may be in response or at top level (we send booking_id when initiating)
    ext_ref = get_val(payload, "ExternalReference", "external_reference") or get_val(data, "ExternalReference", "external_reference")
    return {
        "CheckoutRequestID": get_val(payload, "CheckoutRequestID", "checkout_request_id", "reference"),
        "ExternalReference": ext_ref,
        "ResultCode": get_val(payload, "ResultCode", "result_code"),
        "ResultDesc": get_val(payload, "ResultDesc", "result_desc"),
        "Status": get_val(payload, "Status", "status"),
        "MpesaReceiptNumber": get_val(payload, "MpesaReceiptNumber", "mpesa_receipt_number"),
        "PhoneNumber": get_val(payload, "PhoneNumber", "Phone", "phone_number"),
        "TransactionDate": get_val(payload, "TransactionDate", "transaction_date"),
    }


@router.post("/mpesa/callback")
async def mpesa_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Payhero M-Pesa STK Push Callback URL.
    Called by Payhero after the user completes, cancels, or fails the STK push.
    Updates the Payment record and, on success, confirms the booking.

    IMPORTANT: PAYHERO_CALLBACK_URL in .env must be a **public** URL (e.g. https://your-api.com/api/v1/mpesa/callback).
    If it points to localhost, Payhero cannot reach it and status will stay "pending".
    """
    # Log immediately so we see any request reaching this endpoint (before parsing body)
    logger.info("[PAYHERO CALLBACK] Endpoint hit: method=%s path=%s", request.method, request.url.path)
    print("[PAYHERO CALLBACK] Endpoint hit – request received from Payhero", flush=True)
    try:
        body = await request.body()
        try:
            data = json.loads(body) if body else {}
        except Exception as body_err:
            logger.warning(
                "[PAYHERO CALLBACK] Invalid JSON body (len=%s). Error: %s. Body preview: %s",
                len(body), body_err, (body[:500].decode("utf-8", errors="replace") if body else ""),
            )
            print("[PAYHERO CALLBACK] Invalid JSON – check logs for body preview", flush=True)
            return {"ResultCode": 0, "ResultDesc": "Success"}
        logger.info("[PAYHERO CALLBACK] Received payload: %s", data)
        
        payload = _normalize_callback_payload(data)
        checkout_request_id = payload["CheckoutRequestID"]
        external_reference = payload["ExternalReference"]  # We send booking_id (e.g. BK-xxx) when initiating
        result_code = payload["ResultCode"]
        result_desc = payload["ResultDesc"] or ""
        status_str = payload["Status"]
        
        if not checkout_request_id and not external_reference:
            logger.warning("[PAYHERO CALLBACK] No CheckoutRequestID or ExternalReference in callback")
            return {"ResultCode": 0, "ResultDesc": "Success"}
        
        payment = None
        if checkout_request_id:
            pay_stmt = select(Payment).filter(
                Payment.checkout_request_id == checkout_request_id,
                Payment.status == PaymentStatus.PENDING,
            )
            pay_result = await db.execute(pay_stmt)
            payment = pay_result.scalar_one_or_none()
            
        if not payment and external_reference:
            # Fallback: match by ExternalReference (booking_id we sent when initiating STK push)
            bk_stmt = select(Booking).filter(Booking.booking_id == str(external_reference))
            bk_result = await db.execute(bk_stmt)
            booking = bk_result.scalar_one_or_none()
            
            if booking:
                pay_stmt = select(Payment).filter(
                    Payment.booking_id == booking.id,
                    Payment.status == PaymentStatus.PENDING,
                ).order_by(Payment.id.desc())
                pay_result = await db.execute(pay_stmt)
                payment = pay_result.scalars().first()
                
                if payment:
                    payment.checkout_request_id = checkout_request_id or payment.checkout_request_id
                    logger.info("[PAYHERO CALLBACK] Matched payment by ExternalReference=%s (booking_id)", external_reference)
        
        if not payment:
            logger.warning(
                "[PAYHERO CALLBACK] No pending payment for CheckoutRequestID=%s, ExternalReference=%s",
                checkout_request_id, external_reference,
            )
            return {"ResultCode": 0, "ResultDesc": "Success"}
        
        result_code_str = str(result_code) if result_code is not None else ""
        is_success = result_code_str == "0" or (status_str and str(status_str).lower() == "success")
        
        if is_success:
            receipt = payload["MpesaReceiptNumber"]
            phone = payload["PhoneNumber"]
            transaction_date = payload["TransactionDate"]
            
            payment.status = PaymentStatus.COMPLETED
            payment.result_code = result_code
            payment.result_desc = result_desc
            payment.mpesa_receipt_number = str(receipt) if receipt else None
            payment.mpesa_phone = str(phone) if phone else None
            payment.mpesa_transaction_date = str(transaction_date) if transaction_date else None
            
            bk_stmt = select(Booking).filter(Booking.id == payment.booking_id)
            bk_result = await db.execute(bk_stmt)
            booking = bk_result.scalar_one_or_none()

            if booking and booking.status == BookingStatus.PENDING:
                booking.status = BookingStatus.CONFIRMED
                booking.status_updated_at = datetime.now(timezone.utc)

            if payment.extension_request_id is not None:
                ext_stmt = (
                    select(BookingExtensionRequest)
                    .filter(BookingExtensionRequest.id == payment.extension_request_id)
                )
                ext_result = await db.execute(ext_stmt)
                extension = ext_result.scalar_one_or_none()
                
                if extension and booking and extension.status == "host_approved":
                    from app.routers.bookings import DAMAGE_WAIVER_PRICE_PER_DAY  # type: ignore
                    extension.status = "paid"
                    extra_days = extension.extra_days
                    extra_base = booking.daily_rate * extra_days  # type: ignore
                    extra_damage = (
                        DAMAGE_WAIVER_PRICE_PER_DAY * extra_days  # type: ignore
                        if booking.damage_waiver_enabled  # type: ignore
                        else 0
                    )
                    booking.base_price = (booking.base_price or 0) + extra_base  # type: ignore
                    booking.damage_waiver_fee = (booking.damage_waiver_fee or 0) + extra_damage  # type: ignore
                    booking.total_price = (booking.base_price or 0) + (booking.damage_waiver_fee or 0)  # type: ignore
                    booking.rental_days = (booking.rental_days or 0) + extra_days  # type: ignore
                    booking.end_date = extension.requested_end_date  # type: ignore
                    booking.status_updated_at = datetime.now(timezone.utc)

            await db.commit()
            logger.info("[PAYHERO CALLBACK] Payment successful: Receipt=%s, CheckoutRequestID=%s", receipt, checkout_request_id)
        else:
            # Failed: cancelled, insufficient funds, timeout, or other
            payment.status = PaymentStatus.CANCELLED if result_code_str == "1032" else PaymentStatus.FAILED
            payment.result_code = result_code
            # User-friendly messages for common Safaricom/Payhero codes
            if result_code_str == "1032":
                payment.result_desc = "Payment cancelled. You can try again when ready."
            elif result_code_str == "2029":
                payment.result_desc = "Payment timed out or failed. Please try again."
            elif result_code_str == "1":
                payment.result_desc = "Insufficient funds. Please top up your M-Pesa and try again."
            elif result_desc:
                payment.result_desc = str(result_desc).strip()
            else:
                payment.result_desc = "Payment failed. Please try again."
            
            await db.commit()
            logger.warning(
                "[PAYHERO CALLBACK] Payment failed: ResultCode=%s, ResultDesc=%s, CheckoutRequestID=%s",
                result_code, payment.result_desc, checkout_request_id,
            )
            
        return {"ResultCode": 0, "ResultDesc": "Success"}
    except Exception as e:
        await db.rollback()
        logger.error("[PAYHERO CALLBACK] Error processing callback: %s", str(e), exc_info=True)
        return {"ResultCode": 0, "ResultDesc": "Success"}


@router.post("/payout/callback")
async def payout_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Payhero M-Pesa B2C (Payout) Callback URL.
    Called by Payhero after a payout to a host is completed or fails.
    Updates the Withdrawal record based on ExternalReference (withdrawal_id).
    """
    try:
        data = await request.json()
        logger.info(f"[PAYHERO PAYOUT CALLBACK] Received: {data}")
        
        # Payhero B2C sends ExternalReference which we set to the withdrawal ID
        # It also sends TransactionID, ResultCode, ResultDesc, Status, etc.
        external_reference = data.get("ExternalReference")
        result_code = data.get("ResultCode")
        result_desc = data.get("ResultDesc")
        status_str = data.get("Status")
        checkout_request_id = data.get("CheckoutRequestID") or data.get("TransactionID")
        
        if not external_reference:
            logger.warning("[PAYHERO PAYOUT CALLBACK] No ExternalReference (withdrawal_id) in callback")
            return {"ResultCode": 0, "ResultDesc": "Success"}
            
        # Extract numeric ID from external_reference (handle strings like "WD-123" if needed, 
        # but usually we just send the numeric ID)
        try:
            withdrawal_id = int(str(external_reference).split('-')[-1])
        except (ValueError, IndexError):
            logger.error(f"[PAYHERO PAYOUT CALLBACK] Invalid ExternalReference: {external_reference}")
            return {"ResultCode": 0, "ResultDesc": "Success"}
        
        wd_stmt = select(Withdrawal).filter(
            Withdrawal.id == withdrawal_id,
            Withdrawal.status == WithdrawalStatus.PENDING,
        )
        wd_result = await db.execute(wd_stmt)
        withdrawal = wd_result.scalar_one_or_none()
        
        if not withdrawal:
            logger.warning(f"[PAYHERO PAYOUT CALLBACK] No pending withdrawal for ID={withdrawal_id}")
            return {"ResultCode": 0, "ResultDesc": "Success"}
        
        # Store callback data
        withdrawal.result_code = result_code
        withdrawal.result_desc = result_desc
        withdrawal.checkout_request_id = str(checkout_request_id) if checkout_request_id else None
        withdrawal.mpesa_receipt_number = str(data.get("MpesaReceiptNumber")) if data.get("MpesaReceiptNumber") else None
        withdrawal.mpesa_phone = str(data.get("PhoneNumber")) if data.get("PhoneNumber") else None
        withdrawal.mpesa_transaction_date = str(data.get("TransactionDate")) if data.get("TransactionDate") else None
        withdrawal.processed_at = datetime.now(timezone.utc)
        
        # Payhero uses result_code 0 for success
        if str(result_code) == "0" or (status_str and str(status_str).lower() == "success"):
            withdrawal.status = WithdrawalStatus.COMPLETED
            logger.info(f"[PAYHERO PAYOUT CALLBACK] ✅ Payout Successful: ID={withdrawal_id}, Receipt={withdrawal.mpesa_receipt_number}")
        else:
            withdrawal.status = WithdrawalStatus.FAILED
            logger.warning(f"[PAYHERO PAYOUT CALLBACK] ❌ Payout Failed: {result_desc} (Code: {result_code}, ID: {withdrawal_id})")
            
        await db.commit()
        return {"ResultCode": 0, "ResultDesc": "Success"}
    except Exception as e:
        await db.rollback()
        logger.error(f"[PAYHERO PAYOUT CALLBACK] ❌ Error processing callback: {str(e)}", exc_info=True)
        return {"ResultCode": 0, "ResultDesc": "Success"}
