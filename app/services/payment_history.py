"""The story of one payment, and who may approve it again after it was moved back.

Built from the audit log (nothing new is stored): created → proof → approved → moved back
(reason) → changed (old → new) → proof replaced → approved again. A bulk payment's story
includes its own entries and those of each of its months.

Two-person rule for a payment that was approved once and moved back: whoever moved it back,
or changed it (edit or new proof) since it was last approved, may not approve it again.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.models import AuditLog, BulkChallanGroup, Challan, User, UserRole

STAFF_ROLES = (UserRole.ADMIN, UserRole.SUPERADMIN, UserRole.EXECUTIVE)

APPROVE_ACTIONS = ("challan_approve", "bulk_approve")
CHANGE_ACTIONS = ("challan_revert", "bulk_revert", "challan_update", "challan_proof_upload", "challan_reject", "bulk_reject")

LABELS = {
    "challan_create": "Payment started",
    "challan_admin_record": "Payment entered by an admin",
    "challan_history_import": "Added from the old records",
    "bulk_create": "Payment started (several months)",
    "bulk_pay_together": "Months joined into one payment",
    "challan_proof_upload": "Proof uploaded",
    "challan_update": "Details changed",
    "challan_approve": "Approved",
    "bulk_approve": "Approved",
    "challan_reject": "Rejected",
    "bulk_reject": "Rejected",
    "challan_revert": "Moved back for checking",
    "bulk_revert": "Moved back for checking",
    "challan_unfinished_remind": "Reminder sent to the member",
    "challan_join": "Joined into one payment",
}
FIELD_NAMES = {
    "amount": "Amount", "month": "Month", "campaign_id": "Campaign", "payment_method": "Paid by",
    "received_on": "Date received", "transaction_ref": "Reference", "received_amount": "Amount received",
}


def _group_of(db: Session, challan: Optional[Challan]) -> Optional[BulkChallanGroup]:
    if challan is None or not challan.bulk_group_id:
        return None
    return db.query(BulkChallanGroup).filter(BulkChallanGroup.bulk_group_id == challan.bulk_group_id).first()


def _challans_of(db: Session, group: BulkChallanGroup) -> list[Challan]:
    return db.query(Challan).filter(Challan.bulk_group_id == group.bulk_group_id).all()


def _rows(db: Session, challan_ids: Iterable[int], group_id: Optional[int]):
    challan_ids = list({int(i) for i in challan_ids})
    clauses = []
    if challan_ids:
        clauses.append(and_(AuditLog.entity_type == "Challan", AuditLog.entity_id.in_(challan_ids)))
    if group_id is not None:
        clauses.append(and_(AuditLog.entity_type == "BulkChallanGroup", AuditLog.entity_id == group_id))
    if not clauses:
        return []
    return db.query(AuditLog).filter(or_(*clauses)).order_by(AuditLog.id.asc()).all()


def _scope(db: Session, challan: Optional[Challan], group: Optional[BulkChallanGroup]):
    if group is None:
        group = _group_of(db, challan)
    challans = _challans_of(db, group) if group is not None else ([challan] if challan is not None else [])
    return challans, group


def _load(value) -> dict:
    if not value:
        return {}
    try:
        data = json.loads(value) if isinstance(value, str) else value
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


# ------------------------------------------------------------------ two-person rule

def people_who_changed_it(db: Session, challans: list[Challan], group: Optional[BulkChallanGroup]) -> set[int]:
    """Users who moved back or changed this payment since it was last approved (only when it
    was approved once and moved back; empty otherwise)."""
    was_moved_back = any(c.reversed_at is not None for c in challans) or (
        group is not None and group.reversed_at is not None)
    if not was_moved_back:
        return set()
    rows = _rows(db, [c.id for c in challans], group.id if group is not None else None)
    last_approval = max((r.id for r in rows if r.action in APPROVE_ACTIONS), default=0)
    people = {r.user_id for r in rows if r.id > last_approval and r.action in CHANGE_ACTIONS and r.user_id}
    for c in challans:
        if c.reversed_by_admin_id:
            people.add(int(c.reversed_by_admin_id))
    if group is not None and group.reversed_by_admin_id:
        people.add(int(group.reversed_by_admin_id))
    return {int(p) for p in people}


def assert_can_approve_again(db: Session, user_id: Optional[int], challans: list[Challan],
                             group: Optional[BulkChallanGroup] = None) -> None:
    if user_id is None:
        return
    if int(user_id) in people_who_changed_it(db, challans, group):
        raise HTTPException(
            status_code=403,
            detail="You moved this payment back or changed it, so a different admin must check and approve it again.",
        )


def assert_date_for_approve_again(challans: list[Challan], group: Optional[BulkChallanGroup], verification) -> None:
    """A payment approved again needs the date the money came in, so it stays in the right month."""
    was_moved_back = any(c.reversed_at is not None for c in challans) or (
        group is not None and group.reversed_at is not None)
    if not was_moved_back:
        return
    if verification is not None and getattr(verification, "received_on", None):
        return
    has_date = (group.received_on if group is not None else None) or all(c.received_on for c in challans)
    if not has_date:
        raise HTTPException(
            status_code=400,
            detail="This payment was moved back before. Enter the date the money was received, so it is counted in the right month.",
        )


# ------------------------------------------------------------------ history

def _who(user: Optional[User], viewer_id: Optional[int], viewer_is_staff: bool) -> Optional[str]:
    if user is None:
        return None
    if viewer_id is not None and int(user.id) == int(viewer_id):
        return "You"
    if viewer_is_staff:
        return user.actor_label
    return "the committee" if user.role in STAFF_ROLES else user.actor_label


def _changes(old: dict, new: dict) -> list[dict]:
    out = []
    for key, label in FIELD_NAMES.items():
        if key in new and key in old and old.get(key) != new.get(key):
            out.append({"field": label, "from": old.get(key), "to": new.get(key)})
        elif key in new and key not in old and new.get(key) is not None and old:
            out.append({"field": label, "from": None, "to": new.get(key)})
    return out


def history(db: Session, *, challan: Optional[Challan] = None, group: Optional[BulkChallanGroup] = None,
            viewer_id: Optional[int] = None, viewer_is_staff: bool = False) -> dict:
    challans, group = _scope(db, challan, group)
    rows = _rows(db, [c.id for c in challans], group.id if group is not None else None)
    if not viewer_is_staff:
        rows = [r for r in rows if r.action != "challan_unfinished_remind"]
    user_ids = {r.user_id for r in rows if r.user_id}
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}

    steps = []
    seen_bulk_keys = set()
    proof_seen = False
    for r in rows:
        if r.action not in LABELS:
            continue
        old, new = _load(r.old_values), _load(r.new_values)
        # One step for a whole bulk payment: its months each log the same action at once.
        key = (r.action, r.user_id, str(r.created_at)[:16]) if group is not None and r.entity_type == "Challan" else None
        if key is not None:
            if key in seen_bulk_keys:
                continue
            seen_bulk_keys.add(key)
        label = LABELS[r.action]
        if r.action == "challan_proof_upload":
            label = "New proof uploaded" if proof_seen else "Proof uploaded"
            proof_seen = True
        if r.action in APPROVE_ACTIONS and any(s["action"] in APPROVE_ACTIONS for s in steps):
            label = "Approved again"
        step = {
            "id": r.id,
            "action": r.action,
            "label": label,
            "at": r.created_at.isoformat() if isinstance(r.created_at, datetime) else r.created_at,
            "by": _who(users.get(r.user_id), viewer_id, viewer_is_staff),
            "reason": new.get("reason") or new.get("rejection_reason"),
            "changes": _changes(old, new) if r.action == "challan_update" else [],
        }
        if r.action in APPROVE_ACTIONS and new.get("received_on"):
            step["received_on"] = new.get("received_on")
        steps.append(step)

    first = challans[0] if challans else None
    if first is not None and not any(s["action"] in ("challan_create", "challan_admin_record", "challan_history_import",
                                                    "bulk_create", "bulk_pay_together") for s in steps):
        created = group.created_at if group is not None else first.created_at
        steps.insert(0, {
            "id": 0, "action": "created", "label": "Payment started",
            "at": created.isoformat() if isinstance(created, datetime) else created,
            "by": None, "reason": None, "changes": [],
        })
    number = (group.challan_no or group.bulk_group_id) if group is not None else (
        (first.challan_no or f"CH-{first.id}") if first is not None else None)
    return {"number": number, "steps": steps,
            "moved_back": any(s["action"] in ("challan_revert", "bulk_revert") for s in steps)}
