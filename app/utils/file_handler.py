from pathlib import Path
import secrets


def _safe_extension(filename: str) -> str:
    """Extract a safe lowercase extension from filename (e.g. '.pdf', '.jpg')."""
    ext = Path(str(filename or "")).suffix.lower()
    # Only allow known safe extensions to prevent extension spoofing
    return ext if ext in {".jpg", ".jpeg", ".png", ".pdf"} else ".bin"


def save_file(file_content: bytes, subfolder: str, filename: str) -> str:
    """
    Save uploaded file under a random, opaque filename that carries no PII.

    The original filename is intentionally discarded — only its extension is
    reused so the file remains openable by standard tools.  Ownership is
    tracked via the database FK (Challan.member_id → members → users), not
    via the filename on disk.

    Args:
        file_content: File bytes
        subfolder: Subdirectory inside uploads/
        filename: Original filename (used only for extension extraction)

    Returns:
        Relative path to saved file (safe to store in DB)
    """
    upload_dir = Path(__file__).parent.parent / "uploads" / subfolder
    upload_dir.mkdir(parents=True, exist_ok=True)

    ext = _safe_extension(filename)
    # 16-byte URL-safe random token → 22-char string: zero PII, collision-resistant
    opaque_name = secrets.token_urlsafe(16) + ext
    file_path = upload_dir / opaque_name

    with open(file_path, "wb") as f:
        f.write(file_content)

    return f"uploads/{subfolder}/{opaque_name}"


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
