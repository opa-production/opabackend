from pydantic import BaseModel, EmailStr, Field, model_validator, field_validator
from typing import Optional, List, Literal, Union
from datetime import datetime, date, timezone
import json
import re
from enum import Enum


# Host Auth Schemas
class HostRegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255, alias="fullName")
    email: EmailStr
    password: str = Field(..., min_length=8)
    password_confirmation: str = Field(..., min_length=8, alias="passwordConfirmation")

    model_config = {"populate_by_name": True}

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
    city: Optional[str] = Field(None, max_length=100, description="City where the host operates")


class HostProfileResponse(BaseModel):
    """Complete host profile response"""
    id: int
    full_name: str
    email: str
    bio: Optional[str] = None
    mobile_number: Optional[str] = None
    id_number: Optional[str] = None
    city: Optional[str] = None
    avatar_url: Optional[str] = None
    cover_image_url: Optional[str] = None
    id_document_url: Optional[str] = None
    license_document_url: Optional[str] = None
    terms_accepted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class KycLookupRequest(BaseModel):
    """Step 1: look up a government ID to prefill the user's profile."""
    id_type: str = Field(..., description="NATIONAL_ID, PASSPORT, or DRIVERS_LICENSE")
    id_number: str = Field(..., min_length=1, max_length=100, description="The government-issued ID number")
    country: str = Field("KE", max_length=2, description="ISO 3166-1 alpha-2 country code")


class KycLookupResponse(BaseModel):
    """Verified identity details returned from the government database."""
    verified_name: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    id_number: str
    id_type: str
    country: str


class KycWidgetInitResponse(BaseModel):
    """Credentials the mobile app needs to launch the Dojah widget (Step 2)."""
    reference_id: str = Field(..., description="Unique reference — pass to widget config.reference_id")
    app_id: str = Field(..., description="Dojah App ID — pass to widget app_id")
    p_key: str = Field(..., description="Dojah public key — pass to widget p_key")
    widget_id: str = Field(..., description="Dojah widget ID — pass to widget config.widget_id")


class HostKycStatusResponse(BaseModel):
    """Host KYC verification status (latest attempt)."""
    user_id: int = Field(..., description="Host ID")
    reference_id: Optional[str] = None
    status: str = Field(..., description="approved, declined, pending")
    document_type: Optional[str] = None
    verified_name: Optional[str] = None
    verified_dob: Optional[date] = None
    face_match_score: Optional[float] = None
    decision_reason: Optional[str] = None
    verified_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ClientKycStatusResponse(BaseModel):
    """Client KYC verification status (latest attempt)."""
    user_id: int = Field(..., description="Client ID")
    reference_id: Optional[str] = None
    status: str = Field(..., description="approved, declined, pending")
    document_type: Optional[str] = None
    verified_name: Optional[str] = None
    verified_dob: Optional[date] = None
    face_match_score: Optional[float] = None
    decision_reason: Optional[str] = None
    verified_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class HostLoginRequest(BaseModel):
    email: EmailStr
    password: str
    # Optional: ask backend to issue a device token for biometric login (host app)
    enable_biometrics: Optional[bool] = Field(
        False,
        alias="enableBiometrics",
        description="When true, backend issues a one-time device_token for host biometric login"
    )
    device_name: Optional[str] = Field(
        None,
        alias="deviceName",
        max_length=255,
        description="Optional human-readable device name (e.g. 'Host’s iPhone')"
    )

    model_config = {"populate_by_name": True}


class HostLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    host: HostProfileResponse


class HostChangePasswordRequest(BaseModel):
    """Change host password request (when logged in)"""
    current_password: str = Field(..., description="Current password")
    new_password: str = Field(..., min_length=8, description="New password (min 8 characters)")
    new_password_confirmation: str = Field(..., min_length=8, description="Confirm new password")

    @model_validator(mode='after')
    def passwords_match(self):
        if self.new_password != self.new_password_confirmation:
            raise ValueError('Passwords do not match')
        return self


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


class WalletResponse(BaseModel):
    """Ardena Pay (Stellar) wallet: public key, balances (stored in DB, refreshed from Horizon on GET), optional secret (testnet only)."""
    public_key: str = Field(..., description="Stellar public key (address) – share this to receive USDC")
    network: str = Field("testnet", description="Network: testnet or mainnet")
    balance_xlm: str = Field("0", description="Native XLM balance")
    balance_usdc: str = Field("0", description="USDC balance")
    balance_updated_at: Optional[datetime] = Field(None, description="When balances were last fetched from Stellar")
    secret_key: Optional[str] = Field(None, description="Secret key – only on testnet; keep private and use to import into Freighter/Lobstr")
    created_at: Optional[datetime] = None


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
    terms_accepted_at: Optional[datetime] = None
    email_notifications_enabled: Optional[bool] = True
    sms_notifications_enabled: Optional[bool] = True
    in_app_notifications_enabled: Optional[bool] = True
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ClientLoginRequest(BaseModel):
    email: EmailStr
    password: str
    # Optional: ask backend to issue a device token for biometric login
    enable_biometrics: Optional[bool] = Field(
        False,
        alias="enableBiometrics",
        description="When true, backend issues a one-time device_token for biometric login"
    )
    device_name: Optional[str] = Field(
        None,
        alias="deviceName",
        max_length=255,
        description="Optional human-readable device name (e.g. 'John’s iPhone')"
    )

    model_config = {"populate_by_name": True}


