from typing import Optional, List, Dict, Any, Set
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_, func, select

from app.database import get_db
from app.models import Car, Host, VerificationStatus
from app.schemas import (
    CarDetailResponse,
    AdminCarListResponse,
    CarStatusUpdateRequest,
    BulkCarStatusUpdateRequest,
    CarRejectRequest,
    CarUpdateRequest,
    PaginatedCarListResponse,
    CarResponse
)
from app.auth import get_current_admin
from app.routers.cars import _car_to_response
from app.storage import (
    BUCKETS,
    SUPABASE_CLIENT_INIT_ERROR,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
    build_public_storage_object_url,
    collect_storage_file_paths_http,
    supabase,
)
import json

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


def _parse_features(features_str: Optional[str]) -> Optional[List[str]]:
    """Parse features JSON string to list"""
    if not features_str:
        return None
    try:
        return json.loads(features_str)
    except:
        return None


def _normalize_public_url(raw_url: Any) -> Optional[str]:
    """Normalize Supabase get_public_url return shape across SDK versions."""
    if isinstance(raw_url, str):
        return raw_url
    if hasattr(raw_url, "public_url"):
        return getattr(raw_url, "public_url")
    if hasattr(raw_url, "publicUrl"):
        return getattr(raw_url, "publicUrl")
    if hasattr(raw_url, "data"):
        data = getattr(raw_url, "data")
        if isinstance(data, dict):
            return data.get("publicUrl") or data.get("public_url")
        if hasattr(data, "publicUrl"):
            return getattr(data, "publicUrl")
        if hasattr(data, "public_url"):
            return getattr(data, "public_url")
    if isinstance(raw_url, dict):
        if "publicUrl" in raw_url:
            return raw_url.get("publicUrl")
        if "public_url" in raw_url:
            return raw_url.get("public_url")
        data = raw_url.get("data")
        if isinstance(data, dict):
            return data.get("publicUrl") or data.get("public_url")
    return None


