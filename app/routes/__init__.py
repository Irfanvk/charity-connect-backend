from .auth_routes import router as auth_router
from .invite_routes import router as invite_router
from .member_routes import router as member_router
from .challan_routes import router as challan_router
from .bulk_challan_routes import router as bulk_challan_router
from .admin_router import router as admin_router
from .campaign_routes import router as campaign_router
from .notification_routes import router as notification_router
from .request_routes import router as request_router
from .file_routes import router as file_router
from .user_routes import router as user_router
from .audit_log_routes import router as audit_log_router

__all__ = [
    "auth_router",
    "invite_router",
    "member_router",
    "challan_router",
    "bulk_challan_router",
    "admin_router",
    "campaign_router",
    "notification_router",
    "request_router",
    "file_router",
    "user_router",
    "audit_log_router",
]