class GoogleLoginRequest(BaseModel):
    """Request for Google Authentication"""
    id_token: str = Field(..., description="The ID token received from Google")
    enable_biometrics: Optional[bool] = Field(
        False,
        alias="enableBiometrics",
        description="When true, backend issues a one-time device_token for biometric login"
    )
    device_name: Optional[str] = Field(
        None,
        alias="deviceName",
        max_length=255,
        description="Optional human-readable device name (e.g. 'John’s iPhone')"
    )


class ForgotPasswordRequest(BaseModel):
    """Request to send password reset email"""
    email: EmailStr = Field(..., description="Email address of the account")


class ResetPasswordRequest(BaseModel):
    """Request to reset password with token from email"""
    token: str = Field(..., description="Reset token from the email link")
    new_password: str = Field(..., min_length=8, description="New password (min 8 characters)")
    new_password_confirmation: str = Field(..., min_length=8, description="Confirm new password")

    @model_validator(mode='after')
    def passwords_match(self):
        if self.new_password != self.new_password_confirmation:
            raise ValueError('Passwords do not match')
        return self


class ClientChangePasswordRequest(BaseModel):
    """Change client password request (when logged in)"""
    current_password: str = Field(..., description="Current password")
    new_password: str = Field(..., min_length=8, description="New password (min 8 characters)")
    new_password_confirmation: str = Field(..., min_length=8, description="Confirm new password")

    @model_validator(mode='after')
    def passwords_match(self):
        if self.new_password != self.new_password_confirmation:
            raise ValueError('Passwords do not match')
        return self


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
    city: Optional[str] = Field(
        None,
        min_length=1,
        max_length=100,
        description="Host operating city selected in upload flow (e.g. Nairobi).",
    )


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


class DriveSettingEnum(str, Enum):
    """Drive options for a car - what the host allows"""
    SELF_ONLY = "self_only"
    SELF_AND_CHAUFFEUR = "self_and_chauffeur"
    CHAUFFEUR_ONLY = "chauffeur_only"


# Maps drive_setting -> allowed drive_type values for booking
DRIVE_SETTING_TO_ALLOWED = {
    DriveSettingEnum.SELF_ONLY.value: ["self"],
    DriveSettingEnum.SELF_AND_CHAUFFEUR.value: ["self", "withDriver"],
    DriveSettingEnum.CHAUFFEUR_ONLY.value: ["withDriver"],
}


class DriveSettingsRequest(BaseModel):
    """Request to update car drive setting (host)"""
    drive_setting: DriveSettingEnum = Field(..., description="self_only | self_and_chauffeur | chauffeur_only")


class DriveSettingsResponse(BaseModel):
    """Drive settings for a car"""
    drive_setting: str = Field(..., description="self_only | self_and_chauffeur | chauffeur_only")
    allowed_drive_types: List[str] = Field(..., description="Drive types client can choose when booking")
    labels: dict = Field(default_factory=lambda: {"self": "Self drive", "withDriver": "With chauffeur"})


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


class CarBlockedDateRequest(BaseModel):
    """Request to block a date or date range for a car"""
    start_date: Optional[datetime] = Field(None, description="Start date to block (ISO format)")
    end_date: Optional[datetime] = Field(None, description="End date to block (ISO format)")
    blocked_date: Optional[date] = Field(None, description="Single date to block (YYYY-MM-DD) - alternative to start_date/end_date")
    reason: Optional[str] = Field(None, max_length=500, description="Optional reason for blocking")
    
    @model_validator(mode='after')
    def validate_dates(self):
        # If blocked_date is provided, use it
        if self.blocked_date:
            return self
        
        # If start_date is provided, use it (client sends start_date and end_date)
        if self.start_date:
            self.blocked_date = self.start_date.date()
            return self
        
        raise ValueError("Either 'blocked_date' or 'start_date' must be provided")


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
    drive_setting: Optional[str] = "self_only"
    allowed_drive_types: Optional[List[str]] = None  # ["self"] | ["self","withDriver"] | ["withDriver"]
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


class ClientCardAddPaystackRequest(BaseModel):
    """
    Add a card payment method for paying via Paystack hosted page.
    No card number or CVC is stored — the user enters card details on Paystack's page when they pay.
    """
    name: Optional[str] = Field("", max_length=255, description="Display name (e.g. 'My Visa'). Defaults to 'Card' if empty.")
    is_default: Optional[bool] = Field(False, description="Set as default payment method")

    @field_validator("is_default", mode="before")
    @classmethod
    def coerce_is_default(cls, v):
        if v is None or v == "" or v is False:
            return False
        if v is True or (isinstance(v, str) and v.lower() in ("true", "1", "yes")):
            return True
        return False

    @model_validator(mode="after")
    def normalize_name(self):
        if not (self.name and str(self.name).strip()):
            self.name = "Card"
        else:
            self.name = str(self.name).strip()[:255]
        return self


# Keep the old name as an alias so any existing imports don't break during transition
ClientCardAddPesapalRequest = ClientCardAddPaystackRequest


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


class ClientFeedbackCreateRequest(BaseModel):
    """Create client feedback request schema"""
    content: str = Field(..., min_length=1, max_length=250, description="Feedback content (max 250 characters)")


class ClientFeedbackResponse(BaseModel):
    """Client feedback response schema"""
    id: int
    client_id: int
    content: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ClientFeedbackListResponse(BaseModel):
    """List of client feedbacks response"""
    feedbacks: List[ClientFeedbackResponse]

    class Config:
        from_attributes = True


