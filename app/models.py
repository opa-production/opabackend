from typing import Optional
from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey, Float, Text, Boolean, Enum as SQLEnum
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func
from app.database import Base
import enum
import datetime


class PaymentMethodType(str, enum.Enum):
    """Payment method types"""
    MPESA = "mpesa"
    VISA = "visa"
    MASTERCARD = "mastercard"


class VerificationStatus(str, enum.Enum):
    """Car verification status"""
    AWAITING = "awaiting"
    VERIFIED = "verified"
    DENIED = "denied"


class PaymentMethod(Base):
    """Payment methods for hosts and clients"""
    __tablename__ = "payment_methods"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id"), nullable=True, index=True)  # Nullable to support clients
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=True, index=True)  # Nullable to support hosts

    # Payment method name (e.g., "John's M-Pesa", "My Visa Card")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Payment method type
    method_type: Mapped[PaymentMethodType] = mapped_column(SQLEnum(PaymentMethodType), nullable=False)
    
    # For M-Pesa
    mpesa_number: Mapped[str] = mapped_column(String(20), nullable=True)  # e.g., "254712345678"
    
    # For cards (Visa/Mastercard)
    card_number_hash: Mapped[str] = mapped_column(String(255), nullable=True)  # Hashed card number
    card_last_four: Mapped[str] = mapped_column(String(4), nullable=True)  # Last 4 digits for display
    card_type: Mapped[str] = mapped_column(String(20), nullable=True)  # "visa" or "mastercard"
    expiry_month: Mapped[int] = mapped_column(Integer, nullable=True)  # 1-12
    expiry_year: Mapped[int] = mapped_column(Integer, nullable=True)  # YYYY
    cvc_hash: Mapped[str] = mapped_column(String(255), nullable=True)  # Hashed CVC/CVV

    # Metadata
    is_default: Mapped[bool] = mapped_column(default=False)  # Default payment method
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    
    # Relationships
    host: Mapped["Host"] = relationship(back_populates="payment_methods")
    client: Mapped["Client"] = relationship(back_populates="payment_methods")

class PaymentStatus(str, enum.Enum):
    """Status of an M-Pesa STK push / payment attempt"""
    PENDING = "pending"       # STK sent, waiting for user to enter PIN / complete
    COMPLETED = "completed"   # User paid successfully
    CANCELLED = "cancelled"   # User cancelled on phone
    FAILED = "failed"        # e.g. insufficient funds, timeout, declined


class Payment(Base):
    """Tracks a single payment attempt (e.g. M-Pesa STK push). Enables UI to poll status."""
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), nullable=False, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    # Optional link to an extension request when this payment is for an extension
    extension_request_id: Mapped[int] = mapped_column(ForeignKey("booking_extension_requests.id"), nullable=True, index=True)

    # M-Pesa STK: Safaricom checkout id (unique per push)
    checkout_request_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    # Status: pending -> completed | cancelled | failed (set by callback or timeout)
    status: Mapped[str] = mapped_column(SQLEnum(PaymentStatus), default=PaymentStatus.PENDING, nullable=False)
    # From M-Pesa callback when not success
    result_code: Mapped[Optional[int]] = mapped_column(nullable=True)   # Safaricom ResultCode
    result_desc: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # e.g. "Insufficient funds", "User cancelled"
    # From M-Pesa callback on success
    mpesa_receipt_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    mpesa_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    mpesa_transaction_date: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # Pesapal: Card payment tracking (Visa/Mastercard)
    pesapal_order_tracking_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True, index=True)
    pesapal_merchant_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    pesapal_confirmation_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    pesapal_payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # e.g., "Visa", "Mastercard"
    pesapal_payment_account: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # Last 4 digits
    # Ardena Pay: Stellar transaction hash when payment was made via USDC
    stellar_tx_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    booking: Mapped["Booking"] = relationship(back_populates="payments")
    client: Mapped["Client"] = relationship(back_populates="payments")
    extension_request: Mapped["BookingExtensionRequest"] = relationship(foreign_keys=[extension_request_id])


class RefundStatus(str, enum.Enum):
    """Lifecycle of a refund record."""
    PENDING = "pending"      # Created, awaiting finance processing
    PROCESSING = "processing"  # Being processed at PSP/bank/M-Pesa
    COMPLETED = "completed"  # Money has been sent back to client
    FAILED = "failed"        # Attempted but failed at PSP/bank
    CANCELLED = "cancelled"  # Admin cancelled / closed without paying out


