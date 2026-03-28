from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.security import get_admin_by_email, get_password_hash, verify_password
from app.db.session import get_db
from app.models import Admin
from app.schemas import (
    AdminCreateRequest,
    AdminDetailResponse,
    AdminListResponse,
    AdminOwnPasswordChangeRequest,
    AdminOwnProfileUpdateRequest,
    AdminPasswordChangeRequest,
    AdminProfileResponse,
    AdminUpdateRequest,
    PaginatedAdminListResponse,
)

router = APIRouter()


def require_super_admin(current_admin: Admin = Depends(get_current_admin)) -> Admin:
    """Dependency to ensure current admin is super_admin"""
    if current_admin.role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This operation requires super_admin privileges",
        )
    return current_admin


# Helper function for pagination
def calculate_pagination(page: int, limit: int, total: int) -> dict:
    """Calculate pagination metadata"""
    total_pages = (total + limit - 1) // limit if limit > 0 else 0
    return {"total": total, "page": page, "limit": limit, "total_pages": total_pages}


@router.get("/admin/admins", response_model=PaginatedAdminListResponse)
async def list_admins(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    role: Optional[str] = Query(None, description="Filter by role"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(None, description="Search by name or email"),
    sort_by: Optional[str] = Query(
        "created_at", description="Sort field (id, created_at, full_name, email)"
    ),
    order: Optional[str] = Query(
        "desc", pattern="^(asc|desc)$", description="Sort order"
    ),
    current_admin: Admin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    List all admins (super_admin only)

    - **page**: Page number (starts from 1)
    - **limit**: Number of items per page (1-100)
    - **role**: Filter by role (super_admin, admin, moderator)
    - **is_active**: Filter by active status
    - **search**: Search by name or email
    - **sort_by**: Field to sort by
    - **order**: Sort order (asc or desc)
    """
    # Build query
    stmt = select(Admin)

    # Apply filters
    if role:
        stmt = stmt.filter(Admin.role == role)

    if is_active is not None:
        stmt = stmt.filter(Admin.is_active == is_active)

    if search:
        search_pattern = f"%{search}%"
        stmt = stmt.filter(
            or_(
                Admin.full_name.ilike(search_pattern), Admin.email.ilike(search_pattern)
            )
        )

    # Get total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # Apply sorting
    sort_field = getattr(Admin, sort_by, Admin.created_at)
    if order == "asc":
        stmt = stmt.order_by(sort_field.asc())
    else:
        stmt = stmt.order_by(sort_field.desc())

    # Apply pagination
    skip = (page - 1) * limit
    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    admins = result.scalars().all()

    # Build response
    admin_list = [
        AdminListResponse(
            id=admin.id,
            full_name=admin.full_name,
            email=admin.email,
            role=admin.role,
            is_active=admin.is_active,
            created_at=admin.created_at,
            updated_at=admin.updated_at,
        )
        for admin in admins
    ]

    pagination = calculate_pagination(page, limit, total)

    return PaginatedAdminListResponse(admins=admin_list, **pagination)


@router.get("/admin/admins/{admin_id}", response_model=AdminDetailResponse)
async def get_admin_details(
    admin_id: int,
    current_admin: Admin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed information about a specific admin (super_admin only)"""
    stmt = select(Admin).filter(Admin.id == admin_id)
    result = await db.execute(stmt)
    admin = result.scalars().first()

    if not admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found"
        )

    return AdminDetailResponse(
        id=admin.id,
        full_name=admin.full_name,
        email=admin.email,
        role=admin.role,
        is_active=admin.is_active,
        created_at=admin.created_at,
        updated_at=admin.updated_at,
    )


@router.post(
    "/admin/admins",
    response_model=AdminDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin(
    request: AdminCreateRequest,
    current_admin: Admin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new admin account (super_admin only)

    - Cannot create super_admin via API (only via startup script)
    - Role must be 'admin' or 'moderator'
    """
    # Check if email already exists
    existing_admin = await get_admin_by_email(db, request.email)
    if existing_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    # Create new admin
    new_admin = Admin(
        full_name=request.full_name,
        email=request.email,
        hashed_password=get_password_hash(request.password),
        role=request.role,
        is_active=request.is_active,
    )

    db.add(new_admin)
    await db.commit()
    await db.refresh(new_admin)

    return AdminDetailResponse(
        id=new_admin.id,
        full_name=new_admin.full_name,
        email=new_admin.email,
        role=new_admin.role,
        is_active=new_admin.is_active,
        created_at=new_admin.created_at,
        updated_at=new_admin.updated_at,
    )


@router.put("/admin/admins/{admin_id}", response_model=AdminDetailResponse)
async def update_admin(
    admin_id: int,
    request: AdminUpdateRequest,
    current_admin: Admin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Update admin profile (super_admin only)

    - Cannot update super_admin role
    - Cannot deactivate super_admin
    """
    stmt = select(Admin).filter(Admin.id == admin_id)
    result = await db.execute(stmt)
    admin = result.scalars().first()

    if not admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found"
        )

    # Prevent modifying super_admin
    if admin.role == "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify super_admin account",
        )

    # Update fields
    if request.full_name is not None:
        admin.full_name = request.full_name

    if request.email is not None:
        # Check if email is already taken by another admin
        existing_admin = await get_admin_by_email(db, request.email)
        if existing_admin and existing_admin.id != admin_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )
        admin.email = request.email

    if request.role is not None:
        admin.role = request.role

    if request.is_active is not None:
        admin.is_active = request.is_active

    await db.commit()
    await db.refresh(admin)

    return AdminDetailResponse(
        id=admin.id,
        full_name=admin.full_name,
        email=admin.email,
        role=admin.role,
        is_active=admin.is_active,
        created_at=admin.created_at,
        updated_at=admin.updated_at,
    )


