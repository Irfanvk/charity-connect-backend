"""Relief fund for GCC members: death, serious illness or retirement.

Scheme rules (from the committee):
  1. Only GCC members (expatriates) of the Jamaath.
  2. Monthly fees paid on time; more than 3 unpaid months = not eligible.
  3. Death or serious illness (heart attack, kidney failure, cancer, stroke), after at least
     6 months of membership.
  4. A written application, checked and confirmed by the GCC admins.
  5. Death Rs 50,000; serious illness at least Rs 40,000; or Rs 40,000 on returning home after
     at least 10 years of Gulf service.
  Special note: the Aug 2024 - Mar 2025 fees must be fully paid.

How the app applies them:
  - Rules about the member (unpaid months, months as member, Aug 2024 - Mar 2025, lives abroad,
    years of Gulf service) are WARNINGS: approvers see them and decide.
  - Hard rules: the required documents, an amount not below the default, one claim per reason
    per member, and N approvals (default 3) from admins other than the creator; any one
    rejection stops the claim.
  - The last approval adds an approved "Relief" entry to Fund use; an admin then marks it paid.
"""
from __future__ import annotations

import json
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import func, or_, true
from sqlalchemy.orm import Session, joinedload

from app.models import AuditLog, Challan, FundUtilization, Member, ReliefApproval, ReliefClaim, User
from app.models.models import ChallanType, UserRole
from app.services import report_service as rs
from app.services.notification_service import NotificationService
from app.services.settings_service import get_setting
from app.utils.admin_codes import actor_label_for, actor_labels
from app.utils.timezone import today_business

REASONS = ("death", "illness", "retirement")
ILLNESSES = ("heart_attack", "kidney_failure", "cancer", "stroke")
STATUSES = ("pending", "approved", "rejected", "paid", "cancelled")
ACTIVE = ("pending", "approved", "paid")
PAY_METHODS = ("cash", "bank_transfer", "upi", "cheque")
# Documents each claim needs before it can go for approval.
REQUIRED_DOCS = {
    "death": ("application", "death_certificate"),
    "illness": ("application", "medical_report"),
    "retirement": ("application", "gulf_proof"),
}
DOC_KINDS = ("application", "death_certificate", "medical_report", "gulf_proof", "other")
REASON_LABEL = {"death": "Death", "illness": "Serious illness", "retirement": "Retirement"}


def _is_admin(user: dict) -> bool:
    return str(user.get("role", "")).lower() in ("admin", "superadmin")


def _require_admin(user: dict) -> None:
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required")


def _int_setting(db: Session, key: str) -> int:
    return int(get_setting(db, key))


def default_amount(db: Session, reason: str) -> float:
    return float(_int_setting(db, f"relief_amount_{reason}"))


def scheme(db: Session) -> dict:
    """The numbers the rules page and forms show."""
    return {
        "amounts": {r: default_amount(db, r) for r in REASONS},
        "required_approvals": _int_setting(db, "relief_required_approvals"),
        "max_unpaid_months": _int_setting(db, "relief_max_unpaid_months"),
        "min_membership_months": _int_setting(db, "relief_min_membership_months"),
        "min_gulf_years": _int_setting(db, "relief_min_gulf_years"),
        "required_documents": {k: list(v) for k, v in REQUIRED_DOCS.items()},
        "illnesses": list(ILLNESSES),
    }


# ----------------------------------------------------------------- eligibility
def _membership_months(member: Member, today: date) -> int:
    if not member.join_date:
        start = rs.PLATFORM_START
    else:
        start = rs.to_business(member.join_date).date()
    months = (today.year - start.year) * 12 + today.month - start.month
    if today.day < start.day:
        months -= 1
    return max(0, months)