class Refund(Base):
    """
    Admin‑visible refund record so finance can track refunds for bookings.

    This does not itself move money; it records the decision, amounts, and processing
    status so finance can reconcile with payment providers.
    """
    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), nullable=False, index=True)
    payment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("payments.id"),
        nullable=True,
        index=True,
        doc="Optional link to a specific payment row when refunding a particular attempt.",
    )
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)

    # Financials (in KES)
    amount_original: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Total amount originally paid for this booking (or payment) in KES at refund creation time.",
    )
    amount_refund: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Amount to be refunded to the client in KES, according to policy/decision.",
    )
    percentage: Mapped[float] = mapped_column(
        Float,
        nullable=True,
        doc="Refund percentage of the original amount (0.0‑1.0) for reporting.",
    )

    status: Mapped[RefundStatus] = mapped_column(
        SQLEnum(RefundStatus),
        default=RefundStatus.PENDING,
        nullable=False,
        index=True,
    )

    # Who/why
    reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Short reason visible to client (e.g. 'Cancelled within 24h – 50% refund').",
    )
    internal_note: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Internal note for finance/admin (e.g. PSP reference, manual overrides).",
    )
    created_by_admin_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("admins.id"),
        nullable=True,
        index=True,
        doc="Admin who created this refund record.",
    )
    processed_by_admin_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("admins.id"),
        nullable=True,
        index=True,
        doc="Admin who marked this refund as completed/failed/cancelled.",
    )

    # PSP / external references (optional)
    external_reference: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        doc="Optional reference from payment provider (reversal ID, transaction ID, etc.).",
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True),
        onupdate=func.now(),
        nullable=True,
    )
    processed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the refund was actually processed (money sent).",
    )
    client_deleted_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the client chose to hide/delete this refund from their view.",
    )

    # Relationships
    booking: Mapped["Booking"] = relationship("Booking", foreign_keys=[booking_id])
    payment: Mapped[Optional["Payment"]] = relationship("Payment", foreign_keys=[payment_id])
    client: Mapped["Client"] = relationship("Client", foreign_keys=[client_id])
    created_by_admin: Mapped[Optional["Admin"]] = relationship(
        "Admin",
        foreign_keys=[created_by_admin_id],
    )
    processed_by_admin: Mapped[Optional["Admin"]] = relationship(
        "Admin",
        foreign_keys=[processed_by_admin_id],
    )


class Host(Base):
    """Car owners/rental hosts"""
    __tablename__ = "hosts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=True)
    google_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=True)
    
    # Profile fields
    bio: Mapped[str] = mapped_column(Text, nullable=True)
    mobile_number: Mapped[str] = mapped_column(String(50), nullable=True)
    id_number: Mapped[str] = mapped_column(String(100), nullable=True)  # ID number, passport number, or DL number
    city: Mapped[str] = mapped_column(String(100), nullable=True)  # City where the host operates
    
    # Media URLs (stored in Supabase Storage)
    avatar_url: Mapped[str] = mapped_column(String(500), nullable=True)
    cover_image_url: Mapped[str] = mapped_column(String(500), nullable=True)
    id_document_url: Mapped[str] = mapped_column(String(500), nullable=True)
    license_document_url: Mapped[str] = mapped_column(String(500), nullable=True)
    
    # Account status
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    terms_accepted_at = mapped_column(DateTime(timezone=True), nullable=True)  # When user accepted T&C

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Paid subscription (M-Pesa). Default free; starter/premium set after successful payment.
    subscription_plan: Mapped[str] = mapped_column(String(20), default="free", nullable=False)
    subscription_expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationship to cars
    cars: Mapped[list["Car"]] = relationship(back_populates="host")
    # Relationship to payment methods
    payment_methods: Mapped[list["PaymentMethod"]] = relationship(back_populates="host", cascade="all, delete-orphan")
    # Relationship to feedback
    feedbacks: Mapped["Feedback"] = relationship(back_populates="host", cascade="all, delete-orphan")
    # Relationship to host ratings
    host_ratings: Mapped[list["HostRating"]] = relationship(back_populates="host", cascade="all, delete-orphan")
    # Relationship to client (renter) ratings given by this host
    client_ratings: Mapped[list["ClientRating"]] = relationship(back_populates="host", cascade="all, delete-orphan")
    # Relationship to withdrawals
    withdrawals: Mapped[list["Withdrawal"]] = relationship(back_populates="host", cascade="all, delete-orphan")
    # KYC (Veriff) - one-to-many for history; use latest for status
    host_kycs: Mapped[list["HostKyc"]] = relationship(back_populates="host", cascade="all, delete-orphan")
    # Biometric device tokens for local unlock
    biometric_tokens: Mapped[list["HostBiometricToken"]] = relationship(
        back_populates="host",
        cascade="all, delete-orphan"
    )
    subscription_payments: Mapped[list["HostSubscriptionPayment"]] = relationship(
        "HostSubscriptionPayment",
        back_populates="host",
        cascade="all, delete-orphan",
    )


