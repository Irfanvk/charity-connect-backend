from sqlalchemy.orm import Session
from sqlalchemy import String, cast
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import case
from app.models import Challan, Member, User
from app.models.models import ChallanStatus, ChallanType
from app.schemas import ChallanCreate, ChallanReject, ChallanUpdate
from app.utils.file_handler import save_file, validate_file
from fastapi import HTTPException, status
from datetime import datetime
from app.schemas import ChallanHistoryImportSummary


class ChallanService:
    """Challan management service."""

    SORTABLE_COLUMNS = {
        "created_at": Challan.created_at,
        "updated_at": Challan.updated_at,
        "amount": Challan.amount,
        "status": Challan.status,
        "month": Challan.month,
    }
    
    @staticmethod
    def create_challan(db: Session, member_id: int, challan_data: ChallanCreate):
        """Create new challan."""
        
        # Verify member exists
        member = db.query(Member).filter(Member.id == member_id).first()
        if not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Member not found",
            )
        
        # Validate challan data
        if challan_data.type == ChallanType.MONTHLY and not challan_data.month:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Month required for monthly challans",
            )
        
        if challan_data.type == ChallanType.CAMPAIGN and not challan_data.campaign_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Campaign ID required for campaign challans",
            )
        
        # Check if monthly challan already exists for this month
        if challan_data.type == ChallanType.MONTHLY:
            existing = db.query(Challan).filter(
                Challan.member_id == member_id,
                Challan.type == ChallanType.MONTHLY,
                Challan.month == challan_data.month,
                Challan.status.in_([ChallanStatus.GENERATED, ChallanStatus.PENDING]),
            ).first()
            
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Challan already exists for this month",
                )
        
        new_challan = Challan(
            member_id=member_id,
            type=challan_data.type,
            month=challan_data.month,
            campaign_id=challan_data.campaign_id,
            amount=challan_data.amount,
            payment_method=challan_data.payment_method,
        )
        
        db.add(new_challan)
        db.commit()
        db.refresh(new_challan)
        
        return new_challan

    @staticmethod
    def _normalize_import_status(raw_status: str | None) -> str:
        normalized_status = "generated"
        current = (raw_status or "generated").lower()
        if current in ("approved", "paid", "completed"):
            normalized_status = "approved"
        elif current in ("pending",):
            normalized_status = "pending"
        elif current in ("rejected", "failed"):
            normalized_status = "rejected"
        return normalized_status

    @staticmethod
    def import_challan_history_file(
        db: Session,
        file_bytes: bytes,
        filename: str,
    ) -> ChallanHistoryImportSummary:
        from app.services.member_service import MemberService

        rows = MemberService.read_tabular_rows(file_bytes, filename)

        total_rows = len(rows)
        challans_created = 0
        members_linked_existing = 0
        rows_skipped = 0
        errors: list[str] = []

        for idx, raw_row in enumerate(rows, start=2):
            row = MemberService.normalized_row(raw_row)

            try:
                username = MemberService.normalize_contact(
                    MemberService.row_value(row, ["username", "user_name"])
                )
                member_code = MemberService.normalize_member_code(
                    MemberService.row_value(row, ["member_code", "member_id", "code"])
                )
                si_code = MemberService.si_to_member_code(
                    MemberService.row_value(row, ["si_no", "si", "serial_no"])
                )
                member_code = member_code or si_code

                member = MemberService.find_member_by_identifiers(
                    db=db,
                    member_code=member_code,
                    username=username,
                    phone=MemberService.normalize_contact(MemberService.row_value(row, ["phone", "mobile"])),
                    email=MemberService.normalize_contact(MemberService.row_value(row, ["email", "email_address"])),
                )

                if not member:
                    rows_skipped += 1
                    errors.append(f"Row {idx}: member not found for identifier fields")
                    continue

                members_linked_existing += 1

                donation_month = MemberService.normalize_contact(
                    MemberService.row_value(row, ["month", "donation_month", "payment_month", "period"])
                )
                donation_month = MemberService.parse_month(donation_month)
                if not donation_month:
                    rows_skipped += 1
                    errors.append(f"Row {idx}: missing valid month for monthly challan")
                    continue

                donation_amount_raw = MemberService.row_value(row, ["amount", "donation_amount", "paid_amount"])
                if donation_amount_raw in (None, ""):
                    rows_skipped += 1
                    errors.append(f"Row {idx}: amount is required")
                    continue

                donation_amount = float(donation_amount_raw)
                payment_method = MemberService.normalize_contact(
                    MemberService.row_value(row, ["payment_method", "method"])
                )
                raw_status = MemberService.normalize_contact(
                    MemberService.row_value(row, ["status", "donation_status", "challan_status", "payment_status"])
                )
                normalized_status = ChallanService._normalize_import_status(raw_status)

                duplicate = db.query(Challan).filter(
                    Challan.member_id == member.id,
                    Challan.type == ChallanType.MONTHLY,
                    Challan.month == donation_month,
                    Challan.amount == donation_amount,
                ).first()
                if duplicate:
                    continue

                challan = Challan(
                    member_id=member.id,
                    type=ChallanType.MONTHLY,
                    month=donation_month,
                    amount=donation_amount,
                    payment_method=payment_method,
                    status=normalized_status,
                )
                if normalized_status == "approved":
                    challan.approved_at = datetime.utcnow()
                db.add(challan)
                challans_created += 1
            except (ValueError, TypeError) as exc:
                rows_skipped += 1
                errors.append(f"Row {idx}: {exc}")

        db.commit()

        return ChallanHistoryImportSummary(
            total_rows=total_rows,
            challans_created=challans_created,
            members_linked_existing=members_linked_existing,
            rows_skipped=rows_skipped,
            errors=errors[:50],
        )
    
    @staticmethod
    def upload_proof(db: Session, challan_id: int, file_content: bytes, filename: str):
        """Upload payment proof for challan."""
        
        challan = db.query(Challan).filter(Challan.id == challan_id).first()
        if not challan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Challan not found",
            )
        
        if challan.status not in [ChallanStatus.GENERATED, ChallanStatus.PENDING, ChallanStatus.REJECTED]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot upload proof for this challan status",
            )
        
        # Validate file
        validate_file(file_content, filename)
        
        # Save file
        proof_path = save_file(file_content, "proofs", filename)
        
        # Update challan
        challan.proof_path = proof_path
        challan.proof_uploaded_at = datetime.utcnow()
        challan.status = ChallanStatus.PENDING
        challan.rejection_reason = None
        challan.approved_by_admin_id = None
        challan.approved_at = None
        
        db.commit()
        db.refresh(challan)
        
        return challan
    
    @staticmethod
    def approve_challan(db: Session, challan_id: int, approved_by_admin_id: int):
        """Approve challan."""
        
        challan = db.query(Challan).filter(Challan.id == challan_id).first()
        if not challan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Challan not found",
            )
        
        if challan.status != ChallanStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only pending challans can be approved",
            )
        
        challan.status = ChallanStatus.APPROVED
        challan.approved_by_admin_id = approved_by_admin_id
        challan.approved_at = datetime.utcnow()
        
        db.commit()
        db.refresh(challan)
        
        return challan
    
    @staticmethod
    def reject_challan(db: Session, challan_id: int, reject_data: ChallanReject):
        """Reject challan."""
        
        challan = db.query(Challan).filter(Challan.id == challan_id).first()
        if not challan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Challan not found",
            )
        
        if challan.status != ChallanStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only pending challans can be rejected",
            )
        
        challan.status = ChallanStatus.REJECTED
        challan.rejection_reason = reject_data.rejection_reason
        
        db.commit()
        db.refresh(challan)
        
        return challan

    @staticmethod
    def update_challan(db: Session, challan_id: int, update_data: ChallanUpdate):
        """Update mutable challan fields."""
        challan = db.query(Challan).filter(Challan.id == challan_id).first()
        if not challan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Challan not found",
            )

        changes = update_data.dict(exclude_unset=True)
        for key, value in changes.items():
            setattr(challan, key, value)

        db.commit()
        db.refresh(challan)
        return challan
    
    @staticmethod
    def get_challan(db: Session, challan_id: int):
        """Get challan by ID."""
        challan = db.query(Challan).filter(Challan.id == challan_id).first()
        
        if not challan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Challan not found",
            )
        
        return challan
    
    @staticmethod
    def get_member_challans(
        db: Session,
        member_id: int,
        skip: int = 0,
        limit: int = 100,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ):
        """Get all challans for a member."""
        query = db.query(Challan).filter(Challan.member_id == member_id)
        sort_column = ChallanService.SORTABLE_COLUMNS.get(sort_by, Challan.created_at)
        query = query.order_by(sort_column.desc() if sort_order == "desc" else sort_column.asc())
        return query.offset(skip).limit(limit).all()
    
    @staticmethod
    def get_all_challans(
        db: Session,
        skip: int = 0,
        limit: int = 100,
        # ── existing param (kept for backward compat) ──────────────────────
        status_filter: str = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        # ── new filter params sent by the frontend ─────────────────────────
        search: str = None,
        member_id: int = None,
        created_by: str = None,
        has_proof: bool = None,
    ):
        """Get all challans with optional server-side filtering.

        Frontend sends these query-string params:
          status      → maps to status_filter
          search      → ILIKE on challan_number + member_name (via Member join)
          member_id   → scope to a single member (non-admin users)
          created_by  → scope by creator email (fallback when member_id unknown)
          has_proof   → true = proof_uploaded_at IS NOT NULL
        """
        query = db.query(Challan)
        member_joined = False
        user_joined = False

        def ensure_member_join(q):
            nonlocal member_joined
            if not member_joined:
                q = q.outerjoin(Member, Challan.member_id == Member.id)
                member_joined = True
            return q

        def ensure_user_join(q):
            nonlocal user_joined
            q = ensure_member_join(q)
            if not user_joined:
                q = q.outerjoin(User, Member.user_id == User.id)
                user_joined = True
            return q

        # ── status ──────────────────────────────────────────────────────────
        # Accept both the legacy `status_filter` kwarg and a bare `status`
        # string — the router may pass either depending on how it reads params.
        if status_filter:
            query = query.filter(Challan.status == status_filter)

        # ── has_proof ────────────────────────────────────────────────────────
        # Frontend sends has_proof=true for the "Proof Uploaded" tab.
        # URLSearchParams serialises booleans as the strings "true"/"false",
        # so we normalise here just in case the router passes a string.
        if has_proof is not None:
            # Coerce string → bool in case FastAPI didn't auto-convert
            _has_proof = has_proof if isinstance(has_proof, bool) else str(has_proof).lower() == "true"
            if _has_proof:
                query = query.filter(Challan.proof_uploaded_at.isnot(None))
            else:
                query = query.filter(Challan.proof_uploaded_at.is_(None))

        # ── member_id scoping ────────────────────────────────────────────────
        if member_id is not None:
            query = query.filter(Challan.member_id == member_id)

        # ── created_by scoping (email fallback for non-members) ──────────────
        if created_by:
            term = f"%{created_by.strip()}%"
            query = ensure_user_join(query)
            query = query.filter(
                or_(
                    User.email.ilike(term),
                    User.username.ilike(term),
                )
            )

        # ── search ───────────────────────────────────────────────────────────
        # Searches challan_number directly on the Challan table.
        # Also searches member full_name via a JOIN on the Member table.
        if search:
            term = f"%{search.strip()}%"
            query = ensure_user_join(query)
            query = query.filter(
                or_(
                    cast(Challan.id, String).ilike(term),
                    Challan.month.ilike(term),
                    Member.member_code.ilike(term),
                    User.username.ilike(term),
                    User.email.ilike(term),
                )
            )

        # ── sorting ──────────────────────────────────────────────────────────
        sort_column = ChallanService.SORTABLE_COLUMNS.get(sort_by, Challan.created_at)
        query = query.order_by(
            sort_column.desc() if sort_order == "desc" else sort_column.asc()
        )

        return query.offset(skip).limit(limit).all()

    @staticmethod
    def get_challan_summary(
        db: Session,
        month: str | None = None,
        member_id: int | None = None,
    ) -> dict:
        base_query = db.query(Challan)
        if member_id is not None:
            base_query = base_query.filter(Challan.member_id == member_id)

        total_challans, approved_count, pending_count = base_query.with_entities(
            func.coalesce(func.sum(case((Challan.id.isnot(None), 1), else_=0)), 0),
            func.coalesce(func.sum(case((Challan.status == ChallanStatus.APPROVED, 1), else_=0)), 0),
            func.coalesce(func.sum(case((Challan.status == ChallanStatus.PENDING, 1), else_=0)), 0),
        ).one()

        total_collected = base_query.filter(
            Challan.status == ChallanStatus.APPROVED
        ).with_entities(func.coalesce(func.sum(Challan.amount), 0.0)).scalar() or 0.0

        monthly_query = base_query.filter(Challan.status == ChallanStatus.APPROVED)
        if month:
            monthly_query = monthly_query.filter(Challan.month == month)
        else:
            monthly_query = monthly_query.filter(Challan.month.is_(None))

        monthly_collection = monthly_query.with_entities(
            func.coalesce(func.sum(Challan.amount), 0.0)
        ).scalar() or 0.0

        return {
            "total_challans": int(total_challans),
            "approved_count": int(approved_count),
            "pending_count": int(pending_count),
            "total_collected": float(total_collected),
            "monthly_collection": float(monthly_collection),
        }