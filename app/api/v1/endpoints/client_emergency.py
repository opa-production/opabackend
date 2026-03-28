"""
Client emergency endpoint.

The mobile app shows an emergency screen where the client can type a message and
send it together with their current location. This endpoint records that report
so support/ops can see and respond.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_client
from app.db.session import get_db
from app.models import Booking, Client, EmergencyReport
from app.schemas import ClientEmergencyRequest, ClientEmergencyResponse

router = APIRouter()


@router.post(
    "/client/emergency",
    response_model=ClientEmergencyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_emergency_report(
    body: ClientEmergencyRequest,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """
    Send an emergency message with the client's last known location.

    Body:
    - **message**: required text describing the emergency.
    - **latitude/longitude**: optional location coordinates.
    - **location_accuracy_m**: optional accuracy radius in meters.
    - **booking_id**: optional numeric booking id if the emergency is related
      to a specific trip.
    """
    booking_id = body.booking_id
    booking = None
    if booking_id is not None:
        booking = (
            db.query(Booking)
            .filter(
                Booking.id == booking_id,
                Booking.client_id == current_client.id,
            )
            .first()
        )
        if not booking:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Booking not found for this client",
            )

    report = EmergencyReport(
        client_id=current_client.id,
        booking_id=booking.id if booking else None,
        message=body.message.strip(),
        latitude=body.latitude,
        longitude=body.longitude,
        location_accuracy_m=body.location_accuracy_m,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    return ClientEmergencyResponse(
        id=report.id,
        client_id=report.client_id,
        booking_id=report.booking_id,
        message=report.message,
        latitude=report.latitude,
        longitude=report.longitude,
        location_accuracy_m=report.location_accuracy_m,
        created_at=report.created_at,
    )