class HostSubscriptionPayment(Base):
    """M-Pesa STK checkout for host subscription (starter / premium)."""

    __tablename__ = "host_subscription_payments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id"), nullable=False, index=True)
    plan: Mapped[str] = mapped_column(String(20), nullable=False)  # starter | premium
    amount_ksh: Mapped[float] = mapped_column(Float, nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    checkout_request_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    external_reference: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    result_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    result_desc: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    mpesa_receipt_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    mpesa_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    mpesa_transaction_date: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    host: Mapped["Host"] = relationship("Host", back_populates="subscription_payments")


class HostKyc(Base):
    """Host KYC verification result from Veriff (no doc images stored)."""
    __tablename__ = "host_kycs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id"), nullable=False, index=True)
    veriff_session_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)  # Veriff verification/session ID
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # approved, declined, pending, resubmission_requested
    document_type: Mapped[str] = mapped_column(String(80), nullable=True)  # passport, id_card, drivers_license, etc.
    decision_reason: Mapped[str] = mapped_column(String(500), nullable=True)  # reason if declined
    verified_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=True)  # when Veriff decided
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True, nullable=False)

    host: Mapped["Host"] = relationship(back_populates="host_kycs")


class WithdrawalStatus(str, enum.Enum):
    """Status of a host withdrawal request"""
    PENDING = "pending"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    FAILED = "failed"


class Withdrawal(Base):
    """Host withdrawal request: amount and payment details for admin to process."""
    __tablename__ = "withdrawals"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id"), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(nullable=False)
    status: Mapped[WithdrawalStatus] = mapped_column(SQLEnum(WithdrawalStatus), default=WithdrawalStatus.PENDING, nullable=False)
    # Where to send: mpesa, bank, etc.
    payment_method_type: Mapped[str] = mapped_column(String(20), nullable=False)  # mpesa, bank
    payment_details: Mapped[str] = mapped_column(Text, nullable=True)  # JSON: e.g. {"mpesa_number":"254..."} or {"bank_name":"...","account_number":"..."}
    
    # Payhero/M-Pesa B2C callback fields
    checkout_request_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True) # Payhero TransactionID
    result_code: Mapped[Optional[int]] = mapped_column(nullable=True)
    result_desc: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    mpesa_receipt_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    mpesa_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    mpesa_transaction_date: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Admin processing
    processed_at = mapped_column(DateTime(timezone=True), nullable=True)
    processed_by_admin_id: Mapped[int] = mapped_column(ForeignKey("admins.id"), nullable=True, index=True)
    admin_notes: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    host: Mapped["Host"] = relationship(back_populates="withdrawals")
    processed_by: Mapped["Admin"] = relationship(foreign_keys=[processed_by_admin_id])


class Client(Base):
    """Car renters/clients"""
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=True)
    google_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=True)
    
    # Profile fields
    bio: Mapped[str] = mapped_column(Text, nullable=True)
    fun_fact: Mapped[str] = mapped_column(Text, nullable=True)
    mobile_number: Mapped[str] = mapped_column(String(50), nullable=True)  # Required for updates, but nullable for existing clients
    id_number: Mapped[str] = mapped_column(String(100), nullable=True)  # Required for updates, but nullable for existing clients
    date_of_birth = mapped_column(Date, nullable=True)  # Required for updates, but nullable for existing clients
    gender: Mapped[str] = mapped_column(String(20), nullable=True)  # Required for updates, but nullable for existing clients - e.g., "male", "female", "other"
    
    # Media URLs (stored in Supabase Storage)
    avatar_url: Mapped[str] = mapped_column(String(500), nullable=True)
    id_document_url: Mapped[str] = mapped_column(String(500), nullable=True)
    license_document_url: Mapped[str] = mapped_column(String(500), nullable=True)
    
    # Account status
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    terms_accepted_at = mapped_column(DateTime(timezone=True), nullable=True)  # When user accepted T&C

    # Notification preferences
    email_notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sms_notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    in_app_notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationship to driving license
    driving_license: Mapped["DrivingLicense"] = relationship(back_populates="client", uselist=False, cascade="all, delete-orphan")
    # Relationship to payment methods
    payment_methods: Mapped["PaymentMethod"] = relationship(back_populates="client", cascade="all, delete-orphan")
    # KYC (Veriff) - one-to-many for history; use latest for status
    client_kycs: Mapped["ClientKyc"] = relationship(back_populates="client", cascade="all, delete-orphan")
    # Biometric device tokens for local unlock
    biometric_tokens: Mapped[list["ClientBiometricToken"]] = relationship(
        back_populates="client",
        cascade="all, delete-orphan"
    )


