"""Occasion banners: an image (plus optional message and button) shown on the login page and/or
the members' and admins' dashboards between a start and an end time.

Any admin or superadmin can create, edit, pause or delete a banner; it shows from its start
time with no approval step. Every change is written to the audit log.
Times are stored as naive UTC; the app sends them with their offset (India time).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from sqlalchemy.orm import Session

from app.models import AuditLog, Banner

MAX_DAYS = 400           # a banner can run at most about a year
MAX_ACTIVE_PER_PLACE = 5  # more than this in one slideshow is too many to read


def _utc(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Start and end must be valid dates and times")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _iso(dt: datetime | None) -> str | None:
    return dt.replace(tzinfo=timezone.utc).isoformat() if dt else None


def _now() -> datetime:
    return datetime.utcnow()


def _status(b: Banner, now: datetime) -> str:
    if not b.is_active:
        return "paused"
    if b.ends_at <= now:
        return "past"
    if b.starts_at > now:
        return "scheduled"
    return "active"


def serialize(b: Banner, now: datetime | None = None, full: bool = True) -> dict:
    now = now or _now()
    out = {
        "id": b.id,
        "title": b.title,
        "message": b.message,
        "image_url": b.image_url,
        "button_label": b.button_label,
        "button_link": b.button_link,
        "ends_at": _iso(b.ends_at),
        "updated_at": _iso(b.updated_at) if b.updated_at else None,
    }
    if full:
        out.update({
            "show_on_login": b.show_on_login,
            "show_to_members": b.show_to_members,
            "show_to_admins": b.show_to_admins,
            "starts_at": _iso(b.starts_at),
            "is_active": b.is_active,
            "status": _status(b, now),
            "created_at": _iso(b.created_at) if b.created_at else None,
            "created_by_name": b.created_by.actor_label if b.created_by else None,
            "updated_by_name": b.updated_by.actor_label if b.updated_by else None,
        })
    return out


def _clean(value, limit: int, field: str) -> str | None:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        raise HTTPException(status_code=400, detail=f"{field} can be at most {limit} characters")
    return text or None


def _link(value) -> str | None:
    link = str(value or "").strip()
    if not link:
        return None
    if link.startswith("/") and not link.startswith("//") and "\\" not in link:
        return link
    if link.lower().startswith("https://"):
        return link
    raise HTTPException(status_code=400, detail="The button link must be an app page (starting with /) or an https:// link")


def _image(value) -> str:
    url = str(value or "").strip()
    if not (url.startswith("https://") or url.startswith("/uploads/") or url.startswith("uploads/")):
        raise HTTPException(status_code=400, detail="Please upload the banner image")
    return url


def _apply(b: Banner, data: dict) -> None:
    title = _clean(data.get("title"), 120, "Title")
    if not title:
        raise HTTPException(status_code=400, detail="Give the banner a title")
    b.title = title
    b.message = _clean(data.get("message"), 300, "Message")
    b.image_url = _image(data.get("image_url"))
    b.button_label = _clean(data.get("button_label"), 40, "Button text")
    b.button_link = _link(data.get("button_link"))
    if bool(b.button_label) != bool(b.button_link):
        raise HTTPException(status_code=400, detail="A button needs both its text and where it goes")
    b.show_on_login = bool(data.get("show_on_login"))
    b.show_to_members = bool(data.get("show_to_members"))
    b.show_to_admins = bool(data.get("show_to_admins"))
    if not (b.show_on_login or b.show_to_members or b.show_to_admins):
        raise HTTPException(status_code=400, detail="Choose at least one place to show the banner")
    b.starts_at = _utc(data.get("starts_at"))
    b.ends_at = _utc(data.get("ends_at"))
    if b.ends_at <= b.starts_at:
        raise HTTPException(status_code=400, detail="The end must be after the start")
    if b.ends_at - b.starts_at > timedelta(days=MAX_DAYS):
        raise HTTPException(status_code=400, detail="A banner can run for at most a year")
    if "is_active" in data and data["is_active"] is not None:
        b.is_active = bool(data["is_active"])


def _audit(db: Session, user: dict, action: str, b: Banner, extra: dict | None = None) -> None:
    db.add(AuditLog(user_id=int(user["user_id"]), action=action, entity_type="Banner", entity_id=b.id or 0,
                    new_values=json.dumps({"title": b.title, **(extra or {})}, default=str)))


def _require_admin(user: dict) -> None:
    if str(user.get("role", "")).lower() not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin access required")


def create(db: Session, user: dict, data: dict) -> dict:
    _require_admin(user)
    b = Banner(created_by_user_id=int(user["user_id"]), updated_by_user_id=int(user["user_id"]), is_active=True)
    _apply(b, data)
    db.add(b)
    db.flush()
    _audit(db, user, "banner_create", b, {"starts_at": b.starts_at, "ends_at": b.ends_at})
    db.commit()
    db.refresh(b)
    return serialize(b)


def update(db: Session, user: dict, banner_id: int, data: dict) -> dict:
    _require_admin(user)
    b = db.query(Banner).filter(Banner.id == banner_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Banner not found")
    merged = {**serialize(b), **{k: v for k, v in data.items() if v is not None or k in ("message", "button_label", "button_link")}}
    _apply(b, merged)
    b.updated_by_user_id = int(user["user_id"])
    _audit(db, user, "banner_update", b, {"is_active": b.is_active, "starts_at": b.starts_at, "ends_at": b.ends_at})
    db.commit()
    db.refresh(b)
    return serialize(b)


def delete(db: Session, user: dict, banner_id: int) -> None:
    _require_admin(user)
    b = db.query(Banner).filter(Banner.id == banner_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Banner not found")
    _audit(db, user, "banner_delete", b)
    db.delete(b)
    db.commit()


def list_all(db: Session, user: dict) -> dict:
    _require_admin(user)
    now = _now()
    rows = db.query(Banner).order_by(Banner.starts_at.desc()).all()
    items = [serialize(b, now) for b in rows]
    counts = {s: sum(1 for i in items if i["status"] == s) for s in ("active", "scheduled", "paused", "past")}
    return {"items": items, "counts": counts, "max_per_place": MAX_ACTIVE_PER_PLACE}


def active(db: Session, place: str, role: str | None = None) -> list[dict]:
    """Banners showing right now: place 'login' (anyone) or 'dashboard' (by the viewer's role)."""
    now = _now()
    query = db.query(Banner).filter(Banner.is_active.is_(True), Banner.starts_at <= now, Banner.ends_at > now)
    if place == "login":
        query = query.filter(Banner.show_on_login.is_(True))
    elif place == "dashboard":
        if role in ("admin", "superadmin", "executive"):
            query = query.filter(Banner.show_to_admins.is_(True))
        elif role == "member":
            query = query.filter(Banner.show_to_members.is_(True))
        else:
            return []
    else:
        raise HTTPException(status_code=400, detail="place must be login or dashboard")
    rows = query.order_by(Banner.starts_at.desc()).limit(MAX_ACTIVE_PER_PLACE).all()
    return [serialize(b, now, full=False) for b in rows]
