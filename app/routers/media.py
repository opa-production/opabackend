"""
Media upload endpoints for clients and hosts
"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional, List
import json

from app.database import get_db
from app.models import Client, Host, Car
from app.auth import get_current_client, get_current_host
from app.storage import (
    upload_file_to_storage,
    delete_file_from_storage,
    generate_file_path,
    BUCKETS
)
from pydantic import BaseModel


router = APIRouter()


# Response schemas
class MediaUploadResponse(BaseModel):
    success: bool
    url: Optional[str] = None
    message: str


class MultipleMediaUploadResponse(BaseModel):
    success: bool
    urls: List[str]
    message: str


# ==================== CLIENT ENDPOINTS ====================

@router.post("/client/upload/avatar", response_model=MediaUploadResponse)
async def upload_client_avatar(
    file: UploadFile = File(...),
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """
    Upload or update client profile avatar
    
    - **file**: Image file (JPEG, PNG)
    - Requires client authentication
    - Automatically replaces existing avatar
    """
    # Validate file type
    if not file.content_type or not file.content_type.startswith('image/'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only image files are allowed"
        )
    
    # Read file data
    file_data = await file.read()
    
    # Generate file path
    file_path = generate_file_path(
        user_id=current_client.id,
        category="profile",
        subcategory="avatar",
        filename=file.filename or "avatar.jpg"
    )
    
    # Delete old avatar if exists
    if current_client.avatar_url:
        old_path = current_client.avatar_url.split('/')[-4:]  # Extract path from URL
        await delete_file_from_storage(BUCKETS["client_profile"], "/".join(old_path))
    
    # Upload to Supabase Storage
    result = await upload_file_to_storage(
        bucket_name=BUCKETS["client_profile"],
        file_path=file_path,
        file_data=file_data,
        content_type=file.content_type
    )
    
    # Update database
    current_client.avatar_url = result["url"]
    db.commit()
    db.refresh(current_client)
    
    return MediaUploadResponse(
        success=True,
        url=result["url"],
        message="Avatar uploaded successfully"
    )


@router.post("/client/upload/document", response_model=MediaUploadResponse)
async def upload_client_document(
    file: UploadFile = File(...),
    document_type: str = Form(...),  # 'id' or 'license'
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """
    Upload client identity documents
    
    - **file**: Document image (JPEG, PNG, PDF)
    - **document_type**: Type of document ('id' for national ID, 'license' for driver's license)
    - Requires client authentication
    """
    # Validate document type
    if document_type not in ['id', 'license']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="document_type must be 'id' or 'license'"
        )
    
    # Validate file type
    allowed_types = ['image/jpeg', 'image/png', 'application/pdf']
    if not file.content_type or file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only JPEG, PNG, and PDF files are allowed"
        )
    
    # Read file data
    file_data = await file.read()
    
    # Generate file path
    file_path = generate_file_path(
        user_id=current_client.id,
        category="documents",
        subcategory=document_type,
        filename=file.filename or f"{document_type}.jpg"
    )
    
    # Delete old document if exists
    old_url = current_client.id_document_url if document_type == 'id' else current_client.license_document_url
    if old_url:
        old_path = old_url.split('/')[-4:]  # Extract path from URL
        await delete_file_from_storage(BUCKETS["client_documents"], "/".join(old_path))
    
    # Upload to Supabase Storage
    result = await upload_file_to_storage(
        bucket_name=BUCKETS["client_documents"],
        file_path=file_path,
        file_data=file_data,
        content_type=file.content_type
    )
    
    # Update database
    if document_type == 'id':
        current_client.id_document_url = result["url"]
    else:
        current_client.license_document_url = result["url"]
    
    db.commit()
    db.refresh(current_client)
    
    return MediaUploadResponse(
        success=True,
        url=result["url"],
        message=f"{document_type.upper()} document uploaded successfully"
    )


# ==================== HOST ENDPOINTS ====================

@router.post("/host/upload/avatar", response_model=MediaUploadResponse)
async def upload_host_avatar(
    file: UploadFile = File(...),
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db)
):
    """
    Upload or update host profile avatar
    
    - **file**: Image file (JPEG, PNG)
    - Requires host authentication
    - Automatically replaces existing avatar
    """
    # Validate file type
    if not file.content_type or not file.content_type.startswith('image/'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only image files are allowed"
        )
    
    # Read file data
    file_data = await file.read()
    
    # Generate file path
    file_path = generate_file_path(
        user_id=current_host.id,
        category="profile",
        subcategory="avatar",
        filename=file.filename or "avatar.jpg"
    )
    
    # Delete old avatar if exists
    if current_host.avatar_url:
        old_path = current_host.avatar_url.split('/')[-4:]  # Extract path from URL
        await delete_file_from_storage(BUCKETS["host_profile"], "/".join(old_path))
    
    # Upload to Supabase Storage
    result = await upload_file_to_storage(
        bucket_name=BUCKETS["host_profile"],
        file_path=file_path,
        file_data=file_data,
        content_type=file.content_type
    )
    
    # Update database
    current_host.avatar_url = result["url"]
    db.commit()
    db.refresh(current_host)
    
    return MediaUploadResponse(
        success=True,
        url=result["url"],
        message="Avatar uploaded successfully"
    )


@router.post("/host/upload/cover", response_model=MediaUploadResponse)
async def upload_host_cover_image(
    file: UploadFile = File(...),
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db)
):
    """
    Upload or update host profile cover image
    
    - **file**: Image file (JPEG, PNG)
    - Requires host authentication
    - Automatically replaces existing cover image
    """
    # Validate file type
    if not file.content_type or not file.content_type.startswith('image/'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only image files are allowed"
        )
    
    # Read file data
    file_data = await file.read()
    
    # Generate file path
    file_path = generate_file_path(
        user_id=current_host.id,
        category="profile",
        subcategory="cover",
        filename=file.filename or "cover.jpg"
    )
    
    # Delete old cover if exists
    if current_host.cover_image_url:
        old_path = current_host.cover_image_url.split('/')[-4:]  # Extract path from URL
        await delete_file_from_storage(BUCKETS["host_profile"], "/".join(old_path))
    
    # Upload to Supabase Storage
    result = await upload_file_to_storage(
        bucket_name=BUCKETS["host_profile"],
        file_path=file_path,
        file_data=file_data,
        content_type=file.content_type
    )
    
    # Update database
    current_host.cover_image_url = result["url"]
    db.commit()
    db.refresh(current_host)
    
    return MediaUploadResponse(
        success=True,
        url=result["url"],
        message="Cover image uploaded successfully"
    )


@router.post("/host/upload/document", response_model=MediaUploadResponse)
async def upload_host_document(
    file: UploadFile = File(...),
    document_type: str = Form(...),  # 'id' or 'license'
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db)
):
    """
    Upload host identity documents
    
    - **file**: Document image (JPEG, PNG, PDF)
    - **document_type**: Type of document ('id' for national ID, 'license' for driver's license)
    - Requires host authentication
    """
    # Validate document type
    if document_type not in ['id', 'license']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="document_type must be 'id' or 'license'"
        )
    
    # Validate file type
    allowed_types = ['image/jpeg', 'image/png', 'application/pdf']
    if not file.content_type or file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only JPEG, PNG, and PDF files are allowed"
        )
    
    # Read file data
    file_data = await file.read()
    
    # Generate file path
    file_path = generate_file_path(
        user_id=current_host.id,
        category="documents",
        subcategory=document_type,
        filename=file.filename or f"{document_type}.jpg"
    )
    
    # Delete old document if exists
    old_url = current_host.id_document_url if document_type == 'id' else current_host.license_document_url
    if old_url:
        old_path = old_url.split('/')[-4:]  # Extract path from URL
        await delete_file_from_storage(BUCKETS["host_documents"], "/".join(old_path))
    
    # Upload to Supabase Storage
    result = await upload_file_to_storage(
        bucket_name=BUCKETS["host_documents"],
        file_path=file_path,
        file_data=file_data,
        content_type=file.content_type
    )
    
    # Update database
    if document_type == 'id':
        current_host.id_document_url = result["url"]
    else:
        current_host.license_document_url = result["url"]
    
    db.commit()
    db.refresh(current_host)
    
    return MediaUploadResponse(
        success=True,
        url=result["url"],
        message=f"{document_type.upper()} document uploaded successfully"
    )


@router.post("/host/upload/vehicle/{car_id}/images", response_model=MultipleMediaUploadResponse)
async def upload_vehicle_images(
    car_id: int,
    files: List[UploadFile] = File(...),
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db)
):
    """
    Upload multiple images for a vehicle
    
    - **car_id**: ID of the car
    - **files**: List of image files (JPEG, PNG)
    - Requires host authentication
    - Host must own the vehicle
    - Maximum 10 images per vehicle
    """
    # Verify car ownership
    car = db.query(Car).filter(Car.id == car_id, Car.host_id == current_host.id).first()
    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found or you don't have permission to upload images for this vehicle"
        )
    
    # Validate number of files
    if len(files) > 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 10 images allowed per vehicle"
        )
    
    uploaded_urls = []
    
    for idx, file in enumerate(files):
        # Validate file type
        if not file.content_type or not file.content_type.startswith('image/'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File {file.filename} is not an image"
            )
        
        # Read file data
        file_data = await file.read()
        
        # Generate file path
        file_path = generate_file_path(
            user_id=current_host.id,
            category=f"vehicles/{car_id}",
            subcategory="images",
            filename=file.filename or f"image_{idx}.jpg"
        )
        
        # Upload to Supabase Storage
        result = await upload_file_to_storage(
            bucket_name=BUCKETS["vehicle_media"],
            file_path=file_path,
            file_data=file_data,
            content_type=file.content_type
        )
        
        uploaded_urls.append(result["url"])
    
    # Update car image URLs in database
    car.image_urls = json.dumps(uploaded_urls)
    db.commit()
    db.refresh(car)
    
    return MultipleMediaUploadResponse(
        success=True,
        urls=uploaded_urls,
        message=f"Successfully uploaded {len(uploaded_urls)} images"
    )


@router.post("/host/upload/vehicle/{car_id}/video", response_model=MediaUploadResponse)
async def upload_vehicle_video(
    car_id: int,
    file: UploadFile = File(...),
    current_host: Host = Depends(get_current_host),
    db: Session = Depends(get_db)
):
    """
    Upload a video for a vehicle
    
    - **car_id**: ID of the car
    - **file**: Video file (MP4, MOV)
    - Requires host authentication
    - Host must own the vehicle
    - Automatically replaces existing video
    """
    # Verify car ownership
    car = db.query(Car).filter(Car.id == car_id, Car.host_id == current_host.id).first()
    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found or you don't have permission to upload video for this vehicle"
        )
    
    # Validate file type
    allowed_types = ['video/mp4', 'video/quicktime', 'video/x-msvideo']
    if not file.content_type or file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only MP4 and MOV video files are allowed"
        )
    
    # Read file data
    file_data = await file.read()
    
    # Generate file path
    file_path = generate_file_path(
        user_id=current_host.id,
        category=f"vehicles/{car_id}",
        subcategory="videos",
        filename=file.filename or "video.mp4"
    )
    
    # Delete old video if exists
    if car.video_url:
        old_path = car.video_url.split('/')[-5:]  # Extract path from URL
        await delete_file_from_storage(BUCKETS["vehicle_media"], "/".join(old_path))
    
    # Upload to Supabase Storage
    result = await upload_file_to_storage(
        bucket_name=BUCKETS["vehicle_media"],
        file_path=file_path,
        file_data=file_data,
        content_type=file.content_type
    )
    
    # Update database
    car.video_url = result["url"]
    db.commit()
    db.refresh(car)
    
    return MediaUploadResponse(
        success=True,
        url=result["url"],
        message="Vehicle video uploaded successfully"
    )