class ClientKyc(Base):
    """Client KYC verification result from Veriff (mirrors HostKyc)."""
    __tablename__ = "client_kycs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    veriff_session_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # approved, declined, pending, resubmission_requested
    document_type: Mapped[str] = mapped_column(String(80), nullable=True)
    decision_reason: Mapped[str] = mapped_column(String(500), nullable=True)
    verified_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True, nullable=False)

    client: Mapped["Client"] = relationship(back_populates="client_kycs")


class ClientWallet(Base):
    """Ardena Pay: Stellar wallet for a client (one per client). Testnet/mainnet."""
    __tablename__ = "client_wallets"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, unique=True, index=True)
    network: Mapped[str] = mapped_column(String(20), nullable=False, default="testnet")  # testnet | mainnet
    stellar_public_key: Mapped[str] = mapped_column(String(56), nullable=False, unique=True, index=True)
    stellar_secret_encrypted: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # optional: encrypted or plain for testnet
    # Cached balances (updated on each GET /client/wallet from Horizon)
    balance_xlm: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, default="0")
    balance_usdc: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, default="0")
    balance_updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    client: Mapped["Client"] = relationship(back_populates="wallet")


class StellarPaymentTransaction(Base):
    """Ardena Pay: Record of a USDC or XLM payment from client wallet to platform (booking payment)."""
    __tablename__ = "stellar_payment_transactions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), nullable=False, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    amount_ksh: Mapped[float] = mapped_column(Float, nullable=False)
    amount_usdc: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # USD equivalent for display
    amount_xlm: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # Set when paid in XLM
    stellar_tx_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    from_address: Mapped[str] = mapped_column(String(56), nullable=False)
    to_address: Mapped[str] = mapped_column(String(56), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    booking: Mapped["Booking"] = relationship("Booking", back_populates="stellar_payments")
    client: Mapped["Client"] = relationship("Client", backref="stellar_payment_transactions")


class IncomingStellarPayment(Base):
    """Ardena Pay: Incoming payment to a client's wallet (USDC or XLM). Used for in-app messages/notifications."""
    __tablename__ = "incoming_stellar_payments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    stellar_tx_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    amount_asset: Mapped[str] = mapped_column(String(10), nullable=False)  # "USDC" or "XLM"
    amount: Mapped[str] = mapped_column(String(50), nullable=False)
    from_address: Mapped[str] = mapped_column(String(56), nullable=False)
    to_address: Mapped[str] = mapped_column(String(56), nullable=False)  # client's wallet
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Link to the in-app notification we created for this receipt (optional)
    notification_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    client: Mapped["Client"] = relationship("Client", backref="incoming_stellar_payments")


class ClientBiometricToken(Base):
    """Device token used for biometric-based local unlock (no biometrics stored)."""
    __tablename__ = "client_biometric_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    # SHA-256 hash of a random device secret stored only on the device
    device_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    # Optional human-readable device name/info for UI
    device_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    last_used_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    client: Mapped["Client"] = relationship("Client", back_populates="biometric_tokens")


class HostBiometricToken(Base):
    """Device token used for biometric-based local unlock for hosts (no biometrics stored)."""
    __tablename__ = "host_biometric_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id"), nullable=False, index=True)
    # SHA-256 hash of a random device secret stored only on the device
    device_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    # Optional human-readable device name/info for UI
    device_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    last_used_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    host: Mapped["Host"] = relationship("Host", back_populates="biometric_tokens")


