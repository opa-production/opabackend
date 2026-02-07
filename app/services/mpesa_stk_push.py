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

    try:
        encoded_credentials = base64.b64encode(f"{consumer_key}:{consumer_secret}".encode()).decode()

        headers = {
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "application/json"
        }

        # Send the request and parse the response
        response = requests.get(url, headers=headers).json()
        print(response)

        # Check for errors and return the access token
        if "access_token" in response:
            return response["access_token"]
        else:
            raise Exception("Failed to get access token: " + response["error_description"])
    except Exception as e:
        raise Exception("Failed to get access token: " + str(e)) 

def sendStkPush(amount: str, PhoneNumber: str, AccountReference: str = "CarRental", TransactionDesc: str = "Car Rental Payment"):
    token = generate_access_token()
    print(token)
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    shortCode = os.getenv("MPESA_SHORTCODE") #sandbox -174379
    passkey = os.getenv("MPESA_PASSKEY")
    stk_password = base64.b64encode((shortCode + passkey + timestamp).encode('utf-8')).decode('utf-8')
    
    #choose one depending on you development environment
    #sandbox
    url = os.getenv("MPESA_STK_URL")
    #live
    # url = "https://api.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
    
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
        print(response.json())
        return response.json()
    except Exception as e:
        print('Error:', str(e))
