"""Admin reports: one member's statement, the payments list, who has not paid, the year grid.

Month states (the same words everywhere in the Reports page):
  paid      an approved monthly payment
  waiting   handed in (proof, bulk payment or recorded by an admin), not yet approved
  not_paid  nothing handed in: no challan, a generated one, an imported "pending" one,
            or only rejected ones
  excused   not paid and not owed: an admin excused the month (see seasonal.py)
  pledge    not paid, in a year the member pledged a total instead (owed: what is left of it)
  not_monthly  not paid, the member is not a monthly member
A month counts from the member's join month (or the platform start, Aug 2024, when no join
date is known) through the current month, like the payment forms.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from app.models import Campaign, Challan, Member, User
from app.models.models import ChallanStatus, ChallanType
from app.services.challan_state import is_submitted, submitted_clause
from app.services.settings_service import org_name
from app.utils.countries import COUNTRIES, normalize_country
from app.utils.timezone import BUSINESS_TZ, business_to_naive_utc, to_business, today_business

PLATFORM_START = date(2024, 8, 1)
STATES = ("paid", "waiting", "not_paid", "rejected")
MAX_PAGE = 500
RANK = {"paid": 3, "waiting": 2, "rejected": 1, "not_paid": 0}
NOT_OWED = ("excused", "pledge", "not_monthly")  # open months that are not owed


# ----------------------------------------------------------------- helpers
def _month(d: date) -> str:
    return d.strftime("%Y-%m")


def _add_months(d: date, n: int) -> date:
    i = d.month - 1 + n
    return date(d.year + i // 12, i % 12 + 1, 1)


def _months(start: date, end: date) -> list[str]:
    out, cur = [], start
    while cur <= end:
        out.append(_month(cur))
        cur = _add_months(cur, 1)
    return out


def _parse_month(value: str | None, field: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m").date()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field} must look like 2026-01")


def _month_start_utc(d: date) -> datetime:
    """Midnight on the 1st of the month in India time, as naive UTC (how created_at is stored)."""
    return business_to_naive_utc(datetime(d.year, d.month, 1, tzinfo=BUSINESS_TZ))


def _start_month(member: Member) -> date:
    this_month = today_business().replace(day=1)
    if member.join_date:
        start = to_business(member.join_date).date().replace(day=1)
        start = min(start, this_month)
    else:
        start = PLATFORM_START
    return max(start, PLATFORM_START)


def challan_state(challan: Challan) -> str:
    status = getattr(challan.status, "value", challan.status)
    if status == "approved":
        return "paid"
    if status == "rejected":
        return "rejected"
    return "waiting" if is_submitted(challan) else "not_paid"


def _member_name(member: Member) -> str:
    user = member.user
    return member.full_name or (user.full_name if user else None) or (user.username if user else None) or member.member_code


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return to_business(value).date().isoformat()
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _member_info(member: Member) -> dict:
    user = member.user
    return {
        "id": member.id,
        "member_code": member.member_code,
        "name": _member_name(member),
        "phone": user.phone if user else None,
        "whatsapp_phone": user.whatsapp_phone if user else None,
        "country": member.country,
        "country_name": COUNTRIES.get(member.country or "", ("",))[0] or None,
        "city": member.city,
        "monthly_amount": float(member.monthly_amount or 0),
        "join_date": _iso(member.join_date),
        "status": member.status or "active",
        "registered": bool(user and user.is_active),
    }


def _month_rows(member: Member, challans: Iterable[Challan], start: date, end: date, book=None,
                seasonal=None) -> list[dict]:
    """One row per month start..end; months paid ahead of end are added too.
    Unpaid months show the fee of that month (fee history), paid ones what was paid.
    With ``seasonal`` (seasonal.Book) open months that are not owed say why, with amount 0."""
    def fee_of(month: str) -> float:
        return book.fee(member, month) if book is not None else float(member.monthly_amount or 0)
    best: dict[str, Challan] = {}
    for c in challans:
        if c.type != ChallanType.MONTHLY or not c.month:
            continue
        state = challan_state(c)
        current = best.get(c.month)
        if current is None or RANK[state] > RANK[challan_state(current)]:
            best[c.month] = c
    months = _months(start, end)
    ahead = sorted(m for m, c in best.items() if m > _month(end) and challan_state(c) in ("paid", "waiting"))
    rows = []
    for month in months + ahead:
        c = best.get(month)
        state = challan_state(c) if c else "not_paid"
        if state == "rejected":
            state = "not_paid"  # a rejected payment means the month is still owed
        paid = state in ("paid", "waiting")
        why = seasonal.open_state(member.id, month) if seasonal is not None and not paid else None
        if why:
            state = why
        rows.append({
            "month": month,
            "state": state,
            "amount": float(c.amount) if c is not None and paid else (0.0 if why else fee_of(month)),
            "paid_on": _iso(c.received_on or c.approved_at) if c is not None and state == "paid" else None,
            "handed_in_on": _iso(c.proof_uploaded_at or c.created_at) if c is not None and state == "waiting" else None,
            "method": c.payment_method if c is not None and paid else None,
            "note": (seasonal.reason(member.id, month) if why == "excused" else
                     c.rejection_reason if c is not None and getattr(c.status, "value", c.status) == "rejected" else None),
            "challan_id": c.id if c is not None else None,
            "ahead": month > _month(end),
        })
    return rows


def _totals(rows: list[dict], current_month: str, pledges: list[dict] | None = None) -> dict:
    def total(state):
        picked = [r for r in rows if r["state"] == state]
        return len(picked), round(sum(r["amount"] for r in picked), 2)

    paid_n, paid_amt = total("paid")
    wait_n, wait_amt = total("waiting")
    due_n, due_amt = total("not_paid")
    overdue = [r for r in rows if r["state"] == "not_paid" and r["month"] < current_month]
    paid_up_to = None
    for r in rows:
        if r["state"] in ("paid", "waiting") or r["state"] in NOT_OWED:
            paid_up_to = r["month"]
        else:
            break
    last_paid = max((r["paid_on"] for r in rows if r["paid_on"]), default=None)
    last_paid_month = max((r["month"] for r in rows if r["state"] in ("paid", "waiting")), default=None)
    pledges = pledges or []
    pledge_left = round(sum(p["left"] for p in pledges), 2)
    return {
        "months_paid": paid_n, "amount_paid": paid_amt,
        "months_waiting": wait_n, "amount_waiting": wait_amt,
        "months_due": due_n, "amount_due": round(due_amt + pledge_left, 2),
        "months_excused": sum(1 for r in rows if r["state"] == "excused"),
        "pledges": pledges,              # pledge years: promised, paid, waiting, left
        "pledge_left": pledge_left,      # included in amount_due
        "months_overdue": len(overdue),
        "this_month_due": any(r["month"] == current_month and r["state"] == "not_paid" for r in rows),
        "paid_up_to": paid_up_to,          # every month from the start through this one is paid
        "last_paid_month": last_paid_month,  # latest month paid, even with gaps before it
        "last_payment_on": last_paid,
        "due_months": [r["month"] for r in rows if r["state"] == "not_paid"],
    }


def _members_query(db: Session):
    return db.query(Member).options(joinedload(Member.user))


# ----------------------------------------------------------------- statement
def member_statement(db: Session, member_id: int, from_month: str | None = None, to_month: str | None = None) -> dict:
    member = _members_query(db).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    this_month = today_business().replace(day=1)
    start = _parse_month(from_month, "from_month") or _start_month(member)
    end = _parse_month(to_month, "to_month") or this_month
    start = max(start, PLATFORM_START)
    if end < start:
        raise HTTPException(status_code=400, detail="to_month must not be before from_month")
    if (end.year - start.year) * 12 + end.month - start.month > 240:
        raise HTTPException(status_code=400, detail="Please choose at most 20 years")

    challans = db.query(Challan).filter(Challan.member_id == member.id).all()
    from app.services.fee_history import FeeBook

    from app.services import seasonal

    sbook = seasonal.Book(db, [member])
    rows = _month_rows(member, challans, start, end, FeeBook(db, [member]), sbook)
    pledges = seasonal.pledge_summaries(sbook, member.id, rows)
    donations = sorted(
        (c for c in challans if c.type == ChallanType.CAMPAIGN),
        key=lambda c: c.created_at or datetime.min, reverse=True,
    )
    titles = dict(db.query(Campaign.id, Campaign.title).filter(
        Campaign.id.in_({c.campaign_id for c in donations if c.campaign_id})).all()) if donations else {}
    donation_rows = [{
        "date": _iso(c.received_on or c.approved_at or c.created_at),
        "campaign": titles.get(c.campaign_id) or "Donation",
        "amount": float(c.amount or 0),
        "state": challan_state(c),
    } for c in donations]
    return {
        "organisation": org_name(db),
        "generated_on": datetime.now(BUSINESS_TZ).strftime("%Y-%m-%d %H:%M"),
        "member": _member_info(member),
        "from_month": _month(start),
        "to_month": _month(end),
        "current_month": _month(this_month),
        "months": rows,
        "totals": _totals(rows, _month(this_month), pledges),
        "monthly_member": seasonal.is_monthly(member),
        "donations": donation_rows,
        "donations_total": round(sum(d["amount"] for d in donation_rows if d["state"] == "paid"), 2),
    }


# ----------------------------------------------------------------- dues
def dues(
    db: Session, *, country: str | None = None, min_months: int = 1, search: str | None = None,
    status: str = "active", sort: str = "amount_desc",
) -> dict:
    query = _members_query(db)
    if status in ("active", "inactive"):
        query = query.filter(func.lower(func.coalesce(Member.status, "active")) == status)
    if country:
        if country == "none":
            query = query.filter(Member.country.is_(None))
        else:
            try:
                query = query.filter(Member.country == normalize_country(country))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
    term = (search or "").strip().lower()
    if term:
        like = f"%{term}%"
        query = query.outerjoin(User, User.id == Member.user_id).filter(or_(
            func.lower(func.coalesce(Member.full_name, "")).like(like),
            func.lower(Member.member_code).like(like),
            func.lower(func.coalesce(User.username, "")).like(like),
            func.coalesce(User.phone, "").like(like),
        ))
    members = query.all()
    by_member: dict[int, list[Challan]] = defaultdict(list)
    if members:
        for c in db.query(Challan).filter(Challan.type == ChallanType.MONTHLY,
                                          Challan.member_id.in_([m.id for m in members])).all():
            by_member[c.member_id].append(c)

    this_month = today_business().replace(day=1)
    current = _month(this_month)
    from app.services.fee_history import FeeBook

    from app.services import seasonal

    book = FeeBook(db, members)
    sbook = seasonal.Book(db, members)
    out = []
    for member in members:
        rows = _month_rows(member, by_member.get(member.id, []), _start_month(member), this_month, book, sbook)
        totals = _totals(rows, current, seasonal.pledge_summaries(sbook, member.id, rows))
        wanted = max(1, int(min_months or 1))
        if totals["months_due"] < wanted and not (wanted == 1 and totals["pledge_left"] > 0):
            continue
        out.append({**_member_info(member), **{k: totals[k] for k in (
            "months_due", "amount_due", "months_overdue", "this_month_due", "paid_up_to", "last_paid_month",
            "last_payment_on", "due_months", "months_excused", "pledge_left", "pledges")}})

    keys = {
        "amount_desc": lambda r: (-r["amount_due"], -r["months_due"], r["name"].lower()),
        "months_desc": lambda r: (-r["months_due"], r["name"].lower()),
        "name": lambda r: r["name"].lower(),
        "code": lambda r: r["member_code"],
    }
    if sort not in keys:
        raise HTTPException(status_code=400, detail=f"sort must be one of: {', '.join(keys)}")
    out.sort(key=keys[sort])
    return {
        "organisation": org_name(db),
        "current_month": current,
        "members": out,
        "members_with_dues": len(out),
        "total_amount_due": round(sum(r["amount_due"] for r in out), 2),
        "total_months_due": sum(r["months_due"] for r in out),
        "fee_missing": sum(1 for r in out if r["monthly_amount"] <= 0 and r["months_due"] > 0),
    }


# ----------------------------------------------------------------- payments list
def _payments_query(
    db: Session, *, type: str | None = None, state: str | None = None, month_from: str | None = None,
    month_to: str | None = None, campaign_id: int | None = None, country: str | None = None,
    member_id: int | None = None, search: str | None = None, method: str | None = None,
):
    query = (
        db.query(Challan)
        .join(Member, Member.id == Challan.member_id)
        .outerjoin(User, User.id == Member.user_id)
        .filter(or_(Challan.type != ChallanType.MONTHLY, Challan.month.is_(None), Challan.month >= _month(PLATFORM_START)))
    )
    if type:
        if type not in ("monthly", "campaign"):
            raise HTTPException(status_code=400, detail="type must be monthly or campaign")
        query = query.filter(Challan.type == ChallanType(type))
    if state:
        if state not in STATES:
            raise HTTPException(status_code=400, detail=f"state must be one of: {', '.join(STATES)}")
        open_states = [ChallanStatus.GENERATED, ChallanStatus.PENDING]
        query = query.filter({
            "paid": Challan.status == ChallanStatus.APPROVED,
            "rejected": Challan.status == ChallanStatus.REJECTED,
            "waiting": and_(Challan.status.in_(open_states), submitted_clause()),
            "not_paid": and_(Challan.status.in_(open_states), ~submitted_clause()),
        }[state])
    start = _parse_month(month_from, "month_from")
    end = _parse_month(month_to, "month_to")
    if start or end:
        # Monthly fees by the month they are for; donations by the day they were given.
        start_s = _month(start) if start else "0000-00"
        end_s = _month(end) if end else "9999-99"
        start_dt = _month_start_utc(start) if start else datetime(1900, 1, 1)
        end_dt = _month_start_utc(_add_months(end, 1)) if end else datetime(9999, 1, 1)
        query = query.filter(or_(
            and_(Challan.type == ChallanType.MONTHLY, Challan.month >= start_s, Challan.month <= end_s),
            and_(Challan.type == ChallanType.CAMPAIGN, Challan.created_at >= start_dt, Challan.created_at < end_dt),
        ))
    if campaign_id:
        query = query.filter(Challan.campaign_id == campaign_id)
    if member_id:
        query = query.filter(Challan.member_id == member_id)
    if country:
        if country == "none":
            query = query.filter(Member.country.is_(None))
        else:
            try:
                query = query.filter(Member.country == normalize_country(country))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
    if method:
        query = query.filter(func.lower(func.coalesce(Challan.payment_method, "")) == method.lower())
    term = (search or "").strip().lower()
    if term:
        like = f"%{term}%"
        query = query.filter(or_(
            func.lower(func.coalesce(Member.full_name, "")).like(like),
            func.lower(Member.member_code).like(like),
            func.lower(func.coalesce(User.username, "")).like(like),
            func.coalesce(User.phone, "").like(like),
        ))
    return query


PAYMENT_SORTS = {
    # Donations have no month: they sort by the day they were given, after the monthly fees.
    "month_desc": lambda: [Challan.month.desc().nulls_last(), Challan.created_at.desc()],
    "month_asc": lambda: [Challan.month.asc().nulls_last(), Challan.created_at.asc()],
    "amount_desc": lambda: [Challan.amount.desc()],
    "amount_asc": lambda: [Challan.amount.asc()],
    "member": lambda: [func.lower(func.coalesce(Member.full_name, User.username)), Challan.month.asc()],
    "newest": lambda: [Challan.created_at.desc()],
}


def payments(db: Session, *, skip: int = 0, limit: int = 50, sort: str = "month_desc", **filters) -> dict:
    if sort not in PAYMENT_SORTS:
        raise HTTPException(status_code=400, detail=f"sort must be one of: {', '.join(PAYMENT_SORTS)}")
    limit = max(1, min(int(limit), MAX_PAGE))
    query = _payments_query(db, **filters)

    # Totals per state over everything that matches (not only this page).
    totals = {s: {"count": 0, "amount": 0.0} for s in STATES}
    for c in query.with_entities(Challan.status, Challan.proof_path, Challan.proof_uploaded_at,
                                 Challan.bulk_group_id, Challan.entry_source, Challan.amount).all():
        s = challan_state(c)
        totals[s]["count"] += 1
        totals[s]["amount"] += float(c.amount or 0)
    for s in totals.values():
        s["amount"] = round(s["amount"], 2)
    total = sum(v["count"] for v in totals.values())

    rows = (query.options(joinedload(Challan.member).joinedload(Member.user))
            .order_by(*PAYMENT_SORTS[sort]()).offset(skip).limit(limit).all())
    titles = dict(db.query(Campaign.id, Campaign.title).filter(
        Campaign.id.in_({c.campaign_id for c in rows if c.campaign_id})).all()) if rows else {}
    items = []
    for c in rows:
        m = c.member
        items.append({
            "id": c.id,
            "member_id": m.id,
            "member_code": m.member_code,
            "member_name": _member_name(m),
            "phone": m.user.phone if m.user else None,
            "country": m.country,
            "type": getattr(c.type, "value", c.type),
            "month": c.month,
            "campaign": titles.get(c.campaign_id) if c.campaign_id else None,
            "amount": float(c.amount or 0),
            "state": challan_state(c),
            "method": c.payment_method if challan_state(c) in ("paid", "waiting") else None,
            "paid_on": _iso(c.received_on or c.approved_at) if challan_state(c) == "paid" else None,
            "created_on": _iso(c.created_at),
            "reference": c.transaction_ref,
            "note": c.rejection_reason,
        })
    return {"organisation": org_name(db), "items": items, "total": total, "skip": skip, "limit": limit,
            "has_more": skip + len(items) < total, "totals": totals}


# ----------------------------------------------------------------- year grid
def year_grid(db: Session, year: int, status: str = "active", country: str | None = None) -> dict:
    if not 2024 <= int(year) <= today_business().year + 1:
        raise HTTPException(status_code=400, detail="Pick a year from 2024")
    query = _members_query(db)
    if status in ("active", "inactive"):
        query = query.filter(func.lower(func.coalesce(Member.status, "active")) == status)
    if country:
        query = query.filter(Member.country.is_(None) if country == "none" else Member.country == country.upper())
    members = sorted(query.all(), key=lambda m: _member_name(m).lower())
    months = [f"{year}-{i:02d}" for i in range(1, 13)]
    by_member: dict[int, list[Challan]] = defaultdict(list)
    if members:
        for c in db.query(Challan).filter(Challan.type == ChallanType.MONTHLY, Challan.month.in_(months),
                                          Challan.member_id.in_([m.id for m in members])).all():
            by_member[c.member_id].append(c)
    this_month = _month(today_business().replace(day=1))
    from app.services.fee_history import FeeBook

    from app.services import seasonal

    book = FeeBook(db, members)
    sbook = seasonal.Book(db, members)
    rows = []
    for m in members:
        start = _month(_start_month(m))
        cells = {r["month"]: r for r in _month_rows(m, by_member.get(m.id, []), date(year, 1, 1), date(year, 12, 1),
                                                    book, sbook)}
        states = []
        for month in months:
            if month < start:
                states.append("before_join")
            elif month > this_month and cells[month]["state"] == "not_paid":
                states.append("future")
            else:
                states.append(cells[month]["state"])
        rows.append({"member_code": m.member_code, "name": _member_name(m),
                     "monthly_amount": float(m.monthly_amount or 0), "months": states,
                     "paid": states.count("paid"), "due": states.count("not_paid")})
    return {"organisation": org_name(db), "year": int(year), "months": months, "rows": rows}


# ----------------------------------------------------------------- yearly paid list (Aug-Jul)
def _code_order(code: str | None):
    import re
    m = re.match(r"^MEM-?(\d+)$", str(code or ""), re.IGNORECASE)
    return (0, int(m.group(1)), "") if m else (1, 0, str(code or ""))


def paid_list(db: Session, year: int) -> dict:
    """The committee's yearly paid list for Aug `year` - Jul `year+1`.

    One row per member (inactive too), in member-ID order: month marks P (paid, approved),
    W (proof sent, waiting), - (before the member joined), '' (not paid); and the amount each
    member gave to each campaign in that year (approved donations, by the day received).
    """
    today = today_business()
    current_fy = today.year if today.month >= 8 else today.year - 1
    if not 2024 <= int(year) <= current_fy:
        raise HTTPException(status_code=400, detail="Pick a year from 2024-2025 onwards")
    year = int(year)
    months = [f"{year}-{m:02d}" for m in range(8, 13)] + [f"{year + 1}-{m:02d}" for m in range(1, 8)]
    this_month = _month(today.replace(day=1))
    fy_start, fy_end = date(year, 8, 1), date(year + 1, 7, 1)

    members = sorted(_members_query(db).all(), key=lambda m: _code_order(m.member_code))
    ids = [m.id for m in members]
    monthly: dict[int, list[Challan]] = defaultdict(list)
    donations: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    campaign_totals: dict[int, float] = defaultdict(float)
    if ids:
        for c in db.query(Challan).filter(Challan.member_id.in_(ids), Challan.type == ChallanType.MONTHLY,
                                          Challan.month.in_(months)).all():
            monthly[c.member_id].append(c)
        start_utc, end_utc = _month_start_utc(fy_start), _month_start_utc(_add_months(fy_end, 1))
        for c in db.query(Challan).filter(Challan.member_id.in_(ids), Challan.type == ChallanType.CAMPAIGN,
                                          Challan.status == ChallanStatus.APPROVED).all():
            if c.received_on:
                inside = fy_start <= c.received_on < _add_months(fy_end, 1)
            else:
                when = c.approved_at or c.created_at
                inside = bool(when) and start_utc <= when < end_utc
            if inside and c.campaign_id:
                donations[c.member_id][c.campaign_id] += float(c.amount or 0)
                campaign_totals[c.campaign_id] += float(c.amount or 0)

    titles = dict(db.query(Campaign.id, Campaign.title).filter(Campaign.id.in_(list(campaign_totals))).all()) if campaign_totals else {}
    campaigns = [{"id": cid, "title": titles.get(cid) or f"Campaign {cid}", "total": round(total, 2)}
                 for cid, total in sorted(campaign_totals.items(), key=lambda kv: (titles.get(kv[0]) or "").lower())]

    from app.services.fee_history import FeeBook

    from app.services import seasonal

    book = FeeBook(db, members)
    sbook = seasonal.Book(db, members)
    rows = []
    for si, m in enumerate(members, start=1):
        start = _month(_start_month(m))
        cells = {r["month"]: r for r in _month_rows(m, monthly.get(m.id, []), fy_start, fy_end, book, sbook)}
        marks = []
        for month in months:
            state = cells[month]["state"]
            if (month < start or state == "not_monthly") and state not in ("paid", "waiting"):
                marks.append("-")
            elif state == "paid":
                marks.append("P")
            elif state == "waiting":
                marks.append("W")
            elif state == "excused":
                marks.append("E")
            else:
                marks.append("")  # not paid (or a pledge-year month, not owed by itself)
        place = ", ".join(x for x in [m.city] if x)
        order = _code_order(m.member_code)
        # Pending: months of this year from joining up to this month that are not approved
        # (proof sent but waiting still counts as pending).
        def owed(mo, mark):
            return mo <= this_month and mark in ("", "W") and cells[mo]["state"] != "pledge"

        pending = sum(1 for month, mark in zip(months, marks) if owed(month, mark))
        # A fee changed during the year: months x fee would be wrong, so the sheet gets the sums.
        fee_varies = book.varies(m.id, months[0], months[-1])
        received_amount = round(sum(cells[mo]["amount"] for mo, mark in zip(months, marks) if mark == "P"), 2)
        pledge = (seasonal.pledge_summaries(sbook, m.id, list(cells.values())) or [None])[0]
        pending_amount = round(sum(cells[mo]["amount"] for mo, mark in zip(months, marks) if owed(mo, mark))
                               + (pledge["left"] if pledge else 0), 2)
        rows.append({
            "si": si, "member_number": order[1] if order[0] == 0 else None,
            "pending_months": pending,
            "fee_varies": fee_varies, "received_amount": received_amount, "pending_amount": pending_amount,
            "member_code": m.member_code, "name": _member_name(m), "place": place,
            "status": m.status or "active", "monthly_amount": float(m.monthly_amount or 0), "months": marks,
            "campaigns": {str(cid): round(amount, 2) for cid, amount in donations.get(m.id, {}).items()},
            "monthly_member": seasonal.is_monthly(m),
            "excused_months": marks.count("E"),
            "pledge": pledge,
        })
    return {
        "organisation": org_name(db), "year": year, "label": f"{year}-{year + 1}",
        "months": months, "current_month": this_month, "campaigns": campaigns, "rows": rows,
    }


# ----------------------------------------------------------- my statement
def payment_history(db: Session, member_id: int) -> list[dict]:
    """Every payment of one member, newest first: one entry per payment (a bulk payment, or
    months started together, count once). Old imported "not paid yet" rows are not payments
    and are left out. Paid ones say which receipt to open."""
    challans = db.query(Challan).filter(Challan.member_id == member_id).all()
    titles = dict(db.query(Campaign.id, Campaign.title).filter(
        Campaign.id.in_({c.campaign_id for c in challans if c.campaign_id})).all()) if challans else {}
    groups: dict[str, list[Challan]] = {}
    for c in challans:
        if c.bulk_group_id:
            key = f"g:{c.bulk_group_id}"
        elif c.challan_no and c.type == ChallanType.MONTHLY and challan_state(c) == "not_paid":
            key = f"n:{c.challan_no}"  # months started together, proof still to come
        else:
            key = f"c:{c.id}"
        groups.setdefault(key, []).append(c)

    items = []
    for key, rows in groups.items():
        first = min(rows, key=lambda r: r.id)
        state = challan_state(first)
        if state == "not_paid" and first.created_by_user_id is None:
            continue  # an imported "not paid yet" month, not a payment
        months = sorted(r.month for r in rows if r.month)
        is_campaign = first.type == ChallanType.CAMPAIGN
        items.append({
            "key": key,
            "number": first.challan_no or (first.bulk_group_id if key.startswith("g:") else f"CH-{first.id}"),
            "type": "campaign" if is_campaign else "monthly",
            "months": months,
            "campaign_title": titles.get(first.campaign_id) if is_campaign else None,
            "amount": round(sum(float(r.amount or 0) for r in rows), 2),
            "state": state,
            "rejection_reason": first.rejection_reason if state == "rejected" else None,
            "started_on": _iso(min((r.created_at for r in rows if r.created_at), default=None)),
            "sent_on": _iso(first.proof_uploaded_at) if state != "not_paid" else None,
            "paid_on": _iso(first.received_on or first.approved_at) if state == "paid" else None,
            "receipt": ({"bulk_group_id": first.bulk_group_id} if first.bulk_group_id else {"challan_id": first.id})
            if state == "paid" else None,
            "sort": (first.approved_at or first.proof_uploaded_at or first.created_at or datetime.min).isoformat(),
        })
    items.sort(key=lambda i: i["sort"], reverse=True)
    for i in items:
        i.pop("sort")
    return items


def my_statement(db: Session, user_id: int, year: int | None = None) -> dict:
    """The signed-in person's own statement: one Aug-Jul year month by month, and all payments."""
    member = db.query(Member).filter(Member.user_id == user_id).first()
    if member is None:
        raise HTTPException(status_code=404, detail="There is no member record for your account, so there is no statement.")
    today = today_business()
    current_fy = today.year if today.month >= 8 else today.year - 1
    start_fy = max(PLATFORM_START.year if PLATFORM_START.month >= 8 else PLATFORM_START.year - 1,
                   _start_month(member).year if _start_month(member).month >= 8 else _start_month(member).year - 1)
    fy = current_fy if year is None else int(year)
    if fy < start_fy or fy > current_fy + 3:
        raise HTTPException(status_code=400, detail="There is no statement for that year.")
    joined = _start_month(member)
    from_month = max(f"{fy}-08", _month(joined))  # months before joining are not owed
    to_month = f"{fy + 1}-07"
    data = member_statement(db, member.id, from_month, to_month)
    data["year"] = fy
    data["label"] = f"{fy}-{fy + 1}"
    data["years"] = list(range(start_fy, current_fy + 1))
    data["history"] = payment_history(db, member.id)
    return data
