import os
import json
from typing import Any
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "PMB GCC PORTAL Backend"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    
    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:password@localhost:5432/charity_connect"
    )
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "10"))
    DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "20"))
    DB_POOL_TIMEOUT: int = int(os.getenv("DB_POOL_TIMEOUT", "30"))
    DB_POOL_RECYCLE: int = int(os.getenv("DB_POOL_RECYCLE", "1800"))
    
    # JWT
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    ALGORITHM: str = "HS256"
    
    # CORS Configuration - read from ALLOWED_ORIGINS env var
    CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: os.getenv(
            "ALLOWED_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173"
        ).split(",") if os.getenv("ALLOWED_ORIGINS") else [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return [
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            ]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            stripped = value.strip()
            # Support JSON list and simple comma-separated values.
            if stripped.startswith("["):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except json.JSONDecodeError:
                    pass
            return [item.strip() for item in stripped.split(",") if item.strip()]
        raise ValueError("CORS_ORIGINS must be a list or a string")

    # Trusted host validation (hostnames only, no scheme)
    # In production set ALLOWED_HOSTS=your-app.onrender.com,your-custom-domain.com
    ALLOWED_HOSTS: list[str] = Field(
        default_factory=lambda: ["127.0.0.1", "localhost", "testserver", "*.onrender.com", "*.netlify.app"]
    )

    @field_validator("ALLOWED_HOSTS", mode="before")
    @classmethod
    def parse_allowed_hosts(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return ["127.0.0.1", "localhost", "testserver"]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except json.JSONDecodeError:
                    pass
            return [item.strip() for item in stripped.split(",") if item.strip()]
        raise ValueError("ALLOWED_HOSTS must be a list or a string")

    @field_validator("ACCESS_TOKEN_EXPIRE_MINUTES")
    @classmethod
    def validate_access_token_expiry(cls, value: int) -> int:
        if value < 5 or value > 1440:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be between 5 and 1440")
        return value

    @model_validator(mode="after")
    def validate_security_settings(self):
        weak_defaults = {
            "",
            "your-secret-key-change-in-production",
            "changeme",
            "secret",
            "test-secret-key-for-development-only",
        }

        if self.SECRET_KEY in weak_defaults or len(self.SECRET_KEY) < 32:
            if not self.DEBUG:
                raise ValueError("SECRET_KEY must be set to a strong value (minimum 32 characters) when DEBUG=false")

        if "*" in self.CORS_ORIGINS and not self.DEBUG:
            raise ValueError("CORS_ORIGINS cannot contain '*' when DEBUG=false")

        # Block localhost as the frontend URL in production — it would produce
        # broken invite/reset links sent to real members via WhatsApp.
        if not self.DEBUG:
            _local_patterns = ("localhost", "127.0.0.1", "0.0.0.0")
            if any(p in self.FRONTEND_BASE_URL for p in _local_patterns):
                raise ValueError(
                    "FRONTEND_BASE_URL must be set to the real production domain when DEBUG=False. "
                    f"Current value '{self.FRONTEND_BASE_URL}' contains a localhost address. "
                    "Set FRONTEND_BASE_URL=https://your-domain.netlify.app in your .env file."
                )

        return self
    
    # File Upload
    MAX_UPLOAD_SIZE_MB: int = 3
    UPLOAD_DIR: str = os.path.join(os.path.dirname(__file__), "uploads")

    # Frontend links
    FRONTEND_BASE_URL: str = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")

    @field_validator("FRONTEND_BASE_URL", mode="after")
    @classmethod
    def validate_frontend_base_url(cls, value: str) -> str:
        stripped = value.strip().rstrip("/")
        return stripped
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Redis / Celery
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", REDIS_URL)
    CELERY_RESULT_BACKEND: str = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)
    CELERY_STORE_RESULTS: bool = os.getenv("CELERY_STORE_RESULTS", "false").lower() == "true"
    CELERY_TIMEZONE: str = os.getenv("CELERY_TIMEZONE", "UTC")
    ENABLE_FASTAPI_LIMITER: bool = os.getenv("ENABLE_FASTAPI_LIMITER", "false").lower() == "true"

    # Cloudinary (file storage — uploads, avatars, payment proofs)
    CLOUDINARY_CLOUD_NAME: str = os.getenv("CLOUDINARY_CLOUD_NAME", "")
    CLOUDINARY_API_KEY: str = os.getenv("CLOUDINARY_API_KEY", "")
    CLOUDINARY_API_SECRET: str = os.getenv("CLOUDINARY_API_SECRET", "")
    CLOUDINARY_FOLDER: str = os.getenv("CLOUDINARY_FOLDER", "charity-connect")

    @property
    def cloudinary_configured(self) -> bool:
        return bool(self.CLOUDINARY_CLOUD_NAME and self.CLOUDINARY_API_KEY and self.CLOUDINARY_API_SECRET)

    # WhatsApp Cloud API
    WHATSAPP_ENABLED: bool = os.getenv("WHATSAPP_ENABLED", "false").lower() == "true"
    WHATSAPP_PROVIDER: str = os.getenv("WHATSAPP_PROVIDER", "meta")
    WHATSAPP_API_VERSION: str = os.getenv("WHATSAPP_API_VERSION", "v22.0")
    WHATSAPP_API_URL: str = os.getenv("WHATSAPP_API_URL", "")
    WHATSAPP_API_TOKEN: str = os.getenv("WHATSAPP_API_TOKEN", "")
    WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    WHATSAPP_VERIFY_TOKEN: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "")

    # Web Push (for notifications when app is closed)
    WEB_PUSH_PUBLIC_KEY: str = os.getenv("WEB_PUSH_PUBLIC_KEY", "")
    WEB_PUSH_PRIVATE_KEY: str = os.getenv("WEB_PUSH_PRIVATE_KEY", "")
    WEB_PUSH_SUBJECT: str = os.getenv("WEB_PUSH_SUBJECT", "mailto:admin@example.com")

    @property
    def web_push_private_key_value(self) -> str:
        """Resolve the VAPID private key to a PEM string.

        Supports three formats so the same codebase works locally and on Render/Heroku:
        - File path  → reads the .pem file (local dev: private_key.pem)
        - Base64 PEM → decodes to PEM string (production env var — no multiline needed)
        - Raw PEM    → returned as-is (starts with '-----BEGIN')
        """
        import base64
        key = self.WEB_PUSH_PRIVATE_KEY.strip()
        if not key:
            return ""
        # File path that exists on disk (local dev)
        if os.path.isfile(key):
            try:
                with open(key, "r") as f:
                    return f.read().strip()
            except OSError:
                pass
        # Raw PEM block
        if key.startswith("-----BEGIN"):
            return key
        # Base64-encoded PEM (production: store entire PEM as single base64 env var)
        try:
            decoded = base64.b64decode(key).decode("utf-8")
            if decoded.startswith("-----BEGIN"):
                return decoded.strip()
        except Exception:
            pass
        # Fall back to raw value (pywebpush may accept unencoded keys too)
        return key

    @property
    def web_push_configured(self) -> bool:
        return bool(self.WEB_PUSH_PUBLIC_KEY and self.web_push_private_key_value and self.WEB_PUSH_SUBJECT)

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
