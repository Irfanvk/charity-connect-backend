from fastapi import APIRouter, UploadFile, File, HTTPException
from app.utils.file_handler import validate_file, save_file
import uuid

router = APIRouter(prefix="/files", tags=["Files"])


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
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
    
    # Generate unique filename
    file_extension = file.filename.split('.')[-1] if '.' in file.filename else ''
    unique_filename = f"{uuid.uuid4()}.{file_extension}" if file_extension else f"{uuid.uuid4()}"
    
    # Save file (subfolder: 'proofs', filename: unique_filename)
    save_file(content, 'proofs', unique_filename)
    
    # Return URL
    file_url = f"/uploads/proofs/{unique_filename}"
    
    return {
        "file_url": file_url,
        "filename": unique_filename
    }
