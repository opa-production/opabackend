"""
Supabase Storage integration for media uploads.

This module provides functions for uploading, deleting, and managing
media files in Supabase Storage. All media is organized by user ID
for proper access control and management.
"""
import os
from supabase import create_client, Client as SupabaseClient
from fastapi import HTTPException, status
from datetime import datetime
import uuid
from typing import Optional
import logging

# Configure logging
logger = logging.getLogger(__name__)

# ==================== SUPABASE CONFIGURATION ====================
# Load from environment variables for security
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# Validate configuration and initialize client
supabase: Optional[SupabaseClient] = None

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    logger.warning(
        "Supabase configuration missing. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY "
        "environment variables. Media uploads will fail until configured."
    )
else:
    # Initialize Supabase client with service role key for backend operations
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
        logger.info("Supabase client initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {e}")


# ==================== STORAGE BUCKET NAMES ====================
BUCKETS = {
    # Client buckets - for car renters
    "client_profile": "client-profile-media",  # Avatars, profile images
    "client_documents": "client-documents",    # ID documents, licenses
    "client_misc": "client-misc",              # Other client uploads
    
    # Host buckets - for car owners
    "host_profile": "host-profile-media",      # Avatars, cover images
    "host_documents": "host-documents",        # ID documents, licenses
    "vehicle_media": "vehicle-media",          # Car photos, videos
}


def _check_supabase_client():
    """Ensure Supabase client is initialized before operations."""
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage service unavailable. Please contact support."
        )


def generate_file_path(user_id: int, category: str, subcategory: str, filename: str) -> str:
    """
    Generate a unique file path for Supabase Storage.
    
    Files are organized as: {user_id}/{category}/{subcategory}/{unique_filename}
    
    Args:
        user_id: The user's database ID
        category: Main category (e.g., 'profile', 'documents', 'vehicles')
        subcategory: Subcategory (e.g., 'avatar', 'id', 'license', 'images')
        filename: Original filename
    
    Returns:
        Full path string for storage
    
    Example:
        generate_file_path(123, 'profile', 'avatar', 'photo.jpg')
        -> '123/profile/avatar/photo_1704067200000_abc123de.jpg'
    """
    timestamp = int(datetime.utcnow().timestamp() * 1000)
    unique_id = str(uuid.uuid4())[:8]
    
    # Sanitize filename - keep only alphanumeric, dots, underscores, hyphens
    safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-")
    
    # Handle edge cases
    if not safe_filename or '.' not in safe_filename:
        safe_filename = "file.jpg"
    
    # Split into name and extension
    parts = safe_filename.rsplit('.', 1)
    name = parts[0] if parts[0] else "file"
    ext = parts[1] if len(parts) > 1 else "jpg"
    
    final_filename = f"{name}_{timestamp}_{unique_id}.{ext}"
    
    return f"{user_id}/{category}/{subcategory}/{final_filename}"


async def upload_file_to_storage(
    bucket_name: str,
    file_path: str,
    file_data: bytes,
    content_type: str = "image/jpeg"
) -> dict:
    """
    Upload a file to Supabase Storage.
    
    Args:
        bucket_name: Name of the storage bucket (from BUCKETS dict)
        file_path: Full path where file should be stored
        file_data: Binary file data
        content_type: MIME type of the file
    
    Returns:
        dict with 'success', 'url', and 'path' keys
    
    Raises:
        HTTPException: If upload fails or storage is unavailable
    """
    _check_supabase_client()
    
    try:
        logger.info(f"Uploading to {bucket_name}/{file_path} ({len(file_data)} bytes)")
        
        # Upload file to Supabase Storage with upsert option
        result = supabase.storage.from_(bucket_name).upload(
            path=file_path,
            file=file_data,
            file_options={
                "content-type": content_type,
                "upsert": "true"  # Allow replacing existing files
            }
        )
        
        # Get public URL for the uploaded file
        public_url = supabase.storage.from_(bucket_name).get_public_url(file_path)
        
        logger.info(f"Upload successful: {public_url}")
        
        return {
            "success": True,
            "url": public_url,
            "path": file_path
        }
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Storage upload error: {error_msg}")
        
        # Provide more specific error messages
        if "bucket" in error_msg.lower():
            detail = f"Storage bucket '{bucket_name}' not found or inaccessible"
        elif "size" in error_msg.lower():
            detail = "File size exceeds maximum allowed limit"
        elif "type" in error_msg.lower():
            detail = f"File type '{content_type}' not allowed"
        else:
            detail = f"Failed to upload file: {error_msg}"
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail
        )


async def delete_file_from_storage(bucket_name: str, file_path: str) -> dict:
    """
    Delete a file from Supabase Storage.
    
    Args:
        bucket_name: Name of the storage bucket
        file_path: Full path of the file to delete
    
    Returns:
        dict with 'success' key and optionally 'error'
    """
    _check_supabase_client()
    
    try:
        logger.info(f"Deleting from {bucket_name}/{file_path}")
        supabase.storage.from_(bucket_name).remove([file_path])
        logger.info(f"Delete successful: {file_path}")
        return {"success": True}
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Storage delete error: {error_msg}")
        # Don't raise exception for delete failures - just log and return
        return {"success": False, "error": error_msg}


def get_public_url(bucket_name: str, file_path: str) -> str:
    """
    Get the public URL for a stored file.
    
    Args:
        bucket_name: Name of the storage bucket
        file_path: Full path of the file
    
    Returns:
        Public URL string
    
    Raises:
        HTTPException: If storage is unavailable
    """
    _check_supabase_client()
    return supabase.storage.from_(bucket_name).get_public_url(file_path)


def extract_path_from_url(url: str, bucket_name: str) -> Optional[str]:
    """
    Extract the storage path from a public URL.
    
    This is useful for deleting old files when a user uploads a replacement.
    
    Args:
        url: The full public URL
        bucket_name: The bucket name to look for
    
    Returns:
        The file path within the bucket, or None if extraction fails
    """
    if not url:
        return None
    
    try:
        # URL format: {SUPABASE_URL}/storage/v1/object/public/{bucket}/{path}
        marker = f"/storage/v1/object/public/{bucket_name}/"
        if marker in url:
            return url.split(marker, 1)[1]
        return None
    except Exception as e:
        logger.error(f"Failed to extract path from URL: {e}")
        return None


async def list_user_files(bucket_name: str, user_id: int, category: Optional[str] = None) -> list:
    """
    List all files for a specific user in a bucket.
    
    Args:
        bucket_name: Name of the storage bucket
        user_id: The user's ID
        category: Optional category to filter by
    
    Returns:
        List of file objects with name, size, and metadata
    """
    _check_supabase_client()
    
    try:
        path = str(user_id)
        if category:
            path = f"{user_id}/{category}"
        
        result = supabase.storage.from_(bucket_name).list(path)
        return result
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        return []
