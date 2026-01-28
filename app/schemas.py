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
    mobile_number: str = Field(..., min_length=1, max_length=50, description="Mobile phone number (required)")
    id_number: str = Field(..., min_length=1, max_length=100, description="Driver's licence, passport, or ID number (required)")
    date_of_birth: date = Field(..., description="Date of birth (required, format: YYYY-MM-DD)")
    gender: str = Field(..., min_length=1, max_length=20, description="Gender (required, e.g., 'male', 'female', 'other')")


class ClientProfileResponse(BaseModel):
    """Complete client profile response"""
    id: int
    full_name: str
    email: str
    bio: Optional[str] = None
    fun_fact: Optional[str] = None
    mobile_number: Optional[str] = None  # May be None for existing clients before migration
    id_number: Optional[str] = None  # May be None for existing clients before migration
    date_of_birth: Optional[date] = None  # May be None for existing clients before migration
    gender: Optional[str] = None  # May be None for existing clients before migration
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


class CarMediaRequest(BaseModel):
    """Request schema for updating car media URLs after Supabase upload
    
    Frontend sends:
    - files: REQUIRED - Array of image URLs (max 12)
    - cover_image: OPTIONAL - Cover image URL
    - car_video: OPTIONAL - Video URL
    """
    files: List[str] = Field(..., description="List of image URLs (required, max 12 items)")
    cover_image: Optional[str] = Field(default=None, max_length=500, description="Cover image URL (optional)")
    car_video: Optional[str] = Field(default=None, max_length=500, description="Car video URL (optional)")
    
    @field_validator('files')
    @classmethod
    def validate_files(cls, v):
        if len(v) > 12:
            raise ValueError("Maximum 12 car images allowed")
        if len(v) == 0:
            raise ValueError("At least one image URL is required in files array")
        return v


class CarMediaUrlsRequest(BaseModel):
    """Alternative request schema that accepts 'files' as primary field (for app compatibility)"""
    files: Optional[List[str]] = Field(default=None, description="List of image URLs (optional, will be stored in car_images)")
    cover_image: Optional[str] = Field(default=None, max_length=500, description="Cover image URL (optional, defaults to first file)")
    car_video: Optional[str] = Field(default=None, max_length=500, description="Car video URL")
    
    @field_validator('files')
    @classmethod
    def validate_files(cls, v):
        if v is not None:
            if len(v) > 12:
                raise ValueError("Maximum 12 car images allowed")
            if len(v) == 0:
                raise ValueError("If provided, files must contain at least one image URL")
        return v


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
    verification_status: Optional[str] = None
    is_hidden: Optional[bool] = False
    cover_image: Optional[str] = None
    car_images: Optional[str] = None  # JSON string: '["url1", "url2"]' (frontend expects string, not array)
    car_video: Optional[str] = None
    image_urls: Optional[List[str]] = None  # Legacy - parsed array for backward compatibility
    video_url: Optional[str] = None  # Legacy
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CarStatusResponse(BaseModel):
    """Car verification status response"""
    car_id: int
    verification_status: str
    
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
    name: str = Field(..., min_length=1, max_length=255, description="Name for this M-Pesa payment method (e.g., 'John's M-Pesa')")
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
    name: str = Field(..., min_length=1, max_length=255, description="Name for this card payment method (e.g., 'My Visa Card')")
    card_number: str = Field(..., description="16-digit card number")
    expiry_date: str = Field(..., description="Expiry date in MM/YY format (e.g., '08/30')")
    cvc: str = Field(..., description="3-4 digit CVC/CVV code")
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
        
        # Validate expiry date format MM/YY
        expiry_clean = re.sub(r'[\s]', '', self.expiry_date)
        if not re.match(r'^\d{2}/\d{2}$', expiry_clean):
            raise ValueError('Expiry date must be in MM/YY format (e.g., 08/30)')
        
            # Parse expiry date
        try:
            month_str, year_str = expiry_clean.split('/')
            expiry_month = int(month_str)
            expiry_year = int(year_str)
            
            # Validate month range
            if expiry_month < 1 or expiry_month > 12:
                raise ValueError('Invalid expiry month. Must be between 01 and 12')
            
            # Convert YY to YYYY (assuming 20YY for years 00-99)
            # If year is 00-30, assume 2000-2030, otherwise assume 1900-1999
            if expiry_year <= 30:
                expiry_year_full = 2000 + expiry_year
            else:
                expiry_year_full = 1900 + expiry_year
            
            # Validate expiry date is not in the past
            today = date.today()
            current_year = today.year
            current_month = today.month
            # Card is expired if expiry year is before current year, or same year but expiry month is before current month
            if expiry_year_full < current_year or (expiry_year_full == current_year and expiry_month < current_month):
                raise ValueError('Card expiry date cannot be in the past')
            
            # Store parsed values (will be used in router)
            self._expiry_month = expiry_month
            self._expiry_year = expiry_year_full
            
        except ValueError as e:
            if 'Invalid expiry' in str(e) or 'Card expiry date' in str(e):
                raise
            raise ValueError('Invalid expiry date format. Use MM/YY (e.g., 08/30)')
        
        # Validate CVC/CVV (3-4 digits)
        cvc_clean = re.sub(r'[\s]', '', self.cvc)
        if not re.match(r'^\d{3,4}$', cvc_clean):
            raise ValueError('CVC/CVV must be 3 or 4 digits')
        
        # Store cleaned values
        self.card_number = card_clean
        self.cvc = cvc_clean
        
        return self


