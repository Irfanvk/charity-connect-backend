from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.database import engine, Base
from app.config import settings
from app.routes import (
    auth_router,
    invite_router,
    member_router,
    challan_router,
    campaign_router,
    notification_router,
)

# Import models to ensure they are registered with Base
from app.models import (
    User,
    Member,
    Invite,
    Campaign,
    Challan,
    Notification,
    AuditLog,
)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Backend API for Charity Connect - Membership and Donation Management System",
)

# Create all tables
Base.metadata.create_all(bind=engine)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router)
app.include_router(invite_router)
app.include_router(member_router)
app.include_router(challan_router)
app.include_router(campaign_router)
app.include_router(notification_router)

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
    except Exception as e:
        return {"database_status": "error", "message": str(e)}

