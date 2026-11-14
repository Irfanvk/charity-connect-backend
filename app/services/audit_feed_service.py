"""Audit log feed for the Audit Logs page: server-side filters, pages, readable names and changes.

Entity types were written with mixed spelling over time ("Challan" / "challan",
"MemberRequest" / "member_request"), so everything is compared on a normalised key.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import Session, joinedload

from app.models import AuditLog, User
from app.models import models as m
from app.utils.timezone import BUSINESS_TZ

# Area -> normalised entity types (lower case, no underscores)
AREAS: dict[str, tuple[str, set[str]]] = {
    "members": ("Members", {"member", "user", "memberactivation", "invite"}),
    "payments": ("Payments", {"challan"}),
    "bulk": ("Bulk payments", {"bulkchallangroup", "bulkchallan"}),
    "requests": ("Requests", {"memberrequest", "passwordresetrequest", "passwordreset"}),
    "campaigns": ("Campaigns", {"campaign"}),
    "funds": ("Fund use", {"fundutilization"}),
    "notifications": ("Notifications", {"notification"}),
    "reports": ("Reports", {"report"}),
    "settings": ("Settings & system", {"appsetting", "system"}),
}
ROLES = ("admin", "superadmin", "member", "system")
SENSITIVE_HINTS = ("password", "token", "secret", "hash")
MAX_LIMIT = 100


def _norm(entity_type: str | None) -> str:
    return str(entity_type or "").replace("_", "").replace(" ", "").lower()


def area_of(entity_type: str | None) -> str:
    key = _norm(entity_type)
    for area, (_, types) in AREAS.items():
        if key in types:
            return area
    return "other"


def _norm_column():
    return func.lower(func.replace(AuditLog.entity_type, "_", ""))


def _parse_day(value: str | None, *, end: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        day = datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date '{value}'. Expected YYYY-MM-DD.")
    if end:
        day += timedelta(days=1)
    # The dates are India-time days; created_at is stored as naive UTC.
    return day.replace(tzinfo=BUSINESS_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def _load_json(raw: str | None) -> dict:
    if not raw or not str(raw).strip():
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {"note": str(raw)}
    return value if isinstance(value, dict) else {"value": value}


def _redact(values: dict) -> dict:
    return {
        key: ("(hidden)" if any(h in str(key).lower() for h in SENSITIVE_HINTS) else value)
        for key, value in values.items()
    }


def changes_of(old: dict, new: dict) -> list[dict]:
    """[{field, before, after}] for every field that differs (or only appears on one side)."""
    out = []
    for key in list(dict.fromkeys([*old.keys(), *new.keys()])):
        before, after = old.get(key), new.get(key)
        if key in old and key in new and before == after:
            continue
        out.append({"field": key, "before": before if key in old else None, "after": after if key in new else None})
    return out


def _filtered_query(
    db: Session, *, user_id: int | None = None, role: str | None = None, area: str | None = None,
    action: str | None = None, start_date: str | None = None, end_date: str | None = None,
    search: str | None = None,
):
    query = db.query(AuditLog).outerjoin(User, User.id == AuditLog.user_id)
    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    if role:
        role = role.lower()
        if role not in ROLES:
            raise HTTPException(status_code=400, detail=f"role must be one of: {', '.join(ROLES)}")
        if role == "system":
            query = query.filter(AuditLog.user_id.is_(None))
        else:
            query = query.filter(func.lower(cast(User.role, String)) == role)
    if area:
        if area == "other":
            every = set().union(*(types for _, types in AREAS.values()))
            query = query.filter(~_norm_column().in_(every))
        elif area in AREAS:
            query = query.filter(_norm_column().in_(AREAS[area][1]))
        else:
            raise HTTPException(status_code=400, detail="Unknown area")
    if action:
        query = query.filter(AuditLog.action == action)
    start, end = _parse_day(start_date), _parse_day(end_date, end=True)
    if start:
        query = query.filter(AuditLog.created_at >= start)
    if end:
        query = query.filter(AuditLog.created_at < end)
    term = (search or "").strip()
    if term:
        like = f"%{term.lower()}%"
        query = query.filter(or_(
            func.lower(AuditLog.action).like(like),
            func.lower(AuditLog.entity_type).like(like),
            func.lower(func.coalesce(AuditLog.old_values, "")).like(like),
            func.lower(func.coalesce(AuditLog.new_values, "")).like(like),
            func.lower(func.coalesce(User.username, "")).like(like),
            func.lower(func.coalesce(User.full_name, "")).like(like),
        ))
    return query


def _month_label(month: str | None) -> str:
    try:
        return datetime.strptime(str(month), "%Y-%m").strftime("%b %Y")
    except (TypeError, ValueError):
        return str(month or "")


def _member_names(db: Session, member_ids: Iterable[int]) -> dict[int, str]:
    ids = {i for i in member_ids if i}
    if not ids:
        return {}
    rows = db.query(m.Member.id, m.Member.full_name, m.Member.member_code, User.full_name, User.username) \
        .outerjoin(User, User.id == m.Member.user_id).filter(m.Member.id.in_(ids)).all()
    return {mid: (name or uname or uuser or code or f"Member #{mid}") for mid, name, code, uname, uuser in rows}


def _target_names(db: Session, logs: list[AuditLog]) -> dict[int, str]:
    """Readable name of what each entry is about, looked up in batches per entity type."""
    by_type: dict[str, set[int]] = {}
    for log in logs:
        if log.entity_id:
            by_type.setdefault(_norm(log.entity_type), set()).add(int(log.entity_id))

    names: dict[tuple[str, int], str] = {}

    def rows(model, ids, *cols):
        return db.query(model.id, *cols).filter(model.id.in_(ids)).all() if ids else []

    member_ids = by_type.get("member", set())
    for mid, name in _member_names(db, member_ids).items():
        names[("member", mid)] = name
    for uid, full, uname in rows(User, by_type.get("user", set()), User.full_name, User.username):
        names[("user", uid)] = full or uname
    challans = rows(m.Challan, by_type.get("challan", set()), m.Challan.member_id, m.Challan.month, m.Challan.type)
    bulk = []
    for key in ("bulkchallangroup", "bulkchallan"):
        bulk += [(key, *r) for r in rows(m.BulkChallanGroup, by_type.get(key, set()), m.BulkChallanGroup.member_id,
                                         m.BulkChallanGroup.months_list)]
    requests = []
    for key in ("memberrequest",):
        requests += rows(m.MemberRequest, by_type.get(key, set()), m.MemberRequest.member_id, m.MemberRequest.subject)
    members = _member_names(db, [r[1] for r in challans] + [r[2] for r in bulk] + [r[1] for r in requests])
    for cid, mid, month, ctype in challans:
        kind = getattr(ctype, "value", ctype)
        label = _month_label(month) if month else ("Donation" if str(kind).lower() != "monthly" else "")
        names[("challan", cid)] = " · ".join(x for x in [members.get(mid), label] if x)
    for key, gid, mid, months in bulk:
        try:
            listed = json.loads(months) if isinstance(months, str) else (months or [])
        except ValueError:
            listed = []
        span = f"{_month_label(listed[0])} – {_month_label(listed[-1])}" if len(listed) > 1 else (
            _month_label(listed[0]) if listed else "")
        names[(key, gid)] = " · ".join(x for x in [members.get(mid), span] if x)
    for rid, mid, subject in requests:
        names[("memberrequest", rid)] = " · ".join(x for x in [members.get(mid), subject] if x)
    for key in ("passwordresetrequest", "passwordreset"):
        for pid, ident in rows(m.PasswordResetRequest, by_type.get(key, set()), m.PasswordResetRequest.identifier):
            names[(key, pid)] = f"Password reset for {ident}"
    for cid, title in rows(m.Campaign, by_type.get("campaign", set()), m.Campaign.title):
        names[("campaign", cid)] = title
    for fid, title in rows(m.FundUtilization, by_type.get("fundutilization", set()), m.FundUtilization.title):
        names[("fundutilization", fid)] = title
    for nid, title in rows(m.Notification, by_type.get("notification", set()), m.Notification.title):
        names[("notification", nid)] = title
    for iid, code in rows(m.Invite, by_type.get("invite", set()), m.Invite.invite_code):
        names[("invite", iid)] = f"Invite {code}"
    for aid, full in rows(m.MemberActivation, by_type.get("memberactivation", set()), m.MemberActivation.full_name):
        names[("memberactivation", aid)] = full

    out = {log.id: names.get((_norm(log.entity_type), int(log.entity_id or 0))) for log in logs}

    # The item may be gone (deleted); fall back to what the entry itself recorded.
    missing = [log for log in logs if not out.get(log.id)]
    recorded = {log.id: {**_load_json(log.old_values), **_load_json(log.new_values)} for log in missing}
    fallback_members = _member_names(db, [
        int(v["member_id"]) for v in recorded.values() if str(v.get("member_id") or "").isdigit()
    ])
    for log in missing:
        values = recorded[log.id]
        label = next((str(values[k]) for k in ("subject", "title", "full_name", "username", "identifier", "name")
                      if values.get(k)), None)
        member = fallback_members.get(int(values["member_id"])) if str(values.get("member_id") or "").isdigit() else None
        months = values.get("months") or ([values["month"]] if values.get("month") else [])
        if isinstance(months, list) and months:
            span = _month_label(months[0]) if len(months) == 1 else f"{_month_label(months[0])} – {_month_label(months[-1])}"
        else:
            span = None
        parts = [x for x in (member, span, label if label != member else None) if x]
        out[log.id] = " · ".join(parts) or None
    return out


def _serialize(log: AuditLog, target_name: str | None) -> dict:
    old, new = _redact(_load_json(log.old_values)), _redact(_load_json(log.new_values))
    return {
        "id": log.id,
        # Stored as naive UTC; send it marked as UTC so browsers convert it correctly.
        "created_at": log.created_at.replace(tzinfo=timezone.utc).isoformat() if log.created_at else None,
        "action": log.action,
        "area": area_of(log.entity_type),
        "entity_type": log.entity_type,
        "entity_id": log.entity_id,
        "target_name": target_name,
        "user_id": log.user_id,
        "performed_by_name": log.performed_by_name,
        "performed_by_role": log.performed_by_role,
        "old_values": old,
        "new_values": new,
        "changes": changes_of(old, new),
    }


def feed(db: Session, *, skip: int = 0, limit: int = 50, **filters) -> dict:
    limit = max(1, min(int(limit), MAX_LIMIT))
    query = _filtered_query(db, **filters)
    total = query.with_entities(func.count(AuditLog.id)).scalar() or 0
    by_role = dict(
        query.with_entities(func.lower(func.coalesce(cast(User.role, String), "system")), func.count(AuditLog.id))
        .group_by(func.lower(func.coalesce(cast(User.role, String), "system"))).all()
    )
    logs = (
        query.options(joinedload(AuditLog.user))
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(skip).limit(limit).all()
    )
    targets = _target_names(db, logs)
    actors = query.with_entities(func.count(func.distinct(AuditLog.user_id))).scalar() or 0
    return {
        "items": [_serialize(log, targets.get(log.id)) for log in logs],
        "total": int(total),
        "skip": int(skip),
        "limit": limit,
        "has_more": skip + len(logs) < total,
        "counts": {
            "admin": int(by_role.get("admin", 0)),
            "superadmin": int(by_role.get("superadmin", 0)),
            "actors": int(actors),
        },
    }


def filter_options(db: Session) -> dict:
    """Everyone who has an entry, every action recorded, and the areas, for the filter lists."""
    actor_rows = (
        db.query(User.id, User.full_name, User.username, User.role, func.count(AuditLog.id))
        .join(AuditLog, AuditLog.user_id == User.id)
        .group_by(User.id, User.full_name, User.username, User.role)
        .all()
    )
    actors = sorted(
        (
            {"user_id": uid, "name": full or uname, "role": str(getattr(role, "value", role) or "").lower(), "count": n}
            for uid, full, uname, role, n in actor_rows
        ),
        key=lambda a: (a["role"] != "superadmin", a["role"] != "admin", str(a["name"]).lower()),
    )
    actions = [
        {"action": action, "count": n}
        for action, n in db.query(AuditLog.action, func.count(AuditLog.id)).group_by(AuditLog.action).all()
    ]
    area_counts: dict[str, int] = {}
    for entity_type, n in db.query(AuditLog.entity_type, func.count(AuditLog.id)).group_by(AuditLog.entity_type).all():
        area = area_of(entity_type)
        area_counts[area] = area_counts.get(area, 0) + n
    areas = [{"area": key, "label": label, "count": area_counts.get(key, 0)} for key, (label, _) in AREAS.items()]
    if area_counts.get("other"):
        areas.append({"area": "other", "label": "Other", "count": area_counts["other"]})
    system = db.query(func.count(AuditLog.id)).filter(AuditLog.user_id.is_(None)).scalar() or 0
    return {"actors": actors, "actions": actions, "areas": areas, "system_count": int(system)}


def _local_time(iso: str | None) -> str:
    if not iso:
        return ""
    return datetime.fromisoformat(iso).astimezone(BUSINESS_TZ).strftime("%Y-%m-%d %H:%M")


def as_csv_rows(items: list[dict]) -> list[list[Any]]:
    return [
        [_local_time(i["created_at"]), i["performed_by_name"], i["performed_by_role"] or "", i["action"], i["area"],
         i["target_name"] or f"{i['entity_type']} #{i['entity_id']}",
         "; ".join(f"{c['field']}: {c['before']} -> {c['after']}" for c in i["changes"])]
        for i in items
    ]
