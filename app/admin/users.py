from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, or_, select, delete, update

from app.database import get_db
from app.models import (
    Host, Client, Car, PaymentMethod, Feedback,
    HostPushToken, HostBiometricToken, HostSubscriptionPayment, HostKyc,
    Withdrawal, Booking, BookingExtensionRequest, BookingIssue,
    HostRating, ClientRating, CarRating, CarBlockedDate, WishlistItem,
    SupportMessage, SupportConversation, ClientHostConversation, ClientHostMessage,
    Payment, Refund, StellarPaymentTransaction, EmergencyReport,
)
from app.schemas import (
    HostListResponse,
    HostDetailResponse,
    HostUpdateRequest,
    PaginatedHostListResponse,
    ClientListResponse,
    ClientDetailResponse,
    ClientUpdateRequest,
    PaginatedClientListResponse,
    CarResponse,
    PaymentMethodListResponse,
    FeedbackListResponse
)
from app.auth import get_current_admin
from app.routers.cars import _car_to_response

router = APIRouter()


# Helper function for pagination
def calculate_pagination(page: int, limit: int, total: int) -> dict:
    """Calculate pagination metadata"""
    total_pages = (total + limit - 1) // limit if limit > 0 else 0
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages
    }


# ==================== HOST MANAGEMENT ====================

@router.get("/admin/hosts", response_model=PaginatedHostListResponse)
async def list_hosts(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by name or email"),
    sort_by: Optional[str] = Query("created_at", description="Sort field (id, full_name, email, created_at)"),
    order: Optional[str] = Query("desc", regex="^(asc|desc)$", description="Sort order"),
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    List all hosts with pagination and search
    
    - **page**: Page number (starts from 1)
    - **limit**: Number of items per page (1-100)
    - **search**: Search by name or email (partial match)
    - **sort_by**: Field to sort by (id, full_name, email, created_at)
    - **order**: Sort order (asc or desc)
    """
    # Build base statement
    stmt = select(Host)
    
    # Apply search filter
    if search:
        search_filter = or_(
            Host.full_name.ilike(f"%{search}%"),
            Host.email.ilike(f"%{search}%")
        )
        stmt = stmt.filter(search_filter)
    
    # Get total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0
    
    # Apply sorting
    sort_field = getattr(Host, sort_by, Host.created_at)
    if order == "asc":
        stmt = stmt.order_by(sort_field.asc())
    else:
        stmt = stmt.order_by(sort_field.desc())
    
    # Apply pagination
    skip = (page - 1) * limit
    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    hosts = result.scalars().all()
    
    # Build response with counts
    host_list = []
    for host in hosts:
        cars_count_stmt = select(func.count(Car.id)).filter(Car.host_id == host.id)
        cars_count_result = await db.execute(cars_count_stmt)
        cars_count = cars_count_result.scalar() or 0
        
        pm_count_stmt = select(func.count(PaymentMethod.id)).filter(PaymentMethod.host_id == host.id)
        pm_count_result = await db.execute(pm_count_stmt)
        payment_methods_count = pm_count_result.scalar() or 0
        
        host_list.append(HostListResponse(
            id=host.id,
            full_name=host.full_name,
            email=host.email,
            mobile_number=host.mobile_number,
            is_active=host.is_active,
            cars_count=cars_count,
            payment_methods_count=payment_methods_count,
            created_at=host.created_at
        ))
    
    pagination = calculate_pagination(page, limit, total)
    
    return PaginatedHostListResponse(
        hosts=host_list,
        **pagination
    )


@router.get("/admin/hosts/{host_id}", response_model=HostDetailResponse)
async def get_host_details(
    host_id: int,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed information about a specific host
    
    Includes counts of cars, payment methods, and feedback.
    """
    stmt = select(Host).filter(Host.id == host_id)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()
    
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Host not found"
        )
    
    # Get counts
    cars_count_stmt = select(func.count(Car.id)).filter(Car.host_id == host.id)
    cars_count_result = await db.execute(cars_count_stmt)
    cars_count = cars_count_result.scalar() or 0
    
    pm_count_stmt = select(func.count(PaymentMethod.id)).filter(PaymentMethod.host_id == host.id)
    pm_count_result = await db.execute(pm_count_stmt)
    payment_methods_count = pm_count_result.scalar() or 0
    
    fb_count_stmt = select(func.count(Feedback.id)).filter(Feedback.host_id == host.id)
    fb_count_result = await db.execute(fb_count_stmt)
    feedbacks_count = fb_count_result.scalar() or 0
    
    return HostDetailResponse(
        id=host.id,
        full_name=host.full_name,
        email=host.email,
        bio=host.bio,
        mobile_number=host.mobile_number,
        id_number=host.id_number,
        city=host.city,
        is_active=host.is_active,
        cars_count=cars_count,
        payment_methods_count=payment_methods_count,
        feedbacks_count=feedbacks_count,
        created_at=host.created_at,
        updated_at=host.updated_at
    )