def eligibility(db: Session, member: Member, reason: str | None = None,
                gulf_from_year: int | None = None, gulf_to_year: int | None = None) -> dict:
    """Each rule as {key, ok (True/False/None = not needed), value, limit}; ok False = a warning."""
    today = today_business()
    this_month = rs._month(today.replace(day=1))
    challans = db.query(Challan).filter(Challan.member_id == member.id, Challan.type == ChallanType.MONTHLY).all()
    rows = rs._month_rows(member, challans, rs._start_month(member), today.replace(day=1))
    unpaid = [r["month"] for r in rows if r["state"] == "not_paid" and r["month"] < this_month]
    max_unpaid = _int_setting(db, "relief_max_unpaid_months")
    min_months = _int_setting(db, "relief_min_membership_months")
    min_years = _int_setting(db, "relief_min_gulf_years")
    months_member = _membership_months(member, today)

    checks = [
        {"key": "unpaid_months", "ok": len(unpaid) <= max_unpaid, "value": len(unpaid), "limit": max_unpaid,
         "months": unpaid},
        {"key": "membership_months",
         "ok": None if reason == "retirement" else months_member >= min_months,
         "value": months_member, "limit": min_months},
        {"key": "lives_abroad",
         "ok": None if reason == "retirement" else bool(member.country and member.country != "IN"),
         "value": member.country, "limit": None},
    ]
    if reason == "retirement":
        years = (gulf_to_year - gulf_from_year) if gulf_from_year and gulf_to_year else None
        checks.append({"key": "gulf_years", "ok": years is not None and years >= min_years,
                       "value": years, "limit": min_years})

    earlier = (
        db.query(ReliefClaim)
        .filter(ReliefClaim.member_id == member.id, ReliefClaim.status.in_(ACTIVE))
        .order_by(ReliefClaim.created_at.desc())
        .all()
    )
    return {
        "checks": checks,
        "warnings": [c["key"] for c in checks if c["ok"] is False],
        "all_ok": all(c["ok"] is not False for c in checks),
        "earlier_claims": [{"id": c.id, "reason": c.reason, "status": c.status, "amount": c.amount,
                            "created_at": c.created_at} for c in earlier],
        "blocked_reasons": sorted({c.reason for c in earlier}),
    }


# ----------------------------------------------------------------- serialise
def _name(user: User | None) -> str | None:
    """"admin (A12)" for an admin, the person's name for a member."""
    return user.actor_label if user else None


def serialize(db: Session, claim: ReliefClaim, viewer: dict, *, full: bool = True) -> dict:
    required = _int_setting(db, "relief_required_approvals")
    viewer_id = int(viewer.get("user_id") or 0)
    approvals = [a for a in claim.approvals if a.decision == "approve"]
    mine = next((a for a in claim.approvals if a.admin_user_id == viewer_id), None)
    member = claim.member
    base = {
        "id": claim.id,
        "member_id": claim.member_id,
        "member_code": member.member_code if member else None,
        "member_name": rs._member_name(member) if member else None,
        "reason": claim.reason,
        "illness_type": claim.illness_type,
        "amount": claim.amount,
        "status": claim.status,
        "approvals_count": len(approvals),
        "approvals_needed": required,
        "created_at": claim.created_at,
        "decided_at": claim.decided_at,
        "paid_on": rs._iso(claim.paid_on),
        "rejection_reason": claim.rejection_reason,
    }
    if not full:
        return base
    return {
        **base,
        "details": claim.details,
        "created_by_user_id": claim.created_by_user_id,
        "created_by_name": _name(claim.created_by),
        "rejected_by_name": actor_label_for(db, claim.rejected_by_user_id),
        "paid_by_name": actor_label_for(db, claim.paid_by_user_id),
        "receiver": {
            "name": claim.receiver_name, "relation": claim.receiver_relation, "phone": claim.receiver_phone,
            "bank_account": claim.receiver_bank_account, "ifsc": claim.receiver_ifsc,
            "bank_name": claim.receiver_bank_name, "upi": claim.receiver_upi,
        },
        "gulf_from_year": claim.gulf_from_year,
        "gulf_to_year": claim.gulf_to_year,
        "documents": json.loads(claim.documents or "[]"),
        "eligibility": json.loads(claim.eligibility) if claim.eligibility else None,
        "decisions": [{"admin_user_id": a.admin_user_id, "admin_name": _name(a.admin), "decision": a.decision,
                       "note": a.note, "at": a.created_at} for a in claim.approvals],
        "fund_utilization_id": claim.fund_utilization_id,
        "paid_method": claim.paid_method,
        "paid_reference": claim.paid_reference,
        "paid_receipt_url": claim.paid_receipt_url,
        "cancelled_reason": claim.cancelled_reason,
        "my_decision": mine.decision if mine else None,
        "can_decide": (claim.status == "pending" and _is_admin(viewer) and viewer_id != claim.created_by_user_id
                       and mine is None),
        "can_mark_paid": claim.status == "approved" and _is_admin(viewer),
        "can_cancel": claim.status == "pending" and (
            viewer_id == claim.created_by_user_id or str(viewer.get("role", "")).lower() == "superadmin"),
    }


