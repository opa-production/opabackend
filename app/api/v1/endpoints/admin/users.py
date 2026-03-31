from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.api.v1.endpoints.cars import _car_to_response
from app.db.session import get_db
from app.models import Car, Client, Feedback, Host, PaymentMethod
from app.schemas import (
    CarResponse,
    ClientDetailResponse,
    ClientListResponse,
    ClientUpdateRequest,
    FeedbackListResponse,
    HostDetailResponse,
    HostListResponse,
    HostUpdateRequest,
    PaginatedClientListResponse,
    PaginatedHostListResponse,
    PaymentMethodListResponse,
)

router = APIRouter()


# Helper function for pagination
def calculate_pagination(page: int, limit: int, total: int) -> dict:
    """Calculate pagination metadata"""
    total_pages = (total + limit - 1) // limit if limit > 0 else 0
    return {"total": total, "page": page, "limit": limit, "total_pages": total_pages}


# ==================== HOST MANAGEMENT ====================


@router.get("/admin/hosts", response_model=PaginatedHostListResponse)
async def list_hosts(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by name or email"),
    sort_by: Optional[str] = Query(
        "created_at", description="Sort field (id, full_name, email, created_at)"
    ),
    order: Optional[str] = Query(
        "desc", regex="^(asc|desc)$", description="Sort order"
    ),
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
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
            Host.full_name.ilike(f"%{search}%"), Host.email.ilike(f"%{search}%")
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

        pm_count_stmt = select(func.count(PaymentMethod.id)).filter(
            PaymentMethod.host_id == host.id
        )
        pm_count_result = await db.execute(pm_count_stmt)
        payment_methods_count = pm_count_result.scalar() or 0

        host_list.append(
            HostListResponse(
                id=host.id,
                full_name=host.full_name,
                email=host.email,
                mobile_number=host.mobile_number,
                is_active=host.is_active,
                cars_count=cars_count,
                payment_methods_count=payment_methods_count,
                created_at=host.created_at,
            )
        )

    pagination = calculate_pagination(page, limit, total)

    return PaginatedHostListResponse(hosts=host_list, **pagination)


@router.get("/admin/hosts/{host_id}", response_model=HostDetailResponse)
async def get_host_details(
    host_id: int,
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
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
            status_code=status.HTTP_404_NOT_FOUND, detail="Host not found"
        )

    # Get counts
    cars_count_stmt = select(func.count(Car.id)).filter(Car.host_id == host.id)
    cars_count_result = await db.execute(cars_count_stmt)
    cars_count = cars_count_result.scalar() or 0

    pm_count_stmt = select(func.count(PaymentMethod.id)).filter(
        PaymentMethod.host_id == host.id
    )
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
        updated_at=host.updated_at,
    )


@router.put("/admin/hosts/{host_id}", response_model=HostDetailResponse)
async def update_host(
    host_id: int,
    request: HostUpdateRequest,
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
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
            status_code=status.HTTP_404_NOT_FOUND, detail="Host not found"
        )

    # Check if email is being changed and if it's already taken
    if request.email and request.email != host.email:
        existing_stmt = select(Host).filter(Host.email == request.email)
        existing_result = await db.execute(existing_stmt)
        existing_host = existing_result.scalar_one_or_none()
        if existing_host:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
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

    pm_count_stmt = select(func.count(PaymentMethod.id)).filter(
        PaymentMethod.host_id == host.id
    )
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
        updated_at=host.updated_at,
    )


@router.put("/admin/hosts/{host_id}/deactivate")
async def deactivate_host(
    host_id: int,
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a host account (soft delete)"""
    stmt = select(Host).filter(Host.id == host_id)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()

    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Host not found"
        )

    if not host.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Host account is already inactive",
        )

    host.is_active = False
    await db.commit()

    return {"message": "Host account deactivated successfully"}


@router.put("/admin/hosts/{host_id}/activate")
async def activate_host(
    host_id: int,
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Activate a host account"""
    stmt = select(Host).filter(Host.id == host_id)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()

    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Host not found"
        )

    if host.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Host account is already active",
        )

    host.is_active = True
    await db.commit()

    return {"message": "Host account activated successfully"}


