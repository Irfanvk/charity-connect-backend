import socket
from urllib.parse import urlparse

from app.config import settings


DEFAULT_BROKER_PORTS = {
    "redis": 6379,
    "rediss": 6379,
    "amqp": 5672,
    "amqps": 5671,
}


def celery_result_backend_url() -> str | None:
    if not settings.CELERY_STORE_RESULTS:
        return None

    backend_url = str(settings.CELERY_RESULT_BACKEND or "").strip()
    return backend_url or None


def can_enqueue_celery_tasks(timeout: float = 0.2) -> bool:
    broker_url = str(settings.CELERY_BROKER_URL or "").strip()
    if not broker_url:
        return False

    parsed = urlparse(broker_url)
    host = parsed.hostname
    if not host:
        return True

    port = parsed.port or DEFAULT_BROKER_PORTS.get(parsed.scheme)
    if port is None:
        return True

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False