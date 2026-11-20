"""Payment receipts.

One receipt per approved payment: a single challan, or a bulk payment (several months with
one proof) as a whole. The receipt number is the payment number (PG-2627-0042; older
payments show CH-<id> / BCH-xxxx).

Every receipt has a public verification link (/r/<token>). The token carries a signature
made with the server's secret, so links cannot be guessed or made up; the page shows the
receipt as valid (or no longer valid, if the payment was reverted) with the member's name
shortened, so a forwarded link reveals little.
"""
from __future__ import annotations

import hashlib
import json
import hmac
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.models.models import BulkChallanGroup, Challan, ChallanStatus, ChallanType, User
from app.services.settings_service import get_setting, org_name
from app.utils.timezone import to_business


def _mac(kind: str, item_id: int) -> str:
    key = (settings.SECRET_KEY or "").encode()
    return hmac.new(key, f"receipt:{kind}:{item_id}".encode(), hashlib.sha256).hexdigest()[:20]


def token_for(kind: str, item_id: int) -> str:
    return f"{kind}{int(item_id)}-{_mac(kind, item_id)}"


def parse_token(token: str) -> Optional[tuple[str, int]]:
    try:
        head, mac = str(token).split("-", 1)
        kind, item_id = head[0], int(head[1:])
    except (ValueError, IndexError):
        return None
    if kind not in ("c", "g") or not hmac.compare_digest(mac, _mac(kind, item_id)):
        return None
    return kind, item_id


def verify_url(token: str) -> str:
    from app.utils.invite_share import _normalize_base_url

    return f"{_normalize_base_url()}/r/{token}"


def _status(value) -> str:
    return getattr(value, "value", value) or ""


def _date(value) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "hour"):
        return to_business(value).date().isoformat()
    return value.isoformat()


def _name(db: Session, user_id: Optional[int]) -> Optional[str]:
    """The approving admin's short code (A12), never their name."""
    if not user_id:
        return None
    from app.utils.admin_codes import admin_code

    return admin_code(db, user_id)


def short_name(name: Optional[str]) -> str:
    """'Amina Kutty' -> 'Amina K.' for the public page."""
    parts = str(name or "").split()
    if not parts:
        return "Member"
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1][0]}."


def _member_name(member) -> str:
    if member is None:
        return "Member"
    return member.full_name or (member.user.full_name if member.user is not None else None) or member.member_code


def _base(db: Session) -> dict:
    return {"organisation": org_name(db), "logo_url": get_setting(db, "org_logo_url") or None}


def _for_group(db: Session, group: BulkChallanGroup) -> dict:
    rows = db.query(Challan).filter(Challan.bulk_group_id == group.bulk_group_id).all()
    months = sorted({c.month for c in rows if c.month}) or json.loads(group.months_list or "[]")
    member = rows[0].member if rows else None
    if member is None:
        from app.models.models import Member

        member = db.query(Member).filter(Member.id == group.member_id).first()
    valid = group.status == "approved"
    token = token_for("g", group.id)
    return {
        **_base(db),
        "kind": "bulk",
        "number": group.challan_no or group.bulk_group_id,
        "valid": valid,
        "status": group.status,
        "member_id": group.member_id,
        "member_code": member.member_code if member is not None else None,
        "member_name": _member_name(member),
        "member_phone": (member.user.phone if member is not None and member.user is not None else None),
        "type": "monthly",
        "months": months,
        "campaign_title": None,
        "amount": float(group.total_amount or 0),
        "received_amount": group.received_amount,
        "received_on": _date(group.received_on) or _date(group.approved_at),
        "payment_method": group.payment_method,
        "transaction_ref": group.transaction_ref,
        "approved_on": _date(group.approved_at),
        "approved_by": _name(db, group.approved_by_admin_id),
        "token": token,
        "verify_url": verify_url(token),
    }


def _for_challan(db: Session, challan: Challan) -> dict:
    member = challan.member
    is_campaign = challan.type == ChallanType.CAMPAIGN
    token = token_for("c", challan.id)
    return {
        **_base(db),
        "kind": "single",
        "number": challan.challan_no or f"CH-{challan.id}",
        "valid": _status(challan.status) == ChallanStatus.APPROVED.value,
        "status": _status(challan.status),
        "member_id": challan.member_id,
        "member_code": member.member_code if member is not None else None,
        "member_name": _member_name(member),
        "member_phone": (member.user.phone if member is not None and member.user is not None else None),
        "type": "campaign" if is_campaign else "monthly",
        "months": [challan.month] if challan.month else [],
        "campaign_title": challan.campaign.title if is_campaign and challan.campaign is not None else None,
        "amount": float(challan.amount or 0),
        "received_amount": challan.received_amount,
        "received_on": _date(challan.received_on) or _date(challan.approved_at),
        "payment_method": challan.payment_method,
        "transaction_ref": challan.transaction_ref,
        "approved_on": _date(challan.approved_at),
        "approved_by": _name(db, challan.approved_by_admin_id),
        "token": token,
        "verify_url": verify_url(token),
    }


def for_challan(db: Session, challan: Challan) -> dict:
    """The receipt this challan belongs to (its bulk payment's receipt when it is part of one)."""
    if challan.bulk_group_id:
        group = db.query(BulkChallanGroup).filter(BulkChallanGroup.bulk_group_id == challan.bulk_group_id).first()
        if group is not None:
            return _for_group(db, group)
    return _for_challan(db, challan)


def for_group(db: Session, group: BulkChallanGroup) -> dict:
    return _for_group(db, group)