@router.put("/admin/admins/{admin_id}/password")
async def change_admin_password(
    admin_id: int,
    request: AdminPasswordChangeRequest,
    current_admin: Admin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Change another admin's password (super_admin only)

    - Cannot change super_admin password (use own password change endpoint)
    """
    stmt = select(Admin).filter(Admin.id == admin_id)
    result = await db.execute(stmt)
    admin = result.scalars().first()

    if not admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found"
        )

    # Prevent changing super_admin password
    if admin.role == "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot change super_admin password via this endpoint",
        )

    # Update password
    admin.hashed_password = get_password_hash(request.new_password)
    await db.commit()

    return {"message": "Password changed successfully"}


@router.put("/admin/admins/{admin_id}/deactivate")
async def deactivate_admin(
    admin_id: int,
    current_admin: Admin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate an admin account (super_admin only)"""
    stmt = select(Admin).filter(Admin.id == admin_id)
    result = await db.execute(stmt)
    admin = result.scalars().first()

    if not admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found"
        )

    # Prevent deactivating super_admin
    if admin.role == "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot deactivate super_admin account",
        )

    # Prevent deactivating self
    if admin.id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account",
        )

    if not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin account is already inactive",
        )

    admin.is_active = False
    await db.commit()

    return {"message": "Admin account deactivated successfully"}


@router.put("/admin/admins/{admin_id}/activate")
async def activate_admin(
    admin_id: int,
    current_admin: Admin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Activate an admin account (super_admin only)"""
    stmt = select(Admin).filter(Admin.id == admin_id)
    result = await db.execute(stmt)
    admin = result.scalars().first()

    if not admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found"
        )

    if admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin account is already active",
        )

    admin.is_active = True
    await db.commit()

    return {"message": "Admin account activated successfully"}


@router.delete("/admin/admins/{admin_id}")
async def delete_admin(
    admin_id: int,
    current_admin: Admin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete an admin account (super_admin only)

    - Cannot delete super_admin
    - Cannot delete self
    """
    stmt = select(Admin).filter(Admin.id == admin_id)
    result = await db.execute(stmt)
    admin = result.scalars().first()

    if not admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found"
        )

    # Prevent deleting super_admin
    if admin.role == "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete super_admin account",
        )

    # Prevent deleting self
    if admin.id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    await db.delete(admin)
    await db.commit()

    return {"message": "Admin account deleted successfully"}


# Admin Profile Management (Own Profile)
@router.put("/admin/profile", response_model=AdminProfileResponse)
async def update_own_profile(
    request: AdminOwnProfileUpdateRequest,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Update own admin profile

    - Any admin can update their own profile
    - Cannot change role or is_active status
    """
    # Update fields
    if request.full_name is not None:
        current_admin.full_name = request.full_name

    if request.email is not None:
        # Check if email is already taken by another admin
        existing_admin = await get_admin_by_email(db, request.email)
        if existing_admin and existing_admin.id != current_admin.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )
        current_admin.email = request.email

    await db.commit()
    await db.refresh(current_admin)

    return AdminProfileResponse(
        id=current_admin.id,
        full_name=current_admin.full_name,
        email=current_admin.email,
        role=current_admin.role,
        is_active=current_admin.is_active,
        created_at=current_admin.created_at,
        updated_at=current_admin.updated_at,
    )


@router.put("/admin/change-password")
async def change_own_password(
    request: AdminOwnPasswordChangeRequest,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Change own password

    - Requires current password verification
    - Any admin can change their own password
    """
    # Verify current password
    if not verify_password(request.current_password, current_admin.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    # Update password
    current_admin.hashed_password = get_password_hash(request.new_password)
    await db.commit()

    return {"message": "Password changed successfully"}
