from pathlib import Path
import secrets
import os
from uuid import uuid4
import io

import cloudinary
import cloudinary.uploader

from app.config import settings


def _safe_extension(filename: str) -> str:
    """Extract a safe lowercase extension from filename (e.g. '.pdf', '.jpg')."""
    ext = Path(str(filename or "")).suffix.lower()
    # Only allow known safe extensions to prevent extension spoofing
    return ext if ext in {".jpg", ".jpeg", ".png", ".pdf"} else ".bin"


def _cloudinary_resource_type(ext: str) -> str:
    """Map file extension to Cloudinary resource_type."""
    if ext in {".jpg", ".jpeg", ".png"}:
        return "image"
    # PDFs and other binaries use 'raw'
    return "raw"


def _configure_cloudinary() -> bool:
    """
    Configure Cloudinary from app settings.
    Returns True if all required vars are present, False otherwise.
    """
    if not settings.cloudinary_configured:
        return False
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )
    return True


def save_file(file_content: bytes, subfolder: str, filename: str) -> str:
    """
    Save uploaded file and return a public URL.

    Storage priority:
      1. Cloudinary  (if CLOUDINARY_CLOUD_NAME / API_KEY / API_SECRET are set)
      2. Local disk  (fallback for development)

    The original filename is intentionally discarded — only its extension is
    reused so the file remains openable by standard tools.  Ownership is
    tracked via the database FK, not via the filename.

    Args:
        file_content: File bytes
        subfolder:    Logical category, e.g. 'proofs', 'avatars'
        filename:     Original filename (used only for extension extraction)

    Returns:
        Public URL string (Cloudinary secure_url) or relative local path.
    """
    ext = _safe_extension(filename)
    folder_root = settings.CLOUDINARY_FOLDER

    if _configure_cloudinary():
        resource_type = _cloudinary_resource_type(ext)
        public_id = f"{folder_root}/{subfolder}/{uuid4().hex}"
        result = cloudinary.uploader.upload(
            io.BytesIO(file_content),
            public_id=public_id,
            resource_type=resource_type,
            overwrite=False,
            unique_filename=False,
        )
        return result["secure_url"]

    # --- Local disk fallback (development only) ---
    upload_dir = Path(__file__).parent.parent / "uploads" / subfolder
    upload_dir.mkdir(parents=True, exist_ok=True)
    opaque_name = secrets.token_urlsafe(16) + ext
    file_path = upload_dir / opaque_name
    with open(file_path, "wb") as f:
        f.write(file_content)
    return f"uploads/{subfolder}/{opaque_name}"


def delete_file(public_url: str) -> bool:
    """
    Delete a file from Cloudinary by its secure_url.
    Returns True on success, False if not a Cloudinary URL or deletion fails.
    """
    if "cloudinary.com" not in public_url:
        return False
    if not _configure_cloudinary():
        return False
    try:
        # Extract public_id from URL: .../upload/v12345/{public_id}.{ext}
        parts = public_url.split("/upload/")
        if len(parts) != 2:
            return False
        # Strip version segment (v12345/) if present, then remove extension
        after_upload = parts[1]
        if after_upload.startswith("v") and "/" in after_upload:
            after_upload = after_upload.split("/", 1)[1]
        public_id = after_upload.rsplit(".", 1)[0]
        cloudinary.uploader.destroy(public_id)
        return True
    except Exception:
        return False


def validate_file(file_content: bytes, filename: str, max_size_mb: int = 3) -> bool:
    """
    Validate file size and type.
    
    Args:
        file_content: File bytes
        filename: Filename to check extension
        max_size_mb: Maximum file size in MB
    
    Returns:
        True if valid, raises exception otherwise
    """
    # Check file size
    file_size_mb = len(file_content) / (1024 * 1024)
    if file_size_mb > max_size_mb:
        raise ValueError(f"File size exceeds {max_size_mb}MB limit")

    # Check file extension using the safe extractor
    ext = _safe_extension(filename)
    allowed_extensions = {".jpg", ".jpeg", ".png", ".pdf"}
    if ext not in allowed_extensions:
        raise ValueError(f"File type not allowed. Allowed types: {', '.join(allowed_extensions)}")
    
    return True


def get_client_ip(request) -> str:
    """Extract client IP from request."""
    if request.client:
        return request.client.host
    return "0.0.0.0"