def _extract_legacy_image_urls(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [u for u in parsed if isinstance(u, str)]
        if isinstance(parsed, dict):
            # Handle shapes like {"image_urls":[...]} or {"urls":[...]}
            for key in ("image_urls", "images", "urls", "photos"):
                value = parsed.get(key)
                if isinstance(value, list):
                    return [u for u in value if isinstance(u, str)]
            return []
        if isinstance(parsed, str):
            return [parsed]
    except Exception:
        # Fallback for non-JSON formats (single URL or comma-separated URLs)
        if "," in raw:
            return [u.strip() for u in raw.split(",") if u.strip()]
        if raw.startswith("http://") or raw.startswith("https://"):
            return [raw]
    return []


def _collect_storage_files_recursive(bucket_name: str, base_path: str, max_depth: int = 4) -> List[str]:
    """
    Recursively collect file paths under a base path in Supabase storage.
    """
    if supabase is None:
        return []

    results: List[str] = []
    visited: Set[str] = set()

    known_exts = {
        ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".svg",
        ".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v"
    }

    def _looks_like_file(entry: Dict[str, Any]) -> bool:
        name = (entry.get("name") or "").lower()
        if not name:
            return False
        if "." in name and any(name.endswith(ext) for ext in known_exts):
            return True
        if entry.get("metadata") is not None:
            return True
        if entry.get("id") is not None:
            return True
        return False

    def walk(path: str, depth: int) -> None:
        if depth > max_depth or path in visited:
            return
        visited.add(path)

        try:
            entries = supabase.storage.from_(bucket_name).list(
                path,
                {"limit": 200, "sortBy": {"column": "created_at", "order": "asc"}}
            ) or []
        except Exception:
            return

        for entry in entries:
            name = entry.get("name")
            if not name:
                continue
            child_path = f"{path}/{name}"
            if _looks_like_file(entry):
                results.append(child_path)
            else:
                walk(child_path, depth + 1)

    walk(base_path, 0)
    return results


# ==================== CAR LIST & DETAILS ====================

@router.get("/admin/cars", response_model=PaginatedCarListResponse)
async def list_cars(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by verification status (awaiting/verified/denied)"),
    host_id: Optional[int] = Query(None, description="Filter by host ID"),
    search: Optional[str] = Query(None, description="Search by car name or model"),
    sort_by: Optional[str] = Query("created_at", description="Sort field (id, name, model, year, created_at)"),
    order: Optional[str] = Query("desc", regex="^(asc|desc)$", description="Sort order"),
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    List all cars with pagination, filtering, and search
    
    - **page**: Page number (starts from 1)
    - **limit**: Number of items per page (1-100)
    - **status**: Filter by verification status
    - **host_id**: Filter by host ID
    - **search**: Search by car name or model (partial match)
    - **sort_by**: Field to sort by
    - **order**: Sort order (asc or desc)
    """
    # Build base statement
    stmt = select(Car).options(joinedload(Car.host))
    
    # Apply filters
    if status:
        try:
            status_enum = VerificationStatus(status.lower())
            stmt = stmt.filter(Car.verification_status == status_enum.value)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Must be one of: {', '.join([s.value for s in VerificationStatus])}"
            )
    
    if host_id:
        stmt = stmt.filter(Car.host_id == host_id)
    
    if search:
        search_filter = or_(
            Car.name.ilike(f"%{search}%"),
            Car.model.ilike(f"%{search}%")
        )
        stmt = stmt.filter(search_filter)
    
    # Get total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0
    
    # Apply sorting
    sort_field = getattr(Car, sort_by, Car.created_at)
    if order == "asc":
        stmt = stmt.order_by(sort_field.asc())
    else:
        stmt = stmt.order_by(sort_field.desc())
    
    # Apply pagination
    skip = (page - 1) * limit
    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    cars = result.scalars().unique().all()
    
    # Build response
    car_list = []
    for car in cars:
        car_list.append(AdminCarListResponse(
            id=car.id,
            host_id=car.host_id,
            host_name=car.host.full_name,
            name=car.name,
            model=car.model,
            year=car.year,
            verification_status=VerificationStatus(car.verification_status),
            is_hidden=car.is_hidden,
            created_at=car.created_at
        ))
    
    pagination = calculate_pagination(page, limit, total)
    
    return PaginatedCarListResponse(
        cars=car_list,
        **pagination
    )



@router.get("/admin/cars/awaiting", response_model=PaginatedCarListResponse)
async def get_cars_awaiting_verification(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get cars awaiting verification"""
    stmt = select(Car).options(joinedload(Car.host)).filter(
        Car.verification_status == VerificationStatus.AWAITING.value
    )
    
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0
    
    skip = (page - 1) * limit
    stmt = stmt.order_by(Car.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    cars = result.scalars().unique().all()
    
    car_list = [
        AdminCarListResponse(
            id=car.id,
            host_id=car.host_id,
            host_name=car.host.full_name,
            name=car.name,
            model=car.model,
            year=car.year,
            verification_status=VerificationStatus(car.verification_status),
            is_hidden=car.is_hidden,
            created_at=car.created_at
        )
        for car in cars
    ]
    pagination = calculate_pagination(page, limit, total)
    return PaginatedCarListResponse(cars=car_list, **pagination)

@router.get("/admin/cars/verified", response_model=PaginatedCarListResponse)
async def get_verified_cars(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get verified cars"""
    stmt = select(Car).options(joinedload(Car.host)).filter(
        Car.verification_status == VerificationStatus.VERIFIED.value
    )
    
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0
    
    skip = (page - 1) * limit
    stmt = stmt.order_by(Car.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    cars = result.scalars().unique().all()
    
    car_list = [
        AdminCarListResponse(
            id=car.id,
            host_id=car.host_id,
            host_name=car.host.full_name,
            name=car.name,
            model=car.model,
            year=car.year,
            verification_status=VerificationStatus(car.verification_status),
            is_hidden=car.is_hidden,
            created_at=car.created_at
        )
        for car in cars
    ]
    pagination = calculate_pagination(page, limit, total)
    return PaginatedCarListResponse(cars=car_list, **pagination)

@router.get("/admin/cars/rejected", response_model=PaginatedCarListResponse)
async def get_rejected_cars(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get rejected cars"""
    stmt = select(Car).options(joinedload(Car.host)).filter(
        Car.verification_status == VerificationStatus.DENIED.value
    )
    
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0
    
    skip = (page - 1) * limit
    stmt = stmt.order_by(Car.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    cars = result.scalars().unique().all()
    
    car_list = [
        AdminCarListResponse(
            id=car.id,
            host_id=car.host_id,
            host_name=car.host.full_name,
            name=car.name,
            model=car.model,
            year=car.year,
            verification_status=VerificationStatus(car.verification_status),
            is_hidden=car.is_hidden,
            created_at=car.created_at
        )
        for car in cars
    ]
    pagination = calculate_pagination(page, limit, total)
    return PaginatedCarListResponse(cars=car_list, **pagination)

@router.get("/admin/cars/{car_id}", response_model=CarDetailResponse)
async def get_car_details(
    car_id: int,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed information about a specific car including host information"""
    stmt = select(Car).options(joinedload(Car.host)).filter(Car.id == car_id)
    result = await db.execute(stmt)
    car = result.scalar_one_or_none()
    
    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found"
        )
    return CarDetailResponse(
        id=car.id,
        host_id=car.host_id,
        host_name=car.host.full_name,
        host_email=car.host.email,
        name=car.name,
        model=car.model,
        body_type=car.body_type,
        year=car.year,
        description=car.description,
        seats=car.seats,
        fuel_type=car.fuel_type,
        transmission=car.transmission,
        color=car.color,
        mileage=car.mileage,
        features=_parse_features(car.features),
        daily_rate=car.daily_rate,
        weekly_rate=car.weekly_rate,
        monthly_rate=car.monthly_rate,
        min_rental_days=car.min_rental_days,
        max_rental_days=car.max_rental_days,
        min_age_requirement=car.min_age_requirement,
        rules=car.rules,
        location_name=car.location_name,
        latitude=car.latitude,
        longitude=car.longitude,
        is_complete=car.is_complete,
        verification_status=VerificationStatus(car.verification_status),
        rejection_reason=car.rejection_reason,
        is_hidden=car.is_hidden,
        created_at=car.created_at,
        updated_at=car.updated_at
    )


@router.get("/admin/cars/{car_id}/media")
async def get_car_media(
    car_id: int,
    current_admin=Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Return car media URLs for admin review.

    Tries Supabase folder structures first, then falls back to legacy DB URLs.
    """
    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found"
        )

    image_urls: List[str] = []
    video_urls: List[str] = []
    checked_folders: List[str] = []
    debug_files_found: Dict[str, List[str]] = {}
    debug_errors: Dict[str, str] = {}
    source_counts = {
        "storage_images": 0,
        "storage_videos": 0,
        "db_image_urls": 0,
        "db_cover_image": 0,
        "db_video_url": 0,
    }
    image_exts = (".jpg", ".jpeg", ".png", ".webp")
    video_exts = (".mp4", ".mov", ".webm", ".avi", ".mkv")

    bucket_name = BUCKETS["vehicle_media"]
    use_sdk = supabase is not None
    use_http = (not use_sdk) and bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)
    listing_mode = "sdk" if use_sdk else ("http" if use_http else "none")

    if listing_mode != "none":
        # car_{id} matches current mobile / Supabase dashboard layout (e.g. car_20/)
        folder_candidates = [
            f"car_{car.id}",
            f"car_{car.id}/images",
            f"car_{car.id}/videos",
            f"user_{car.host_id}/car_{car.id}",
            f"user_{car.host_id}/car_{car.id}/images",
            f"user_{car.host_id}/car_{car.id}/videos",
            f"{car.host_id}/vehicles/{car.id}",
            f"{car.host_id}/vehicles/{car.id}/images",
            f"{car.host_id}/vehicles/{car.id}/videos",
        ]
        seen = set()

        for folder in folder_candidates:
            if folder in seen:
                continue
            seen.add(folder)
            checked_folders.append(folder)
            try:
                if use_sdk:
                    collected_paths = _collect_storage_files_recursive(bucket_name, folder)
                else:
                    collected_paths = collect_storage_file_paths_http(bucket_name, folder)
            except Exception as exc:
                collected_paths = []
                debug_errors[folder] = str(exc)
            debug_files_found[folder] = collected_paths

            for full_path in collected_paths:
                filename = full_path.rsplit("/", 1)[-1].lower()
                if not filename:
                    continue
                if use_sdk:
                    public_url = _normalize_public_url(
                        supabase.storage.from_(bucket_name).get_public_url(full_path)
                    )
                else:
                    public_url = build_public_storage_object_url(bucket_name, full_path)
                if not public_url:
                    debug_errors[full_path] = "Failed to build public URL"
                    continue

                if filename.startswith("image_") and filename.endswith(image_exts):
                    image_urls.append(public_url)
                    source_counts["storage_images"] += 1
                elif filename.endswith(image_exts):
                    image_urls.append(public_url)
                    source_counts["storage_images"] += 1
                elif filename.endswith(video_exts):
                    video_urls.append(public_url)
                    source_counts["storage_videos"] += 1

    # Fallback to legacy DB-stored URLs if storage listing is unavailable/empty.
    legacy_images = _extract_legacy_image_urls(car.image_urls)
    image_urls.extend(legacy_images)
    source_counts["db_image_urls"] = len(legacy_images)
    if car.cover_image:
        image_urls.append(car.cover_image)
        source_counts["db_cover_image"] = 1
    if car.video_url:
        video_urls.append(car.video_url)
        source_counts["db_video_url"] = 1

    # Preserve order while removing duplicates.
    image_urls_before_dedupe = len(image_urls)
    video_urls_before_dedupe = len(video_urls)
    image_urls = list(dict.fromkeys([u for u in image_urls if isinstance(u, str) and u.strip()]))
    video_urls = list(dict.fromkeys([u for u in video_urls if isinstance(u, str) and u.strip()]))

    return {
        "car_id": car.id,
        "host_id": car.host_id,
        "folder_paths": checked_folders,
        "cover_image_url": image_urls[0] if image_urls else None,
        "image_urls": image_urls,
        "video_urls": video_urls,
        "debug": {
            "bucket": BUCKETS["vehicle_media"],
            "listing_mode": listing_mode,
            "supabase_url_configured": bool(SUPABASE_URL),
            "supabase_service_role_configured": bool(SUPABASE_SERVICE_ROLE_KEY),
            "supabase_client_initialized": supabase is not None,
            "supabase_init_error": SUPABASE_CLIENT_INIT_ERROR,
            "source_counts": source_counts,
            "checked_folders": checked_folders,
            "files_found_by_folder": debug_files_found,
            "errors": debug_errors,
            "image_count_before_dedupe": image_urls_before_dedupe,
            "image_count_after_dedupe": len(image_urls),
            "video_count_before_dedupe": video_urls_before_dedupe,
            "video_count_after_dedupe": len(video_urls),
        },
    }


# ==================== CAR VERIFICATION STATUS ====================

@router.put("/admin/cars/{car_id}/status", response_model=CarDetailResponse)
async def update_car_status(
    car_id: int,
    request: CarStatusUpdateRequest,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Update car verification status
    
    - **verification_status**: New status (awaiting/verified/denied)
    - **rejection_reason**: Required if status is "denied"
    """
    stmt = select(Car).filter(Car.id == car_id)
    result = await db.execute(stmt)
    car = result.scalar_one_or_none()
    
    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found"
        )
    
    car.verification_status = request.verification_status.value
    
    if request.verification_status == VerificationStatus.DENIED:
        car.rejection_reason = request.rejection_reason
    else:
        # Clear rejection reason if status is not denied
        car.rejection_reason = None
    
    await db.commit()
    await db.refresh(car)
    
    # Reload with host info
    stmt = select(Car).options(joinedload(Car.host)).filter(Car.id == car_id)
    result = await db.execute(stmt)
    car = result.scalar_one_or_none()
    
    return CarDetailResponse(
        id=car.id,
        host_id=car.host_id,
        host_name=car.host.full_name,
        host_email=car.host.email,
        name=car.name,
        model=car.model,
        body_type=car.body_type,
        year=car.year,
        description=car.description,
        seats=car.seats,
        fuel_type=car.fuel_type,
        transmission=car.transmission,
        color=car.color,
        mileage=car.mileage,
        features=_parse_features(car.features),
        daily_rate=car.daily_rate,
        weekly_rate=car.weekly_rate,
        monthly_rate=car.monthly_rate,
        min_rental_days=car.min_rental_days,
        max_rental_days=car.max_rental_days,
        min_age_requirement=car.min_age_requirement,
        rules=car.rules,
        location_name=car.location_name,
        latitude=car.latitude,
        longitude=car.longitude,
        is_complete=car.is_complete,
        verification_status=VerificationStatus(car.verification_status),
        rejection_reason=car.rejection_reason,
        is_hidden=car.is_hidden,
        created_at=car.created_at,
        updated_at=car.updated_at
    )


@router.put("/admin/cars/bulk-status")
async def bulk_update_car_status(
    request: BulkCarStatusUpdateRequest,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Bulk update verification status for multiple cars
    
    - **car_ids**: List of car IDs to update
    - **verification_status**: New status (awaiting/verified/denied)
    - **rejection_reason**: Required if status is "denied"
    """
    # Verify all cars exist
    stmt = select(Car).filter(Car.id.in_(request.car_ids))
    result = await db.execute(stmt)
    cars = result.scalars().all()
    
    if len(cars) != len(request.car_ids):
        found_ids = {car.id for car in cars}
        missing_ids = set(request.car_ids) - found_ids
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cars not found: {list(missing_ids)}"
        )
    
    # Update all cars
    updated_count = 0
    for car in cars:
        car.verification_status = request.verification_status.value
        if request.verification_status == VerificationStatus.DENIED:
            car.rejection_reason = request.rejection_reason
        else:
            car.rejection_reason = None
        updated_count += 1
    
    await db.commit()
    
    return {
        "message": f"Successfully updated {updated_count} car(s)",
        "updated_count": updated_count,
        "verification_status": request.verification_status.value
    }


@router.put("/admin/cars/{car_id}/approve", response_model=CarDetailResponse)
async def approve_car(
    car_id: int,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Approve a car (set status to verified)"""
    stmt = select(Car).filter(Car.id == car_id)
    result = await db.execute(stmt)
    car = result.scalar_one_or_none()
    
    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found"
        )
    
    car.verification_status = VerificationStatus.VERIFIED.value
    car.rejection_reason = None
    
    await db.commit()
    await db.refresh(car)
    
    # Reload with host info
    stmt = select(Car).options(joinedload(Car.host)).filter(Car.id == car_id)
    result = await db.execute(stmt)
    car = result.scalar_one_or_none()
    
    return CarDetailResponse(
        id=car.id,
        host_id=car.host_id,
        host_name=car.host.full_name,
        host_email=car.host.email,
        name=car.name,
        model=car.model,
        body_type=car.body_type,
        year=car.year,
        description=car.description,
        seats=car.seats,
        fuel_type=car.fuel_type,
        transmission=car.transmission,
        color=car.color,
        mileage=car.mileage,
        features=_parse_features(car.features),
        daily_rate=car.daily_rate,
        weekly_rate=car.weekly_rate,
        monthly_rate=car.monthly_rate,
        min_rental_days=car.min_rental_days,
        max_rental_days=car.max_rental_days,
        min_age_requirement=car.min_age_requirement,
        rules=car.rules,
        location_name=car.location_name,
        latitude=car.latitude,
        longitude=car.longitude,
        is_complete=car.is_complete,
        verification_status=VerificationStatus(car.verification_status),
        rejection_reason=car.rejection_reason,
        is_hidden=car.is_hidden,
        created_at=car.created_at,
        updated_at=car.updated_at
    )


@router.put("/admin/cars/{car_id}/reject", response_model=CarDetailResponse)
async def reject_car(
    car_id: int,
    request: CarRejectRequest,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Reject a car (set status to denied with rejection reason)"""
    stmt = select(Car).filter(Car.id == car_id)
    result = await db.execute(stmt)
    car = result.scalar_one_or_none()
    
    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found"
        )
    
    car.verification_status = VerificationStatus.DENIED.value
    car.rejection_reason = request.rejection_reason
    
    await db.commit()
    await db.refresh(car)
    
    # Reload with host info
    stmt = select(Car).options(joinedload(Car.host)).filter(Car.id == car_id)
    result = await db.execute(stmt)
    car = result.scalar_one_or_none()
    
    return CarDetailResponse(
        id=car.id,
        host_id=car.host_id,
        host_name=car.host.full_name,
        host_email=car.host.email,
        name=car.name,
        model=car.model,
        body_type=car.body_type,
        year=car.year,
        description=car.description,
        seats=car.seats,
        fuel_type=car.fuel_type,
        transmission=car.transmission,
        color=car.color,
        mileage=car.mileage,
        features=_parse_features(car.features),
        daily_rate=car.daily_rate,
        weekly_rate=car.weekly_rate,
        monthly_rate=car.monthly_rate,
        min_rental_days=car.min_rental_days,
        max_rental_days=car.max_rental_days,
        min_age_requirement=car.min_age_requirement,
        rules=car.rules,
        location_name=car.location_name,
        latitude=car.latitude,
        longitude=car.longitude,
        is_complete=car.is_complete,
        verification_status=VerificationStatus(car.verification_status),
        rejection_reason=car.rejection_reason,
        is_hidden=car.is_hidden,
        created_at=car.created_at,
        updated_at=car.updated_at
    )


# ==================== CAR CONTENT MANAGEMENT ====================

@router.put("/admin/cars/{car_id}", response_model=CarDetailResponse)
async def update_car(
    car_id: int,
    request: CarUpdateRequest,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Update car details (admin can edit any field)
    
    Only provided fields will be updated.
    """
    stmt = select(Car).filter(Car.id == car_id)
    result = await db.execute(stmt)
    car = result.scalar_one_or_none()
    
    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found"
        )
    
    # Update fields if provided
    if request.name is not None:
        car.name = request.name
    if request.model is not None:
        car.model = request.model
    if request.body_type is not None:
        car.body_type = request.body_type
    if request.year is not None:
        car.year = request.year
    if request.description is not None:
        car.description = request.description
    if request.seats is not None:
        car.seats = request.seats
    if request.fuel_type is not None:
        car.fuel_type = request.fuel_type
    if request.transmission is not None:
        car.transmission = request.transmission
    if request.color is not None:
        car.color = request.color
    if request.mileage is not None:
        car.mileage = request.mileage
    if request.features is not None:
        car.features = json.dumps(request.features) if request.features else None
    if request.daily_rate is not None:
        car.daily_rate = request.daily_rate
    if request.weekly_rate is not None:
        car.weekly_rate = request.weekly_rate
    if request.monthly_rate is not None:
        car.monthly_rate = request.monthly_rate
    if request.min_rental_days is not None:
        car.min_rental_days = request.min_rental_days
    if request.max_rental_days is not None:
        car.max_rental_days = request.max_rental_days
    if request.min_age_requirement is not None:
        car.min_age_requirement = request.min_age_requirement
    if request.rules is not None:
        car.rules = request.rules
    if request.location_name is not None:
        car.location_name = request.location_name
    if request.latitude is not None:
        car.latitude = request.latitude
    if request.longitude is not None:
        car.longitude = request.longitude
    
    await db.commit()
    await db.refresh(car)
    
    # Reload with host info
    stmt = select(Car).options(joinedload(Car.host)).filter(Car.id == car_id)
    result = await db.execute(stmt)
    car = result.scalar_one_or_none()
    
    return CarDetailResponse(
        id=car.id,
        host_id=car.host_id,
        host_name=car.host.full_name,
        host_email=car.host.email,
        name=car.name,
        model=car.model,
        body_type=car.body_type,
        year=car.year,
        description=car.description,
        seats=car.seats,
        fuel_type=car.fuel_type,
        transmission=car.transmission,
        color=car.color,
        mileage=car.mileage,
        features=_parse_features(car.features),
        daily_rate=car.daily_rate,
        weekly_rate=car.weekly_rate,
        monthly_rate=car.monthly_rate,
        min_rental_days=car.min_rental_days,
        max_rental_days=car.max_rental_days,
        min_age_requirement=car.min_age_requirement,
        rules=car.rules,
        location_name=car.location_name,
        latitude=car.latitude,
        longitude=car.longitude,
        is_complete=car.is_complete,
        verification_status=VerificationStatus(car.verification_status),
        rejection_reason=car.rejection_reason,
        is_hidden=car.is_hidden,
        created_at=car.created_at,
        updated_at=car.updated_at
    )


@router.delete("/admin/cars/{car_id}")
async def delete_car(
    car_id: int,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Permanently delete a car listing"""
    stmt = select(Car).filter(Car.id == car_id)
    result = await db.execute(stmt)
    car = result.scalar_one_or_none()
    
    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found"
        )
    
    await db.delete(car)
    await db.commit()
    
    return {"message": "Car deleted successfully"}


@router.put("/admin/cars/{car_id}/hide")
async def hide_car(
    car_id: int,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Hide car from public listing"""
    stmt = select(Car).filter(Car.id == car_id)
    result = await db.execute(stmt)
    car = result.scalar_one_or_none()
    
    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found"
        )
    
    if car.is_hidden:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Car is already hidden"
        )
    
    car.is_hidden = True
    await db.commit()
    
    return {"message": "Car hidden from public listing successfully"}


@router.put("/admin/cars/{car_id}/show")
async def show_car(
    car_id: int,
    current_admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Show car in public listing"""
    stmt = select(Car).filter(Car.id == car_id)
    result = await db.execute(stmt)
    car = result.scalar_one_or_none()
    
    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found"
        )
    
    if not car.is_hidden:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Car is already visible"
        )
    
    car.is_hidden = False
    await db.commit()
    
    return {"message": "Car is now visible in public listing"}