class DrivingLicense(Base):
    """Client driving license information"""
    __tablename__ = "driving_licenses"
    
    id = mapped_column(Integer, primary_key=True, index=True)
    client_id = mapped_column(Integer, ForeignKey("clients.id"), unique=True, nullable=False, index=True)
    
    # License information
    license_number = mapped_column(String(50), nullable=False, unique=True, index=True)  # Mix of letters and numbers
    category = mapped_column(String(10), nullable=False)  # One letter + number (e.g., B1, C2, D1)
    issue_date = mapped_column(Date, nullable=False)
    expiry_date = mapped_column(Date, nullable=False)
    
    # Verification status
    is_verified = mapped_column(Boolean, default=False, nullable=False)  # Admin verification status
    verification_notes = mapped_column(Text, nullable=True)  # Admin notes
    
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    
    # Relationship to client
    client = relationship("Client", back_populates="driving_license")


class Car(Base):
    """Car listings"""
    __tablename__ = "cars"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id"), nullable=False)
    
    # Endpoint 1: Basics
    name: Mapped[str] = mapped_column(String(255))
    model: Mapped[str] = mapped_column(String(100))
    body_type: Mapped[str] = mapped_column(String(50))
    year: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)

    # Endpoint 2: Technical Specs (nullable until PUT /cars/{id}/specs — draft row after basics)
    seats: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fuel_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    transmission: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    color: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    mileage: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    features: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON string for up to 12 features

    # Endpoint 3: Pricing & Rules (nullable until PUT /cars/{id}/pricing)
    daily_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    weekly_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    monthly_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    min_rental_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_rental_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    min_age_requirement: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rules: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Endpoint 4: Location
    location_name: Mapped[str] = mapped_column(String(255), nullable=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=True)
    longitude: Mapped[float] = mapped_column(Float, nullable=True)

    # Media URLs (stored in Supabase Storage)
    image_urls: Mapped[str] = mapped_column(Text, nullable=True)  # JSON array of image URLs (legacy, kept for backward compatibility)
    video_url: Mapped[str] = mapped_column(String(500), nullable=True)  # Legacy, kept for backward compatibility
    
    # New media structure (uploaded directly by app to Supabase)
    cover_image: Mapped[str] = mapped_column(String(500), nullable=True)  # Single cover image URL
    car_images: Mapped[str] = mapped_column(Text, nullable=True)  # JSON array of up to 12 car image URLs
    car_video: Mapped[str] = mapped_column(String(500), nullable=True)  # Car video URL
    
    # Drive options: self_only | self_and_chauffeur | chauffeur_only
    drive_setting = Column(String(30), default="self_only", nullable=False)

    # Status tracking
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_status: Mapped[str] = mapped_column(String(20), default=VerificationStatus.AWAITING.value, nullable=False)
    rejection_reason: Mapped[str] = mapped_column(Text, nullable=True)  # Reason for rejection if denied
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # Hide from public listing
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationship to host
    host: Mapped["Host"] = relationship(back_populates="cars")
    # Relationship to bookings
    bookings: Mapped[list["Booking"]] = relationship(back_populates="car", cascade="all, delete-orphan")


class BookingStatus(str, enum.Enum):
    """Booking status lifecycle"""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class Booking(Base):
    """Car rental bookings"""
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    booking_id: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)  # Human-readable ID like BK-12345678
    
    # Foreign keys
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    car_id: Mapped[int] = mapped_column(ForeignKey("cars.id"), nullable=False, index=True)
    
    # Booking dates
    start_date: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    
    # Pickup and return details
    pickup_time: Mapped[str] = mapped_column(String(10), nullable=True)  # e.g., "10:00"
    return_time: Mapped[str] = mapped_column(String(10), nullable=True)
    pickup_location: Mapped[str] = mapped_column(String(500), nullable=True)
    return_location: Mapped[str] = mapped_column(String(500), nullable=True)
    
    # Pricing
    daily_rate: Mapped[float] = mapped_column(Float, nullable=False)  # Rate at time of booking
    rental_days: Mapped[int] = mapped_column(Integer, nullable=False)
    base_price: Mapped[float] = mapped_column(Float, nullable=False)  # daily_rate * rental_days
    damage_waiver_fee: Mapped[float] = mapped_column(Float, nullable=False)
    total_price: Mapped[float] = mapped_column(Float, nullable=False)
    damage_waiver_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    drive_type: Mapped[str] = mapped_column(String(20), default="self")  # 'self' or 'withDriver'
    check_in_preference: Mapped[str] = mapped_column(String(20), default="self")  # 'self' or 'assisted'
    special_requirements: Mapped[str] = mapped_column(Text, nullable=True)
        
    # Status
    status: Mapped[str] = mapped_column(SQLEnum(BookingStatus), default=BookingStatus.PENDING, nullable=False)
    status_updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str] = mapped_column(Text, nullable=True)
        
    # Timestamps
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    pickup_reminder_sent_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    client_deleted_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the client chose to hide/delete this booking from their view.",
    )

    # Relationships
    client: Mapped["Client"] = relationship(back_populates="bookings")
    car: Mapped["Car"] = relationship(back_populates="bookings")
    payments: Mapped[list["Payment"]] = relationship(back_populates="booking", cascade="all, delete-orphan")
    # Must cascade-delete: booking_id is NOT NULL; otherwise deleting car -> bookings tries to NULL FK and fails
    stellar_payments: Mapped[list["StellarPaymentTransaction"]] = relationship(
        "StellarPaymentTransaction",
        back_populates="booking",
        cascade="all, delete-orphan",
    )