class PaymentMethodResponse(BaseModel):
    """Payment method response schema"""
    id: int
    host_id: Optional[int] = None  # Nullable to support clients
    client_id: Optional[int] = None  # Nullable to support hosts
    name: str
    method_type: str  # Will be automatically converted from PaymentMethodType enum
    mpesa_number: Optional[str] = None
    card_last_four: Optional[str] = None
    card_type: Optional[str] = None
    expiry_month: Optional[int] = None  # Stored internally, used to format expiry_date
    expiry_year: Optional[int] = None  # Stored internally, used to format expiry_date
    expiry_date: Optional[str] = None  # Formatted as MM/YY (e.g., "08/30")
    is_default: bool
    created_at: Optional[datetime] = None  # Made optional to handle cases where it might be None initially
    updated_at: Optional[datetime] = None

    @model_validator(mode='after')
    def format_expiry_date(self):
        """Format expiry date as MM/YY if card payment method"""
        if self.expiry_month is not None and self.expiry_year is not None:
            # Convert YYYY to YY (last 2 digits)
            year_short = self.expiry_year % 100
            # Format as MM/YY with zero padding
            self.expiry_date = f"{self.expiry_month:02d}/{year_short:02d}"
        return self

    class Config:
        from_attributes = True


class PaymentMethodListResponse(BaseModel):
    """List of payment methods response"""
    payment_methods: List[PaymentMethodResponse]


# Feedback Schemas
class FeedbackCreateRequest(BaseModel):
    """Create feedback request schema"""
    content: str = Field(..., min_length=1, max_length=250, description="Feedback content (max 250 characters)")


class FeedbackResponse(BaseModel):
    """Feedback response schema"""
    id: int
    host_id: int
    content: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class FeedbackListResponse(BaseModel):
    """List of feedbacks response"""
    feedbacks: List[FeedbackResponse]
    
    class Config:
        from_attributes = True


# Support Message Schemas
class SupportMessageRequest(BaseModel):
    """Request to send a message in support conversation"""
    message: str = Field(..., min_length=1, max_length=2000, description="Message content")


class SupportMessageResponse(BaseModel):
    """Individual message in a conversation"""
    id: int
    conversation_id: int
    sender_type: str  # "host" or "admin"
    sender_id: int
    sender_name: Optional[str] = None  # Host name or Admin name
    message: str
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class SupportConversationResponse(BaseModel):
    """Support conversation with messages"""
    id: int
    host_id: int
    host_name: Optional[str] = None
    host_email: Optional[str] = None
    status: str  # open, closed
    is_read_by_host: bool
    is_read_by_admin: bool
    messages: List[SupportMessageResponse]
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_message_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SupportConversationListResponse(BaseModel):
    """Paginated support conversations list (for admin)"""
    conversations: List[SupportConversationResponse]
    total: int
    page: int
    limit: int
    total_pages: int
    unread_count: Optional[int] = None  # For admin: unread conversations count


