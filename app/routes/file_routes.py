from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from app.utils.file_handler import validate_file, save_file
from app.utils.auth import get_current_user

router = APIRouter(prefix="/files", tags=["Files"])


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    _current_user: dict = Depends(get_current_user),
):
    """
    Upload file and return public URL.
    
    Accepts: jpg, png, pdf
    Max size: 3MB
    
    Returns:
        dict: {"file_url": str, "filename": str}
    """
    # Read file content
    content = await file.read()
    
    # Validate file
    try:
        validate_file(content, file.filename, max_size_mb=3)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    
    # Save file — save_file returns the actual stored path (opaque filename)
    saved_path = save_file(content, 'proofs', file.filename)
    
    # Build URL from the real saved path
    if saved_path.startswith("http"):
        file_url = saved_path
    elif saved_path.startswith("/"):
        file_url = saved_path
    else:
        file_url = f"/{saved_path}"
    
    return {
        "file_url": file_url,
        "filename": saved_path.split("/")[-1]
    }