class BookingExtensionRequest(Base):
    """Client request to extend an existing booking (same trip, later drop-off)."""
    __tablename__ = "booking_extension_requests"

    id = mapped_column(Integer, primary_key=True, index=True)
    booking_id = mapped_column(Integer, ForeignKey("bookings.id"), nullable=False, index=True)
    client_id = mapped_column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    host_id = mapped_column(Integer, ForeignKey("hosts.id"), nullable=False, index=True)

    # Dates
    old_end_date = mapped_column(DateTime(timezone=True), nullable=False)
    requested_end_date = mapped_column(DateTime(timezone=True), nullable=False)

    # Pricing for the extension period only
    extra_days = mapped_column(Integer, nullable=False)
    extra_amount = mapped_column(Float, nullable=False)  # Includes base + damage waiver for extra_days

    # Drop-off details
    dropoff_same_as_previous = mapped_column(Boolean, default=True, nullable=False)
    new_dropoff_location = mapped_column(String(500), nullable=True)

    # Lifecycle
    # pending_host_approval -> host_approved -> paid | expired | rejected
    status = mapped_column(String(50), nullable=False, index=True)
    host_note = mapped_column(Text, nullable=True)

    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    # Many-to-one: each extension belongs to one booking; no delete-orphan cascade from this side
    booking: Mapped["Booking"] = relationship("Booking", foreign_keys=[booking_id])
    client = relationship("Client", foreign_keys=[client_id])
    host = relationship("Host", foreign_keys=[host_id])


