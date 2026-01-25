from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey, Float, Text, Boolean, Enum as SQLEnum, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


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

    id = Column(Integer, primary_key=True, index=True)
    host_id = Column(Integer, ForeignKey("hosts.id"), nullable=True, index=True)  # Nullable to support clients
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)  # Nullable to support hosts
    
    # Payment method name (e.g., "John's M-Pesa", "My Visa Card")
    name = Column(String(255), nullable=False)
    
    # Payment method type
    method_type = Column(SQLEnum(PaymentMethodType), nullable=False)
    
    # For M-Pesa
    mpesa_number = Column(String(20), nullable=True)  # e.g., "254712345678"
    
    # For cards (Visa/Mastercard)
    card_number_hash = Column(String(255), nullable=True)  # Hashed card number
    card_last_four = Column(String(4), nullable=True)  # Last 4 digits for display
    card_type = Column(String(20), nullable=True)  # "visa" or "mastercard"
    expiry_month = Column(Integer, nullable=True)  # 1-12
    expiry_year = Column(Integer, nullable=True)  # YYYY
    cvc_hash = Column(String(255), nullable=True)  # Hashed CVC/CVV
    
    # Metadata
    is_default = Column(Boolean, default=False)  # Default payment method
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    host = relationship("Host", foreign_keys=[host_id], back_populates="payment_methods")
    client = relationship("Client", foreign_keys=[client_id], back_populates="payment_methods")


class Host(Base):
    """Car owners/rental hosts"""
    __tablename__ = "hosts"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    
    # Profile fields
    bio = Column(Text, nullable=True)
    mobile_number = Column(String(50), nullable=True)
    id_number = Column(String(100), nullable=True)  # ID number, passport number, or DL number
    
    # Media URLs (stored in Supabase Storage)
    avatar_url = Column(String(500), nullable=True)
    cover_image_url = Column(String(500), nullable=True)
    id_document_url = Column(String(500), nullable=True)
    license_document_url = Column(String(500), nullable=True)
    
    # Account status
    is_active = Column(Boolean, default=True, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationship to cars
    cars = relationship("Car", back_populates="host")
    # Relationship to payment methods
    payment_methods = relationship("PaymentMethod", back_populates="host", cascade="all, delete-orphan")
    # Relationship to feedback
    feedbacks = relationship("Feedback", back_populates="host", cascade="all, delete-orphan")


class Client(Base):
    """Car renters/clients"""
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    
    # Profile fields
    bio = Column(Text, nullable=True)
    fun_fact = Column(Text, nullable=True)
    mobile_number = Column(String(50), nullable=True)  # Required for updates, but nullable for existing clients
    id_number = Column(String(100), nullable=True)  # Required for updates, but nullable for existing clients
    date_of_birth = Column(Date, nullable=True)  # Required for updates, but nullable for existing clients
    gender = Column(String(20), nullable=True)  # Required for updates, but nullable for existing clients - e.g., "male", "female", "other"
    
    # Media URLs (stored in Supabase Storage)
    avatar_url = Column(String(500), nullable=True)
    id_document_url = Column(String(500), nullable=True)
    license_document_url = Column(String(500), nullable=True)
    
    # Account status
    is_active = Column(Boolean, default=True, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationship to driving license
    driving_license = relationship("DrivingLicense", back_populates="client", uselist=False, cascade="all, delete-orphan")
    # Relationship to payment methods
    payment_methods = relationship("PaymentMethod", back_populates="client", cascade="all, delete-orphan")


class DrivingLicense(Base):
    """Client driving license information"""
    __tablename__ = "driving_licenses"
    
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), unique=True, nullable=False, index=True)
    
    # License information
    license_number = Column(String(50), nullable=False, unique=True, index=True)  # Mix of letters and numbers
    category = Column(String(10), nullable=False)  # One letter + number (e.g., B1, C2, D1)
    issue_date = Column(Date, nullable=False)
    expiry_date = Column(Date, nullable=False)
    
    # Verification status
    is_verified = Column(Boolean, default=False, nullable=False)  # Admin verification status
    verification_notes = Column(Text, nullable=True)  # Admin notes
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationship to client
    client = relationship("Client", back_populates="driving_license")