@router.put("/admin/hosts/{host_id}", response_model=HostDetailResponse)
async def update_host(
    host_id: int,
    request: HostUpdateRequest,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Update host profile information
    
    Only provided fields will be updated.
    """
    stmt = select(Host).filter(Host.id == host_id)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()
    
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Host not found"
        )
    
    # Check if email is being changed and if it's already taken
    if request.email and request.email != host.email:
        existing_stmt = select(Host).filter(Host.email == request.email)
        existing_result = await db.execute(existing_stmt)
        existing_host = existing_result.scalar_one_or_none()
        if existing_host:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
    
    # Update fields
    if request.full_name is not None:
        host.full_name = request.full_name
    if request.email is not None:
        host.email = request.email
    if request.bio is not None:
        host.bio = request.bio
    if request.mobile_number is not None:
        host.mobile_number = request.mobile_number
    if request.id_number is not None:
        host.id_number = request.id_number
    if request.city is not None:
        host.city = request.city
    
    await db.commit()
    await db.refresh(host)
    
    # Get counts for response
    cars_count_stmt = select(func.count(Car.id)).filter(Car.host_id == host.id)
    cars_count_result = await db.execute(cars_count_stmt)
    cars_count = cars_count_result.scalar() or 0
    
    pm_count_stmt = select(func.count(PaymentMethod.id)).filter(PaymentMethod.host_id == host.id)
    pm_count_result = await db.execute(pm_count_stmt)
    payment_methods_count = pm_count_result.scalar() or 0
    
    fb_count_stmt = select(func.count(Feedback.id)).filter(Feedback.host_id == host.id)
    fb_count_result = await db.execute(fb_count_stmt)
    feedbacks_count = fb_count_result.scalar() or 0
    
    return HostDetailResponse(
        id=host.id,
        full_name=host.full_name,
        email=host.email,
        bio=host.bio,
        mobile_number=host.mobile_number,
        id_number=host.id_number,
        city=host.city,
        is_active=host.is_active,
        cars_count=cars_count,
        payment_methods_count=payment_methods_count,
        feedbacks_count=feedbacks_count,
        created_at=host.created_at,
        updated_at=host.updated_at
    )


@router.put("/admin/hosts/{host_id}/deactivate")
async def deactivate_host(
    host_id: int,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Deactivate a host account (soft delete)"""
    stmt = select(Host).filter(Host.id == host_id)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()
    
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Host not found"
        )
    
    if not host.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Host account is already inactive"
        )
    
    host.is_active = False
    await db.commit()
    
    return {"message": "Host account deactivated successfully"}


