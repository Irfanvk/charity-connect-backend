"""Centralized audit-log helper.

Usage::

    from app.utils.audit import log_audit

    log_audit(
        db,
        user_id=current_user["user_id"],
        action="challan_approve",
        entity_type="Challan",
        entity_id=challan.id,
        new_values={"status": "approved"},
    )

The helper serialises *old_values* / *new_values* to JSON automatically when
they are passed as dicts, and silently tolerates ``None`` values.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.models import AuditLog


def log_audit(
    db: Session,
    *,
    user_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | str = 0,
    old_values: dict[str, Any] | str | None = None,
    new_values: dict[str, Any] | str | None = None,
    ip_address: str | None = None,
    auto_commit: bool = False,
) -> AuditLog:
    """Create an ``AuditLog`` row and flush it to the session.

    Parameters
    ----------
    db:
        Active SQLAlchemy session.
    user_id:
        The user performing the action (``None`` for system-level events).
    action:
        Short verb describing the operation, e.g. ``"challan_approve"``.
    entity_type:
        The entity/table affected, e.g. ``"Challan"``, ``"Campaign"``.
    entity_id:
        PK of the affected row.  Defaults to ``0`` for system-level entries.
    old_values / new_values:
        Optional state snapshots.  Dicts are JSON-serialised automatically.
    ip_address:
        Optional client IP.
    auto_commit:
        When ``True`` the helper calls ``db.commit()`` after adding the log.
        Normally the caller commits as part of its own transaction.
    """

    def _serialise(val: dict | str | None) -> str | None:
        if val is None:
            return None
        if isinstance(val, str):
            return val
        return json.dumps(val, default=str)

    entry = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=int(entity_id) if entity_id is not None else 0,
        old_values=_serialise(old_values),
        new_values=_serialise(new_values),
        ip_address=ip_address,
    )
    db.add(entry)
    if auto_commit:
        db.commit()
    return entry
