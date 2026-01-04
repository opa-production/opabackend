"""
Supabase Storage integration for media uploads
"""
import os
from supabase import create_client, Client
from fastapi import HTTPException, status
from datetime import datetime
import uuid

# Supabase configuration from environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://mvzddrdfkgydoitrblpq.supabase.co")
SUPABASE_SERVICE_ROLE_KEY = os.getenv(
    "SUPABASE_SERVICE_ROLE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im12emRkcmRma2d5ZG9pdHJibHBxIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2Njk3NTAyMiwiZXhwIjoyMDgyNTUxMDIyfQ.o0csPVj6MLCNa0_crtBllxl8UgkivrXOjZ08KZUqpg0"
)

# Initialize Supabase client with service role key for backend operations
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# Storage bucket names
BUCKETS = {
    # Client buckets
    "client_profile": "client-profile-media",
    "client_documents": "client-documents",
    "client_misc": "client-misc",
    
    # Host buckets
    "host_profile": "host-profile-media",
    "host_documents": "host-documents",
    "vehicle_media": "vehicle-media",
}


def generate_file_path(user_id: int, category: str, subcategory: str, filename: str) -> str:
    """
    Generate a deterministic file path for Supabase Storage
    
    Args:
        user_id: The user's ID
        category: Main category (e.g., 'avatar', 'documents', 'vehicles')
        subcategory: Subcategory (e.g., 'id', 'license', 'images')
        filename: Original filename or generated name
    
    Returns:
        Full path string for storage
    """
    timestamp = int(datetime.utcnow().timestamp() * 1000)
    unique_id = str(uuid.uuid4())[:8]
    
    # Sanitize filename
    safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-")
    final_filename = f"{safe_filename.split('.')[0]}_{timestamp}_{unique_id}.{safe_filename.split('.')[-1]}"
    
    return f"{user_id}/{category}/{subcategory}/{final_filename}"


async def upload_file_to_storage(
    bucket_name: str,
    file_path: str,
    file_data: bytes,
    content_type: str = "image/jpeg"
) -> dict:
    """
    Upload a file to Supabase Storage
    
    Args:
        bucket_name: Name of the storage bucket
        file_path: Full path where file should be stored
        file_data: Binary file data
        content_type: MIME type of the file
    
    Returns:
        dict with 'success', 'url', and 'path' keys
    """
    try:
        # Upload file to Supabase Storage
        result = supabase.storage.from_(bucket_name).upload(
            path=file_path,
            file=file_data,
            file_options={
                "content-type": content_type,
                "upsert": "true"  # Allow replacing existing files
            }
        )
        
        # Get public URL
        public_url = supabase.storage.from_(bucket_name).get_public_url(file_path)
        
        return {
            "success": True,
            "url": public_url,
            "path": file_path
        }
    except Exception as e:
        print(f"Storage upload error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file to storage: {str(e)}"
        )


async def delete_file_from_storage(bucket_name: str, file_path: str) -> dict:
    """
    Delete a file from Supabase Storage
    
    Args:
        bucket_name: Name of the storage bucket
        file_path: Full path of the file to delete
    
    Returns:
        dict with 'success' key
    """
    try:
        supabase.storage.from_(bucket_name).remove([file_path])
        return {"success": True}
    except Exception as e:
        print(f"Storage delete error: {str(e)}")
        return {"success": False, "error": str(e)}


def get_public_url(bucket_name: str, file_path: str) -> str:
    """
    Get the public URL for a stored file
    
    Args:
        bucket_name: Name of the storage bucket
        file_path: Full path of the file
    
    Returns:
        Public URL string
    """
    return supabase.storage.from_(bucket_name).get_public_url(file_path)
