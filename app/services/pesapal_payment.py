"""
Pesapal API client (Visa/Mastercard). Two different base URLs:

- PESAPAL_BASE_URL: Pesapal's API (we call them). Sandbox: https://cybqa.pesapal.com/pesapalv3, Live: https://pay.pesapal.com/v3
- PESAPAL_CALLBACK_BASE_URL: Our API base (used in payments router only). Where Pesapal and the user reach us
  (e.g. https://api.ardena.xyz/api/v1 or ngrok for local). Never used in this file.
"""
from dotenv import load_dotenv
import os
import logging
import requests
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

load_dotenv()
logger = logging.getLogger(__name__)

# Pesapal's server (auth, submit order, get status). Sandbox default.
PESAPAL_BASE_URL = os.getenv("PESAPAL_BASE_URL", "https://cybqa.pesapal.com/pesapalv3").rstrip("/")
PESAPAL_CONSUMER_KEY = os.getenv("PESAPAL_CONSUMER_KEY")
PESAPAL_CONSUMER_SECRET = os.getenv("PESAPAL_CONSUMER_SECRET")
# Pre-registered IPN ID (from Pesapal dashboard). Required for SubmitOrderRequest.
PESAPAL_IPN_ID = os.getenv("PESAPAL_IPN_ID")

_auth_token_cache: Optional[Dict[str, Any]] = None

