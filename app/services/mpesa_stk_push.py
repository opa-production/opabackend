from dotenv import load_dotenv
import os
import base64
import requests
from datetime import datetime

load_dotenv()

def generate_access_token():
    consumer_key = os.getenv("CONSUMER_KEY")
    consumer_secret = os.getenv("CONSUMER_SECRET")
    url = os.getenv("MPESA_TOKEN_URL")

    if not all([consumer_key, consumer_secret, url]):
        raise Exception("M-Pesa configuration missing: CONSUMER_KEY, CONSUMER_SECRET, or MPESA_TOKEN_URL")

    try:
        encoded_credentials = base64.b64encode(f"{consumer_key}:{consumer_secret}".encode()).decode()

        headers = {
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "application/json"
        }

        response = requests.get(url, headers=headers).json() # type: ignore

        if "access_token" in response:
            return response["access_token"]
        else:
            raise Exception("Failed to get access token: " + response.get("error_description", "Unknown error"))
    except Exception as e:
        raise Exception("Failed to get access token: " + str(e)) 

def sendStkPush(amount: str, PhoneNumber: str, AccountReference: str = "CarRental", TransactionDesc: str = "Car Rental Payment"):
    token = generate_access_token()
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    shortCode = os.getenv("MPESA_SHORTCODE") 
    passkey = os.getenv("MPESA_PASSKEY")
    
    if not all([shortCode, passkey]):
        raise Exception("M-Pesa configuration missing: MPESA_SHORTCODE or MPESA_PASSKEY")

    shortCode = str(shortCode)
    passkey = str(passkey)
    
    stk_password = base64.b64encode((shortCode + passkey + timestamp).encode('utf-8')).decode('utf-8')
    
    url = os.getenv("MPESA_STK_URL")
    
    if not url:
        raise Exception("M-Pesa configuration missing: MPESA_STK_URL")
    
    headers = {
        'Authorization': 'Bearer '+token,
        'Content-Type': 'application/json'
    }
    print(headers)
    
    requestBody = {
        "BusinessShortCode": shortCode,
        "Password": stk_password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline", 
        "Amount": amount,
        "PartyA": PhoneNumber,
        "PartyB": shortCode,
        "PhoneNumber": PhoneNumber,
        "CallBackURL": os.getenv("MPESA_CALLBACK_URL", "https://fruity-weeks-care.loca.lt/mpesa/callback"),
        "AccountReference": AccountReference,
        "TransactionDesc": TransactionDesc
    }
    
    try:
        response = requests.post(url, json=requestBody, headers=headers)
        return response.json()
    except Exception as e:
        return {"ResponseCode": "1", "ResponseDescription": str(e)}
