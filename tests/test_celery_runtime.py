"""Work is only handed to Celery when a worker is declared running."""
import socket

from app.config import settings
from app.workers import runtime


def test_disabled_by_default_even_if_broker_is_reachable(monkeypatch):
    monkeypatch.setattr(settings, "CELERY_WORKERS_ENABLED", False)
    monkeypatch.setattr(settings, "CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(AssertionError("not called")))
    assert runtime.can_enqueue_celery_tasks() is False


def test_enabled_needs_a_reachable_broker(monkeypatch):
    monkeypatch.setattr(settings, "CELERY_WORKERS_ENABLED", True)
    monkeypatch.setattr(settings, "CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: _Conn())
    assert runtime.can_enqueue_celery_tasks() is True

    def refuse(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(socket, "create_connection", refuse)
    assert runtime.can_enqueue_celery_tasks() is False