class BookingIssue(Base):
    """Host-reported issue concerning an active (or past) booking."""
    __tablename__ = "host_booking_issues"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False, index=True)
    host_id = Column(Integer, ForeignKey("hosts.id"), nullable=False, index=True)

    issue_type = Column(String(50), nullable=False, index=True)  # e.g. damage, late_return, no_show, misconduct, other
    description = Column(Text, nullable=False)

    # Status: open, in_review, resolved, closed
    status = Column(String(50), default="open", nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    booking = relationship("Booking", foreign_keys=[booking_id])
    host = relationship("Host", foreign_keys=[host_id])


# Update Client model to include bookings relationship
Client.bookings = relationship("Booking", back_populates="client", cascade="all, delete-orphan")
Client.payments = relationship("Payment", back_populates="client", cascade="all, delete-orphan")
Client.wallet = relationship("ClientWallet", back_populates="client", uselist=False, cascade="all, delete-orphan")
# Update Client model to include host ratings relationship
Client.host_ratings = relationship("HostRating", back_populates="client", cascade="all, delete-orphan")
# Update Client model to include ratings received from hosts
Client.client_ratings = relationship("ClientRating", back_populates="client", cascade="all, delete-orphan")


class Feedback(Base):
    """Host feedback"""
    __tablename__ = "feedbacks"

    id = mapped_column(Integer, primary_key=True, index=True)
    host_id = mapped_column(Integer, ForeignKey("hosts.id"), nullable=False, index=True)
    
    # Feedback content
    content = mapped_column(String(250), nullable=False)  # Max 250 characters
    
    # Admin moderation
    is_flagged = mapped_column(Boolean, default=False, nullable=False)  # Flagged for review
    
    # Metadata
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationship to host
    host = relationship("Host", foreign_keys=[host_id])


class ClientFeedback(Base):
    """Client feedback (general app feedback or suggestions)."""
    __tablename__ = "client_feedbacks"

    id = mapped_column(Integer, primary_key=True, index=True)
    client_id = mapped_column(Integer, ForeignKey("clients.id"), nullable=False, index=True)

    # Feedback content
    content = mapped_column(String(250), nullable=False)  # Max 250 characters

    # Admin moderation
    is_flagged = mapped_column(Boolean, default=False, nullable=False)  # Flagged for review

    # Metadata
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationship to client
    client = relationship("Client", foreign_keys=[client_id])


class HostRating(Base):
    """Client ratings for hosts"""
    __tablename__ = "host_ratings"

    id = mapped_column(Integer, primary_key=True, index=True)
    host_id = mapped_column(Integer, ForeignKey("hosts.id"), nullable=False, index=True)
    client_id = mapped_column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    booking_id = mapped_column(Integer, ForeignKey("bookings.id"), nullable=True, index=True)  # Optional: link to booking
    
    # Rating (1-5 stars)
    rating = mapped_column(Integer, nullable=False)  # 1 to 5
    
    # Review content
    review = mapped_column(Text, nullable=True)  # Optional text review
    
    # Metadata
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    host = relationship("Host", back_populates="host_ratings", foreign_keys=[host_id])
    client = relationship("Client", back_populates="host_ratings", foreign_keys=[client_id])
    booking = relationship("Booking", foreign_keys=[booking_id])
    
    # Unique constraint: one rating per client per host (or per booking if booking_id is provided)
    __table_args__ = (
        # Allow multiple ratings per client-host pair, but one per booking
        # We'll enforce this in the API logic
    )


class ClientRating(Base):
    """Host ratings for clients (renters)"""
    __tablename__ = "client_ratings"

    id = mapped_column(Integer, primary_key=True, index=True)
    client_id = mapped_column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    host_id = mapped_column(Integer, ForeignKey("hosts.id"), nullable=False, index=True)
    booking_id = mapped_column(Integer, ForeignKey("bookings.id"), nullable=True, index=True)  # Optional: link to booking

    # Rating (1-5 stars)
    rating = mapped_column(Integer, nullable=False)  # 1 to 5

    # Review content
    review = mapped_column(Text, nullable=True)  # Optional text review

    # Metadata
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    client = relationship("Client", back_populates="client_ratings", foreign_keys=[client_id])
    host = relationship("Host", back_populates="client_ratings", foreign_keys=[host_id])
    booking = relationship("Booking", foreign_keys=[booking_id])


class Admin(Base):
    """System administrators"""
    __tablename__ = "admins"

    id = mapped_column(Integer, primary_key=True, index=True)
    full_name = mapped_column(String(255), nullable=False)
    email = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password = mapped_column(String(255), nullable=False)
    
    # Admin role (super_admin, finance, customer_service)
    role = mapped_column(String(50), default="customer_service", nullable=False)
    
    # Account status
    is_active = mapped_column(Boolean, default=True, nullable=False)
    
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), onupdate=func.now())


class Notification(Base):
    """System notifications"""
    __tablename__ = "notifications"

    id = mapped_column(Integer, primary_key=True, index=True)
    
    # Recipient information
    recipient_type = mapped_column(String(20), nullable=False, index=True)  # "host" or "client"
    recipient_id = mapped_column(Integer, nullable=False, index=True)  # Host ID or Client ID
    
    # Notification content
    title = mapped_column(String(255), nullable=False)
    message = mapped_column(Text, nullable=False)
    notification_type = mapped_column(String(20), default="info", nullable=False)  # info, warning, success, error
    
    # Sender information (admin who sent it)
    sender_name = mapped_column(String(255), nullable=False, default="[Deon,CEO ardena]")
    
    # Read status
    is_read = mapped_column(Boolean, default=False, nullable=False, index=True)
    
    # Metadata
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class SupportConversation(Base):
    """Support conversation thread - one per host"""
    __tablename__ = "support_conversations"

    id = mapped_column(Integer, primary_key=True, index=True)
    host_id = mapped_column(Integer, ForeignKey("hosts.id"), nullable=False, unique=True, index=True)  # One conversation per host
    
    # Status
    status = mapped_column(String(20), default="open", nullable=False, index=True)  # open, closed
    is_read_by_host = mapped_column(Boolean, default=False, nullable=False)  # Host has read latest admin message
    is_read_by_admin = mapped_column(Boolean, default=False, nullable=False)  # Admin has read latest host message
    
    # Metadata
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = mapped_column(DateTime(timezone=True), onupdate=func.now())
    last_message_at = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)  # Last message timestamp
    
    # Relationships
    host = relationship("Host", foreign_keys=[host_id])
    messages = relationship("SupportMessage", back_populates="conversation", cascade="all, delete-orphan")


