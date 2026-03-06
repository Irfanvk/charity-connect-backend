from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from app.database import engine, Base
from app.config import settings
from app.routes import (
    auth_router,
    invite_router,
    member_router,
    challan_router,
    bulk_challan_router,
    campaign_router,
    notification_router,
    file_router,
    user_router,
    audit_log_router,
)
import logging
import app.models as _models

# Configure logging
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Backend API for Charity Connect - Membership and Donation Management System",
    openapi_url="/openapi/v1.json" if settings.DEBUG else None,  # Disable OpenAPI in production
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# Create all tables
Base.metadata.create_all(bind=engine)

# Add security middleware: TrustedHost
if not settings.DEBUG:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.ALLOWED_HOSTS,
    )

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router)
app.include_router(invite_router)
app.include_router(member_router)
app.include_router(challan_router)
app.include_router(bulk_challan_router)
app.include_router(campaign_router)
app.include_router(notification_router)
app.include_router(file_router)
app.include_router(user_router)
app.include_router(audit_log_router)


def _ensure_detail_list(detail, default_loc=None, default_type="error"):
    loc = default_loc or ["request"]

    if isinstance(detail, list):
        normalized = []
        for item in detail:
            if isinstance(item, dict):
                normalized.append(
                    {
                        "type": item.get("type", default_type),
                        "loc": list(item.get("loc", loc)),
                        "msg": item.get("msg") or item.get("detail") or str(item),
                        "input": item.get("input"),
                    }
                )
            else:
                normalized.append({"type": default_type, "loc": loc, "msg": str(item), "input": None})
        return normalized

    if isinstance(detail, dict):
        return [
            {
                "type": detail.get("type", default_type),
                "loc": list(detail.get("loc", loc)),
                "msg": detail.get("msg") or detail.get("detail") or str(detail),
                "input": detail.get("input"),
            }
        ]

    return [{"type": default_type, "loc": loc, "msg": str(detail), "input": None}]


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, exc: RequestValidationError):
    detail = _ensure_detail_list(exc.errors(), default_loc=["body"], default_type="validation_error")
    return JSONResponse(status_code=422, content={"detail": detail})


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException):
    detail = _ensure_detail_list(exc.detail, default_type="http_error")
    return JSONResponse(status_code=exc.status_code, content={"detail": detail}, headers=exc.headers)


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, _exc: Exception):
    detail = _ensure_detail_list("Internal server error", default_type="server_error")
    return JSONResponse(status_code=500, content={"detail": detail})

# Health check endpoints
@app.get("/")
def root():
    return {
        "message": "Charity Connect Backend",
        "version": settings.APP_VERSION,
        "status": "running",
    }

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
    }

@app.get("/test-db")
def test_db():
    """Test database connection."""
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1"))
            return {"database_status": "connected", "result": result.scalar()}
    except SQLAlchemyError as e:
        return {"database_status": "error", "message": str(e)}

