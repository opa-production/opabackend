import asyncio
import logging
from app.core.config import settings
import requests
from requests.auth import HTTPBasicAuth
import json

logger = logging.getLogger(__name__)

def generate_kra_auth_token(url: str) -> dict:
    """
    Generates a KRA authentication token for the given URL.
    Args:
        url: The URL to generate the token for.
        
    Returns:
        The generated token.
    """
    auth = HTTPBasicAuth(settings.KRA_CONSUMER_KEY, settings.KRA_CONSUMER_SECRET)

    headers = {
        "Accept": "application/json",
    }

    response = requests.post(
        url, auth=auth, headers=headers, timeout=10
    )
    response.raise_for_status()

    try:
        return response.json()
    except json.JSONDecodeError:
        logger.error("Error decoding JSON response from Gava Connect API")
        raise Exception("Error decoding JSON response from Gava Connect API")
    

class GavaConnectService:
    """
    Service for integrating with Gava Connect API.
    """

    @classmethod
    async def verify_identity(cls, national_id_number: str) -> dict:
        """
        Initiates a Gava Connect verification process for the given national ID number.
        Args:
            national_id_number: The user's national ID.
            
        Returns:
            dict containing "full_name" and "kra_pin".
            Raises an Exception if the ID is deemed invalid (e.g., empty or specific error cases).
        """
        url = settings.KRA_API_BASE_URL + "/checker/v1/pin"

