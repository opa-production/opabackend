"""
Payment processing endpoints
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Request, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, and_, or_
from datetime import datetime, timezone, timedelta
from typing import List, Optional
import json
import logging
import os

from app.database import get_db
from app.models import (
    Booking,
    PaymentMethod,
    Client,
    BookingStatus,
    PaymentMethodType,
    Payment,
    PaymentStatus,
    Withdrawal,
    WithdrawalStatus,
    BookingExtensionRequest,
    ClientWallet,
    StellarPaymentTransaction,
)
from app.auth import get_current_client
from app.schemas import (
    PaymentRequest,
    PaymentResponse,
    PaymentStatusResponse,
    PaymentStatusEnum,
    BookingExtensionPaymentRequest,
    ArdenaPayPaymentRequest,
    ArdenaPayPaymentResponse,
    StellarTransactionResponse,
)
from app.services.mpesa_stk_push import sendStkPush
from app.services.host_subscription_payment import process_host_subscription_mpesa_callback
from app.services.mpesa_callback_utils import infer_insufficient_funds, normalize_stk_result_code
from app.services.pesapal_payment import (
    get_ipn_id,
    submit_order,
    build_billing_address,
    get_transaction_status as pesapal_get_transaction_status,
)
from app.services.stellar_wallet import (
    get_balances,
    parse_balances_for_response,
    send_usdc_payment,
    send_xlm_payment,
    ksh_to_usdc,
    ksh_to_xlm,
    ksh_to_usd_float,
    _get_platform_public_key,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _payment_to_status_response(payment: Payment) -> PaymentStatusResponse:
    """Build PaymentStatusResponse from Payment model."""
    status_enum = PaymentStatusEnum(payment.status)
    message = payment.result_desc if payment.status != PaymentStatus.PENDING else None
    # For M-Pesa use checkout_request_id; for Pesapal card use order_tracking_id in both fields for polling
    checkout_or_tracking = payment.checkout_request_id or payment.pesapal_order_tracking_id or ""
    return PaymentStatusResponse(
        checkout_request_id=checkout_or_tracking,
        booking_id=payment.booking.booking_id,
        status=status_enum,
        message=message,
        amount=payment.amount,
        paid_at=payment.updated_at if payment.status == PaymentStatus.COMPLETED else None,
        mpesa_receipt_number=payment.mpesa_receipt_number,
        order_tracking_id=payment.pesapal_order_tracking_id,
    )


@router.post("/client/payments/process", response_model=PaymentResponse, status_code=status.HTTP_200_OK)
async def process_payment(
    background_tasks: BackgroundTasks,
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
        redirect_url: Optional[str] = None

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
        elif payment_method.method_type in (PaymentMethodType.VISA, PaymentMethodType.MASTERCARD):
            # Pesapal card: use OUR API base (not PESAPAL_BASE_URL). So Pesapal and user can reach our /pesapal/return and IPN.
            # e.g. https://api.ardena.xyz/api/v1 or ngrok https://xxx.ngrok-free.dev/api/v1
            callback_base = os.getenv("PESAPAL_CALLBACK_BASE_URL", "").rstrip("/")
            if not callback_base:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Card payment is not configured. Set PESAPAL_CALLBACK_BASE_URL to your API base (e.g. https://api.ardena.xyz/api/v1 or ngrok URL + /api/v1).",
                )
            ipn_url = f"{callback_base}/pesapal/ipn"
            ipn_id = get_ipn_id(ipn_url)
            if not ipn_id:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Pesapal IPN not configured. Set PESAPAL_IPN_ID in env or ensure PESAPAL_CALLBACK_BASE_URL is correct.",
                )
            callback_url = f"{callback_base}/pesapal/return"
            parts = (current_client.full_name or "Client").strip().split(None, 1)
            first_name = parts[0] if parts else "Client"
            last_name = parts[1] if len(parts) > 1 else ""
            billing_address = build_billing_address(
                email=current_client.email,
                first_name=first_name,
                last_name=last_name,
                phone_number=current_client.mobile_number,
                country_code="KE",
            )
            payment = Payment(
                booking_id=booking.id,
                client_id=current_client.id,
                amount=float(booking.total_price),
                status=PaymentStatus.PENDING,
            )
            db.add(payment)
            db.commit()
            db.refresh(payment)
            # Pesapal requires a unique "id" per SubmitOrderRequest (retries or same booking = new payment row = unique id)
            ref_safe = str(booking.booking_id).replace(" ", "_")
            reference = f"{ref_safe}-{payment.id}"[:50]
            result = submit_order(
                amount=float(booking.total_price),
                currency="KES",
                description=f"Booking {booking.booking_id}"[:100],
                callback_url=callback_url,
                notification_id=ipn_id,
                billing_address=billing_address,
                reference=reference,
            )
            if result.get("status") != "success":
                db.delete(payment)
                db.commit()
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=result.get("message", "Pesapal order submission failed"),
                )
            payment.pesapal_order_tracking_id = result.get("order_tracking_id")
            payment.pesapal_merchant_reference = result.get("merchant_reference")
            db.commit()
            db.refresh(payment)
            transaction_id = result.get("order_tracking_id") or transaction_id
            payment_message = (
                "Redirect to complete card payment. You can poll GET /client/payments/status?booking_id=... for status."
            )
            redirect_url = result.get("redirect_url")
            # Build response and return with redirect_url (handled below)
        else:
            # Other methods (e.g. future): confirm booking immediately
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
            booking=BookingResponse(**booking_to_response(final_booking)),  # Include full booking details
            redirect_url=redirect_url,
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


@router.post("/client/payments/process-ardena-pay", response_model=ArdenaPayPaymentResponse, status_code=status.HTTP_200_OK)
async def process_ardena_pay(
    background_tasks: BackgroundTasks,
    request: ArdenaPayPaymentRequest,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """
    Pay for a booking with Ardena Pay. Use payWithXlm=true to deduct XLM (converted from KSH);
    otherwise deducts USDC. UI can show XLM balance and convert to USD; when paying in XLM,
    backend deducts XLM and UI shows remaining XLM (converted to USD).
    """
    platform_key = _get_platform_public_key()
    if not platform_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ardena Pay is not configured (missing STELLAR_PLATFORM_PUBLIC_KEY).",
        )
    wallet = db.query(ClientWallet).filter(ClientWallet.client_id == current_client.id).first()
    if not wallet or not wallet.stellar_secret_encrypted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Ardena Pay wallet found. Create one with POST /api/v1/client/wallet.",
        )
    booking_query = db.query(Booking).options(joinedload(Booking.car)).filter(Booking.client_id == current_client.id)
    if isinstance(request.booking_id, int):
        booking = booking_query.filter(Booking.id == request.booking_id).first()
    else:
        booking = booking_query.filter(Booking.booking_id == request.booking_id).first()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    if booking.status != BookingStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Booking has already been processed. Current status: {booking.status}",
        )
    amount_ksh = float(booking.total_price)
    amount_usdc_str = ksh_to_usdc(amount_ksh)
    balances_raw = get_balances(wallet.stellar_public_key)
    balances = parse_balances_for_response(balances_raw)
    pay_with_xlm = getattr(request, "pay_with_xlm", False)

    if pay_with_xlm:
        amount_xlm_str = ksh_to_xlm(amount_ksh)
        balance_xlm = float(balances.get("xlm", "0"))
        amount_xlm_float = float(amount_xlm_str)
        if balance_xlm < amount_xlm_float:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient XLM balance. Need {amount_xlm_str} XLM, have {balance_xlm:.2f} XLM.",
            )
        tx_hash = send_xlm_payment(
            wallet.stellar_secret_encrypted,
            platform_key,
            amount_xlm_str,
        )
        if not tx_hash:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Stellar XLM payment failed. Please try again or use another payment method.",
            )
        result_desc = "Ardena Pay XLM"
        amount_xlm_for_record = amount_xlm_str
    else:
        balance_usdc = float(balances.get("usdc", "0"))
        amount_usdc_float = float(amount_usdc_str)
        if balance_usdc < amount_usdc_float:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient USDC balance. Need {amount_usdc_str} USDC, have {balance_usdc:.2f} USDC.",
            )
        tx_hash = send_usdc_payment(
            wallet.stellar_secret_encrypted,
            platform_key,
            amount_usdc_str,
        )
        if not tx_hash:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Stellar payment failed. Please try again or use another payment method.",
            )
        result_desc = "Ardena Pay USDC"
        amount_xlm_for_record = None

    try:
        payment = Payment(
            booking_id=booking.id,
            client_id=current_client.id,
            amount=amount_ksh,
            status=PaymentStatus.COMPLETED,
            result_desc=result_desc,
            stellar_tx_hash=tx_hash,
        )
        db.add(payment)
        stellar_tx = StellarPaymentTransaction(
            booking_id=booking.id,
            client_id=current_client.id,
            amount_ksh=amount_ksh,
            amount_usdc=amount_usdc_str,
            amount_xlm=amount_xlm_for_record,
            stellar_tx_hash=tx_hash,
            from_address=wallet.stellar_public_key,
            to_address=platform_key,
        )
        db.add(stellar_tx)
        booking.status = BookingStatus.CONFIRMED
        booking.status_updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(booking)
    except Exception as e:
        db.rollback()
        logger.exception("Ardena Pay: failed to save payment/booking: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment was sent but recording failed. Contact support with your wallet address.",
        )
    from app.models import Car
    from app.routers.bookings import booking_to_response
    from app.schemas import BookingResponse
    final_booking = db.query(Booking).options(
        joinedload(Booking.car).joinedload(Car.host)
    ).filter(Booking.id == booking.id).first()
    if not final_booking:
        raise HTTPException(status_code=404, detail="Booking not found after payment")
    from app.services.booking_emails import send_booking_ticket_email
    background_tasks.add_task(send_booking_ticket_email, booking.id)
    return ArdenaPayPaymentResponse(
        success=True,
        booking_id=str(final_booking.booking_id),
        amount_ksh=amount_ksh,
        amount_usdc=amount_usdc_str,
        amount_xlm=amount_xlm_for_record,
        stellar_tx_hash=tx_hash,
        message="Payment successful. Your booking is now confirmed.",
        paid_at=datetime.now(timezone.utc),
        booking=BookingResponse(**booking_to_response(final_booking)),
    )


@router.get("/client/payments/transactions", response_model=List[StellarTransactionResponse])
def list_ardena_pay_transactions(
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
    booking_id: Optional[int] = Query(None, description="Filter by booking id"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """
    List Ardena Pay (USDC/XLM) transactions for the current client. Optionally filter by booking_id.
    amount_usd is always set (from amount_ksh) for display.
    """
    q = db.query(StellarPaymentTransaction).filter(StellarPaymentTransaction.client_id == current_client.id)
    if booking_id is not None:
        q = q.filter(StellarPaymentTransaction.booking_id == booking_id)
    rows = q.order_by(StellarPaymentTransaction.created_at.desc()).offset(skip).limit(limit).all()
    return [
        StellarTransactionResponse(
            id=r.id,
            booking_id=r.booking_id,
            amount_ksh=r.amount_ksh,
            amount_usd=ksh_to_usd_float(r.amount_ksh),
            amount_usdc=r.amount_usdc,
            amount_xlm=r.amount_xlm,
            stellar_tx_hash=r.stellar_tx_hash,
            from_address=r.from_address,
            to_address=r.to_address,
            created_at=r.created_at,
        )
        for r in rows
    ]


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

@router.get("/pesapal/return")
async def pesapal_return(
    OrderTrackingId: Optional[str] = Query(None, alias="OrderTrackingId"),
    OrderMerchantReference: Optional[str] = Query(None, alias="OrderMerchantReference"),
):
    """
    Pesapal redirects the customer here after payment. We send them to FRONTEND_URL (e.g. oparides://payment/result).
    For custom schemes, many browsers don't follow 302 so we return HTML with "Open in app" link and auto-redirect attempt.
    """
    from fastapi.responses import RedirectResponse, HTMLResponse
    from app.config import settings
    frontend = (settings.FRONTEND_URL or "https://ardena.co.ke").strip()
    if frontend.endswith("://"):
        base = frontend
    else:
        base = frontend.rstrip("/")
    params = []
    if OrderTrackingId:
        params.append(f"OrderTrackingId={OrderTrackingId}")
    if OrderMerchantReference:
        params.append(f"OrderMerchantReference={OrderMerchantReference}")
    qs = "&".join(params)
    path_suffix = f"payment/result?{qs}" if qs else "payment/result"
    redirect_to = f"{base}{path_suffix}" if base.endswith("://") else f"{base}/{path_suffix}"
    # Custom scheme (e.g. oparides://): return HTML so user can tap "Open in app" if 302 is not followed
    if "://" in base and not base.startswith("http"):
        import html
        safe_url = html.escape(redirect_to, quote=True)
        html_content = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Payment complete</title>
<script>window.location.href = {repr(redirect_to)};</script>
</head><body>
<p>Payment submitted. Opening app...</p>
<p><a href="{safe_url}">Open in app</a> if nothing happens.</p>
</body></html>"""
        return HTMLResponse(content=html_content, status_code=200)
    return RedirectResponse(url=redirect_to, status_code=302)


def _pesapal_ipn_handle(
    background_tasks: BackgroundTasks,
    OrderTrackingId: Optional[str],
    OrderMerchantReference: Optional[str],
) -> dict:
    """Shared logic for Pesapal IPN (GET with OrderTrackingId, OrderMerchantReference)."""
    if not OrderTrackingId:
        logger.warning("[PESAPAL IPN] Missing OrderTrackingId")
        return {"status": "ok"}
    background_tasks.add_task(
        _pesapal_ipn_process,
        order_tracking_id=OrderTrackingId,
        merchant_reference=OrderMerchantReference or "",
    )
    return {"status": "ok"}


@router.get("/pesapal/ipn")
async def pesapal_ipn(
    background_tasks: BackgroundTasks,
    OrderTrackingId: Optional[str] = Query(None, alias="OrderTrackingId"),
    OrderMerchantReference: Optional[str] = Query(None, alias="OrderMerchantReference"),
):
    """
    Pesapal IPN. Pesapal sends GET with OrderTrackingId and OrderMerchantReference.
    """
    return _pesapal_ipn_handle(background_tasks, OrderTrackingId, OrderMerchantReference)


@router.get("/payments/ipn")
async def payments_ipn(
    background_tasks: BackgroundTasks,
    OrderTrackingId: Optional[str] = Query(None, alias="OrderTrackingId"),
    OrderMerchantReference: Optional[str] = Query(None, alias="OrderMerchantReference"),
):
    """Alias for Pesapal IPN so dashboard URL https://api.ardena.xyz/api/v1/payments/ipn works."""
    return _pesapal_ipn_handle(background_tasks, OrderTrackingId, OrderMerchantReference)


def _apply_pesapal_result_to_payment(db: Session, payment: Payment, result: dict) -> None:
    """Apply Pesapal GetTransactionStatus result to payment and booking. Caller must commit."""
    payment_status = (result.get("payment_status") or "").lower()
    if payment_status == "completed":
        payment.status = PaymentStatus.COMPLETED
        payment.result_desc = result.get("message") or "Card payment completed"
        payment.pesapal_confirmation_code = result.get("confirmation_code")
        payment.pesapal_payment_method = result.get("payment_method")
        payment.pesapal_payment_account = result.get("payment_account")
        booking = payment.booking
        if booking and booking.status == BookingStatus.PENDING:
            booking.status = BookingStatus.CONFIRMED
            booking.status_updated_at = datetime.now(timezone.utc)
        if payment.extension_request_id and booking:
            ext = (
                db.query(BookingExtensionRequest)
                .filter(BookingExtensionRequest.id == payment.extension_request_id)
                .first()
            )
            if ext and ext.status == "host_approved":
                from app.routers.bookings import DAMAGE_WAIVER_PRICE_PER_DAY
                ext.status = "paid"
                extra_days = ext.extra_days
                extra_base = float(booking.daily_rate or 0) * extra_days
                extra_damage = (
                    DAMAGE_WAIVER_PRICE_PER_DAY * extra_days
                    if booking.damage_waiver_enabled
                    else 0
                )
                booking.base_price = (booking.base_price or 0) + extra_base
                booking.damage_waiver_fee = (booking.damage_waiver_fee or 0) + extra_damage
                booking.total_price = (booking.base_price or 0) + (booking.damage_waiver_fee or 0)
                booking.rental_days = (booking.rental_days or 0) + extra_days
                booking.end_date = ext.requested_end_date
                booking.status_updated_at = datetime.now(timezone.utc)
        db.commit()
        if booking and payment.extension_request_id is None:
            from app.services.booking_emails import send_booking_ticket_email
            try:
                send_booking_ticket_email(booking.id)
            except Exception as e:
                logger.exception("[PESAPAL] send_booking_ticket_email failed: %s", e)
    elif payment_status in ("failed", "invalid", "reversed"):
        payment.status = PaymentStatus.FAILED
        payment.result_desc = result.get("message") or f"Payment status: {payment_status}"
        db.commit()


def _pesapal_ipn_process(
    order_tracking_id: str,
    merchant_reference: str,
) -> None:
    """Background task: fetch Pesapal status and update Payment + Booking. Uses its own DB session."""
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        result = pesapal_get_transaction_status(order_tracking_id)
        if result.get("status") != "success":
            logger.warning("[PESAPAL IPN] GetTransactionStatus failed: %s", result.get("message"))
            return
        payment = (
            db.query(Payment)
            .options(joinedload(Payment.booking))
            .filter(
                Payment.pesapal_order_tracking_id == order_tracking_id,
                Payment.status == PaymentStatus.PENDING,
            )
            .first()
        )
        if not payment and merchant_reference:
            payment = (
                db.query(Payment)
                .options(joinedload(Payment.booking))
                .filter(
                    Payment.pesapal_merchant_reference == merchant_reference,
                    Payment.status == PaymentStatus.PENDING,
                )
                .first()
            )
        if not payment:
            logger.warning("[PESAPAL IPN] No pending payment for OrderTrackingId=%s", order_tracking_id)
            return
        payment_status = (result.get("payment_status") or "").lower()
        if payment_status in ("completed", "failed", "invalid", "reversed"):
            _apply_pesapal_result_to_payment(db, payment, result)
            logger.info("[PESAPAL IPN] Updated payment: order_tracking_id=%s, status=%s", order_tracking_id, payment_status)
    except Exception as e:
        logger.exception("[PESAPAL IPN] Error: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


@router.get("/client/payments/status", response_model=PaymentStatusResponse)
async def get_payment_status(
    checkout_request_id: Optional[str] = Query(None, description="M-Pesa CheckoutRequestID or Pesapal order_tracking_id"),
    order_tracking_id: Optional[str] = Query(None, description="Pesapal order_tracking_id (alternative to checkout_request_id)"),
    booking_id: Optional[str] = Query(None, description="Booking ID (e.g. BK-ABC12345); returns latest payment for this booking"),
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Get status of an M-Pesa or Pesapal card payment. Poll after initiating payment.
    - **pending**: User has not yet completed or cancelled.
    - **completed**: Payment successful; booking is confirmed.
    - **cancelled**: User cancelled (M-Pesa) or failed (card).
    - **failed**: e.g. insufficient funds, timeout (see `message` for reason).

    Provide one of: checkout_request_id, order_tracking_id, or booking_id.
    """
    lookup_id = checkout_request_id or order_tracking_id
    if not lookup_id and not booking_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide one of: checkout_request_id, order_tracking_id, or booking_id",
        )
    
    payment = None
    if checkout_request_id:
        stmt = (
            select(Payment)
            .options(joinedload(Payment.booking))
            .filter(
                Payment.client_id == current_client.id,
                or_(Payment.checkout_request_id == lookup_id, Payment.pesapal_order_tracking_id == lookup_id),
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
    """
    Extract and normalize callback payload.
    Payhero may use `response`, Safaricom uses Body.stkCallback — we must read **both**;
    otherwise CheckoutRequestID/ResultCode stay null and STK stays pending forever.
    """
    if not isinstance(data, dict):
        data = {}

    def get_val(p: object, *keys: str):
        if not isinstance(p, dict):
            return None
        for k in keys:
            if k in p and p[k] is not None:
                return p[k]
        return None

    response = data.get("response")
    response = response if isinstance(response, dict) else None
    stk_callback = None
    body = data.get("Body")
    if isinstance(body, dict):
        sc = body.get("stkCallback")
        if isinstance(sc, dict):
            stk_callback = sc

    # Search order: flat response object, Safaricom stkCallback, then top-level body
    layers = [x for x in (response, stk_callback, data) if isinstance(x, dict)]

    def first(*keys: str):
        for layer in layers:
            v = get_val(layer, *keys)
            if v is not None:
                return v
        return None

    ext_ref = first("ExternalReference", "external_reference")
    if ext_ref is None:
        ext_ref = get_val(data, "ExternalReference", "external_reference")

    return {
        "CheckoutRequestID": first("CheckoutRequestID", "checkout_request_id", "reference"),
        "ExternalReference": ext_ref,
        "ResultCode": first("ResultCode", "result_code"),
        "ResultDesc": first("ResultDesc", "result_desc"),
        "Status": first("Status", "status"),
        "MpesaReceiptNumber": first("MpesaReceiptNumber", "mpesa_receipt_number"),
        "PhoneNumber": first("PhoneNumber", "Phone", "phone_number"),
        "TransactionDate": first("TransactionDate", "transaction_date"),
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

        # Host subscription uses ExternalReference H-SUB-{id}. Handle before booking Payment lookup so
        # we never mis-route if Payhero payload is unusual.
        ext_for_sub = str(external_reference).strip() if external_reference else ""
        if ext_for_sub.upper().startswith("H-SUB"):
            if process_host_subscription_mpesa_callback(db, payload):
                logger.info(
                    "[PAYHERO CALLBACK] Handled host subscription (H-SUB first): CheckoutRequestID=%s, ExternalReference=%s",
                    checkout_request_id,
                    external_reference,
                )
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
            # Host subscription STK (external_reference H-SUB-{id})
            if process_host_subscription_mpesa_callback(db, payload):
                logger.info(
                    "[PAYHERO CALLBACK] Handled host subscription: CheckoutRequestID=%s, ExternalReference=%s",
                    checkout_request_id,
                    external_reference,
                )
                return {"ResultCode": 0, "ResultDesc": "Success"}
            logger.warning(
                "[PAYHERO CALLBACK] No pending payment for CheckoutRequestID=%s, ExternalReference=%s",
                checkout_request_id, external_reference,
            )
            return {"ResultCode": 0, "ResultDesc": "Success"}
        
        result_code_str = normalize_stk_result_code(result_code)
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
            elif infer_insufficient_funds(result_code_str, str(result_desc)):
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