@router.put("/admin/hosts/{host_id}/activate")
async def activate_host(
    host_id: int,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Activate a host account"""
    stmt = select(Host).filter(Host.id == host_id)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()
    
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Host not found"
        )
    
    if host.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Host account is already active"
        )
    
    host.is_active = True
    await db.commit()
    
    return {"message": "Host account activated successfully"}


@router.delete("/admin/hosts/{host_id}")
async def delete_host(
    host_id: int,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Permanently delete a host account and all related data
    
    This will delete:
    - Host account
    - All cars owned by the host
    - All payment methods
    - All feedback entries
    
    This action cannot be undone.
    """
    stmt = select(Host).filter(Host.id == host_id)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()
    
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Host not found"
        )
    
    # Get counts for response
    cars_count_stmt = select(func.count(Car.id)).filter(Car.host_id == host.id)
    cars_count_result = await db.execute(cars_count_stmt)
    cars_count = cars_count_result.scalar() or 0
    
    pm_count_stmt = select(func.count(PaymentMethod.id)).filter(PaymentMethod.host_id == host.id)
    pm_count_result = await db.execute(pm_count_stmt)
    payment_methods_count = pm_count_result.scalar() or 0
    
    fb_count_stmt = select(func.count(Feedback.id)).filter(Feedback.host_id == host.id)
    fb_count_result = await db.execute(fb_count_stmt)
    feedbacks_count = fb_count_result.scalar() or 0
    
    # Subqueries reused across delete steps
    car_ids_q = select(Car.id).filter(Car.host_id == host.id)
    booking_ids_q = select(Booking.id).where(Booking.car_id.in_(car_ids_q))
    supp_conv_ids_q = select(SupportConversation.id).filter(SupportConversation.host_id == host.id)
    chat_conv_ids_q = select(ClientHostConversation.id).filter(ClientHostConversation.host_id == host.id)

    # 1. Deepest booking dependents
    await db.execute(delete(Refund).where(Refund.booking_id.in_(booking_ids_q)))
    await db.execute(delete(StellarPaymentTransaction).where(StellarPaymentTransaction.booking_id.in_(booking_ids_q)))
    await db.execute(delete(CarRating).where(CarRating.car_id.in_(car_ids_q)))
    await db.execute(delete(HostRating).filter(HostRating.host_id == host.id))
    await db.execute(delete(ClientRating).filter(ClientRating.host_id == host.id))
    # Null out nullable booking FK on emergency reports to avoid constraint violation
    await db.execute(
        update(EmergencyReport)
        .where(EmergencyReport.booking_id.in_(booking_ids_q))
        .values(booking_id=None)
    )

    # 2. Payments (depends on bookings and booking_extension_requests)
    await db.execute(delete(Payment).where(Payment.booking_id.in_(booking_ids_q)))

    # 3. Booking dependents that reference bookings directly
    await db.execute(delete(BookingIssue).where(BookingIssue.booking_id.in_(booking_ids_q)))
    await db.execute(delete(BookingExtensionRequest).where(BookingExtensionRequest.booking_id.in_(booking_ids_q)))

    # 4. Bookings and remaining car dependents
    await db.execute(delete(Booking).where(Booking.car_id.in_(car_ids_q)))
    await db.execute(delete(WishlistItem).where(WishlistItem.car_id.in_(car_ids_q)))
    await db.execute(delete(CarBlockedDate).where(CarBlockedDate.car_id.in_(car_ids_q)))

    # 5. Conversations
    await db.execute(delete(ClientHostMessage).where(ClientHostMessage.conversation_id.in_(chat_conv_ids_q)))
    await db.execute(delete(ClientHostConversation).filter(ClientHostConversation.host_id == host.id))
    await db.execute(delete(SupportMessage).where(SupportMessage.conversation_id.in_(supp_conv_ids_q)))
    await db.execute(delete(SupportConversation).filter(SupportConversation.host_id == host.id))

    # 6. Direct host dependents
    await db.execute(delete(HostPushToken).filter(HostPushToken.host_id == host.id))
    await db.execute(delete(HostBiometricToken).filter(HostBiometricToken.host_id == host.id))
    await db.execute(delete(HostSubscriptionPayment).filter(HostSubscriptionPayment.host_id == host.id))
    await db.execute(delete(HostKyc).filter(HostKyc.host_id == host.id))
    await db.execute(delete(Withdrawal).filter(Withdrawal.host_id == host.id))
    await db.execute(delete(Feedback).filter(Feedback.host_id == host.id))
    await db.execute(delete(PaymentMethod).filter(PaymentMethod.host_id == host.id))
    await db.execute(delete(Car).filter(Car.host_id == host.id))

    # 7. Delete the host
    await db.delete(host)
    await db.commit()
    
    return {
        "message": "Host account deleted successfully",
        "deleted_data": {
            "cars": cars_count,
            "payment_methods": payment_methods_count,
            "feedbacks": feedbacks_count
        }
    }


@router.get("/admin/hosts/{host_id}/cars", response_model=List[CarResponse])
async def get_host_cars(
    host_id: int,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get all cars owned by a specific host"""
    stmt = select(Host).filter(Host.id == host_id)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()
    
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Host not found"
        )
    
    car_stmt = select(Car).filter(Car.host_id == host_id)
    car_result = await db.execute(car_stmt)
    cars = car_result.scalars().all()
    return [_car_to_response(car) for car in cars]


@router.get("/admin/hosts/{host_id}/payment-methods", response_model=PaymentMethodListResponse)
async def get_host_payment_methods(
    host_id: int,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get all payment methods for a specific host"""
    stmt = select(Host).filter(Host.id == host_id)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()
    
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Host not found"
        )
    
    pm_stmt = select(PaymentMethod).filter(
        PaymentMethod.host_id == host_id
    ).order_by(PaymentMethod.is_default.desc(), PaymentMethod.created_at.desc())
    pm_result = await db.execute(pm_stmt)
    payment_methods = pm_result.scalars().all()
    
    return PaymentMethodListResponse(payment_methods=payment_methods)


