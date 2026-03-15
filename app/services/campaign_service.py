from sqlalchemy.orm import Session
from sqlalchemy import func, distinct
from app.models import Campaign, Challan
from app.models.models import ChallanType
from app.schemas import CampaignCreate, CampaignUpdate
from app.schemas import CampaignPaymentImportSummary
from fastapi import HTTPException, status
from datetime import datetime


class CampaignService:
    """Campaign management service."""

    @staticmethod
    def _normalize_campaign_values(
        *,
        target_mode: str,
        target_amount: float | None,
        min_amount: float,
        start_date: datetime,
        end_date_mode: str,
        end_date: datetime | None,
    ) -> dict:
        if min_amount <= 0:
            raise ValueError("Minimum amount must be greater than 0")

        if target_mode not in ("targeted", "unlimited"):
            raise ValueError("target_mode must be 'targeted' or 'unlimited'")

        if end_date_mode not in ("fixed", "open"):
            raise ValueError("end_date_mode must be 'fixed' or 'open'")

        normalized_target_amount = float(target_amount) if target_amount is not None else None
        if target_mode == "targeted":
            if normalized_target_amount is None or normalized_target_amount <= 0:
                raise ValueError("Target amount must be greater than 0 for targeted campaigns")
        else:
            normalized_target_amount = None

        normalized_end_date = end_date
        if end_date_mode == "fixed":
            if normalized_end_date is None:
                raise ValueError("End date is required for fixed-duration campaigns")
            if normalized_end_date < start_date:
                raise ValueError("End date cannot be earlier than start date")
        else:
            normalized_end_date = None

        return {
            "target_mode": target_mode,
            "target_amount": normalized_target_amount,
            "min_amount": float(min_amount),
            "start_date": start_date,
            "end_date_mode": end_date_mode,
            "end_date": normalized_end_date,
        }

    @staticmethod
    def _attach_campaign_stats(db: Session, campaign: Campaign | None):
        if not campaign:
            return campaign

        collected_amount, participants_count = db.query(
            func.coalesce(func.sum(Challan.amount), 0.0),
            func.count(distinct(Challan.member_id)),
        ).filter(
            Challan.campaign_id == campaign.id,
            Challan.type == ChallanType.CAMPAIGN,
            Challan.status == "approved",
        ).one()

        campaign.collected_amount = float(collected_amount or 0.0)
        campaign.participants_count = int(participants_count or 0)
        return campaign

    @staticmethod
    def _attach_campaign_stats_bulk(db: Session, campaigns: list[Campaign]):
        if not campaigns:
            return campaigns

        campaign_ids = [campaign.id for campaign in campaigns]

        stats_rows = db.query(
            Challan.campaign_id,
            func.coalesce(func.sum(Challan.amount), 0.0).label("collected_amount"),
            func.count(distinct(Challan.member_id)).label("participants_count"),
        ).filter(
            Challan.campaign_id.in_(campaign_ids),
            Challan.type == ChallanType.CAMPAIGN,
            Challan.status == "approved",
        ).group_by(Challan.campaign_id).all()

        stats_by_campaign_id = {
            row.campaign_id: {
                "collected_amount": float(row.collected_amount or 0.0),
                "participants_count": int(row.participants_count or 0),
            }
            for row in stats_rows
        }

        for campaign in campaigns:
            stats = stats_by_campaign_id.get(campaign.id, None)
            campaign.collected_amount = stats["collected_amount"] if stats else 0.0
            campaign.participants_count = stats["participants_count"] if stats else 0

        return campaigns
    
    @staticmethod
    def create_campaign(db: Session, campaign_data: CampaignCreate, admin_id: int):
        """Create new campaign."""
        normalized = CampaignService._normalize_campaign_values(
            target_mode=campaign_data.target_mode.value if hasattr(campaign_data.target_mode, "value") else str(campaign_data.target_mode),
            target_amount=campaign_data.target_amount,
            min_amount=campaign_data.min_amount,
            start_date=campaign_data.start_date,
            end_date_mode=campaign_data.end_date_mode.value if hasattr(campaign_data.end_date_mode, "value") else str(campaign_data.end_date_mode),
            end_date=campaign_data.end_date,
        )
        
        new_campaign = Campaign(
            title=campaign_data.title,
            description=campaign_data.description,
            target_mode=normalized["target_mode"],
            target_amount=normalized["target_amount"],
            min_amount=normalized["min_amount"],
            start_date=normalized["start_date"],
            end_date_mode=normalized["end_date_mode"],
            end_date=normalized["end_date"],
            created_by_admin_id=admin_id,
        )
        
        db.add(new_campaign)
        db.commit()
        db.refresh(new_campaign)
        
        return CampaignService._attach_campaign_stats(db, new_campaign)

    @staticmethod
    def import_campaign_payments_file(
        db: Session,
        file_bytes: bytes,
        filename: str,
        imported_by_user_id: int | None,
    ) -> CampaignPaymentImportSummary:
        from app.services.member_service import MemberService

        rows = MemberService.read_tabular_rows(file_bytes, filename)

        total_rows = len(rows)
        campaigns_created = 0
        challans_created = 0
        members_linked_existing = 0
        rows_skipped = 0
        errors: list[str] = []

        known_campaign_ids: set[int] = {row[0] for row in db.query(Campaign.id).all()}

        for idx, raw_row in enumerate(rows, start=2):
            row = MemberService.normalized_row(raw_row)

            try:
                row_type = (MemberService.normalize_contact(MemberService.row_value(row, ["type", "donation_type"])) or "campaign").lower()
                if row_type not in ("campaign", "donation", "one-time", "one_time"):
                    rows_skipped += 1
                    errors.append(f"Row {idx}: unsupported type '{row_type}'")
                    continue

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

                amount_raw = MemberService.row_value(row, ["amount", "donation_amount", "paid_amount"])
                if amount_raw in (None, ""):
                    rows_skipped += 1
                    errors.append(f"Row {idx}: amount is required")
                    continue

                amount = float(amount_raw)
                campaign_name = MemberService.row_value(row, ["suggested_campaign_name", "campaign_name", "campaign"])
                campaign_id = MemberService.resolve_campaign_for_import(
                    db,
                    campaign_name,
                    imported_by_user_id,
                )

                if not campaign_id:
                    campaign_id = MemberService.resolve_campaign_for_import(
                        db,
                        "General Fund / One-Time Contribution 2024-2025",
                        imported_by_user_id,
                    )

                if not campaign_id:
                    rows_skipped += 1
                    errors.append(f"Row {idx}: unable to resolve campaign")
                    continue

                if campaign_id not in known_campaign_ids:
                    campaigns_created += 1
                    known_campaign_ids.add(campaign_id)

                payment_method = MemberService.normalize_contact(
                    MemberService.row_value(row, ["payment_method", "method"])
                )
                raw_status = MemberService.normalize_contact(
                    MemberService.row_value(row, ["status", "donation_status", "challan_status", "payment_status"])
                )

                normalized_status = "generated"
                current = (raw_status or "generated").lower()
                if current in ("approved", "paid", "completed"):
                    normalized_status = "approved"
                elif current in ("pending",):
                    normalized_status = "pending"
                elif current in ("rejected", "failed"):
                    normalized_status = "rejected"

                duplicate = db.query(Challan).filter(
                    Challan.member_id == member.id,
                    Challan.type == ChallanType.CAMPAIGN,
                    Challan.campaign_id == campaign_id,
                    Challan.amount == amount,
                ).first()
                if duplicate:
                    continue

                challan = Challan(
                    member_id=member.id,
                    type=ChallanType.CAMPAIGN,
                    campaign_id=campaign_id,
                    month=None,
                    amount=amount,
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

        return CampaignPaymentImportSummary(
            total_rows=total_rows,
            campaigns_created=campaigns_created,
            challans_created=challans_created,
            members_linked_existing=members_linked_existing,
            rows_skipped=rows_skipped,
            errors=errors[:50],
        )
    
    @staticmethod
    def get_campaign(db: Session, campaign_id: int):
        """Get campaign by ID."""
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        
        if not campaign:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign not found",
            )
        
        return CampaignService._attach_campaign_stats(db, campaign)
    
    @staticmethod
    def get_all_campaigns(db: Session, skip: int = 0, limit: int = 100, active_only: bool = False):
        """Get all campaigns with optional filtering."""
        query = db.query(Campaign)
        
        if active_only:
            query = query.filter(Campaign.is_active == True)
        
        campaigns = query.offset(skip).limit(limit).all()
        return CampaignService._attach_campaign_stats_bulk(db, campaigns)
    
    @staticmethod
    def update_campaign(db: Session, campaign_id: int, update_data: CampaignUpdate):
        """Update campaign information."""
        campaign = CampaignService.get_campaign(db, campaign_id)
        
        update_fields = update_data.model_dump(exclude_unset=True)

        resolved = CampaignService._normalize_campaign_values(
            target_mode=update_fields.get("target_mode", campaign.target_mode),
            target_amount=update_fields.get("target_amount", campaign.target_amount),
            min_amount=update_fields.get("min_amount", campaign.min_amount),
            start_date=update_fields.get("start_date", campaign.start_date),
            end_date_mode=update_fields.get("end_date_mode", campaign.end_date_mode),
            end_date=update_fields.get("end_date", campaign.end_date),
        )

        for key, value in update_fields.items():
            if value is not None:
                setattr(campaign, key, value)

        campaign.target_mode = resolved["target_mode"]
        campaign.target_amount = resolved["target_amount"]
        campaign.min_amount = resolved["min_amount"]
        campaign.start_date = resolved["start_date"]
        campaign.end_date_mode = resolved["end_date_mode"]
        campaign.end_date = resolved["end_date"]
        
        db.commit()
        db.refresh(campaign)
        
        return CampaignService._attach_campaign_stats(db, campaign)
    
    @staticmethod
    def delete_campaign(db: Session, campaign_id: int):
        """Delete campaign."""
        campaign = CampaignService.get_campaign(db, campaign_id)
        
        db.delete(campaign)
        db.commit()
        
        return {"message": "Campaign deleted"}