class AdminResponseRequest(BaseModel):
    """Request for admin to respond to a support conversation"""
    message: str = Field(..., min_length=1, max_length=2000, description="Admin response message")


# ==================== ADMIN SCHEMAS ====================

# Admin Auth Schemas
class AdminProfileResponse(BaseModel):
    """Complete admin profile response"""
    id: int
    full_name: str
    email: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    admin: AdminProfileResponse


# Admin User Management Schemas
class HostListResponse(BaseModel):
    """Host list item response"""
    id: int
    full_name: str
    email: str
    mobile_number: Optional[str] = None
    is_active: bool
    cars_count: int = 0
    payment_methods_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class HostDetailResponse(BaseModel):
    """Full host detail response"""
    id: int
    full_name: str
    email: str
    bio: Optional[str] = None
    mobile_number: Optional[str] = None
    id_number: Optional[str] = None
    is_active: bool
    cars_count: int = 0
    payment_methods_count: int = 0
    feedbacks_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class HostUpdateRequest(BaseModel):
    """Update host profile request"""
    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    bio: Optional[str] = Field(None, max_length=2000)
    mobile_number: Optional[str] = Field(None, max_length=50)
    id_number: Optional[str] = Field(None, max_length=100)


class PaginatedHostListResponse(BaseModel):
    """Paginated host list response"""
    hosts: List[HostListResponse]
    total: int
    page: int
    limit: int
    total_pages: int


class ClientListResponse(BaseModel):
    """Client list item response"""
    id: int
    full_name: str
    email: str
    mobile_number: Optional[str] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ClientDetailResponse(BaseModel):
    """Full client detail response"""
    id: int
    full_name: str
    email: str
    bio: Optional[str] = None
    fun_fact: Optional[str] = None
    mobile_number: Optional[str] = None
    id_number: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ClientUpdateRequest(BaseModel):
    """Update client profile request"""
    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    bio: Optional[str] = Field(None, max_length=2000)
    fun_fact: Optional[str] = Field(None, max_length=500)
    mobile_number: Optional[str] = Field(None, max_length=50)
    id_number: Optional[str] = Field(None, max_length=100)


class PaginatedClientListResponse(BaseModel):
    """Paginated client list response"""
    clients: List[ClientListResponse]
    total: int
    page: int
    limit: int
    total_pages: int


# ==================== DRIVING LICENSE SCHEMAS ====================

class DrivingLicenseRequest(BaseModel):
    """Add or update driving license information"""
    license_number: str = Field(..., min_length=5, max_length=50, description="License number (mix of letters and numbers)")
    category: str = Field(..., min_length=2, max_length=10, description="License category (one letter + number, e.g., B1, C2)")
    issue_date: date = Field(..., description="License issue date")
    expiry_date: date = Field(..., description="License expiry date")
    
    @model_validator(mode='after')
    def validate_license_number(self):
        """Validate license number contains letters and numbers"""
        if not any(c.isalpha() for c in self.license_number):
            raise ValueError('License number must contain at least one letter')
        if not any(c.isdigit() for c in self.license_number):
            raise ValueError('License number must contain at least one number')
        # Allow only alphanumeric characters
        if not self.license_number.replace(' ', '').isalnum():
            raise ValueError('License number can only contain letters, numbers, and spaces')
        return self
    
    @model_validator(mode='after')
    def validate_category(self):
        """Validate category format: one letter followed by one or more numbers"""
        category_clean = self.category.strip().upper()
        if len(category_clean) < 2:
            raise ValueError('Category must be at least 2 characters (one letter + number)')
        
        # Check if first character is a letter
        if not category_clean[0].isalpha():
            raise ValueError('Category must start with a letter')
        
        # Check if remaining characters are numbers
        if not category_clean[1:].isdigit():
            raise ValueError('Category must have numbers after the letter (e.g., B1, C2, D1)')
        
        self.category = category_clean
        return self
    
    @model_validator(mode='after')
    def validate_dates(self):
        """Validate issue and expiry dates according to Kenyan system"""
        from datetime import date, timedelta
        
        today = date.today()
        
        # Issue date cannot be in the future
        if self.issue_date > today:
            raise ValueError('Issue date cannot be in the future')
        
        # Calculate expected expiry date (3 years from issue date)
        expected_expiry = self.issue_date + timedelta(days=3*365)  # 3 years
        
        # Allow small margin (within 5 days) for expiry date
        days_diff = abs((self.expiry_date - expected_expiry).days)
        if days_diff > 5:
            raise ValueError(
                f'Expiry date must be approximately 3 years from issue date. '
                f'Expected expiry: {expected_expiry.strftime("%Y-%m-%d")}, '
                f'but got: {self.expiry_date.strftime("%Y-%m-%d")}'
            )
        
        # Expiry date must be after issue date
        if self.expiry_date <= self.issue_date:
            raise ValueError('Expiry date must be after issue date')
        
        return self


