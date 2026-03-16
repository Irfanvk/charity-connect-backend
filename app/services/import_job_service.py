from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Any, Callable


class ImportJobService:
    """In-memory async import job tracker for long-running file imports."""

    _lock = threading.Lock()
    _jobs: dict[str, dict[str, Any]] = {}

    @classmethod
    def create_job(cls, *, job_type: str, filename: str) -> str:
        job_id = uuid.uuid4().hex
        now = datetime.utcnow().isoformat()
        with cls._lock:
            cls._jobs[job_id] = {
                "job_id": job_id,
                "job_type": job_type,
                "filename": filename,
                "status": "queued",
                "progress": 0,
                "message": "Queued",
                "created_at": now,
                "updated_at": now,
                "result": None,
                "error": None,
            }
        return job_id

    @classmethod
    def get_job(cls, job_id: str) -> dict[str, Any] | None:
        with cls._lock:
            job = cls._jobs.get(job_id)
            return dict(job) if job else None

    @classmethod
    def update_progress(cls, job_id: str, *, progress: int, message: str) -> None:
        now = datetime.utcnow().isoformat()
        with cls._lock:
            job = cls._jobs.get(job_id)
            if not job:
                return
            job["status"] = "running"
            job["progress"] = max(0, min(100, int(progress)))
            job["message"] = message
            job["updated_at"] = now

    @classmethod
    def _mark_started(cls, job_id: str) -> None:
        cls.update_progress(job_id, progress=1, message="Import started")

    @classmethod
    def _mark_completed(cls, job_id: str, result: Any) -> None:
        now = datetime.utcnow().isoformat()
        with cls._lock:
            job = cls._jobs.get(job_id)
            if not job:
                return
            job["status"] = "completed"
            job["progress"] = 100
            job["message"] = "Import completed"
            job["result"] = result
            job["updated_at"] = now

    @classmethod
    def _mark_failed(cls, job_id: str, error: str) -> None:
        now = datetime.utcnow().isoformat()
        with cls._lock:
            job = cls._jobs.get(job_id)
            if not job:
                return
            job["status"] = "failed"
            job["message"] = "Import failed"
            job["error"] = error
            job["updated_at"] = now

    @classmethod
    def run_in_thread(cls, *, job_id: str, runner: Callable[[], Any]) -> None:
        def _worker() -> None:
            cls._mark_started(job_id)
            try:
                result = runner()
                cls._mark_completed(job_id, result)
            except Exception as exc:  # pragma: no cover  # noqa: BLE001
                cls._mark_failed(job_id, str(exc))

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