@router.get("/admin/hosts/{host_id}/feedback", response_model=FeedbackListResponse)
async def get_host_feedback(
    host_id: int,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get all feedback for a specific host"""
    stmt = select(Host).filter(Host.id == host_id)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()
    
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Host not found"
        )
    
    fb_stmt = select(Feedback).filter(
        Feedback.host_id == host_id
    ).order_by(Feedback.created_at.desc())
    fb_result = await db.execute(fb_stmt)
    feedbacks = fb_result.scalars().all()
    
    return FeedbackListResponse(feedbacks=feedbacks)


# ==================== CLIENT MANAGEMENT ====================

@router.get("/admin/clients", response_model=PaginatedClientListResponse)
async def list_clients(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by name or email"),
    sort_by: Optional[str] = Query("created_at", description="Sort field (id, full_name, email, created_at)"),
    order: Optional[str] = Query("desc", regex="^(asc|desc)$", description="Sort order"),
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    List all clients with pagination and search
    
    - **page**: Page number (starts from 1)
    - **limit**: Number of items per page (1-100)
    - **search**: Search by name or email (partial match)
    - **sort_by**: Field to sort by (id, full_name, email, created_at)
    - **order**: Sort order (asc or desc)
    """
    # Build query
    stmt = select(Client)
    
    # Apply search filter
    if search:
        search_filter = or_(
            Client.full_name.ilike(f"%{search}%"),
            Client.email.ilike(f"%{search}%")
        )
        stmt = stmt.filter(search_filter)
    
    # Get total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0
    
    # Apply sorting
    sort_field = getattr(Client, sort_by, Client.created_at)
    if order == "asc":
        stmt = stmt.order_by(sort_field.asc())
    else:
        stmt = stmt.order_by(sort_field.desc())
    
    # Apply pagination
    skip = (page - 1) * limit
    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    clients = result.scalars().all()
    
    # Build response
    client_list = [
        ClientListResponse(
            id=client.id,
            full_name=client.full_name,
            email=client.email,
            mobile_number=client.mobile_number,
            is_active=client.is_active,
            created_at=client.created_at
        )
        for client in clients
    ]
    
    pagination = calculate_pagination(page, limit, total)
    
    return PaginatedClientListResponse(
        clients=client_list,
        **pagination
    )


@router.get("/admin/clients/{client_id}", response_model=ClientDetailResponse)
async def get_client_details(
    client_id: int,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed information about a specific client"""
    stmt = select(Client).filter(Client.id == client_id)
    result = await db.execute(stmt)
    client = result.scalar_one_or_none()
    
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )
    
    return client


@router.put("/admin/clients/{client_id}", response_model=ClientDetailResponse)
async def update_client(
    client_id: int,
    request: ClientUpdateRequest,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Update client profile information
    
    Only provided fields will be updated.
    """
    stmt = select(Client).filter(Client.id == client_id)
    result = await db.execute(stmt)
    client = result.scalar_one_or_none()
    
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )
    
    # Check if email is being changed and if it's already taken
    if request.email and request.email != client.email:
        existing_stmt = select(Client).filter(Client.email == request.email)
        existing_result = await db.execute(existing_stmt)
        existing_client = existing_result.scalar_one_or_none()
        if existing_client:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
    
    # Update fields
    if request.full_name is not None:
        client.full_name = request.full_name
    if request.email is not None:
        client.email = request.email
    if request.bio is not None:
        client.bio = request.bio
    if request.fun_fact is not None:
        client.fun_fact = request.fun_fact
    if request.mobile_number is not None:
        client.mobile_number = request.mobile_number
    if request.id_number is not None:
        client.id_number = request.id_number
    
    await db.commit()
    await db.refresh(client)
    
    return client


@router.put("/admin/clients/{client_id}/deactivate")
async def deactivate_client(
    client_id: int,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Deactivate a client account (soft delete)"""
    stmt = select(Client).filter(Client.id == client_id)
    result = await db.execute(stmt)
    client = result.scalar_one_or_none()
    
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )
    
    if not client.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Client account is already inactive"
        )
    
    client.is_active = False
    await db.commit()
    
    return {"message": "Client account deactivated successfully"}


@router.put("/admin/clients/{client_id}/activate")
async def activate_client(
    client_id: int,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Activate a client account"""
    stmt = select(Client).filter(Client.id == client_id)
    result = await db.execute(stmt)
    client = result.scalar_one_or_none()
    
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )
    
    if client.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Client account is already active"
        )
    
    client.is_active = True
    await db.commit()
    
    return {"message": "Client account activated successfully"}


@router.delete("/admin/clients/{client_id}")
async def delete_client(
    client_id: int,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Permanently delete a client account
    
    This action cannot be undone.
    """
    stmt = select(Client).filter(Client.id == client_id)
    result = await db.execute(stmt)
    client = result.scalar_one_or_none()
    
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )
    
    storage_uuid = client.storage_uuid
    client_id_val = client.id
    await db.delete(client)
    await db.commit()

    from app.storage import delete_user_storage_folder, BUCKETS
    for folder in filter(None, [str(client_id_val), storage_uuid]):
        await delete_user_storage_folder(BUCKETS["client_profile"], folder)
        await delete_user_storage_folder(BUCKETS["client_documents"], folder)

    return {"message": "Client account deleted successfully"}