class DrivingLicenseResponse(BaseModel):
    """Driving license information response"""
    id: int
    client_id: int
    license_number: str
    category: str
    issue_date: date
    expiry_date: date
    is_verified: bool
    verification_notes: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


# Admin Car Management Schemas
class CarDetailResponse(BaseModel):
    """Car detail response with host information"""
    id: int
    host_id: int
    host_name: str
    host_email: str
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
    verification_status: str
    rejection_reason: Optional[str] = None
    is_hidden: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CarStatusUpdateRequest(BaseModel):
    """Update car verification status request"""
    verification_status: str
    rejection_reason: Optional[str] = Field(None, max_length=1000, description="Required if status is 'denied'")

    @model_validator(mode='after')
    def validate_rejection_reason(self):
        if self.verification_status == "denied" and not self.rejection_reason:
            raise ValueError('rejection_reason is required when verification_status is "denied"')
        return self


class BulkCarStatusUpdateRequest(BaseModel):
    """Bulk update car status request"""
    car_ids: List[int] = Field(..., min_length=1, description="List of car IDs to update")
    verification_status: str
    rejection_reason: Optional[str] = Field(None, max_length=1000, description="Required if status is 'denied'")

    @model_validator(mode='after')
    def validate_rejection_reason(self):
        if self.verification_status == "denied" and not self.rejection_reason:
            raise ValueError('rejection_reason is required when verification_status is "denied"')
        return self


class CarRejectRequest(BaseModel):
    """Reject car request"""
    rejection_reason: str = Field(..., min_length=1, max_length=1000, description="Reason for rejection")