def get_auth_token() -> Optional[str]:
    """
    Get OAuth token from Pesapal API.
    Caches token until it expires (Pesapal tokens typically last 5 minutes).
    """
    global _auth_token_cache

    if not all([PESAPAL_CONSUMER_KEY, PESAPAL_CONSUMER_SECRET]):
        logger.error("[PESAPAL] Configuration missing: PESAPAL_CONSUMER_KEY or PESAPAL_CONSUMER_SECRET")
        return None

    if _auth_token_cache and _auth_token_cache.get("expires_at"):
        if datetime.now() < _auth_token_cache["expires_at"]:
            return _auth_token_cache["token"]

    try:
        url = f"{PESAPAL_BASE_URL}/api/Auth/RequestToken"
        payload = {
            "consumer_key": PESAPAL_CONSUMER_KEY,
            "consumer_secret": PESAPAL_CONSUMER_SECRET
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        logger.info("[PESAPAL] Requesting authentication token...")
        response = requests.post(url, json=payload, headers=headers, timeout=30)

        if response.status_code == 200:
            data = response.json()
            token = data.get("token")
            if token:
                _auth_token_cache = {
                    "token": token,
                    "expires_at": datetime.now() + timedelta(minutes=4)
                }
                logger.info("[PESAPAL] Authentication successful")
                return token
            else:
                logger.error(f"[PESAPAL] No token in response: {data}")
                return None
        else:
            logger.error(f"[PESAPAL] Auth failed: {response.status_code}, {response.text}")
            return None

    except Exception as e:
        logger.error(f"[PESAPAL] Auth exception: {str(e)}")
        return None


def get_ipn_id(callback_base_url: Optional[str] = None) -> Optional[str]:
    """
    Return IPN ID for use in SubmitOrderRequest. Uses PESAPAL_IPN_ID from env if set;
    otherwise registers the given callback_base_url as IPN and returns the new ID.
    callback_base_url should be the full URL to your IPN endpoint (e.g. https://api.example.com/api/v1/pesapal/ipn).
    """
    if PESAPAL_IPN_ID:
        return PESAPAL_IPN_ID
    if callback_base_url:
        return register_ipn_url(callback_base_url)
    logger.error("[PESAPAL] No PESAPAL_IPN_ID and no callback_base_url provided for IPN registration")
    return None


def register_ipn_url(callback_url: str) -> Optional[str]:
    """
    Register IPN (Instant Payment Notification) URL with Pesapal.
    Returns IPN ID if successful.
    """
    token = get_auth_token()
    if not token:
        return None
    
    try:
        url = f"{PESAPAL_BASE_URL}/api/URLSetup/RegisterIPN"
        payload = {
            "url": callback_url,
            "ipn_notification_type": "GET"
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        
        logger.info(f"[PESAPAL] Registering IPN URL: {callback_url}")
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        if response.status_code in (200, 201):
            data = response.json()
            ipn_id = data.get("ipn_id")
            logger.info(f"[PESAPAL] IPN registered successfully: {ipn_id}")
            return ipn_id
        else:
            logger.error(f"[PESAPAL] IPN registration failed: {response.status_code}, {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"[PESAPAL] IPN registration exception: {str(e)}")
        return None


def build_billing_address(
    email: str,
    first_name: str,
    last_name: str,
    phone_number: Optional[str] = None,
    country_code: str = "KE",
) -> Dict[str, Any]:
    """
    Build Pesapal billing_address object. email_address or phone_number required.
    """
    addr: Dict[str, Any] = {
        "email_address": email,
        "country_code": country_code,
        "first_name": first_name,
        "last_name": last_name,
    }
    if phone_number:
        # Normalize: ensure country code (254 for Kenya)
        phone = str(phone_number).strip()
        if phone.startswith("0"):
            phone = "254" + phone[1:]
        elif not phone.startswith("254") and country_code == "KE":
            phone = "254" + phone
        addr["phone_number"] = phone
    return addr


def submit_order(
    amount: float,
    currency: str,
    description: str,
    callback_url: str,
    notification_id: str,
    billing_address: Dict[str, Any],
    reference: str
) -> Dict[str, Any]:
    """
    Submit order to Pesapal for card payment processing (Visa/Mastercard).
    Returns dict with order details including redirect_url for the customer.
    """
    token = get_auth_token()
    if not token:
        logger.error("[PESAPAL] Cannot submit order: authentication failed")
        return {
            "status": "error",
            "message": "Pesapal authentication failed"
        }

    try:
        url = f"{PESAPAL_BASE_URL}/api/Transactions/SubmitOrderRequest"

        payload = {
            "id": reference,
            "currency": currency,
            "amount": amount,
            "description": description[:100] if description else "Payment",  # max 100 chars
            "callback_url": callback_url,
            "notification_id": notification_id,
            "billing_address": billing_address
        }

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }

        logger.info(f"[PESAPAL] Submitting order: ref={reference}, amount={amount} {currency}")
        response = requests.post(url, json=payload, headers=headers, timeout=30)

        if response.status_code in (200, 201):
            data = response.json()
            # Handle both snake_case and camelCase response keys
            order_tracking_id = data.get("order_tracking_id") or data.get("orderTrackingId")
            merchant_reference = data.get("merchant_reference") or data.get("merchantReference")
            redirect_url = data.get("redirect_url") or data.get("redirectUrl")

            if data.get("error"):
                error_msg = data.get("error", {}).get("message", "Unknown error") if isinstance(data.get("error"), dict) else str(data.get("error"))
                logger.error(f"[PESAPAL] Order submission error: {error_msg}")
                return {"status": "error", "message": error_msg}

            if order_tracking_id and redirect_url:
                logger.info(f"[PESAPAL] Order submitted successfully: tracking_id={order_tracking_id}")
                return {
                    "status": "success",
                    "order_tracking_id": order_tracking_id,
                    "merchant_reference": merchant_reference or reference,
                    "redirect_url": redirect_url,
                    "message": "Order created successfully"
                }
            else:
                logger.error(f"[PESAPAL] Missing order_tracking_id or redirect_url in response: {data}")
                return {
                    "status": "error",
                    "message": "Invalid response from Pesapal"
                }
        else:
            logger.error(f"[PESAPAL] Order submission failed: {response.status_code}, {response.text}")
            return {
                "status": "error",
                "message": f"Order submission failed: {response.text[:200]}"
            }

    except requests.exceptions.RequestException as e:
        logger.error(f"[PESAPAL] Request exception: {str(e)}")
        return {
            "status": "error",
            "message": f"Connection error: {str(e)}"
        }
    except Exception as e:
        logger.error(f"[PESAPAL] Unexpected error: {str(e)}")
        return {
            "status": "error",
            "message": f"Internal error: {str(e)}"
        }


def get_transaction_status(order_tracking_id: str) -> Dict[str, Any]:
    """
    Query transaction status from Pesapal.
    Returns dict with payment status and details.
    """
    token = get_auth_token()
    if not token:
        logger.error("[PESAPAL] Cannot get status: authentication failed")
        return {
            "status": "error",
            "message": "Pesapal authentication failed"
        }
    
    try:
        url = f"{PESAPAL_BASE_URL}/api/Transactions/GetTransactionStatus"
        params = {"orderTrackingId": order_tracking_id}
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}"
        }
        
        logger.info(f"[PESAPAL] Checking status for: {order_tracking_id}")
        response = requests.get(url, params=params, headers=headers, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            payment_status = data.get("payment_status_description", "").lower()
            
            return {
                "status": "success",
                "payment_status": payment_status,
                "payment_method": data.get("payment_method"),
                "amount": data.get("amount"),
                "currency": data.get("currency"),
                "merchant_reference": data.get("merchant_reference"),
                "payment_account": data.get("payment_account"),
                "confirmation_code": data.get("confirmation_code"),
                "created_date": data.get("created_date"),
                "status_code": data.get("status_code"),
                "message": data.get("message", "")
            }
        else:
            logger.error(f"[PESAPAL] Status check failed: {response.status_code}, {response.text}")
            return {
                "status": "error",
                "message": f"Status check failed: {response.text[:200]}"
            }
            
    except Exception as e:
        logger.error(f"[PESAPAL] Status check exception: {str(e)}")
        return {
            "status": "error",
            "message": f"Status check error: {str(e)}"
        }
