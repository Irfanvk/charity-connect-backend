"""
Seed test data for integration testing
Creates admin user, multiple member users, valid invite code, and bulk challan test data
"""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.database import SessionLocal, engine
from app.models.models import Base, User, Member, Invite, UserRole, BulkChallanGroup, Challan, ChallanType, ChallanStatus
from app.utils.auth import hash_password, generate_invite_code, generate_member_code
import json

# Create tables if they don't exist
Base.metadata.create_all(bind=engine)

def seed_test_data():
    db = SessionLocal()
    
    try:
        print("🌱 Seeding test data...")
        
        # === ADMIN USER ===
        existing_admin = db.query(User).filter(User.username == "admin").first()
        if existing_admin:
            print("⚠️  Admin user already exists. Skipping...")
            admin_user = existing_admin
        else:
            admin_user = User(
                username="admin",
                email="admin@charityconnect.com",
                phone="+1234567890",
                password_hash=hash_password("Admin@123"),
                role=UserRole.ADMIN,
                is_active=True
            )
            db.add(admin_user)
            db.commit()
            db.refresh(admin_user)
            print(f"✅ Admin user created: {admin_user.username} (ID: {admin_user.id})")
        
        # === MEMBER USERS (5 total for bulk operations testing) ===
        member_users = []
        member_profiles = []
        
        for i in range(1, 6):
            username = f"testmember{i}" if i > 1 else "testmember"
            email = f"member{i}@charityconnect.com" if i > 1 else "member@charityconnect.com"
            
            existing_member_user = db.query(User).filter(User.username == username).first()
            if existing_member_user:
                print(f"⚠️  Member user '{username}' already exists. Skipping...")
                member_users.append(existing_member_user)
                member_profile = db.query(Member).filter(Member.user_id == existing_member_user.id).first()
                if member_profile:
                    member_profiles.append(member_profile)
            else:
                # Get the last member code for sequential generation
                last_member = db.query(Member).order_by(Member.id.desc()).first()
                last_code = last_member.member_code if last_member else None
                new_member_code = generate_member_code(last_code)
                
                # Create member user
                member_user = User(
                    username=username,
                    email=email,
                    phone=f"+987654{i:04d}",
                    password_hash=hash_password("Member@123"),
                    role=UserRole.MEMBER,
                    is_active=True
                )
                db.add(member_user)
                db.commit()
                db.refresh(member_user)
                
                # Create member profile
                member_profile = Member(
                    user_id=member_user.id,
                    member_code=new_member_code,
                    monthly_amount=100.0,
                    address=f"{100 + i*10} Test Street, Test City",
                    status="active"
                )
                db.add(member_profile)
                db.commit()
                db.refresh(member_profile)
                
                member_users.append(member_user)
                member_profiles.append(member_profile)
                print(f"✅ Member user created: {member_user.username} (ID: {member_user.id}, Code: {new_member_code})")
        
        # === BULK CHALLAN GROUPS (for v1.1 testing) ===
        print("\n🎯 Creating bulk challan test data...")
        
        # Check if bulk groups already exist
        existing_bulk_count = db.query(BulkChallanGroup).count()
        if existing_bulk_count > 0:
            print(f"⚠️  {existing_bulk_count} bulk group(s) already exist. Skipping bulk data creation...")
        else:
            # Create 2 pending bulk groups for first 2 members
            for i, member_profile in enumerate(member_profiles[:2]):
                bulk_group_id = f"bulk-20260303-{i:03d}"
                months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"]
                challan_ids = []
                
                # Create 5 challans for this bulk group
                for month in months:
                    challan = Challan(
                        member_id=member_profile.id,
                        type=ChallanType.MONTHLY,
                        month=month,
                        amount=100.0,
                        status=ChallanStatus.PENDING,
                        bulk_group_id=bulk_group_id,
                        proof_path=None,
                        created_at=datetime.utcnow()
                    )
                    db.add(challan)
                    db.flush()
                    challan_ids.append(challan.id)
                
                # Create bulk group record
                bulk_group = BulkChallanGroup(
                    bulk_group_id=bulk_group_id,
                    member_id=member_profile.id,
                    amount_per_month=100.0,
                    total_amount=500.0,
                    proof_file_id=f"test-proof-{i:03d}.jpg",
                    status="pending_approval",
                    months_list=json.dumps(months),
                    challan_ids_list=json.dumps(challan_ids),
                    created_by_user_id=member_profile.user_id,
                    notes=f"Test bulk payment group {i+1} - Pending admin approval",
                    created_at=datetime.utcnow()
                )
                db.add(bulk_group)
                db.commit()
                print(f"✅ Bulk group created: {bulk_group_id} (5 challans for member {member_profile.member_code})")
            
            print(f"✅ Created 2 pending bulk groups with 10 total challans")
        
        # === INVITE CODE ===
        existing_invite = db.query(Invite).filter(
            Invite.is_used == False,
            Invite.expiry_date > datetime.utcnow()
        ).first()
        
        if existing_invite:
            print(f"\n⚠️  Valid invite code already exists: {existing_invite.invite_code}")
            valid_invite = existing_invite
        else:
            invite_code_str = generate_invite_code()
            invite = Invite(
                invite_code=invite_code_str,
                email=None,  # Generic invite
                phone=None,
                is_used=False,
                expiry_date=datetime.utcnow() + timedelta(days=30),
                created_by_admin_id=admin_user.id
            )
            db.add(invite)
            db.commit()
            db.refresh(invite)
            valid_invite = invite
            print(f"\n✅ Invite code created: {invite.invite_code} (Expires: {invite.expiry_date.date()})")
        
        # === PRINT TEST CREDENTIALS ===
        print("\n" + "="*70)
        print("📋 TEST CREDENTIALS & DATA SUMMARY")
        print("="*70)
        
        print("\n🔑 Admin User:")
        print(f"   Email: {admin_user.email}")
        print(f"   Username: {admin_user.username}")
        print(f"   Password: Admin@123")
        print(f"   Role: {admin_user.role}")
        
        print("\n👥 Member Users (5 total):")
        for i, (user, profile) in enumerate(zip(member_users, member_profiles), 1):
            print(f"\n   Member {i}:")
            print(f"     Email: {user.email}")
            print(f"     Username: {user.username}")
            print(f"     Password: Member@123")
            print(f"     Member Code: {profile.member_code}")
            print(f"     Monthly Amount: {profile.monthly_amount} Rs")
        
        print("\n🎟️  Valid Invite Code:")
        print(f"   Code: {valid_invite.invite_code}")
        print(f"   Expires: {valid_invite.expiry_date.date()}")
        
        # Bulk operations summary
        bulk_count = db.query(BulkChallanGroup).filter(
            BulkChallanGroup.status == "pending_approval"
        ).count()
        challan_count = db.query(Challan).filter(
            Challan.bulk_group_id.isnot(None)
        ).count()
        
        print("\n📦 Bulk Operations Test Data:")
        print(f"   Pending bulk groups: {bulk_count}")
        print(f"   Linked challans: {challan_count}")
        print(f"   API endpoint: GET /admin/bulk-pending-review")
        
        print("\n" + "="*70)
        print("✅ Test data seeded successfully! Ready for v1.1 testing.")
        print("="*70)
        print("\n💡 Test bulk operations:")
        print("   1. Login as admin")
        print("   2. GET /admin/bulk-pending-review (should return 2 pending)")
        print("   3. PATCH /admin/bulk/bulk-20260303-000/approve")
        print("   4. Login as testmember3")
        print("   5. POST /challans/bulk-create (create new bulk)")
        print("="*70 + "\n")
        
    except Exception as e:
        print(f"❌ Error seeding data: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed_test_data()