class SupportMessage(Base):
    """Individual messages in a support conversation"""
    __tablename__ = "support_messages"

    id = mapped_column(Integer, primary_key=True, index=True)
    conversation_id = mapped_column(Integer, ForeignKey("support_conversations.id"), nullable=False, index=True)
    
    # Sender information
    sender_type = mapped_column(String(20), nullable=False, index=True)  # "host" or "admin"
    sender_id = mapped_column(Integer, nullable=False)  # Host ID or Admin ID
    
    # Message content
    message = mapped_column(Text, nullable=False)
    
    # Read status (for the recipient)
    is_read = mapped_column(Boolean, default=False, nullable=False)
    
    # Metadata
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # Relationships
    conversation = relationship("SupportConversation", back_populates="messages")


class ClientHostConversation(Base):
    """Conversation between a client and a host"""
    __tablename__ = "client_host_conversations"

    id = mapped_column(Integer, primary_key=True, index=True)
    client_id = mapped_column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    host_id = mapped_column(Integer, ForeignKey("hosts.id"), nullable=False, index=True)
    
    # Read status
    is_read_by_client = mapped_column(Boolean, default=False, nullable=False)
    is_read_by_host = mapped_column(Boolean, default=False, nullable=False)
    
    # Metadata
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = mapped_column(DateTime(timezone=True), onupdate=func.now())
    last_message_at = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # Relationships
    client = relationship("Client", foreign_keys=[client_id])
    host = relationship("Host", foreign_keys=[host_id])
    messages = relationship("ClientHostMessage", back_populates="conversation", cascade="all, delete-orphan")


class ClientHostMessage(Base):
    """Individual messages in a client-host conversation"""
    __tablename__ = "client_host_messages"

    id = mapped_column(Integer, primary_key=True, index=True)
    conversation_id = mapped_column(Integer, ForeignKey("client_host_conversations.id"), nullable=False, index=True)
    
    # Sender information
    sender_type = mapped_column(String(20), nullable=False, index=True)  # "client" or "host"
    sender_id = mapped_column(Integer, nullable=False)  # Client ID or Host ID
    
    # Message content
    message = mapped_column(Text, nullable=False)
    
    # Read status (for the recipient)
    is_read = mapped_column(Boolean, default=False, nullable=False)
    
    # Metadata
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # Relationships
    conversation = relationship("ClientHostConversation", back_populates="messages")


class CarBlockedDate(Base):
    """Blocked dates for cars (maintenance, unavailable dates)"""
    __tablename__ = "car_blocked_dates"

    id = mapped_column(Integer, primary_key=True, index=True)
    car_id = mapped_column(Integer, ForeignKey("cars.id"), nullable=False, index=True)
    
    # Blocked date range (table has start_date and end_date as NOT NULL)
    start_date = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_date = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    
    # Single blocked date (nullable, for backward compatibility)
    blocked_date = mapped_column(Date, nullable=True, index=True)
    reason = mapped_column(Text, nullable=True)  # Optional reason for blocking
    
    # Metadata
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    car = relationship("Car", foreign_keys=[car_id])


class Subscriber(Base):
    """Newsletter / marketing email subscribers (website signup)."""
    __tablename__ = "subscribers"

    id = mapped_column(Integer, primary_key=True, index=True)
    email = mapped_column(String(255), unique=True, nullable=False, index=True)
    is_subscribed = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    unsubscribed_at = mapped_column(DateTime(timezone=True), nullable=True)


class EmergencyReport(Base):
    """Emergency message sent by a client, including their last known location."""
    __tablename__ = "emergency_reports"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    booking_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("bookings.id"),
        nullable=True,
        index=True,
        doc="Optional link to the booking the emergency relates to (if any).",
    )

    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Last known location (as sent from the device)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    location_accuracy_m: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        doc="Optional accuracy radius in meters as reported by the device.",
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    client: Mapped["Client"] = relationship("Client", foreign_keys=[client_id])
    booking: Mapped[Optional["Booking"]] = relationship("Booking", foreign_keys=[booking_id])


class WishlistItem(Base):
    """Client wishlist – a car the client has liked."""
    __tablename__ = "wishlist_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    car_id: Mapped[int] = mapped_column(ForeignKey("cars.id"), nullable=False, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    client: Mapped["Client"] = relationship("Client", foreign_keys=[client_id])
    car: Mapped["Car"] = relationship("Car", foreign_keys=[car_id])