class Car(Base):
    """Car listings"""
    __tablename__ = "cars"

    id = Column(Integer, primary_key=True, index=True)
    host_id = Column(Integer, ForeignKey("hosts.id"), nullable=False)
    
    # Endpoint 1: Basics
    name = Column(String(255))
    model = Column(String(100))
    body_type = Column(String(50))
    year = Column(Integer)
    description = Column(Text)
    
    # Endpoint 2: Technical Specs
    seats = Column(Integer)
    fuel_type = Column(String(50))
    transmission = Column(String(50))
    color = Column(String(50))
    mileage = Column(Integer)
    features = Column(Text)  # JSON string for up to 12 features
    
    # Endpoint 3: Pricing & Rules
    daily_rate = Column(Float)
    weekly_rate = Column(Float)
    monthly_rate = Column(Float)
    min_rental_days = Column(Integer)
    max_rental_days = Column(Integer, nullable=True)
    min_age_requirement = Column(Integer)
    rules = Column(Text)
    
    # Endpoint 4: Location
    location_name = Column(String(255), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    
    # Media URLs (stored in Supabase Storage)
    image_urls = Column(Text, nullable=True)  # JSON array of image URLs (legacy, kept for backward compatibility)
    video_url = Column(String(500), nullable=True)  # Legacy, kept for backward compatibility
    
    # New media structure (uploaded directly by app to Supabase)
    cover_image = Column(String(500), nullable=True)  # Single cover image URL
    car_images = Column(Text, nullable=True)  # JSON array of up to 12 car image URLs
    car_video = Column(String(500), nullable=True)  # Car video URL
    
    # Status tracking
    is_complete = Column(Boolean, default=False)
    verification_status = Column(String(20), default=VerificationStatus.AWAITING.value, nullable=False)
    rejection_reason = Column(Text, nullable=True)  # Reason for rejection if denied
    is_hidden = Column(Boolean, default=False, nullable=False)  # Hide from public listing
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationship to host
    host = relationship("Host", back_populates="cars")
    # Relationship to bookings
    bookings = relationship("Booking", back_populates="car", cascade="all, delete-orphan")
    # Relationship to blocked dates
    blocked_dates = relationship("CarBlockedDate", back_populates="car", cascade="all, delete-orphan")


class BookingStatus(str, enum.Enum):
    """Booking status lifecycle"""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class CarBlockedDate(Base):
    """Blocked dates for cars (host-managed calendar)"""
    __tablename__ = "car_blocked_dates"
    
    id = Column(Integer, primary_key=True, index=True)
    car_id = Column(Integer, ForeignKey("cars.id"), nullable=False, index=True)
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    reason = Column(String(255), nullable=True)  # Optional reason for blocking
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationship to car
    car = relationship("Car", back_populates="blocked_dates")
    
    # Index for efficient date range queries
    __table_args__ = (
        Index('idx_car_blocked_dates_range', 'car_id', 'start_date', 'end_date'),
    )


class Booking(Base):
    """Car rental bookings"""
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(String(50), unique=True, index=True, nullable=False)  # Human-readable ID like BK-12345678
    
    # Foreign keys
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    car_id = Column(Integer, ForeignKey("cars.id"), nullable=False, index=True)
    
    # Booking dates
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    
    # Pickup and return details
    pickup_time = Column(String(10), nullable=True)  # e.g., "10:00"
    return_time = Column(String(10), nullable=True)
    pickup_location = Column(Text, nullable=True)  # JSON array: ["nairobi", "karen", "westside mall"]
    return_location = Column(Text, nullable=True)  # JSON array: ["nairobi", "karen", "westside mall"]
    dropoff_same_as_pickup = Column(Boolean, default=True, nullable=False)  # Toggle for same location
    
    # Pricing
    daily_rate = Column(Float, nullable=False)  # Rate at time of booking
    rental_days = Column(Integer, nullable=False)
    base_price = Column(Float, nullable=False)  # daily_rate * rental_days
    damage_waiver_fee = Column(Float, default=0)
    total_price = Column(Float, nullable=False)
    
    # Options
    damage_waiver_enabled = Column(Boolean, default=False)
    drive_type = Column(String(20), default="self")  # 'self' or 'withDriver'
    check_in_preference = Column(String(20), default="self")  # 'self' or 'assisted'
    special_requirements = Column(Text, nullable=True)
    
    # Status
    status = Column(SQLEnum(BookingStatus), default=BookingStatus.PENDING, nullable=False)
    status_updated_at = Column(DateTime(timezone=True), nullable=True)
    cancellation_reason = Column(Text, nullable=True)
    
    # Pickup and dropoff confirmation (host only for MVP)
    pickup_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    dropoff_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    client = relationship("Client", back_populates="bookings")
    car = relationship("Car", back_populates="bookings")


# Update Client model to include bookings relationship
Client.bookings = relationship("Booking", back_populates="client", cascade="all, delete-orphan")


class Feedback(Base):
    """Host feedback"""
    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, index=True)
    host_id = Column(Integer, ForeignKey("hosts.id"), nullable=False, index=True)
    
    # Feedback content
    content = Column(String(250), nullable=False)  # Max 250 characters
    
    # Admin moderation
    is_flagged = Column(Boolean, default=False, nullable=False)  # Flagged for review
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationship to host
    host = relationship("Host", foreign_keys=[host_id])


