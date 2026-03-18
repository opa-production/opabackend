from dotenv import load_dotenv
import os
import logging
import httpx

load_dotenv()
logger = logging.getLogger(__name__)

PAYHERO_URL = "https://backend.payhero.co.ke/api/v2/payments"

async def sendStkPush(amount: str, PhoneNumber: str, AccountReference: str = "CarRental"):
    auth_token = os.getenv("PAYHERO_AUTH_TOKEN")
    channel_id = os.getenv("PAYHERO_CHANNEL_ID")
    callback_url = os.getenv("PAYHERO_CALLBACK_URL")

    # Payhero must be able to POST to this URL from the internet; otherwise payment status stays "pending"
    if callback_url:
        url_lower = callback_url.lower()
        if "localhost" in url_lower or "127.0.0.1" in url_lower or url_lower.startswith("http://192.168.") or url_lower.startswith("http://10."):
            logger.warning(
                "[PAYHERO] PAYHERO_CALLBACK_URL is not public (%s). Payhero cannot reach it; payment status will never update. Use a public URL (e.g. https://your-api.com/api/v1/mpesa/callback) or ngrok for local testing.",
                callback_url.split("?")[0] if "?" in callback_url else callback_url[:80],
            )
    else:
        logger.warning("[PAYHERO] PAYHERO_CALLBACK_URL is not set. Payhero may use a default or payment status will not update.")

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

        async with httpx.AsyncClient() as client:
            response = await client.post(PAYHERO_URL, json=payload, headers=headers, timeout=30.0)

        if response.status_code in (200, 201):
            data = response.json()
            if data.get("success") or data.get("status") == "Success":
                # Payhero callback sends "CheckoutRequestID" (e.g. ws_CO_...). Use same key from init response.
                checkout_id = (
                    data.get("checkout_request_id")
                    or data.get("CheckoutRequestID")
                    or data.get("reference")
                )
                logger.info("[PAYHERO] Init response keys: %s; using CheckoutRequestID=%s", list(data.keys()), checkout_id)
                return {
                    "ResponseCode": "0",
                    "ResponseDescription": data.get("message", "STK Push initiated successfully"),
                    "CheckoutRequestID": checkout_id
                }
            else:
                logger.error(f"[PAYHERO] API returned error: {data}")
                return {
                    "ResponseCode": "1",
                    "ResponseDescription": data.get("message", "Failed to initiate STK push")
                }
        else:
            # Parse error body so the client sees the real reason (e.g. merchant insufficient balance)
            try:
                err = response.json()
                msg = err.get("error_message") or err.get("message") or response.text[:200] or f"Payhero error: {response.status_code}"
            except Exception:
                msg = response.text[:200] or f"Payhero error: {response.status_code}"
            logger.error("[PAYHERO] Request failed: status=%s, body=%s", response.status_code, response.text[:500])
            return {
                "ResponseCode": str(response.status_code),
                "ResponseDescription": msg.strip() if isinstance(msg, str) else str(msg)
            }

    except httpx.RequestError as e:
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
