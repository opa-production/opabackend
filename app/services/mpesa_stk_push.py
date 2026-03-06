from dotenv import load_dotenv
import os
import logging
import requests

load_dotenv()
logger = logging.getLogger(__name__)

PAYHERO_URL = "https://backend.payhero.co.ke/api/v2/payments"

def sendStkPush(amount: str, PhoneNumber: str, AccountReference: str = "CarRental"):
    auth_token = os.getenv("PAYHERO_AUTH_TOKEN")
    channel_id = os.getenv("PAYHERO_CHANNEL_ID")
    callback_url = os.getenv("PAYHERO_CALLBACK_URL")

    if not all([auth_token, channel_id]):
        logger.error("[PAYHERO] Configuration missing: PAYHERO_AUTH_TOKEN or PAYHERO_CHANNEL_ID")
        return {
            "ResponseCode": "1",
            "ResponseDescription": "Payhero configuration missing (Auth Token or Channel ID)"
        }

    try:
        headers = {
            "Authorization": f"Basic {auth_token}",
            "Content-Type": "application/json"
        }

        try:
            amount_val = int(float(amount))
        except (ValueError, TypeError):
            logger.error(f"[PAYHERO] Invalid amount: {amount}")
            return {
                "ResponseCode": "1",
                "ResponseDescription": f"Invalid amount: {amount}"
            }

        payload = {
            "amount": amount_val,
            "phone_number": PhoneNumber,
            "channel_id": int(channel_id),
            "provider": "m-pesa",
            "external_reference": AccountReference,
            "callback_url": callback_url,
        }

        logger.info(f"[PAYHERO] Initiating STK push: {PhoneNumber}, amount={amount_val}, ref={AccountReference}")

        response = requests.post(PAYHERO_URL, json=payload, headers=headers, timeout=30)

        if response.status_code in (200, 201):
            data = response.json()
            if data.get("success") or data.get("status") == "Success":
                return {
                    "ResponseCode": "0",
                    "ResponseDescription": data.get("message", "STK Push initiated successfully"),
                    "CheckoutRequestID": data.get("reference")
                }
            else:
                logger.error(f"[PAYHERO] API returned error: {data}")
                return {
                    "ResponseCode": "1",
                    "ResponseDescription": data.get("message", "Failed to initiate STK push")
                }
        else:
            logger.error(f"[PAYHERO] Request failed: status={response.status_code}, body={response.text[:500]}")
            return {
                "ResponseCode": str(response.status_code),
                "ResponseDescription": f"Payhero error: {response.status_code}"
            }

    except requests.exceptions.RequestException as e:
        logger.error(f"[PAYHERO] Request exception: {str(e)}")
        return {
            "ResponseCode": "1",
            "ResponseDescription": f"Connection error: {str(e)}"
        }
    except Exception as e:
        logger.error(f"[PAYHERO] Unexpected error: {str(e)}")
        return {
            "ResponseCode": "1",
            "ResponseDescription": f"Internal error: {str(e)}"
        }