class Admin(Base):
    """System administrators"""
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    
    # Admin role (super_admin, admin, moderator)
    role = Column(String(50), default="admin", nullable=False)
    
    # Account status
    is_active = Column(Boolean, default=True, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Notification(Base):
    """System notifications"""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    
    # Recipient information
    recipient_type = Column(String(20), nullable=False, index=True)  # "host" or "client"
    recipient_id = Column(Integer, nullable=False, index=True)  # Host ID or Client ID
    
    # Notification content
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    notification_type = Column(String(20), default="info", nullable=False)  # info, warning, success, error
    
    # Sender information (admin who sent it)
    sender_name = Column(String(255), nullable=False, default="[Deon,CEO ardena]")
    
    # Read status
    is_read = Column(Boolean, default=False, nullable=False, index=True)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class SupportConversation(Base):
    """Support conversation thread - one per host"""
    __tablename__ = "support_conversations"

    id = Column(Integer, primary_key=True, index=True)
    host_id = Column(Integer, ForeignKey("hosts.id"), nullable=False, unique=True, index=True)  # One conversation per host
    
    # Status
    status = Column(String(20), default="open", nullable=False, index=True)  # open, closed
    is_read_by_host = Column(Boolean, default=False, nullable=False)  # Host has read latest admin message
    is_read_by_admin = Column(Boolean, default=False, nullable=False)  # Admin has read latest host message
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_message_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)  # Last message timestamp
    
    # Relationships
    host = relationship("Host", foreign_keys=[host_id])
    messages = relationship("SupportMessage", back_populates="conversation", cascade="all, delete-orphan")


class SupportMessage(Base):
    """Individual messages in a support conversation"""
    __tablename__ = "support_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("support_conversations.id"), nullable=False, index=True)
    
    # Sender information
    sender_type = Column(String(20), nullable=False, index=True)  # "host" or "admin"
    sender_id = Column(Integer, nullable=False)  # Host ID or Admin ID
    
    # Message content
    message = Column(Text, nullable=False)
    
    # Read status (for the recipient)
    is_read = Column(Boolean, default=False, nullable=False)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # Relationships
    conversation = relationship("SupportConversation", back_populates="messages")


class ClientHostConversation(Base):
    """Conversation between a client and a host"""
    __tablename__ = "client_host_conversations"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    host_id = Column(Integer, ForeignKey("hosts.id"), nullable=False, index=True)
    
    # Unique constraint: one conversation per client-host pair
    # Note: We'll enforce this in application logic since SQLite has limitations
    
    # Status
    is_read_by_client = Column(Boolean, default=False, nullable=False)  # Client has read latest host message
    is_read_by_host = Column(Boolean, default=False, nullable=False)  # Host has read latest client message
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_message_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)  # Last message timestamp
    
    # Relationships
    client = relationship("Client", foreign_keys=[client_id])
    host = relationship("Host", foreign_keys=[host_id])
    messages = relationship("ClientHostMessage", back_populates="conversation", cascade="all, delete-orphan")


class ClientHostMessage(Base):
    """Individual messages in a client-host conversation"""
    __tablename__ = "client_host_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("client_host_conversations.id"), nullable=False, index=True)
    
    # Sender information
    sender_type = Column(String(20), nullable=False, index=True)  # "client" or "host"
    sender_id = Column(Integer, nullable=False)  # Client ID or Host ID
    
    # Message content
    message = Column(Text, nullable=False)
    
    # Read status (for the recipient)
    is_read = Column(Boolean, default=False, nullable=False)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # Relationships
    conversation = relationship("ClientHostConversation", back_populates="messages")