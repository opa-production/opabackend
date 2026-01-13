from pydantic import BaseModel, EmailStr, Field, model_validator, field_validator
from typing import Optional, List, Literal
from datetime import datetime, date
import json
import re
from enum import Enum


# Host Auth Schemas
class HostRegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8)
    password_confirmation: str = Field(..., min_length=8)

    @model_validator(mode='after')
    def passwords_match(self):
        if self.password != self.password_confirmation:
            raise ValueError('Passwords do not match')
        return self


class HostRegisterResponse(BaseModel):
    id: int
    full_name: str
    email: str
    created_at: datetime

    class Config:
        from_attributes = True


class HostProfileUpdateRequest(BaseModel):
    """Update host profile fields"""
    bio: Optional[str] = Field(None, max_length=2000)
    mobile_number: Optional[str] = Field(None, max_length=50)
    id_number: Optional[str] = Field(None, max_length=100, description="ID number, passport number, or driver's license number")


class HostProfileResponse(BaseModel):
    """Complete host profile response"""
    id: int
    full_name: str
    email: str
    bio: Optional[str] = None
    mobile_number: Optional[str] = None
    id_number: Optional[str] = None
    avatar_url: Optional[str] = None
    cover_image_url: Optional[str] = None
    id_document_url: Optional[str] = None
    license_document_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class HostLoginRequest(BaseModel):
    email: EmailStr
    password: str


class HostLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    host: HostProfileResponse


class TokenData(BaseModel):
    host_id: Optional[int] = None


# Client Auth Schemas
class ClientRegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8)
    password_confirmation: str = Field(..., min_length=8)

    @model_validator(mode='after')
    def passwords_match(self):
        if self.password != self.password_confirmation:
            raise ValueError('Passwords do not match')
        return self


class ClientRegisterResponse(BaseModel):
    id: int
    full_name: str
    email: str
    created_at: datetime

    class Config:
        from_attributes = True


class ClientProfileUpdateRequest(BaseModel):
    """Update client profile fields"""
    bio: Optional[str] = Field(None, max_length=2000)
    fun_fact: Optional[str] = Field(None, max_length=500)
    mobile_number: Optional[str] = Field(None, max_length=50)
    id_number: Optional[str] = Field(None, max_length=100, description="Driver's licence, passport, or ID number")


class ClientProfileResponse(BaseModel):
    """Complete client profile response"""
    id: int
    full_name: str
    email: str
    bio: Optional[str] = None
    fun_fact: Optional[str] = None
    mobile_number: Optional[str] = None
    id_number: Optional[str] = None
    avatar_url: Optional[str] = None
    id_document_url: Optional[str] = None
    license_document_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ClientLoginRequest(BaseModel):
    email: EmailStr
    password: str


class ClientLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    client: ClientProfileResponse


# Car Upload Schemas
class CarBasicsRequest(BaseModel):
    """Endpoint 1: Car Basics"""
    name: str = Field(..., min_length=1, max_length=255)
    model: str = Field(..., min_length=1, max_length=100)
    body_type: str = Field(..., min_length=1, max_length=50)
    year: int = Field(..., ge=1900, le=2100)
    description: str = Field(..., min_length=1)


class CarTechnicalSpecsRequest(BaseModel):
    """Endpoint 2: Technical Specs"""
    seats: int = Field(..., ge=1, le=50)
    fuel_type: str = Field(..., min_length=1, max_length=50)
    transmission: str = Field(..., min_length=1, max_length=50)
    color: str = Field(..., min_length=1, max_length=50)
    mileage: int = Field(..., ge=0)
    features: List[str] = Field(default_factory=list, max_length=12)


class CarPricingRulesRequest(BaseModel):
    """Endpoint 3: Pricing & Rules"""
    daily_rate: float = Field(..., gt=0)
    weekly_rate: float = Field(..., gt=0)
    monthly_rate: float = Field(..., gt=0)
    min_rental_days: int = Field(..., ge=1)
    max_rental_days: Optional[int] = Field(None)
    min_age_requirement: int = Field(..., ge=18, le=100)
    rules: str = Field(..., min_length=1)

    @model_validator(mode='after')
    def validate_max_rental_days(self):
        """Validate max_rental_days: 0 or None means no maximum, otherwise must be >= 1"""
        if self.max_rental_days is not None:
            if self.max_rental_days == 0:
                # Convert 0 to None (no maximum)
                self.max_rental_days = None
            elif self.max_rental_days < 1:
                raise ValueError('max_rental_days must be greater than or equal to 1 if provided')
        return self