def link_for_challans(db: Session, challans) -> Optional[str]:
    """Verification link for the receipt of these just-approved challans (WhatsApp message)."""
    if not challans:
        return None
    try:
        return for_challan(db, challans[0])["verify_url"]
    except Exception:
        return None


def public_view(db: Session, token: str) -> dict:
    parsed = parse_token(token)
    if parsed is None:
        raise HTTPException(status_code=404, detail="This receipt link is not valid.")
    kind, item_id = parsed
    if kind == "g":
        group = db.query(BulkChallanGroup).filter(BulkChallanGroup.id == item_id).first()
        data = _for_group(db, group) if group is not None else None
    else:
        challan = db.query(Challan).filter(Challan.id == item_id).first()
        data = _for_challan(db, challan) if challan is not None else None
    if data is None:
        raise HTTPException(status_code=404, detail="This receipt was not found.")
    keep = ("organisation", "logo_url", "number", "valid", "type", "months", "campaign_title", "amount",
            "received_on", "approved_on")
    out = {k: data[k] for k in keep}
    out["member_name"] = short_name(data["member_name"])
    out["member_code"] = data["member_code"]
    return out


# ---------------------------------------------------------------- receipts list (admins)
def list_receipts(db: Session, *, search: Optional[str] = None, date_from=None, date_to=None,
                  kind: str = "all", method: Optional[str] = None, checked_by: Optional[str] = None,
                  skip: int = 0, limit: int = 50) -> dict:
    """Every receipt (approved payment), newest first, with search and filters.

    One row per receipt: a single approved challan, or an approved bulk payment as a whole.
    Dates are the day the money was received (or approved, for older payments), India time.
    """
    from sqlalchemy.orm import joinedload

    from app.models.models import Member
    from app.utils.admin_codes import code_from

    singles = (
        db.query(Challan)
        .options(joinedload(Challan.member).joinedload(Member.user), joinedload(Challan.campaign))
        .filter(Challan.status == ChallanStatus.APPROVED, Challan.bulk_group_id.is_(None))
        .all()
    )
    groups = db.query(BulkChallanGroup).filter(BulkChallanGroup.status == "approved").all()
    member_ids = {g.member_id for g in groups}
    members = {m.id: m for m in db.query(Member).options(joinedload(Member.user)).filter(Member.id.in_(member_ids)).all()} if member_ids else {}
    admin_ids = {c.approved_by_admin_id for c in singles} | {g.approved_by_admin_id for g in groups}
    admin_ids.discard(None)
    admin_members = dict(db.query(Member.user_id, Member.member_code).filter(Member.user_id.in_(admin_ids)).all()) if admin_ids else {}
    code_of = {uid: code_from(admin_members.get(uid), uid) for uid in admin_ids}

    def day(received, approved):
        value = received or approved
        if value is None:
            return None
        return to_business(value).date() if hasattr(value, "hour") else value

    rows = []
    for c in singles:
        m = c.member
        campaign = c.type == ChallanType.CAMPAIGN
        rows.append({
            "kind": "single", "challan_id": c.id, "bulk_group_id": None,
            "number": c.challan_no or f"CH-{c.id}",
            "member_code": m.member_code if m is not None else None, "member_name": _member_name(m),
            "type": "campaign" if campaign else "monthly",
            "months": [c.month] if c.month else [],
            "campaign_title": c.campaign.title if campaign and c.campaign is not None else None,
            "amount": float(c.amount or 0), "received_amount": c.received_amount,
            "date": day(c.received_on, c.approved_at), "payment_method": c.payment_method,
            "transaction_ref": c.transaction_ref, "checked_by": code_of.get(c.approved_by_admin_id),
        })
    for g in groups:
        m = members.get(g.member_id)
        rows.append({
            "kind": "bulk", "challan_id": None, "bulk_group_id": g.bulk_group_id,
            "number": g.challan_no or g.bulk_group_id,
            "member_code": m.member_code if m is not None else None, "member_name": _member_name(m),
            "type": "monthly", "months": sorted(json.loads(g.months_list or "[]")), "campaign_title": None,
            "amount": float(g.total_amount or 0), "received_amount": g.received_amount,
            "date": day(g.received_on, g.approved_at), "payment_method": g.payment_method,
            "transaction_ref": g.transaction_ref, "checked_by": code_of.get(g.approved_by_admin_id),
        })

    all_codes = sorted({r["checked_by"] for r in rows if r["checked_by"]})
    term = (search or "").strip().lower()
    if term:
        rows = [r for r in rows if term in " ".join(str(v or "") for v in (
            r["number"], r["member_code"], r["member_name"], r["transaction_ref"], r["campaign_title"],
            " ".join(r["months"]))).lower()]
    if kind in ("monthly", "campaign"):
        rows = [r for r in rows if r["type"] == kind]
    if method:
        rows = [r for r in rows if (r["payment_method"] or "") == method]
    if checked_by:
        rows = [r for r in rows if (r["checked_by"] or "").lower() == checked_by.strip().lower()]
    if date_from:
        rows = [r for r in rows if r["date"] and r["date"] >= date_from]
    if date_to:
        rows = [r for r in rows if r["date"] and r["date"] <= date_to]

    rows.sort(key=lambda r: (r["date"] or date_min(), r["number"]), reverse=True)
    total_amount = round(sum(float(r["received_amount"] if r["received_amount"] is not None else r["amount"]) for r in rows), 2)
    page = rows[skip: skip + limit]
    for r in page:
        r["date"] = r["date"].isoformat() if r["date"] else None
    return {
        "total": len(rows), "total_amount": total_amount, "items": page,
        "checked_by_codes": all_codes,
    }


def date_min():
    from datetime import date

    return date.min