# ==================== HOST RATING SCHEMAS ====================

class HostRatingCreateRequest(BaseModel):
    """Request to create a host rating"""
    host_id: int = Field(..., description="ID of the host being rated")
    rating: int = Field(..., ge=1, le=5, description="Rating from 1 to 5 stars")
    review: Optional[str] = Field(None, max_length=1000, description="Optional text review (max 1000 characters)")
    booking_id: Optional[int] = Field(None, description="Optional: ID of the completed booking this rating is for")


class HostRatingUpdateRequest(BaseModel):
    """Request to update a host rating"""
    rating: int = Field(..., ge=1, le=5, description="Rating from 1 to 5 stars")
    review: Optional[str] = Field(None, max_length=1000, description="Optional text review (max 1000 characters)")


class HostRatingResponse(BaseModel):
    """Host rating response schema"""
    id: int
    host_id: int
    client_id: int
    booking_id: Optional[int] = None
    rating: int
    review: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    # Client info (for display)
    client_name: Optional[str] = None
    
    class Config:
        from_attributes = True


class HostRatingListResponse(BaseModel):
    """List of host ratings response"""
    ratings: List[HostRatingResponse]
    total: int
    average_rating: Optional[float] = None
    
    class Config:
        from_attributes = True


# ==================== CLIENT (RENTER) RATING SCHEMAS ====================

class ClientRatingCreateRequest(BaseModel):
    """Request for a host to create a client/renter rating"""
    client_id: int = Field(..., description="ID of the client being rated")
    rating: int = Field(..., ge=1, le=5, description="Rating from 1 to 5 stars")
    review: Optional[str] = Field(None, max_length=1000, description="Optional text review (max 1000 characters)")
    booking_id: Optional[int] = Field(None, description="Optional: ID of the completed booking this rating is for")


class ClientRatingUpdateRequest(BaseModel):
    """Request for a host to update a client/renter rating"""
    rating: int = Field(..., ge=1, le=5, description="Rating from 1 to 5 stars")
    review: Optional[str] = Field(None, max_length=1000, description="Optional text review (max 1000 characters)")


class ClientRatingResponse(BaseModel):
    """Client/renter rating response schema"""
    id: int
    client_id: int
    host_id: int
    booking_id: Optional[int] = None
    rating: int
    review: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    # Display helpers
    client_name: Optional[str] = None
    host_name: Optional[str] = None

    class Config:
        from_attributes = True


class ClientRatingListResponse(BaseModel):
    """List of client/renter ratings response"""
    ratings: List[ClientRatingResponse]
    total: int
    average_rating: Optional[float] = None

    class Config:
        from_attributes = True


# ==================== CAR RATING SCHEMAS ====================

class CarRatingCreateRequest(BaseModel):
    """Request to create a car rating (primary rating)"""
    car_id: int = Field(..., description="ID of the car being rated")
    rating: int = Field(..., ge=1, le=5, description="Rating from 1 to 5 stars")
    review: Optional[str] = Field(None, max_length=1000, description="Optional text review (max 1000 characters)")
    booking_id: Optional[int] = Field(None, description="ID of the completed booking this rating is for")


class CarRatingUpdateRequest(BaseModel):
    """Request to update a car rating"""
    rating: int = Field(..., ge=1, le=5, description="Rating from 1 to 5 stars")
    review: Optional[str] = Field(None, max_length=1000, description="Optional text review (max 1000 characters)")


class CarRatingResponse(BaseModel):
    """Car rating response schema"""
    id: int
    car_id: int
    client_id: int
    booking_id: Optional[int] = None
    rating: int
    review: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    # Display helpers
    client_name: Optional[str] = None
    car_name: Optional[str] = None

    class Config:
        from_attributes = True


class CarRatingListResponse(BaseModel):
    """List of car ratings response"""
    ratings: List[CarRatingResponse]
    total: int
    average_rating: Optional[float] = None

    class Config:
        from_attributes = True


class ClientProfileForHostResponse(BaseModel):
    """Client summary for hosts (e.g. when viewing a renter profile). Includes trips count and rating."""
    id: int
    full_name: str
    email: str
    avatar_url: Optional[str] = None
    trips_count: int = Field(..., description="Number of completed bookings (trips) by this client")
    average_rating: Optional[float] = Field(None, description="Average rating from hosts (1-5)")

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
    host_id: Optional[int] = None
    host_name: Optional[str] = None
    host_email: Optional[str] = None
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    client_email: Optional[str] = None
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
    expires_in: int = Field(..., description="Access token lifetime in seconds (matches JWT exp)")
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
    city: Optional[str] = None
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
    city: Optional[str] = Field(None, max_length=100)


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


class AdminMultiChannelBroadcastToClientsRequest(BaseModel):
    """
    Admin request to broadcast a message to all clients,
    sending via in‑app notifications and/or email depending on each client's preferences.
    """
    title: str = Field(..., min_length=1, max_length=255, description="Notification title (used for in‑app and default email subject)")
    message: str = Field(..., min_length=1, max_length=1000, description="Plain text message for in‑app notification")
    type: Optional[str] = Field("info", description="Notification type: info, warning, success, error")
    email_subject: Optional[str] = Field(
        None,
        max_length=255,
        description="Optional custom email subject. Defaults to title when omitted.",
    )
    email_body_html: Optional[str] = Field(
        None,
        description="Optional full HTML body for the email. If omitted, a simple HTML wrapper around `message` is used.",
    )


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


