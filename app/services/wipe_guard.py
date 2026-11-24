"""Safeguards for the superadmin "System wipe" (it deletes every member, payment and the audit log).

1. One superadmin asks, with a purpose and their password.
2. A different superadmin approves, with their own password, within 24 hours.
3. The asker runs the wipe within 24 hours of the approval, once.
4. A database backup must have finished in the last hour (the nightly backup script writes
   /root/backups/last_ok after each good backup; Run-Backup-Now.cmd makes one on demand).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.models import User, WipeApproval
from app.utils.auth import verify_password

VALID_FOR = timedelta(hours=24)
BACKUP_MAX_AGE = timedelta(hours=1)


def backup_marker() -> Path:
    return Path(os.environ.get("WIPE_BACKUP_MARKER", "/root/backups/last_ok"))


def check_fresh_backup() -> str:
    marker = backup_marker()
    if not marker.exists():
        raise HTTPException(status_code=400, detail=(
            "No database backup found. Make one first (Run-Backup-Now.cmd), then try again within an hour."))
    age = datetime.now() - datetime.fromtimestamp(marker.stat().st_mtime)
    if age > BACKUP_MAX_AGE:
        raise HTTPException(status_code=400, detail=(
            f"The last database backup is {int(age.total_seconds() // 3600)} hour(s) old. Make a fresh one "
            "(Run-Backup-Now.cmd), then try again within an hour."))
    return marker.read_text(encoding="utf-8", errors="replace").strip()[:200]


def _superadmin(db: Session, user_id: int, password: str) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not verify_password(str(password or ""), user.password_hash):
        raise HTTPException(status_code=403, detail="Password verification failed.")
    return user


def request(db: Session, user_id: int, purpose: str, password: str) -> WipeApproval:
    purpose = " ".join(str(purpose or "").split())
    if len(purpose) < 10:
        raise HTTPException(status_code=400, detail="Please describe the purpose (at least 10 characters).")
    _superadmin(db, user_id, password)
    row = WipeApproval(requested_by_user_id=user_id, purpose=purpose[:1000], requested_at=datetime.utcnow())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def approve(db: Session, request_id: int, user_id: int, password: str) -> WipeApproval:
    row = db.query(WipeApproval).filter(WipeApproval.id == request_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Wipe request not found.")
    if row.requested_by_user_id == user_id:
        raise HTTPException(status_code=403, detail="A different superadmin must approve this wipe request.")
    if row.approved_at is not None or row.used_at is not None:
        raise HTTPException(status_code=409, detail="This wipe request was already approved or used.")
    if datetime.utcnow() - row.requested_at > VALID_FOR:
        raise HTTPException(status_code=400, detail="This wipe request is older than 24 hours. Ask again.")
    _superadmin(db, user_id, password)
    row.approved_by_user_id = user_id
    row.approved_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def use(db: Session, request_id: int | None, user_id: int) -> WipeApproval:
    """Check the approval for the wipe about to run and mark it used (not committed here)."""
    if not request_id:
        raise HTTPException(status_code=400, detail=(
            "A wipe needs a request approved by another superadmin (wipe_request_id)."))
    row = db.query(WipeApproval).filter(WipeApproval.id == request_id).first()
    if row is None or row.requested_by_user_id != user_id:
        raise HTTPException(status_code=403, detail="Use a wipe request you made yourself.")
    if row.approved_at is None or not row.approved_by_user_id:
        raise HTTPException(status_code=400, detail="This wipe request is not approved by another superadmin yet.")
    if row.used_at is not None:
        raise HTTPException(status_code=409, detail="This wipe request was already used.")
    if datetime.utcnow() - row.approved_at > VALID_FOR:
        raise HTTPException(status_code=400, detail="The approval is older than 24 hours. Ask again.")
    row.used_at = datetime.utcnow()
    return row


def serialize(row: WipeApproval) -> dict:
    return {
        "id": row.id,
        "requested_by_user_id": row.requested_by_user_id,
        "purpose": row.purpose,
        "requested_at": row.requested_at.isoformat() if row.requested_at else None,
        "approved_by_user_id": row.approved_by_user_id,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "used_at": row.used_at.isoformat() if row.used_at else None,
    }