class CarLocationRequest(BaseModel):
    """Endpoint 4: Location"""
    location_name: Optional[str] = Field(None, max_length=255)
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)

    @model_validator(mode='after')
    def location_provided(self):
        """Ensure either location_name OR coordinates are provided"""
        if not self.location_name and (self.latitude is None or self.longitude is None):
            raise ValueError('Either location_name or both latitude and longitude must be provided')
        if self.location_name and (self.latitude is not None or self.longitude is not None):
            raise ValueError('Provide either location_name OR coordinates, not both')
        if (self.latitude is not None and self.longitude is None) or (self.latitude is None and self.longitude is not None):
            raise ValueError('Both latitude and longitude must be provided together')
        return self


class CarResponse(BaseModel):
    """Car response schema"""
    id: int
    host_id: int
    name: Optional[str] = None
    model: Optional[str] = None
    body_type: Optional[str] = None
    year: Optional[int] = None
    description: Optional[str] = None
    seats: Optional[int] = None
    fuel_type: Optional[str] = None
    transmission: Optional[str] = None
    color: Optional[str] = None
    mileage: Optional[int] = None
    features: Optional[List[str]] = None
    daily_rate: Optional[float] = None
    weekly_rate: Optional[float] = None
    monthly_rate: Optional[float] = None
    min_rental_days: Optional[int] = None
    max_rental_days: Optional[int] = None
    min_age_requirement: Optional[int] = None
    rules: Optional[str] = None
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_complete: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Payment Method Schemas
class PaymentMethodTypeEnum(str, Enum):
    """Payment method types"""
    MPESA = "mpesa"
    VISA = "visa"
    MASTERCARD = "mastercard"


class MpesaPaymentMethodAddRequest(BaseModel):
    """Add M-Pesa payment method request schema"""
    mpesa_number: str = Field(..., max_length=20, description="M-Pesa phone number (e.g., 254712345678)")
    is_default: Optional[bool] = Field(False, description="Set as default payment method")
    
    @model_validator(mode='after')
    def validate_mpesa_number(self):
        """Validate M-Pesa number"""
        if not self.mpesa_number:
            raise ValueError('M-Pesa number is required')
        # Remove any spaces or dashes
        mpesa_clean = re.sub(r'[\s-]', '', self.mpesa_number)
        # Validate format (should start with country code like 254 for Kenya)
        if not re.match(r'^\d{9,15}$', mpesa_clean):
            raise ValueError('M-Pesa number must be 9-15 digits')
        self.mpesa_number = mpesa_clean
        return self


class CardPaymentMethodAddRequest(BaseModel):
    """Add card payment method request schema"""
    card_number: str = Field(..., description="16-digit card number")
    cvc: str = Field(..., description="3-4 digit CVC/CVV code")
    expiry_month: int = Field(..., ge=1, le=12, description="Expiry month (1-12)")
    expiry_year: int = Field(..., ge=2024, le=2099, description="Expiry year (YYYY)")
    card_type: Literal["visa", "mastercard"] = Field(..., description="Card type (visa or mastercard)")
    is_default: Optional[bool] = Field(False, description="Set as default payment method")
    
    @model_validator(mode='after')
    def validate_card_data(self):
        """Validate card data"""
        # Validate card number format (16 digits, no spaces)
        card_clean = re.sub(r'[\s-]', '', self.card_number)
        if not re.match(r'^\d{16}$', card_clean):
            raise ValueError('Card number must be exactly 16 digits')
        
        # Validate card type matches first digit
        first_digit = card_clean[0]
        if self.card_type == "visa" and first_digit != '4':
            raise ValueError('Visa cards must start with 4')
        if self.card_type == "mastercard" and first_digit != '5':
            raise ValueError('Mastercard cards must start with 5')
        
        # Validate CVC/CVV (3-4 digits)
        cvc_clean = re.sub(r'[\s]', '', self.cvc)
        if not re.match(r'^\d{3,4}$', cvc_clean):
            raise ValueError('CVC/CVV must be 3 or 4 digits')
        
        # Validate expiry date is not in the past
        today = date.today()
        current_year = today.year
        current_month = today.month
        # Card is expired if expiry year is before current year, or same year but expiry month is before current month
        if self.expiry_year < current_year or (self.expiry_year == current_year and self.expiry_month < current_month):
            raise ValueError('Card expiry date cannot be in the past')
        
        # Store cleaned values
        self.card_number = card_clean
        self.cvc = cvc_clean
        
        return self


class PaymentMethodResponse(BaseModel):
    """Payment method response schema"""
    id: int
    host_id: int
    method_type: str  # Will be automatically converted from PaymentMethodType enum
    mpesa_number: Optional[str] = None
    card_last_four: Optional[str] = None
    card_type: Optional[str] = None
    expiry_month: Optional[int] = None
    expiry_year: Optional[int] = None
    is_default: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PaymentMethodListResponse(BaseModel):
    """List of payment methods response"""
    payment_methods: List[PaymentMethodResponse]
    
    class Config:
        from_attributes = True