class NotificationToggleRequest(BaseModel):
    """Generic request body for toggling a notification preference."""
    enabled: bool = Field(..., description="True to enable this notification type, false to disable it")


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
    role: str = Field(
        "customer_service",
        pattern="^(finance|customer_service)$",
        description="Role: finance or customer_service (super_admin cannot be created via API)",
    )
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
    role: Optional[str] = Field(
        None,
        pattern="^(finance|customer_service)$",
        description="Role: finance or customer_service",
    )
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


# ==================== NEWSLETTER SUBSCRIBERS ====================

class SubscribeRequest(BaseModel):
    """Request to subscribe to newsletter (public)."""
    email: EmailStr = Field(..., description="Email to subscribe")


class UnsubscribeRequest(BaseModel):
    """Request to unsubscribe from newsletter (public)."""
    email: EmailStr = Field(..., description="Email to unsubscribe")


class SubscriberItemResponse(BaseModel):
    """Single subscriber (admin list)."""
    id: int
    email: str
    is_subscribed: bool
    created_at: Optional[datetime] = None
    unsubscribed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SubscriberListResponse(BaseModel):
    """Paginated subscriber list (admin)."""
    subscribers: List[SubscriberItemResponse]
    total: int
    page: int
    limit: int
    total_pages: int


class AdminSendNewsletterRequest(BaseModel):
    """Send newsletter email to all subscribers (admin)."""
    subject: str = Field(..., min_length=1, max_length=500)
    body_html: str = Field(..., min_length=1, description="HTML body of the email")


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


class BiometricLoginRequest(BaseModel):
    """Biometric login using a device token stored in secure local storage."""
    device_token: str = Field(..., min_length=1, max_length=255, description="Raw device token string from secure storage")


class BiometricRevokeRequest(BaseModel):
    """Disable biometric login for current client – one device or all devices."""
    device_token: Optional[str] = Field(
        default=None,
        description="Optional raw device token to revoke for a single device. If omitted, revokes all biometric tokens for this client."
    )


class HostLoginResponseWithRefresh(BaseModel):
    """Host login response with refresh token"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    host: HostProfileResponse
    # Optional one-time device token for biometric login setup (host app)
    device_token: Optional[str] = Field(
        default=None,
        description="One-time device token for host biometric login (only present when enableBiometrics was true)"
    )


class ClientLoginResponseWithRefresh(BaseModel):
    """Client login response with refresh token"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    client: ClientProfileResponse
    # Optional one-time device token for biometric login setup
    device_token: Optional[str] = Field(
        default=None,
        description="One-time device token for biometric login (only present when enableBiometrics was true)"
    )


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
    # Host operating city (from hosts.city) — use with operating_cities from GET /config for grouping
    host_city: Optional[str] = None
    # New media fields (preferred)
    cover_image: Optional[str] = None
    car_images: Optional[List[str]] = None  # Array of image URLs for carousel
    car_video: Optional[str] = None
    # Legacy fields (for backward compatibility)
    image_urls: Optional[List[str]] = None
    video_url: Optional[str] = None
    # Drive options (for client car details + booking)
    drive_setting: Optional[str] = "self_only"
    allowed_drive_types: Optional[List[str]] = None  # ["self"] | ["self","withDriver"] | ["withDriver"]
    # Host information
    host_name: Optional[str] = None
    host_avatar_url: Optional[str] = None
    host_created_at: Optional[datetime] = None  # When host joined; use for "Since Feb", "6 months", "2 years" etc.
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
    booked_dates: List[dict]  # List of {start_date, end_date, status} for booked periods
    blocked_dates: List[dict] = []  # List of {start_date, end_date, reason} for host-blocked periods
    unavailable_dates: List[dict] = []  # Combined booked + blocked dates for calendar rendering
    next_available_date: Optional[str] = None  # ISO format date string for next available date
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
    host_city: Optional[str] = None

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


# ==================== WISHLIST SCHEMAS ====================


class WishlistSummaryResponse(BaseModel):
    """Summary card for the client's wishlist: count and latest car image."""
    total_cars: int
    latest_car_id: Optional[int] = None
    latest_car_name: Optional[str] = None
    latest_cover_image: Optional[str] = None


class WishlistCarItem(BaseModel):
    """Single car item in the client's wishlist."""
    car_id: int
    name: Optional[str] = None
    model: Optional[str] = None
    daily_rate: Optional[float] = None
    cover_image: Optional[str] = None
    location_name: Optional[str] = None
    host_city: Optional[str] = None
    created_at: datetime


class WishlistListResponse(BaseModel):
    """List of wishlist cars for a client."""
    cars: List[WishlistCarItem]


# ==================== BOOKING SCHEMAS ====================

class BookingStatusEnum(str, Enum):
    """Booking status enum for API"""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


def _location_to_str(v: Union[str, List[str], None]) -> Optional[str]:
    """Convert location to string - accepts array (e.g. from address picker) or string"""
    if v is None:
        return None
    if isinstance(v, list):
        return ", ".join(str(x) for x in v) if v else None
    return str(v) if v else None


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
    dropoff_same_as_pickup: Optional[bool] = Field(None, description="If true, return_location is same as pickup")

    @field_validator("pickup_location", "return_location", mode="before")
    @classmethod
    def parse_location(cls, v: Union[str, List[str], None]) -> Optional[str]:
        return _location_to_str(v)

    @model_validator(mode="after")
    def validate_dates_and_return_location(self):
        if self.start_date >= self.end_date:
            raise ValueError("End date must be after start date")
        now = datetime.now(timezone.utc)
        start = self.start_date
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if start < now:
            raise ValueError("Start date cannot be in the past")
        # When dropoff_same_as_pickup, use pickup_location for return_location if empty
        if self.dropoff_same_as_pickup and not self.return_location and self.pickup_location:
            self.return_location = self.pickup_location
        return self