@router.delete("/admin/hosts/{host_id}")
async def delete_host(
    host_id: int,
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
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
            status_code=status.HTTP_404_NOT_FOUND, detail="Host not found"
        )

    # Get counts for response
    cars_count_stmt = select(func.count(Car.id)).filter(Car.host_id == host.id)
    cars_count_result = await db.execute(cars_count_stmt)
    cars_count = cars_count_result.scalar() or 0

    pm_count_stmt = select(func.count(PaymentMethod.id)).filter(
        PaymentMethod.host_id == host.id
    )
    pm_count_result = await db.execute(pm_count_stmt)
    payment_methods_count = pm_count_result.scalar() or 0

    fb_count_stmt = select(func.count(Feedback.id)).filter(Feedback.host_id == host.id)
    fb_count_result = await db.execute(fb_count_stmt)
    feedbacks_count = fb_count_result.scalar() or 0

    # Delete all cars (cascade should handle payment methods and feedbacks)
    await db.execute(delete(Car).filter(Car.host_id == host.id))

    # Delete the host
    await db.delete(host)
    await db.commit()

    return {
        "message": "Host account deleted successfully",
        "deleted_data": {
            "cars": cars_count,
            "payment_methods": payment_methods_count,
            "feedbacks": feedbacks_count,
        },
    }


@router.get("/admin/hosts/{host_id}/cars", response_model=List[CarResponse])
async def get_host_cars(
    host_id: int,
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get all cars owned by a specific host"""
    stmt = select(Host).filter(Host.id == host_id)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()

    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Host not found"
        )

    car_stmt = select(Car).filter(Car.host_id == host_id)
    car_result = await db.execute(car_stmt)
    cars = car_result.scalars().all()
    return [_car_to_response(car) for car in cars]


@router.get(
    "/admin/hosts/{host_id}/payment-methods", response_model=PaymentMethodListResponse
)
async def get_host_payment_methods(
    host_id: int,
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get all payment methods for a specific host"""
    stmt = select(Host).filter(Host.id == host_id)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()

    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Host not found"
        )

    pm_stmt = (
        select(PaymentMethod)
        .filter(PaymentMethod.host_id == host_id)
        .order_by(PaymentMethod.is_default.desc(), PaymentMethod.created_at.desc())
    )
    pm_result = await db.execute(pm_stmt)
    payment_methods = pm_result.scalars().all()

    return PaymentMethodListResponse(payment_methods=payment_methods)


@router.get("/admin/hosts/{host_id}/feedback", response_model=FeedbackListResponse)
async def get_host_feedback(
    host_id: int,
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get all feedback for a specific host"""
    stmt = select(Host).filter(Host.id == host_id)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()

    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Host not found"
        )

    fb_stmt = (
        select(Feedback)
        .filter(Feedback.host_id == host_id)
        .order_by(Feedback.created_at.desc())
    )
    fb_result = await db.execute(fb_stmt)
    feedbacks = fb_result.scalars().all()

    return FeedbackListResponse(feedbacks=feedbacks)


# ==================== CLIENT MANAGEMENT ====================


@router.get("/admin/clients", response_model=PaginatedClientListResponse)
async def list_clients(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by name or email"),
    sort_by: Optional[str] = Query(
        "created_at", description="Sort field (id, full_name, email, created_at)"
    ),
    order: Optional[str] = Query(
        "desc", regex="^(asc|desc)$", description="Sort order"
    ),
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
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
            Client.full_name.ilike(f"%{search}%"), Client.email.ilike(f"%{search}%")
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
            created_at=client.created_at,
        )
        for client in clients
    ]

    pagination = calculate_pagination(page, limit, total)

    return PaginatedClientListResponse(clients=client_list, **pagination)


@router.get("/admin/clients/{client_id}", response_model=ClientDetailResponse)
async def get_client_details(
    client_id: int,
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed information about a specific client"""
    stmt = select(Client).filter(Client.id == client_id)
    result = await db.execute(stmt)
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
        )

    return client


@router.put("/admin/clients/{client_id}", response_model=ClientDetailResponse)
async def update_client(
    client_id: int,
    request: ClientUpdateRequest,
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
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
            status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
        )

    # Check if email is being changed and if it's already taken
    if request.email and request.email != client.email:
        existing_stmt = select(Client).filter(Client.email == request.email)
        existing_result = await db.execute(existing_stmt)
        existing_client = existing_result.scalar_one_or_none()
        if existing_client:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
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
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a client account (soft delete)"""
    stmt = select(Client).filter(Client.id == client_id)
    result = await db.execute(stmt)
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
        )

    if not client.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Client account is already inactive",
        )

    client.is_active = False
    await db.commit()

    return {"message": "Client account deactivated successfully"}


@router.put("/admin/clients/{client_id}/activate")
async def activate_client(
    client_id: int,
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Activate a client account"""
    stmt = select(Client).filter(Client.id == client_id)
    result = await db.execute(stmt)
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
        )

    if client.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Client account is already active",
        )

    client.is_active = True
    await db.commit()

    return {"message": "Client account activated successfully"}


@router.delete("/admin/clients/{client_id}")
async def delete_client(
    client_id: int,
    current_admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
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
            status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
        )

    await db.delete(client)
    await db.commit()

    return {"message": "Client account deleted successfully"}
