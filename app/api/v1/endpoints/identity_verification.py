from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import get_current_client
from app.models import Client
from app.services.gava_connect import GavaConnectService

router = APIRouter()

class IdentityVerificationResponse(BaseModel):
    full_name: str
    kra_pin: str
    national_id_number: str

@router.get(
    "/client/identity/verify/{national_id_number}",
    response_model=IdentityVerificationResponse,
    status_code=status.HTTP_200_OK,
)
async def verify_identity(
    national_id_number: str,
    current_client: Client = Depends(get_current_client),
) -> Any:
    """
    Verify identity using Gava Connect based on the national ID number.
    Returns the user's full name and KRA PIN automatically without storing
    a dedicated model instance in the database.
    """
    try:
        identity_data = await GavaConnectService.verify_identity(
            national_id_number=national_id_number
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Gava Connect verification failed: {str(e)}",
        )

    return IdentityVerificationResponse(
        national_id_number=national_id_number,
        full_name=identity_data.get("full_name", ""),
        kra_pin=identity_data.get("kra_pin", ""),
    )