class BookingUpdateRequest(BaseModel):
    """
    Request to update a PENDING booking (e.g. change dates or details before paying).
    All fields are optional; only provided fields are updated.
    """
    start_date: Optional[datetime] = Field(None, description="New rental start date")
    end_date: Optional[datetime] = Field(None, description="New rental end date")
    pickup_time: Optional[str] = Field(None, max_length=10)
    return_time: Optional[str] = Field(None, max_length=10)
    pickup_location: Optional[str] = Field(None, max_length=500)
    return_location: Optional[str] = Field(None, max_length=500)
    damage_waiver_enabled: Optional[bool] = None
    drive_type: Optional[str] = Field(None, description="'self' or 'withDriver'")
    check_in_preference: Optional[str] = Field(None, description="'self' or 'assisted'")
    special_requirements: Optional[str] = Field(None, max_length=2000)
    dropoff_same_as_pickup: Optional[bool] = Field(None, description="If true, return_location = pickup_location")

    @field_validator("pickup_location", "return_location", mode="before")
    @classmethod
    def parse_location(cls, v: Union[str, List[str], None]) -> Optional[str]:
        return _location_to_str(v)

    @model_validator(mode="after")
    def validate_dates_if_provided(self):
        if self.start_date is not None and self.end_date is not None and self.start_date >= self.end_date:
            raise ValueError("End date must be after start date")
        if self.start_date is not None:
            now = datetime.now(timezone.utc)
            start = self.start_date.replace(tzinfo=timezone.utc) if self.start_date.tzinfo is None else self.start_date
            if start < now:
                raise ValueError("Start date cannot be in the past")
        if self.dropoff_same_as_pickup and not self.return_location and self.pickup_location:
            self.return_location = self.pickup_location
        return self


class BookingResponse(BaseModel):
    """Booking response with full details"""
    id: int
    booking_id: str
    client_id: int
    client_name: Optional[str] = None   # Renter's name (for host views)
    client_email: Optional[str] = None  # Renter's email (for host contact)
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
    
    # Refund / cancellation details (for client visibility)
    refund_eligible: Optional[bool] = Field(
        default=None,
        description="Whether this booking is currently eligible for an automatic refund under the platform policy",
    )
    refund_amount: Optional[float] = Field(
        default=None,
        description="Estimated refund amount in KES if the client cancels now (base trip only, excludes extensions)",
    )
    refund_percentage: Optional[float] = Field(
        default=None,
        description="Estimated refund percentage (0.0‑1.0) that applies if cancelled now",
    )
    refund_policy_code: Optional[str] = Field(
        default=None,
        description="Short code for the policy rule applied, e.g. FULL_BEFORE_24H, HALF_WITHIN_24H, NO_REFUND_AFTER_START, NO_PAYMENT",
    )
    refund_policy_reason: Optional[str] = Field(
        default=None,
        description="Human‑readable explanation of how the refund rule was applied",
    )
    
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


class BookingExtensionStatusEnum(str, Enum):
    """Status of a booking extension request."""
    PENDING_HOST_APPROVAL = "pending_host_approval"
    HOST_APPROVED = "host_approved"
    PAID = "paid"
    EXPIRED = "expired"
    REJECTED = "rejected"


class BookingExtensionCreateRequest(BaseModel):
    """
    Client request to extend an existing booking (same trip, later drop-off only).

    - Only `end_date` is changed (no new pickup date)
    """
    new_end_date: datetime = Field(..., description="New drop-off date/time (must be after current end_date)")
    dropoff_same_as_previous: bool = Field(
        True,
        description="If true, keep the same drop-off location as the current booking",
    )
    new_dropoff_location: Optional[str] = Field(
        None,
        max_length=500,
        description="New drop-off location if different from the original one",
    )

    @model_validator(mode="after")
    def validate_locations(self):
        if not self.dropoff_same_as_previous and not self.new_dropoff_location:
            raise ValueError("new_dropoff_location is required when dropoff_same_as_previous is false")
        return self


class BookingExtensionRequestResponse(BaseModel):
    """Booking extension request details."""
    id: int
    booking_id: int
    client_id: int
    host_id: int
    old_end_date: datetime
    requested_end_date: datetime
    extra_days: int
    extra_amount: float
    dropoff_same_as_previous: bool
    new_dropoff_location: Optional[str] = None
    status: BookingExtensionStatusEnum
    host_note: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class BookingExtensionListResponse(BaseModel):
    """List of extension requests for a booking."""
    extensions: List[BookingExtensionRequestResponse]


# ==================== HOST BOOKING ISSUES SCHEMAS ====================

ISSUE_TYPES = ["damage", "late_return", "no_show", "misconduct", "other"]


