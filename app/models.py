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
    
    # Status tracking
    is_complete = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationship to host
    host = relationship("Host", back_populates="cars")


