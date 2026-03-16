"""
seed_admin.py — Create initial admin / superadmin users in the database.
Usage:
    python seed_admin.py
"""
import os
import getpass
import sys
from dotenv import load_dotenv
import psycopg2
from passlib.context import CryptContext

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not found in .env")
    sys.exit(1)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_role_enum_values(conn) -> list[str]:
    """Discover valid role values from the actual enum type in the DB."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT e.enumlabel
            FROM pg_enum e
            JOIN pg_type t ON e.enumtypid = t.oid
            JOIN pg_attribute a ON a.atttypid = t.oid
            JOIN pg_class c ON a.attrelid = c.oid
            WHERE c.relname = 'users' AND a.attname = 'role'
            ORDER BY e.enumsortorder;
            """
        )
        rows = cur.fetchall()
    return [r[0] for r in rows] if rows else ["superadmin", "admin", "member"]


def create_user(conn, username: str, email: str, password: str, role: str) -> None:
    password_hash = pwd_context.hash(password)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (username, email, password_hash, role, is_active)
            VALUES (%s, %s, %s, %s::userrole, true)
            ON CONFLICT (username) DO NOTHING
            RETURNING id, username, role;
            """,
            (username, email or None, password_hash, role),
        )
        row = cur.fetchone()
        if row:
            print(f"  Created user  id={row[0]}  username='{row[1]}'  role={row[2]}")
        else:
            print(f"  Username '{username}' already exists — skipped.")
    conn.commit()


def main():
    print("=== CharityConnect — Seed Admin Users ===\n")
    print(f"Database: {DATABASE_URL[:40]}...\n")

    try:
        conn = psycopg2.connect(DATABASE_URL)
    except Exception as e:
        print(f"ERROR: Could not connect to database: {e}")
        sys.exit(1)

    ROLES = get_role_enum_values(conn)
    print(f"Valid roles in DB: {', '.join(ROLES)}\n")

    while True:
        print("--- New user ---")
        username = input("  Username       : ").strip()
        if not username:
            print("  Username cannot be empty.\n")
            continue

        email = input("  Email (optional): ").strip()

        while True:
            password = getpass.getpass("  Password       : ")
            confirm  = getpass.getpass("  Confirm password: ")
            if password == confirm:
                break
            print("  Passwords do not match. Try again.")

        print(f"  Roles: {', '.join(ROLES)}")
        role_input = input("  Role           : ").strip()
        # Accept case-insensitive input while preserving DB enum's exact casing.
        role_lookup = {r.lower(): r for r in ROLES}
        role = role_lookup.get(role_input.lower())
        if role is None:
            print(f"  Invalid role '{role_input}'. Must be one of {ROLES}.\n")
            continue

        create_user(conn, username, email, password, role)

        again = input("\nAdd another user? [y/N]: ").strip().lower()
        if again != "y":
            break

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