class ReportIssueRequest(BaseModel):
    """Request to report an issue for an active booking."""
    issue_type: str = Field(..., description="Type: damage, late_return, no_show, misconduct, other")
    description: str = Field(..., min_length=1, max_length=2000, description="Issue description")

    @field_validator("issue_type")
    @classmethod
    def validate_issue_type(cls, v: str) -> str:
        if v not in ISSUE_TYPES:
            raise ValueError(f"issue_type must be one of: {', '.join(ISSUE_TYPES)}")
        return v


class BookingIssueResponse(BaseModel):
    """Host booking issue response."""
    id: int
    booking_id: int
    booking_id_display: str = Field(..., description="Human-readable booking ID e.g. BK-12345678")
    host_id: int
    issue_type: str
    description: str
    status: str = Field(..., description="open, in_review, resolved, closed")
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class BookingIssueListResponse(BaseModel):
    """Paginated list of host booking issues."""
    issues: List[BookingIssueResponse]
    total: int
    page: int
    limit: int


# ==================== HOST EARNINGS SCHEMAS ====================


class HostEarningsSummaryResponse(BaseModel):
    """Summary of host earnings for home/dashboard: net earnings, commission, withdrawable."""
    total_gross: float = Field(..., description="Total amount received from paid bookings (before commission)")
    commission_rate: float = Field(..., description="Platform commission rate (e.g. 0.15 for 15%)")
    commission_amount: float = Field(..., description="Total commission deducted")
    net_earnings: float = Field(..., description="Host earnings after commission (total_gross - commission)")
    pending_withdrawals_total: float = Field(..., description="Sum of pending + completed withdrawal amounts already claimed")
    withdrawable: float = Field(..., description="Amount available to withdraw (net_earnings - pending_withdrawals_total)")
    paid_bookings_count: int = Field(..., description="Number of paid (confirmed/active/completed) bookings")


class HostTransactionItem(BaseModel):
    """Single transaction (paid booking) for host earnings list."""
    booking_id: str
    car_name: Optional[str] = None
    client_name: Optional[str] = None
    amount: float = Field(..., description="Booking total (gross)")
    commission_amount: float
    net_amount: float
    paid_at: Optional[datetime] = None
    mpesa_receipt_number: Optional[str] = None


class HostTransactionListResponse(BaseModel):
    """Paginated list of host transactions (earnings per booking)."""
    transactions: List[HostTransactionItem]
    total: int
    skip: int
    limit: int


# ==================== WITHDRAWAL SCHEMAS ====================


class WithdrawalCreateRequest(BaseModel):
    """Host request to withdraw earnings."""
    amount: float = Field(..., gt=0, description="Amount to withdraw")
    payment_method_type: str = Field(..., description="mpesa or bank")
    mpesa_number: Optional[str] = Field(None, description="M-Pesa phone number (e.g. 254712345678) when payment_method_type is mpesa")
    bank_name: Optional[str] = Field(None, description="Bank name when payment_method_type is bank")
    account_number: Optional[str] = Field(None, description="Account number when payment_method_type is bank")
    account_name: Optional[str] = Field(None, description="Account holder name (optional)")

    @model_validator(mode="after")
    def validate_payment_details(self):
        if self.payment_method_type.lower() == "mpesa":
            if not self.mpesa_number or not str(self.mpesa_number).strip():
                raise ValueError("mpesa_number is required when payment_method_type is mpesa")
        elif self.payment_method_type.lower() == "bank":
            if not self.bank_name or not self.account_number:
                raise ValueError("bank_name and account_number are required when payment_method_type is bank")
        return self


class WithdrawalResponse(BaseModel):
    """Single withdrawal response (host or admin)."""
    id: int
    host_id: int
    host_name: Optional[str] = None
    host_email: Optional[str] = None
    amount: float
    status: str
    payment_method_type: str
    payment_details: Optional[str] = None  # JSON string for display
    processed_at: Optional[datetime] = None
    processed_by_admin_id: Optional[int] = None
    admin_notes: Optional[str] = None
    
    # Payhero/M-Pesa B2C callback fields
    checkout_request_id: Optional[str] = None
    result_code: Optional[int] = None
    result_desc: Optional[str] = None
    mpesa_receipt_number: Optional[str] = None
    mpesa_phone: Optional[str] = None
    mpesa_transaction_date: Optional[str] = None
    
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WithdrawalListResponse(BaseModel):
    """Paginated list of withdrawals."""
    withdrawals: List[WithdrawalResponse]
    total: int
    skip: int
    limit: int


class WithdrawalUpdateRequest(BaseModel):
    """Admin update: set status and optional notes."""
    status: str = Field(..., description="completed, rejected, or cancelled")
    admin_notes: Optional[str] = Field(None, max_length=2000)


