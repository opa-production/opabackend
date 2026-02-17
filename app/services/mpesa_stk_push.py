from dotenv import load_dotenv
import os
import base64
import logging
import requests
from datetime import datetime

load_dotenv()
logger = logging.getLogger(__name__)

# Supported env vars (either naming works):
#   CONSUMER_KEY or MPESA_CONSUMER_KEY
#   CONSUMER_SECRET or MPESA_CONSUMER_SECRET
#   MPESA_TOKEN_URL, MPESA_STK_URL (optional if MPESA_ENVIRONMENT is set)
#   MPESA_ENVIRONMENT = 'production' | 'sandbox' -> picks live or sandbox URLs when *_URL not set
#   MPESA_SHORTCODE or MPESA_EXPRESS_SHORTCODE (express used for STK push when set)
#   MPESA_PASSKEY, MPESA_CALLBACK_URL (required)
#   MPESA_SHORTCODE_TYPE = 'till_number' | 'paybill' -> Till uses CustomerBuyGoodsOnline

LIVE_TOKEN_URL = "https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
LIVE_STK_URL = "https://api.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
SANDBOX_TOKEN_URL = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
SANDBOX_STK_URL = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"


def _get_token_url():
    url = os.getenv("MPESA_TOKEN_URL")
    if url:
        return url
    env = (os.getenv("MPESA_ENVIRONMENT") or "").strip().lower()
    return LIVE_TOKEN_URL if env in ("production", "live") else SANDBOX_TOKEN_URL


def _get_stk_url():
    url = os.getenv("MPESA_STK_URL")
    if url:
        return url
    env = (os.getenv("MPESA_ENVIRONMENT") or "").strip().lower()
    return LIVE_STK_URL if env in ("production", "live") else SANDBOX_STK_URL


def generate_access_token():
    consumer_key = os.getenv("MPESA_CONSUMER_KEY") or os.getenv("CONSUMER_KEY")
    consumer_secret = os.getenv("MPESA_CONSUMER_SECRET") or os.getenv("CONSUMER_SECRET")
    url = _get_token_url()

    if not all([consumer_key, consumer_secret, url]):
        raise Exception("M-Pesa configuration missing: CONSUMER_KEY/MPESA_CONSUMER_KEY, CONSUMER_SECRET/MPESA_CONSUMER_SECRET, or MPESA_TOKEN_URL/MPESA_ENVIRONMENT")

    try:
        encoded_credentials = base64.b64encode(f"{consumer_key}:{consumer_secret}".encode()).decode()
        headers = {"Authorization": f"Basic {encoded_credentials}", "Content-Type": "application/json"}
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            logger.error(f"[MPESA] Token request failed: status={response.status_code}, body={response.text[:500]}")
            raise Exception(f"Token request failed: HTTP {response.status_code}")
        data = response.json()
        if "access_token" in data:
            return data["access_token"]
        raise Exception("Failed to get access token: " + data.get("error_description", str(data)))
    except requests.exceptions.RequestException as e:
        logger.error(f"[MPESA] Token request error: {e}")
        raise Exception("Failed to get access token: " + str(e)) 

def sendStkPush(amount: str, PhoneNumber: str, AccountReference: str = "CarRental", TransactionDesc: str = "Car Rental Payment"):
    token = generate_access_token()
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    # STK push: prefer MPESA_EXPRESS_SHORTCODE when set (till/paybill used for express), else MPESA_SHORTCODE
    shortCode = os.getenv("MPESA_EXPRESS_SHORTCODE") or os.getenv("MPESA_SHORTCODE")
    passkey = os.getenv("MPESA_PASSKEY")
    callback_url = os.getenv("MPESA_CALLBACK_URL")
    shortcode_type = (os.getenv("MPESA_SHORTCODE_TYPE") or "paybill").strip().lower()

    if not shortCode or not passkey:
        raise Exception("M-Pesa configuration missing: MPESA_EXPRESS_SHORTCODE/MPESA_SHORTCODE or MPESA_PASSKEY")
    if not callback_url or not callback_url.startswith("http"):
        logger.error("[MPESA] MPESA_CALLBACK_URL missing or invalid (must be public HTTPS URL)")
        raise Exception("M-Pesa configuration missing or invalid: MPESA_CALLBACK_URL (must be a public HTTPS URL)")

    shortCode = str(shortCode)
    passkey = str(passkey)
    stk_password = base64.b64encode((shortCode + passkey + timestamp).encode('utf-8')).decode('utf-8')
    url = _get_stk_url()

    # Till number uses CustomerBuyGoodsOnline; Paybill uses CustomerPayBillOnline
    transaction_type = "CustomerBuyGoodsOnline" if shortcode_type == "till_number" else "CustomerPayBillOnline"

    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    requestBody = {
        "BusinessShortCode": shortCode,
        "Password": stk_password,
        "Timestamp": timestamp,
        "TransactionType": transaction_type,
        "Amount": amount,
        "PartyA": PhoneNumber,
        "PartyB": shortCode,
        "PhoneNumber": PhoneNumber,
        "CallBackURL": callback_url,
        "AccountReference": AccountReference,
        "TransactionDesc": TransactionDesc,
    }

    try:
        response = requests.post(url, json=requestBody, headers=headers, timeout=30)
        body_text = response.text
        if response.status_code != 200:
            logger.error(
                f"[MPESA] STK push request failed: status={response.status_code}, url={url}, body={body_text[:500]}"
            )
            print(f"[MPESA] STK push request failed: status={response}, url={url}, body={body_text[:500]}")
            try:
                data = response.json()
                return {
                    "ResponseCode": str(data.get("errorCode", response.status_code)),
                    "ResponseDescription": data.get("errorMessage", body_text or f"HTTP {response.status_code}"),
                }
            except Exception:
                return {
                    "ResponseCode": "1",
                    "ResponseDescription": f"HTTP {response.status_code}: {body_text[:200] or 'No body'}",
                }
        try:
            return response.json()
        except Exception as e:
            logger.error(f"[MPESA] STK response not JSON: {body_text[:300]}, error={e}")
            return {"ResponseCode": "1", "ResponseDescription": "Invalid response from M-Pesa"}
    except requests.exceptions.RequestException as e:
        logger.error(f"[MPESA] STK push request error: {e}")
        return {"ResponseCode": "1", "ResponseDescription": str(e)}
