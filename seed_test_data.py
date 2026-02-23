"""
Seed test data for integration testing
Creates admin user, member user, and valid invite code
"""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.database import SessionLocal, engine
from app.models.models import Base, User, Member, Invite, UserRole
from app.utils.auth import hash_password, generate_invite_code, generate_member_code

# Create tables if they don't exist
Base.metadata.create_all(bind=engine)

def seed_test_data():
    db = SessionLocal()
    
    try:
        print("🌱 Seeding test data...")
        
        # Check if admin user already exists
        existing_admin = db.query(User).filter(User.username == "admin").first()
        if existing_admin:
            print("⚠️  Admin user already exists. Skipping...")
        else:
            # Create admin user
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
        
        # Check if member user already exists
        existing_member_user = db.query(User).filter(User.username == "testmember").first()
        if existing_member_user:
            print("⚠️  Member user already exists. Skipping...")
        else:
            # Get the last member code for sequential generation
            last_member = db.query(Member).order_by(Member.id.desc()).first()
            last_code = last_member.member_code if last_member else None
            new_member_code = generate_member_code(last_code)
            
            # Create member user
            member_user = User(
                username="testmember",
                email="member@charityconnect.com",
                phone="+9876543210",
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
                monthly_amount=500.0,
                address="123 Test Street, Test City",
                status="active"
            )
            db.add(member_profile)
            db.commit()
            db.refresh(member_profile)
            print(f"✅ Member user created: {member_user.username} (ID: {member_user.id}, Code: {new_member_code})")
        
        # Create invite code (always create a fresh one for testing)
        admin_user = db.query(User).filter(User.role == UserRole.ADMIN).first()
        if not admin_user:
            print("❌ No admin user found. Cannot create invite code.")
            return
        
        # Check for existing unused invite codes
        existing_invite = db.query(Invite).filter(
            Invite.is_used == False,
            Invite.expiry_date > datetime.utcnow()
        ).first()
        
        if existing_invite:
            print(f"⚠️  Valid invite code already exists: {existing_invite.invite_code}")
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
            print(f"✅ Invite code created: {invite.invite_code} (Expires: {invite.expiry_date.date()})")
        
        print("\n" + "="*60)
        print("📋 TEST CREDENTIALS")
        print("="*60)
        
        # Fetch latest data
        admin = db.query(User).filter(User.username == "admin").first()
        member = db.query(User).filter(User.username == "testmember").first()
        valid_invite = db.query(Invite).filter(
            Invite.is_used == False,
            Invite.expiry_date > datetime.utcnow()
        ).first()
        
        print("\n🔑 Admin User:")
        print(f"   Email: {admin.email}")
        print(f"   Username: {admin.username}")
        print(f"   Password: Admin@123")
        print(f"   Role: {admin.role}")
        
        print("\n👤 Member User:")
        print(f"   Email: {member.email}")
        print(f"   Username: {member.username}")
        print(f"   Password: Member@123")
        print(f"   Role: {member.role}")
        if member.member:
            print(f"   Member Code: {member.member.member_code}")
        
        print("\n🎟️  Valid Invite Code:")
        print(f"   Code: {valid_invite.invite_code}")
        print(f"   Expires: {valid_invite.expiry_date.date()}")
        
        print("\n" + "="*60)
        print("✅ Test data seeded successfully!")
        print("="*60)
        
    except Exception as e:
        print(f"❌ Error seeding data: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed_test_data()
