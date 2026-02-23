from datetime import datetime
from pathlib import Path


def save_file(file_content: bytes, subfolder: str, filename: str) -> str:
    """
    Save uploaded file and return relative path.
    
    Args:
        file_content: File bytes
        subfolder: Subdirectory in uploads folder
        filename: Name to save file as
    
    Returns:
        Relative path to saved file
    """
    # Create uploads directory if it doesn't exist
    upload_dir = Path(__file__).parent.parent / "uploads" / subfolder
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    # Add timestamp to filename to ensure uniqueness
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_")
    final_filename = timestamp + filename
    
    file_path = upload_dir / final_filename
    
    with open(file_path, "wb") as f:
        f.write(file_content)
    
    # Return relative path
    return f"uploads/{subfolder}/{final_filename}"


def validate_file(file_content: bytes, filename: str, max_size_mb: int = 5) -> bool:
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
    
    # Check file extension
    allowed_extensions = {".jpg", ".jpeg", ".png", ".pdf"}
    file_ext = Path(filename).suffix.lower()
    
    if file_ext not in allowed_extensions:
        raise ValueError(f"File type not allowed. Allowed types: {', '.join(allowed_extensions)}")
    
    return True


def get_client_ip(request) -> str:
    """Extract client IP from request."""
    if request.client:
        return request.client.host
    return "0.0.0.0"