class CarUpdateRequest(BaseModel):
    """Admin car update request - can update any field"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    model: Optional[str] = Field(None, min_length=1, max_length=100)
    body_type: Optional[str] = Field(None, min_length=1, max_length=50)
    year: Optional[int] = Field(None, ge=1900, le=2100)
    description: Optional[str] = Field(None, min_length=1)
    seats: Optional[int] = Field(None, ge=1, le=50)
    fuel_type: Optional[str] = Field(None, min_length=1, max_length=50)
    transmission: Optional[str] = Field(None, min_length=1, max_length=50)
    color: Optional[str] = Field(None, min_length=1, max_length=50)
    mileage: Optional[int] = Field(None, ge=0)
    features: Optional[List[str]] = Field(None, max_length=12)
    daily_rate: Optional[float] = Field(None, gt=0)
    weekly_rate: Optional[float] = Field(None, gt=0)
    monthly_rate: Optional[float] = Field(None, gt=0)
    min_rental_days: Optional[int] = Field(None, ge=1)
    max_rental_days: Optional[int] = Field(None, ge=1)
    min_age_requirement: Optional[int] = Field(None, ge=18, le=100)
    rules: Optional[str] = Field(None, min_length=1)
    location_name: Optional[str] = Field(None, max_length=255)
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)


class AdminCarListResponse(BaseModel):
    """Car list item response for admin"""
    id: int
    host_id: int
    host_name: str
    name: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    verification_status: str
    is_hidden: bool
    created_at: datetime

    class Config:
        from_attributes = True


class PaginatedCarListResponse(BaseModel):
    """Paginated car list response"""
    cars: List[AdminCarListResponse]
    total: int
    page: int
    limit: int
    total_pages: int


# Admin Dashboard Schemas
class DashboardStatsResponse(BaseModel):
    """Dashboard statistics response"""
    total_hosts: int
    active_hosts: int
    inactive_hosts: int
    total_clients: int
    active_clients: int
    inactive_clients: int
    total_cars: int
    cars_awaiting_verification: int
    verified_cars: int
    rejected_cars: int
    hidden_cars: int
    visible_cars: int


class ActivityItem(BaseModel):
    """Activity item response"""
    type: str  # "host_registration", "client_registration", "car_submission", "car_status_change"
    entity_type: str  # "host", "client", "car"
    entity_id: int
    entity_name: Optional[str] = None
    description: str
    timestamp: datetime


class RecentActivityResponse(BaseModel):
    """Recent activity response"""
    activities: List[ActivityItem]
    total: int


class VerificationQueueStatsResponse(BaseModel):
    """Verification queue statistics response"""
    cars_awaiting_verification: int
    average_verification_time_hours: Optional[float] = None  # Average time from submission to verification
    rejection_rate: float  # Percentage of rejected cars (0-100)
    total_processed: int  # Total cars that have been verified or rejected
    verified_count: int
    rejected_count: int


# Admin Feedback Management Schemas
class AdminFeedbackListResponse(BaseModel):
    """Feedback list item with host information"""
    id: int
    host_id: int
    host_name: str
    host_email: str
    content: str
    is_flagged: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AdminFeedbackDetailResponse(BaseModel):
    """Full feedback detail with host information"""
    id: int
    host_id: int
    host_name: str
    host_email: str
    host_mobile_number: Optional[str] = None
    content: str
    is_flagged: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PaginatedFeedbackListResponse(BaseModel):
    """Paginated feedback list response"""
    feedbacks: List[AdminFeedbackListResponse]
    total: int
    page: int
    limit: int
    total_pages: int


# Admin Notification Schemas
class NotificationRequest(BaseModel):
    """Notification request schema"""
    title: str = Field(..., min_length=1, max_length=255, description="Notification title")
    message: str = Field(..., min_length=1, max_length=1000, description="Notification message")
    type: Optional[str] = Field("info", description="Notification type (info, warning, success, error)")


class BroadcastNotificationRequest(BaseModel):
    """Broadcast notification request"""
    title: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1, max_length=1000)
    type: Optional[str] = Field("info", description="Notification type")


class UserNotificationRequest(BaseModel):
    """Send notification to specific user"""
    user_type: str = Field(..., pattern="^(host|client)$", description="User type: host or client")
    user_id: int = Field(..., description="User ID")
    title: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1, max_length=1000)
    type: Optional[str] = Field("info", description="Notification type")


class NotificationResponse(BaseModel):
    """Notification response"""
    message: str
    sent_count: Optional[int] = None
    user_id: Optional[int] = None
    user_type: Optional[str] = None


# Host Notification Schemas
class HostNotificationResponse(BaseModel):
    """Notification response for host"""
    id: int
    title: str
    message: str
    notification_type: str
    sender_name: str
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class HostNotificationListResponse(BaseModel):
    """List of notifications for host"""
    notifications: List[HostNotificationResponse]
    total: int
    unread_count: int


class ClientNotificationResponse(BaseModel):
    """Notification response for client"""
    id: int
    title: str
    message: str
    notification_type: str
    sender_name: str
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ClientNotificationListResponse(BaseModel):
    """List of notifications for client"""
    notifications: List[ClientNotificationResponse]
    total: int
    unread_count: int


# Admin Management Schemas
class AdminListResponse(BaseModel):
    """Admin list item"""
    id: int
    full_name: str
    email: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AdminDetailResponse(BaseModel):
    """Full admin detail"""
    id: int
    full_name: str
    email: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AdminCreateRequest(BaseModel):
    """Create new admin request"""
    full_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters")
    password_confirmation: str = Field(..., min_length=8)
    role: str = Field("admin", pattern="^(admin|moderator)$", description="Role: admin or moderator (super_admin cannot be created via API)")
    is_active: bool = Field(True, description="Account active status")

    @model_validator(mode='after')
    def passwords_match(self):
        if self.password != self.password_confirmation:
            raise ValueError('Passwords do not match')
        return self


class AdminUpdateRequest(BaseModel):
    """Update admin profile request"""
    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    role: Optional[str] = Field(None, pattern="^(admin|moderator)$", description="Role: admin or moderator")
    is_active: Optional[bool] = None


class AdminPasswordChangeRequest(BaseModel):
    """Change admin password request"""
    new_password: str = Field(..., min_length=8, description="New password must be at least 8 characters")
    new_password_confirmation: str = Field(..., min_length=8)

    @model_validator(mode='after')
    def passwords_match(self):
        if self.new_password != self.new_password_confirmation:
            raise ValueError('Passwords do not match')
        return self


class AdminOwnPasswordChangeRequest(BaseModel):
    """Change own password request"""
    current_password: str = Field(..., description="Current password")
    new_password: str = Field(..., min_length=8, description="New password must be at least 8 characters")
    new_password_confirmation: str = Field(..., min_length=8)

    @model_validator(mode='after')
    def passwords_match(self):
        if self.new_password != self.new_password_confirmation:
            raise ValueError('Passwords do not match')
        return self


class AdminOwnProfileUpdateRequest(BaseModel):
    """Update own profile request"""
    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None


class PaginatedAdminListResponse(BaseModel):
    """Paginated admin list response"""
    admins: List[AdminListResponse]
    total: int
    page: int
    limit: int
    total_pages: int


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
    """Car listing for client browsing - full car details page"""
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
    # New media fields (preferred)
    cover_image: Optional[str] = None
    car_images: Optional[List[str]] = None  # Array of image URLs for carousel
    car_video: Optional[str] = None
    # Legacy fields (for backward compatibility)
    image_urls: Optional[List[str]] = None
    video_url: Optional[str] = None
    # Host information
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


# ==================== EXPLORE PAGE SCHEMAS ====================

class CarExploreItemResponse(BaseModel):
    """Simplified car item for explore page"""
    id: int
    cover_image: Optional[str] = None  # First image from image_urls
    car_name: Optional[str] = None
    price_per_day: Optional[float] = None
    rating: Optional[float] = None  # Placeholder for future rating system
    is_renters_favourite: bool = False  # Placeholder for future favourite system
    is_wishlisted: bool = False  # Placeholder for future wishlist system
    location_name: Optional[str] = None

    class Config:
        from_attributes = True


class CarExploreListResponse(BaseModel):
    """Paginated explore page car list response"""
    cars: List[CarExploreItemResponse]
    total: int
    page: int
    limit: int
    total_pages: int

    class Config:
        from_attributes = True


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


# ==================== CLIENT-HOST MESSAGING SCHEMAS ====================

class ClientHostMessageRequest(BaseModel):
    """Request to send a message"""
    message: str = Field(..., min_length=1, max_length=2000, description="Message content (1-2000 characters)")


class ClientHostMessageResponse(BaseModel):
    """Response for a client-host message"""
    id: int
    conversation_id: int
    sender_type: str  # "client" or "host"
    sender_id: int
    sender_name: Optional[str] = None
    sender_avatar_url: Optional[str] = None
    message: str
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ClientHostConversationResponse(BaseModel):
    """Response for a client-host conversation"""
    id: int
    client_id: int
    client_name: str
    client_email: str
    client_avatar_url: Optional[str] = None
    host_id: int
    host_name: str
    host_email: str
    host_avatar_url: Optional[str] = None
    is_read_by_client: bool
    is_read_by_host: bool
    messages: List[ClientHostMessageResponse]
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_message_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ClientHostConversationListResponse(BaseModel):
    """Response for a list of client-host conversations"""
    conversations: List[ClientHostConversationResponse]


# ==================== PAYMENT SCHEMAS ====================

class PaymentRequest(BaseModel):
    """Request to process a payment"""
    booking_id: str = Field(..., description="The booking ID to pay for (e.g., BK-12345678)")
    payment_method_id: int = Field(..., description="ID of the payment method to use")


class PaymentResponse(BaseModel):
    """Response for a payment processing"""
    success: bool
    booking_id: str
    amount_paid: float
    payment_method_type: str
    payment_method_name: str
    transaction_id: str
    message: str
    paid_at: datetime
    booking: dict  # BookingResponse as dict (to avoid circular import)
