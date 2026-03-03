"""
Database migration for Bulk Operations v1.1
Adds challan_bulk_groups table and bulk_group_id column to challans table
"""
from sqlalchemy import text
from app.database import SessionLocal, engine

def run_migration():
    db = SessionLocal()
    
    try:
        print("🔄 Starting bulk operations migration (v1.1)...")
        
        # Check if challan_bulk_groups table exists
        result = db.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'challan_bulk_groups'
            );
        """))
        table_exists = result.scalar()
        
        if table_exists:
            print("⚠️  Table 'challan_bulk_groups' already exists. Skipping table creation...")
        else:
            # Create challan_bulk_groups table
            print("📦 Creating 'challan_bulk_groups' table...")
            db.execute(text("""
                CREATE TABLE challan_bulk_groups (
                    id SERIAL PRIMARY KEY,
                    bulk_group_id VARCHAR(50) UNIQUE NOT NULL,
                    member_id INTEGER NOT NULL,
                    amount_per_month FLOAT NOT NULL,
                    total_amount FLOAT NOT NULL,
                    proof_file_id VARCHAR(255) NOT NULL,
                    status VARCHAR(20) DEFAULT 'pending_approval' NOT NULL,
                    months_list TEXT NOT NULL,
                    challan_ids_list TEXT NOT NULL,
                    admin_notes TEXT,
                    approved_by_admin_id INTEGER,
                    rejection_reason TEXT,
                    created_by_user_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    approved_at TIMESTAMP,
                    rejected_at TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT,
                    FOREIGN KEY (member_id) REFERENCES members(id),
                    FOREIGN KEY (created_by_user_id) REFERENCES users(id),
                    FOREIGN KEY (approved_by_admin_id) REFERENCES users(id)
                );
            """))
            db.commit()
            print("✅ Table 'challan_bulk_groups' created successfully")
        
        # Check if bulk_group_id column exists in challans table
        result = db.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = 'challans' 
                AND column_name = 'bulk_group_id'
            );
        """))
        column_exists = result.scalar()
        
        if column_exists:
            print("⚠️  Column 'bulk_group_id' already exists in 'challans' table. Skipping...")
        else:
            # Add bulk_group_id column to challans table
            print("📝 Adding 'bulk_group_id' column to 'challans' table...")
            db.execute(text("""
                ALTER TABLE challans 
                ADD COLUMN bulk_group_id VARCHAR(50);
            """))
            db.commit()
            print("✅ Column 'bulk_group_id' added successfully")
            
            # Create index for better query performance
            print("📇 Creating index on 'bulk_group_id'...")
            db.execute(text("""
                CREATE INDEX idx_challans_bulk_group_id 
                ON challans(bulk_group_id);
            """))
            db.commit()
            print("✅ Index created successfully")
        
        print("\n" + "="*60)
        print("✅ Migration completed successfully!")
        print("="*60)
        print("\n💡 Next steps:")
        print("   1. Run: python seed_test_data.py")
        print("   2. Start server: uvicorn app.main:app --reload")
        print("   3. Test bulk endpoints at: http://localhost:8000/docs")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    run_migration()