def _load(db: Session, claim_id: int, lock: bool = False) -> ReliefClaim:
    query = db.query(ReliefClaim).options(joinedload(ReliefClaim.member).joinedload(Member.user),
                                          joinedload(ReliefClaim.approvals))
    if lock:
        query = db.query(ReliefClaim).filter(ReliefClaim.id == claim_id).with_for_update()
        claim = query.first()
    else:
        claim = query.filter(ReliefClaim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim


def _audit(db: Session, user: dict, action: str, claim: ReliefClaim, values: dict) -> None:
    db.add(AuditLog(user_id=int(user["user_id"]), action=action, entity_type="ReliefClaim",
                    entity_id=claim.id, new_values=json.dumps(values, default=str)))


def _notify(db: Session, user_id: int | None, title: str, message: str, claim: ReliefClaim,
            ntype: str = "info", link: str | None = None) -> None:
    """Admins get it under "Fund approvals"; the member (link="/Relief") under payment updates."""
    if not user_id:
        return
    for_member = link == "/Relief"
    NotificationService._send_status_notification(
        db, user_id, title, message, ntype,
        category="payment_updates" if for_member else "admin_fund_approvals",
        link_url=link or f"/Relief?claim={claim.id}", entity_type="relief_claim", entity_id=claim.id,
    )


def _inr(amount) -> str:
    return NotificationService._format_inr(amount)


# ----------------------------------------------------------------- create
def _clean(value, limit: int | None = None) -> str | None:
    text = " ".join(str(value or "").split())
    if limit and len(text) > limit:
        raise HTTPException(status_code=400, detail=f"Text too long (max {limit} characters)")
    return text or None


def _documents(raw: list[dict]) -> list[dict]:
    out = []
    for doc in raw or []:
        kind = str(doc.get("kind") or "").strip()
        url = str(doc.get("url") or "").strip()
        if kind not in DOC_KINDS:
            raise HTTPException(status_code=400, detail=f"Unknown document kind: {kind or '(empty)'}")
        if not (url.startswith("https://") or url.startswith("/uploads/") or url.startswith("uploads/")):
            raise HTTPException(status_code=400, detail="Documents must be uploaded through the app")
        out.append({"kind": kind, "url": url, "name": _clean(doc.get("name"), 200)})
    return out


def create_claim(db: Session, user: dict, data: dict) -> dict:
    _require_admin(user)
    member = db.query(Member).options(joinedload(Member.user)).filter(Member.id == data.get("member_id")).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    reason = data.get("reason")
    if reason not in REASONS:
        raise HTTPException(status_code=400, detail="Reason must be death, illness or retirement")
    illness = data.get("illness_type")
    if reason == "illness" and illness not in ILLNESSES:
        raise HTTPException(status_code=400, detail="Choose the illness: heart attack, kidney failure, cancer or stroke")

    minimum = default_amount(db, reason)
    amount = float(data.get("amount") or minimum)
    if amount < minimum:
        raise HTTPException(status_code=400, detail=f"The amount cannot be less than {_inr(minimum)} for this reason")

    receiver_name = _clean(data.get("receiver_name"), 255)
    relation = _clean(data.get("receiver_relation"), 50)
    if not receiver_name:
        raise HTTPException(status_code=400, detail="Who receives the money? Enter the receiver's name")
    if reason == "death" and (not relation or relation.lower() == "self"):
        raise HTTPException(status_code=400, detail="For a death claim, enter the family member who receives it and their relation")

    gulf_from, gulf_to = data.get("gulf_from_year"), data.get("gulf_to_year")
    if reason == "retirement":
        this_year = today_business().year
        if not gulf_from or not gulf_to or not (1950 <= int(gulf_from) <= int(gulf_to) <= this_year):
            raise HTTPException(status_code=400, detail="Enter the years of Gulf service (from and to)")
        gulf_from, gulf_to = int(gulf_from), int(gulf_to)
    else:
        gulf_from = gulf_to = None

    docs = _documents(data.get("documents") or [])
    missing = [k for k in REQUIRED_DOCS[reason] if not any(d["kind"] == k for d in docs)]
    if missing:
        raise HTTPException(status_code=400, detail=f"Please upload: {', '.join(m.replace('_', ' ') for m in missing)}")

    existing = db.query(ReliefClaim.id).filter(ReliefClaim.member_id == member.id, ReliefClaim.reason == reason,
                                               ReliefClaim.status.in_(ACTIVE)).first()
    if existing:
        raise HTTPException(status_code=409, detail="This member already has a relief claim for this reason (relief is given once per reason)")

    check = eligibility(db, member, reason, gulf_from, gulf_to)
    claim = ReliefClaim(
        member_id=member.id, reason=reason, illness_type=illness if reason == "illness" else None,
        details=_clean(data.get("details"), 2000), amount=amount, status="pending",
        created_by_user_id=int(user["user_id"]),
        receiver_name=receiver_name, receiver_relation=relation or ("self" if reason != "death" else None),
        receiver_phone=_clean(data.get("receiver_phone"), 30),
        receiver_bank_account=_clean(data.get("receiver_bank_account"), 40),
        receiver_ifsc=(_clean(data.get("receiver_ifsc"), 20) or "").upper() or None,
        receiver_bank_name=_clean(data.get("receiver_bank_name"), 120),
        receiver_upi=_clean(data.get("receiver_upi"), 120),
        gulf_from_year=gulf_from, gulf_to_year=gulf_to,
        documents=json.dumps(docs), eligibility=json.dumps(check, default=str),
    )
    db.add(claim)
    db.flush()
    _audit(db, user, "relief_claim_create", claim, {"member_id": member.id, "reason": reason, "amount": amount,
                                                    "warnings": check["warnings"]})
    db.commit()

    name = rs._member_name(member)
    label = REASON_LABEL[reason]
    for admin_id in NotificationService._active_admin_ids(db, exclude_user_id=claim.created_by_user_id):
        _notify(db, admin_id, "Relief claim needs your approval",
                f"{label} relief of {_inr(amount)} for {name} needs your approval.", claim)
    _notify(db, member.user_id, "Relief claim opened",
            f"A {label.lower()} relief claim of {_inr(amount)} was opened for you. You will be told when it is decided.",
            claim, link="/Relief")
    return serialize(db, _load(db, claim.id), user)


# ----------------------------------------------------------------- decide
def _decide_guard(claim: ReliefClaim, user: dict) -> None:
    _require_admin(user)
    if claim.status != "pending":
        raise HTTPException(status_code=400, detail="This claim has already been decided")
    if int(user["user_id"]) == claim.created_by_user_id:
        raise HTTPException(status_code=403, detail="You created this claim, so other admins must approve it")
    if any(a.admin_user_id == int(user["user_id"]) for a in claim.approvals):
        raise HTTPException(status_code=400, detail="You have already decided on this claim")


def approve(db: Session, user: dict, claim_id: int, note: str | None = None) -> dict:
    claim = _load(db, claim_id, lock=True)
    _decide_guard(claim, user)
    db.add(ReliefApproval(claim_id=claim.id, admin_user_id=int(user["user_id"]), decision="approve",
                          note=_clean(note, 1000)))
    db.flush()
    db.refresh(claim)
    approvals = sum(1 for a in claim.approvals if a.decision == "approve")
    required = _int_setting(db, "relief_required_approvals")
    member = db.query(Member).options(joinedload(Member.user)).filter(Member.id == claim.member_id).first()
    name = rs._member_name(member)
    done = approvals >= required
    if done:
        now = datetime.utcnow()
        claim.status = "approved"
        claim.decided_at = now
        fund = FundUtilization(
            title=f"Relief ({REASON_LABEL[claim.reason].lower()}): {name}",
            description=f"Relief claim #{claim.id} for {name} ({member.member_code}), "
                        f"approved by {approvals} admins. Receiver: {claim.receiver_name}"
                        f"{f' ({claim.receiver_relation})' if claim.receiver_relation else ''}.",
            amount=claim.amount, category="Relief", recipient=claim.receiver_name, date=now,
            registered_by_admin_id=claim.created_by_user_id, status="approved",
            approved_by_admin_id=int(user["user_id"]), approved_at=now,
        )
        db.add(fund)
        db.flush()
        claim.fund_utilization_id = fund.id
    _audit(db, user, "relief_claim_approve", claim, {"approvals": approvals, "required": required,
                                                     "approved": done, "note": note})
    db.commit()
    if done:
        approvers = db.query(ReliefApproval.admin_user_id).filter(ReliefApproval.claim_id == claim.id,
                                                                  ReliefApproval.decision == "approve").all()
        labels = actor_labels(db, [a[0] for a in approvers], staff=True)
        by = ", ".join(labels[a[0]] for a in approvers if a[0] in labels) or "the admins"  # for the admins
        _notify(db, claim.created_by_user_id, "Relief claim approved",
                f"The relief claim for {name} ({_inr(claim.amount)}) is approved by {by}. Please mark it paid once the money is given.",
                claim, ntype="success")
        _notify(db, member.user_id, "Relief approved",
                f"Your relief of {_inr(claim.amount)} is approved by the committee. The admins will tell you when it is paid.",
                claim, ntype="success", link="/Relief")
    return serialize(db, _load(db, claim.id), user)


def reject(db: Session, user: dict, claim_id: int, reason: str) -> dict:
    claim = _load(db, claim_id, lock=True)
    _decide_guard(claim, user)
    reason = _clean(reason, 1000)
    if not reason:
        raise HTTPException(status_code=400, detail="Please give a reason for rejecting")
    db.add(ReliefApproval(claim_id=claim.id, admin_user_id=int(user["user_id"]), decision="reject", note=reason))
    claim.status = "rejected"
    claim.rejected_by_user_id = int(user["user_id"])
    claim.rejection_reason = reason
    claim.decided_at = datetime.utcnow()
    _audit(db, user, "relief_claim_reject", claim, {"reason": reason})
    db.commit()
    member = db.query(Member).filter(Member.id == claim.member_id).first()
    by = actor_label_for(db, int(user["user_id"]), staff=True) or "an admin"
    _notify(db, claim.created_by_user_id, "Relief claim rejected",
            f"The relief claim for {rs._member_name(member)} was rejected by {by}. Reason: {reason}", claim, ntype="warning")
    _notify(db, member.user_id if member else None, "Relief claim not approved",
            f"Your relief claim was not approved by the committee. Reason: {reason}", claim, ntype="warning", link="/Relief")
    return serialize(db, _load(db, claim.id), user)


def mark_paid(db: Session, user: dict, claim_id: int, data: dict) -> dict:
    _require_admin(user)
    claim = _load(db, claim_id, lock=True)
    if claim.status != "approved":
        raise HTTPException(status_code=400, detail="Only an approved claim can be marked paid")
    method = data.get("method")
    if method not in PAY_METHODS:
        raise HTTPException(status_code=400, detail="How was it paid? cash, bank transfer, UPI or cheque")
    try:
        paid_on = datetime.strptime(str(data.get("paid_on") or ""), "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Enter the date it was paid")
    if paid_on.date() > today_business():
        raise HTTPException(status_code=400, detail="The paid date cannot be in the future")
    receipt = data.get("receipt_url")
    if receipt:
        _documents([{"kind": "other", "url": receipt}])
    claim.status = "paid"
    claim.paid_on = paid_on
    claim.paid_method = method
    claim.paid_reference = _clean(data.get("reference"), 120)
    claim.paid_receipt_url = receipt or None
    claim.paid_by_user_id = int(user["user_id"])
    _audit(db, user, "relief_claim_paid", claim, {"paid_on": paid_on.date(), "method": method,
                                                  "reference": claim.paid_reference})
    db.commit()
    member = db.query(Member).filter(Member.id == claim.member_id).first()
    _notify(db, member.user_id if member else None, "Relief paid",
            f"Your relief of {_inr(claim.amount)} was paid on {paid_on:%d %b %Y}"
            " by the committee.", claim, ntype="success", link="/Relief")
    return serialize(db, _load(db, claim.id), user)


def cancel(db: Session, user: dict, claim_id: int, reason: str) -> dict:
    _require_admin(user)
    claim = _load(db, claim_id, lock=True)
    if claim.status != "pending":
        raise HTTPException(status_code=400, detail="Only a claim waiting for approval can be cancelled")
    if int(user["user_id"]) != claim.created_by_user_id and str(user.get("role", "")).lower() != "superadmin":
        raise HTTPException(status_code=403, detail="Only the admin who created it, or a superadmin, can cancel it")
    reason = _clean(reason, 1000)
    if not reason:
        raise HTTPException(status_code=400, detail="Please give a reason for cancelling")
    claim.status = "cancelled"
    claim.cancelled_reason = reason
    claim.decided_at = datetime.utcnow()
    _audit(db, user, "relief_claim_cancel", claim, {"reason": reason})
    db.commit()
    return serialize(db, _load(db, claim.id), user)


# ----------------------------------------------------------------- lists
def list_claims(db: Session, user: dict, status: str | None = None, search: str | None = None) -> dict:
    _require_admin(user)
    query = db.query(ReliefClaim).join(Member, Member.id == ReliefClaim.member_id).outerjoin(User, User.id == Member.user_id)
    if status:
        if status == "to_decide":
            mine = db.query(ReliefApproval.claim_id).filter(ReliefApproval.admin_user_id == int(user["user_id"]))
            query = query.filter(ReliefClaim.status == "pending", ReliefClaim.created_by_user_id != int(user["user_id"]),
                                 ~ReliefClaim.id.in_(mine))
        elif status in STATUSES:
            query = query.filter(ReliefClaim.status == status)
        else:
            raise HTTPException(status_code=400, detail="Unknown status")
    term = (search or "").strip().lower()
    if term:
        like = f"%{term}%"
        query = query.filter(or_(func.lower(func.coalesce(Member.full_name, "")).like(like),
                                 func.lower(Member.member_code).like(like),
                                 func.lower(func.coalesce(User.username, "")).like(like),
                                 func.lower(ReliefClaim.receiver_name).like(like)))
    claims = query.options(joinedload(ReliefClaim.member).joinedload(Member.user),
                           joinedload(ReliefClaim.approvals)).order_by(ReliefClaim.created_at.desc()).all()
    counts = dict(db.query(ReliefClaim.status, func.count(ReliefClaim.id)).group_by(ReliefClaim.status).all())
    mine = {row[0] for row in db.query(ReliefApproval.claim_id).filter(ReliefApproval.admin_user_id == int(user["user_id"])).all()}
    to_decide = db.query(func.count(ReliefClaim.id)).filter(
        ReliefClaim.status == "pending", ReliefClaim.created_by_user_id != int(user["user_id"]),
        ~ReliefClaim.id.in_(mine) if mine else true()).scalar() or 0
    return {
        "items": [serialize(db, c, user) for c in claims],
        "counts": {s: int(counts.get(s, 0)) for s in STATUSES} | {"to_decide": int(to_decide)},
        "paid_total": round(float(db.query(func.coalesce(func.sum(ReliefClaim.amount), 0))
                                  .filter(ReliefClaim.status == "paid").scalar() or 0), 2),
        "scheme": scheme(db),
    }


def get_claim(db: Session, user: dict, claim_id: int) -> dict:
    _require_admin(user)
    return serialize(db, _load(db, claim_id), user)


def member_eligibility(db: Session, user: dict, member_id: int, reason: str | None = None,
                       gulf_from_year: int | None = None, gulf_to_year: int | None = None) -> dict:
    _require_admin(user)
    member = db.query(Member).options(joinedload(Member.user)).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    if reason and reason not in REASONS:
        raise HTTPException(status_code=400, detail="Unknown reason")
    return {"member": rs._member_info(member), "eligibility": eligibility(db, member, reason, gulf_from_year, gulf_to_year),
            "scheme": scheme(db)}


def my_relief(db: Session, user: dict) -> dict:
    """The signed-in member: the scheme numbers, their own rule checks and any claims for them."""
    member = db.query(Member).options(joinedload(Member.user)).filter(Member.user_id == int(user["user_id"])).first()
    data = {"scheme": scheme(db), "eligibility": None, "claims": []}
    if not member:
        return data
    data["eligibility"] = eligibility(db, member)
    claims = (db.query(ReliefClaim).options(joinedload(ReliefClaim.member), joinedload(ReliefClaim.approvals))
              .filter(ReliefClaim.member_id == member.id).order_by(ReliefClaim.created_at.desc()).all())
    data["claims"] = [serialize(db, c, user, full=False) for c in claims]
    return data
