from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Text, Boolean, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class PaymentMethodType(str, enum.Enum):
    """Payment method types"""
    MPESA = "mpesa"
    VISA = "visa"
    MASTERCARD = "mastercard"


class PaymentMethod(Base):
    """Payment methods for hosts"""
    __tablename__ = "payment_methods"

    id = Column(Integer, primary_key=True, index=True)
    host_id = Column(Integer, ForeignKey("hosts.id"), nullable=False, index=True)
    
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
    
    # Relationship to host
    host = relationship("Host", back_populates="payment_methods")


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
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationship to cars
    cars = relationship("Car", back_populates="host")
    # Relationship to payment methods
    payment_methods = relationship("PaymentMethod", back_populates="host", cascade="all, delete-orphan")


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
    mobile_number = Column(String(50), nullable=True)
    id_number = Column(String(100), nullable=True)  # Driver's licence/passport number
    
    # Media URLs (stored in Supabase Storage)
    avatar_url = Column(String(500), nullable=True)
    id_document_url = Column(String(500), nullable=True)
    license_document_url = Column(String(500), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


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
    image_urls = Column(Text, nullable=True)  # JSON array of image URLs
    video_url = Column(String(500), nullable=True)
    
    # Status tracking
    is_complete = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationship to host
    host = relationship("Host", back_populates="cars")
    # Relationship to bookings
    bookings = relationship("Booking", back_populates="car", cascade="all, delete-orphan")


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
    pickup_location = Column(String(500), nullable=True)
    return_location = Column(String(500), nullable=True)
    
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
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    client = relationship("Client", back_populates="bookings")
    car = relationship("Car", back_populates="bookings")


# Update Client model to include bookings relationship
Client.bookings = relationship("Booking", back_populates="client", cascade="all, delete-orphan")