# ==================== TOKEN SCHEMAS ====================

class RefreshTokenRequest(BaseModel):
    """Request to refresh access token using refresh token"""
    refresh_token: str = Field(..., description="Valid refresh token")


class TokenPairResponse(BaseModel):
    """Response containing both access and refresh tokens"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Access token expiration time in seconds")


class HostLoginResponseWithRefresh(BaseModel):
    """Host login response with refresh token"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    host: HostProfileResponse


class ClientLoginResponseWithRefresh(BaseModel):
    """Client login response with refresh token"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    client: ClientProfileResponse


class ClientTokenData(BaseModel):
    """Token data for client authentication"""
    client_id: Optional[int] = None


# ==================== CAR LISTING SCHEMAS (CLIENT VIEW) ====================

class CarListingResponse(BaseModel):
    """Car listing for client browsing"""
    id: int
    host_id: int
    name: Optional[str] = None
    model: Optional[str] = None
    body_type: Optional[str] = None
    year: Optional[int] = None
    description: Optional[str] = None
    seats: Optional[int] = None
    fuel_type: Optional[str] = None
    transmission: Optional[str] = None
    color: Optional[str] = None
    mileage: Optional[int] = None
    features: Optional[List[str]] = None
    daily_rate: Optional[float] = None
    weekly_rate: Optional[float] = None
    monthly_rate: Optional[float] = None
    min_rental_days: Optional[int] = None
    max_rental_days: Optional[int] = None
    min_age_requirement: Optional[int] = None
    rules: Optional[str] = None
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    image_urls: Optional[List[str]] = None
    video_url: Optional[str] = None
    host_name: Optional[str] = None
    host_avatar_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class CarListResponse(BaseModel):
    """Paginated car listing response"""
    cars: List[CarListingResponse]
    total: int
    skip: int
    limit: int

    class Config:
        from_attributes = True


class CarAvailabilityResponse(BaseModel):
    """Car availability response"""
    car_id: int
    available: bool
    booked_dates: List[dict]  # List of {start_date, end_date} for booked periods
    message: str


# ==================== BOOKING SCHEMAS ====================

class BookingStatusEnum(str, Enum):
    """Booking status enum for API"""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class BookingCreateRequest(BaseModel):
    """Request to create a new booking"""
    car_id: int = Field(..., description="ID of the car to book")
    start_date: datetime = Field(..., description="Rental start date")
    end_date: datetime = Field(..., description="Rental end date")
    pickup_time: Optional[str] = Field("10:00", max_length=10)
    return_time: Optional[str] = Field("10:00", max_length=10)
    pickup_location: Optional[str] = Field(None, max_length=500)
    return_location: Optional[str] = Field(None, max_length=500)
    damage_waiver_enabled: Optional[bool] = Field(False)
    drive_type: Optional[str] = Field("self", description="'self' or 'withDriver'")
    check_in_preference: Optional[str] = Field("self", description="'self' or 'assisted'")
    special_requirements: Optional[str] = Field(None, max_length=2000)

    @model_validator(mode='after')
    def validate_dates(self):
        if self.start_date >= self.end_date:
            raise ValueError('End date must be after start date')
        if self.start_date < datetime.now():
            raise ValueError('Start date cannot be in the past')
        return self


class BookingResponse(BaseModel):
    """Booking response with full details"""
    id: int
    booking_id: str
    client_id: int
    car_id: int
    
    # Car details (denormalized for convenience)
    car_name: Optional[str] = None
    car_model: Optional[str] = None
    car_year: Optional[int] = None
    car_make: Optional[str] = None
    car_image_urls: Optional[List[str]] = None
    
    # Host details
    host_id: Optional[int] = None
    host_name: Optional[str] = None
    
    # Booking dates
    start_date: datetime
    end_date: datetime
    pickup_time: Optional[str] = None
    return_time: Optional[str] = None
    pickup_location: Optional[str] = None
    return_location: Optional[str] = None
    
    # Pricing
    daily_rate: float
    rental_days: int
    base_price: float
    damage_waiver_fee: float
    total_price: float
    
    # Options
    damage_waiver_enabled: bool
    drive_type: Optional[str] = None
    check_in_preference: Optional[str] = None
    special_requirements: Optional[str] = None
    
    # Status
    status: str
    status_updated_at: Optional[datetime] = None
    cancellation_reason: Optional[str] = None
    
    # Timestamps
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class BookingListResponse(BaseModel):
    """Paginated booking list response"""
    bookings: List[BookingResponse]
    total: int
    skip: int
    limit: int


class BookingCancelRequest(BaseModel):
    """Request to cancel a booking"""
    reason: Optional[str] = Field(None, max_length=1000, description="Cancellation reason")