class RefundStatusEnum(str, Enum):
    """Refund lifecycle for admin/finance UI."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RefundCreateRequest(BaseModel):
    """
    Admin request to create a refund record for a booking/payment.

    Normally used after a cancellation when the policy says a refund is due.
    """
    booking_id: int = Field(..., description="Internal numeric booking ID (not BK-… string)")
    payment_id: Optional[int] = Field(
        None,
        description="Optional payment ID when refunding a specific payment attempt",
    )
    amount_refund: float = Field(..., gt=0, description="Refund amount in KES to send back to client")
    percentage: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Refund percentage (0.0‑1.0) of the original amount for reporting",
    )
    reason: Optional[str] = Field(
        None,
        max_length=1000,
        description="Short reason visible to client (e.g. 'Cancelled >24h – full refund').",
    )
    internal_note: Optional[str] = Field(
        None,
        max_length=2000,
        description="Internal note for finance/admin (PSP reference, manual override, etc.)",
    )


class RefundUpdateRequest(BaseModel):
    """
    Admin request to update a refund record status and internal details.
    """
    status: RefundStatusEnum = Field(..., description="New refund status")
    internal_note: Optional[str] = Field(
        None,
        max_length=2000,
        description="Optional updated internal note for this refund",
    )
    external_reference: Optional[str] = Field(
        None,
        max_length=255,
        description="Optional PSP/bank reference for this refund",
    )


class RefundResponse(BaseModel):
    """Single refund record for admin UI."""
    id: int
    booking_id: int
    payment_id: Optional[int] = None
    client_id: int
    amount_original: float
    amount_refund: float
    percentage: Optional[float] = None
    status: RefundStatusEnum
    reason: Optional[str] = None
    internal_note: Optional[str] = None
    created_by_admin_id: Optional[int] = None
    processed_by_admin_id: Optional[int] = None
    external_reference: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None

    # Useful denormalized info for the admin web:
    booking_code: Optional[str] = Field(
        None,
        description="Human‑readable booking code (BK‑…)",
    )
    client_name: Optional[str] = None
    client_email: Optional[str] = None

    class Config:
        from_attributes = True


class RefundListResponse(BaseModel):
    """Paginated list of refunds for admin UI."""
    refunds: List[RefundResponse]
    total: int
    page: int
    limit: int


class ClientRefundResponse(BaseModel):
    """Refund record as visible to a client."""
    id: int
    booking_id: int
    amount_refund: float
    status: RefundStatusEnum
    reason: Optional[str] = None
    created_at: datetime
    processed_at: Optional[datetime] = None

    # Helpful extras for the app
    booking_code: Optional[str] = None

    class Config:
        from_attributes = True


class ClientRefundListResponse(BaseModel):
    """Paginated list of refunds for a client."""
    refunds: List[ClientRefundResponse]
    total: int
    skip: int
    limit: int


class ClientEmergencyRequest(BaseModel):
    """Client emergency message with location."""
    message: str = Field(..., min_length=1, max_length=2000, description="Emergency message describing the situation")
    latitude: Optional[float] = Field(
        None,
        ge=-90,
        le=90,
        description="Client's last known latitude",
    )
    longitude: Optional[float] = Field(
        None,
        ge=-180,
        le=180,
        description="Client's last known longitude",
    )
    location_accuracy_m: Optional[float] = Field(
        None,
        ge=0,
        description="Optional accuracy radius in meters as reported by the device",
    )
    booking_id: Optional[int] = Field(
        None,
        description="Optional numeric booking id this emergency relates to (if known)",
    )


class ClientEmergencyResponse(BaseModel):
    """Emergency report created for a client."""
    id: int
    client_id: int
    booking_id: Optional[int] = None
    message: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_accuracy_m: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


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

class BookingExtensionPaymentRequest(BaseModel):
    """Request to start payment for an approved booking extension."""
    payment_method_id: int = Field(..., description="ID of the payment method to use", alias="paymentMethodId")

    model_config = {"populate_by_name": True}


class PaymentRequest(BaseModel):
    """Request to process a payment. Accepts both snake_case and camelCase.
    booking_id can be either the string ID (e.g. 'BK-ABC12345') or the numeric database id.
    """
    booking_id: Union[str, int] = Field(..., description="Booking ID (string like 'BK-ABC12345') or numeric id", alias="bookingId")
    payment_method_id: int = Field(..., description="ID of the payment method to use", alias="paymentMethodId")

    model_config = {"populate_by_name": True}

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
    booking: BookingResponse
    # For card (Pesapal): redirect user to this URL to complete payment
    redirect_url: Optional[str] = None


class ArdenaPayPaymentRequest(BaseModel):
    """Request to pay for a booking with Ardena Pay. Use payWithXlm=true to pay with XLM (default: USDC)."""
    booking_id: Union[str, int] = Field(..., description="Booking ID (e.g. 'BK-ABC12345') or numeric id", alias="bookingId")
    pay_with_xlm: bool = Field(False, description="If true, deduct XLM (converted from KSH); if false, deduct USDC", alias="payWithXlm")
    model_config = {"populate_by_name": True}


class ArdenaPayPaymentResponse(BaseModel):
    """Response after successful Ardena Pay (USDC or XLM) payment."""
    success: bool
    booking_id: str
    amount_ksh: float
    amount_usdc: str
    amount_xlm: Optional[str] = None
    stellar_tx_hash: str
    message: str
    paid_at: datetime
    booking: BookingResponse


class StellarTransactionResponse(BaseModel):
    """Single Ardena Pay (USDC or XLM) transaction record for listing. amount_usd is always set for UI display."""
    id: int
    booking_id: int
    amount_ksh: float
    amount_usd: float = 0.0
    amount_usdc: Optional[str] = None
    amount_xlm: Optional[str] = None
    stellar_tx_hash: str
    from_address: str
    to_address: str
    created_at: datetime

    class Config:
        from_attributes = True


class IncomingWalletPaymentResponse(BaseModel):
    """Incoming Ardena Pay (USDC or XLM) payment to the client's wallet – for in-app 'You received X' messages."""
    id: int
    amount_asset: str  # "USDC" or "XLM"
    amount: str
    from_address: str
    stellar_tx_hash: str
    created_at: datetime
    notification_id: Optional[int] = None  # In-app notification created for this receipt

    class Config:
        from_attributes = True


