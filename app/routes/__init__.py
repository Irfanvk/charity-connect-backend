from .auth_routes import router as auth_router
from .invite_routes import router as invite_router
from .member_routes import router as member_router
from .challan_routes import router as challan_router
from .campaign_routes import router as campaign_router
from .notification_routes import router as notification_router

__all__ = [
    "auth_router",
    "invite_router",
    "member_router",
    "challan_router",
    "campaign_router",
    "notification_router",
]