class PaymentStatusEnum(str, Enum):
    """Payment attempt status (for UI polling)"""
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class PaymentStatusResponse(BaseModel):
    """Response for GET payment status – UI polls this after STK push or Paystack redirect."""
    checkout_request_id: str  # M-Pesa CheckoutRequestID or Paystack reference when applicable
    booking_id: str
    status: PaymentStatusEnum
    message: Optional[str] = None  # e.g. "Insufficient funds", "User cancelled"
    amount: float
    paid_at: Optional[datetime] = None  # Set when status is completed
    mpesa_receipt_number: Optional[str] = None
    paystack_reference: Optional[str] = None  # Paystack reference for card payments

    class Config:
        from_attributes = True


class MpesaStkPushRequest(BaseModel):
    """Internal schema for M-Pesa STK Push request"""
    BusinessShortCode: str
    Password: str
    Timestamp: str
    Amount: str
    PartyA: str
    PartyB: str
    TransactionType: str
    PhoneNumber: str
    TransactionDesc: str
    AccountReference: str
    CallBackUrl: str

class MpesaStkPushResponse(BaseModel):
    """Internal schema for M-Pesa STK Push response"""
    MerchantRequestID: str
    CheckoutRequestID: str
    ResponseCode: str
    ResponseDescription: str
    CustomerMessage: str


# --- Host subscription (M-Pesa Payhero) ---

class HostSubscriptionPlanCode(str, Enum):
    """Sellable subscription tiers (free is default on host, not purchased via checkout)."""
    starter = "starter"
    premium = "premium"


class HostSubscriptionPlanPublic(BaseModel):
    """One plan row for catalog / pricing UI."""
    code: str  # free | starter | premium
    name: str
    description: str
    price_kes: int  # 0 for free
    duration_days: int  # 0 for free (not billed)
    features: List[str] = Field(default_factory=list)


class HostSubscriptionPlansResponse(BaseModel):
    plans: List[HostSubscriptionPlanPublic]


class HostSubscriptionCheckoutRequest(BaseModel):
    """Start M-Pesa STK for host subscription."""
    plan: HostSubscriptionPlanCode = Field(..., description="starter or premium")
    phone_number: str = Field(
        ...,
        min_length=9,
        max_length=20,
        description="M-Pesa phone (e.g. 254712345678 or 0712345678)",
    )


class HostSubscriptionCheckoutResponse(BaseModel):
    success: bool = True
    message: str
    plan: str
    amount_kes: int
    checkout_request_id: Optional[str] = None
    external_reference: str = Field(
        ...,
        description="Reference sent to M-Pesa; poll payment-status with checkout_request_id.",
    )
    stk_pending_window_seconds: int = Field(
        ...,
        description="Match your UI countdown: pending auto-expires server-side after this if no PIN.",
    )


class HostSubscriptionMeResponse(BaseModel):
    """Current subscription for the authenticated host."""
    plan: str  # free | starter | premium
    expires_at: Optional[datetime] = None
    is_paid_active: bool = Field(
        ...,
        description="True if plan is starter or premium and expires_at is in the future",
    )
    is_trial: bool = Field(
        False,
        description="True if the host is currently in their free trial period.",
    )
    trial_available: bool = Field(
        False,
        description="True if the host has never used their free trial and is currently on the free plan.",
    )
    days_remaining: Optional[int] = None
    has_pending_checkout: bool = Field(
        False,
        description="True if an STK push is in progress (within server timeout window).",
    )
    pending_plan: Optional[str] = Field(None, description="Plan for in-progress checkout, if any.")
    pending_checkout_request_id: Optional[str] = Field(
        None,
        description="Poll payment-status with this id while pending.",
    )
    pending_seconds_remaining: Optional[int] = Field(
        None,
        description="Seconds left before server clears pending (no PIN); null if no pending.",
    )
    stk_pending_window_seconds: int = Field(
        90,
        description="Configured STK pending window (seconds); same as checkout response field.",
    )
    pending_paystack_reference: Optional[str] = Field(
        None,
        description="Paystack reference for an in-progress card checkout; poll card-status with this.",
    )


class HostTrialActivateResponse(BaseModel):
    """Response after successfully activating the free trial."""
    success: bool = True
    message: str
    plan: str
    expires_at: datetime
    days_granted: int


class HostSubscriptionPaymentStatusEnum(str, Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    expired = "expired"


class HostSubscriptionPaymentStatusResponse(BaseModel):
    checkout_request_id: Optional[str] = None
    external_reference: str
    plan: str
    amount_kes: float
    status: HostSubscriptionPaymentStatusEnum
    message: Optional[str] = None
    mpesa_receipt_number: Optional[str] = None
    # Card payment fields (populated for Paystack payments)
    paystack_reference: Optional[str] = None
    paystack_card_last4: Optional[str] = None
    paystack_card_brand: Optional[str] = None


class HostSubscriptionCardCheckoutRequest(BaseModel):
    """Start a Paystack card checkout for host subscription."""
    plan: HostSubscriptionPlanCode = Field(..., description="starter or premium")


class HostSubscriptionCardCheckoutResponse(BaseModel):
    """Response after initialising a Paystack card checkout."""
    success: bool = True
    message: str
    plan: str
    amount_kes: int
    paystack_reference: str = Field(..., description="Poll card-status with this reference.")
    authorization_url: str = Field(..., description="Open this URL in the browser / WebView for payment.")

