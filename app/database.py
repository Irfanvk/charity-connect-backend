import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

logger = logging.getLogger(__name__)

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


def _add_missing_columns(connection, inspector, table: str, ddl: dict) -> set:
    """Guarded ADD COLUMN; returns the names of columns that were added."""
    if not inspector.has_table(table):
        return set()
    existing = {column["name"] for column in inspector.get_columns(table)}
    added = set()
    for name, column_ddl in ddl.items():
        if name not in existing:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {column_ddl}"))
            added.add(name)
    return added


def _ensure_separation_of_duties_columns(connection, inspector) -> None:
    reversal_ddl = {
        "reversed_at": "TIMESTAMP",
        "reversed_by_admin_id": "INTEGER REFERENCES users(id)",
        "reversal_reason": "TEXT",
    }
    _add_missing_columns(connection, inspector, "challans", reversal_ddl)
    _add_missing_columns(connection, inspector, "challan_bulk_groups", reversal_ddl)

    added = _add_missing_columns(
        connection,
        inspector,
        "fund_utilizations",
        {
            "status": "VARCHAR(20) NOT NULL DEFAULT 'pending'",
            "approved_by_admin_id": "INTEGER REFERENCES users(id)",
            "approved_at": "TIMESTAMP",
            "rejection_reason": "TEXT",
            **reversal_ddl,
        },
    )
    if "status" in added:
        # Rows that existed before the two-person rule keep counting towards balances.
        connection.execute(text("UPDATE fund_utilizations SET status = 'approved', approved_at = created_at"))


def _ensure_admin_recorded_payment_columns(connection, inspector) -> None:
    added = _add_missing_columns(
        connection,
        inspector,
        "challans",
        {
            "created_by_user_id": "INTEGER REFERENCES users(id)",
            "entry_source": "VARCHAR(20)",
            "transaction_ref": "VARCHAR(100)",
            "received_on": "DATE",
            "collected_by_user_id": "INTEGER REFERENCES users(id)",
            "entry_notes": "TEXT",
        },
    )
    if "entry_source" in added:
        # Imported history is approved without an approver or proof; everything else was member-created.
        connection.execute(text(
            "UPDATE challans SET entry_source = 'import' "
            "WHERE LOWER(CAST(status AS VARCHAR)) = 'approved' AND approved_by_admin_id IS NULL AND proof_path IS NULL"
        ))
        connection.execute(text("UPDATE challans SET entry_source = 'self' WHERE entry_source IS NULL"))

def _ensure_notification_ux_columns(connection, inspector) -> None:
    _add_missing_columns(connection, inspector, "notifications", {
        "category": "VARCHAR(30)",
        "link_url": "VARCHAR(255)",
        "entity_type": "VARCHAR(30)",
        "entity_id": "INTEGER",
        "is_urgent": "BOOLEAN NOT NULL DEFAULT false",
    })
    _add_missing_columns(connection, inspector, "push_subscriptions", {
        "vapid_key_id": "VARCHAR(32)",
        "last_success_at": "TIMESTAMP",
        "last_failure_at": "TIMESTAMP",
        "last_failure_reason": "VARCHAR(255)",
        "device_label": "VARCHAR(100)",
    })
    _add_missing_columns(connection, inspector, "users", {
        "quiet_hours_enabled": "BOOLEAN NOT NULL DEFAULT false",
        "quiet_hours_start": "VARCHAR(5)",
        "quiet_hours_end": "VARCHAR(5)",
    })


def _ensure_member_activation_columns(connection, inspector) -> None:
    # The member_activations table itself is created by Base.metadata.create_all.
    _add_missing_columns(connection, inspector, "users", {
        "whatsapp_phone": "VARCHAR(20)",
        "welcome_pending": "BOOLEAN NOT NULL DEFAULT false",
    })


def _ensure_payment_reminder_columns(connection, inspector) -> None:
    # The payment_reminder_logs table itself is created by Base.metadata.create_all.
    _add_missing_columns(connection, inspector, "users", {
        "payment_reminder_enabled": "BOOLEAN",
        "payment_reminder_day": "INTEGER",
        "onboarding_completed_at": "TIMESTAMP",
    })
    _add_missing_columns(connection, inspector, "users", {
        "app_version": "VARCHAR(40)",
        "app_version_seen_at": "TIMESTAMP",
    })


def ensure_runtime_schema() -> None:
    """Apply additive schema updates for existing deployments."""
    with engine.begin() as connection:
        inspector = inspect(connection)

        if inspector.has_table("users"):
            user_columns = {column["name"] for column in inspector.get_columns("users")}
            if "last_seen_at" not in user_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN last_seen_at TIMESTAMP"))
            if "notification_permission" not in user_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN notification_permission VARCHAR(20)"))
            if "notification_permission_updated_at" not in user_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN notification_permission_updated_at TIMESTAMP"))
            if "device_display_mode" not in user_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN device_display_mode VARCHAR(30)"))
            if "last_activity_user_agent" not in user_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN last_activity_user_agent VARCHAR(500)"))

        if inspector.has_table("members"):
            member_columns = {column["name"]: column for column in inspector.get_columns("members")}
            if "notes" not in member_columns:
                connection.execute(text("ALTER TABLE members ADD COLUMN notes TEXT"))

        if inspector.has_table("notifications"):
            notification_columns = {column["name"] for column in inspector.get_columns("notifications")}
            if "type" not in notification_columns:
                connection.execute(text("ALTER TABLE notifications ADD COLUMN type VARCHAR(20) DEFAULT 'info'"))
                connection.execute(text("UPDATE notifications SET type = 'info' WHERE type IS NULL"))

        _ensure_separation_of_duties_columns(connection, inspector)
        _ensure_admin_recorded_payment_columns(connection, inspector)
        _ensure_notification_ux_columns(connection, inspector)
        _ensure_member_activation_columns(connection, inspector)
        _ensure_payment_reminder_columns(connection, inspector)

        if not inspector.has_table("campaigns"):
            return

        columns = {column["name"]: column for column in inspector.get_columns("campaigns")}
        dialect = connection.dialect.name

        if "target_mode" not in columns:
            connection.execute(text("ALTER TABLE campaigns ADD COLUMN target_mode VARCHAR(20) DEFAULT 'targeted'"))
        if "min_amount" not in columns:
            connection.execute(text("ALTER TABLE campaigns ADD COLUMN min_amount DOUBLE PRECISION DEFAULT 100.0"))
        if "end_date_mode" not in columns:
            connection.execute(text("ALTER TABLE campaigns ADD COLUMN end_date_mode VARCHAR(20) DEFAULT 'fixed'"))

        connection.execute(text("UPDATE campaigns SET target_mode = COALESCE(target_mode, 'targeted')"))
        connection.execute(text("UPDATE campaigns SET min_amount = COALESCE(min_amount, 100.0)"))
        connection.execute(text("UPDATE campaigns SET end_date_mode = COALESCE(end_date_mode, 'fixed')"))

        if dialect == "postgresql":
            connection.execute(text("ALTER TABLE campaigns ALTER COLUMN target_amount DROP NOT NULL"))
            connection.execute(text("ALTER TABLE campaigns ALTER COLUMN end_date DROP NOT NULL"))
            connection.execute(text("ALTER TABLE campaigns ALTER COLUMN target_mode SET NOT NULL"))
            connection.execute(text("ALTER TABLE campaigns ALTER COLUMN min_amount SET NOT NULL"))
            connection.execute(text("ALTER TABLE campaigns ALTER COLUMN end_date_mode SET NOT NULL"))
        else:
            logger.warning(
                "Campaign runtime migration added mode columns but did not relax NOT NULL constraints for non-PostgreSQL dialect '%s'",
                dialect,
            )

        # ── app_settings table ────────────────────────────────────────────
        if not inspector.has_table("app_settings"):
            if dialect == "postgresql":
                connection.execute(text("""
                    CREATE TABLE app_settings (
                        id SERIAL PRIMARY KEY,
                        key VARCHAR(100) NOT NULL UNIQUE,
                        value TEXT NOT NULL DEFAULT '',
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                """))
            else:
                connection.execute(text("""
                    CREATE TABLE app_settings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        key VARCHAR(100) NOT NULL UNIQUE,
                        value TEXT NOT NULL DEFAULT '',
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
            connection.execute(text("CREATE INDEX ix_app_settings_key ON app_settings (key)"))
            logger.info("Created app_settings table")

        setting_columns = {c["name"] for c in inspect(connection).get_columns("app_settings")}
        if "updated_by_user_id" not in setting_columns:
            connection.execute(text("ALTER TABLE app_settings ADD COLUMN updated_by_user_id INTEGER REFERENCES users(id)"))

        # ── push_subscriptions table ─────────────────────────────────────
        if not inspector.has_table("push_subscriptions"):
            if dialect == "postgresql":
                connection.execute(text("""
                    CREATE TABLE push_subscriptions (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id),
                        endpoint TEXT NOT NULL UNIQUE,
                        p256dh VARCHAR(255) NOT NULL,
                        auth VARCHAR(255) NOT NULL,
                        user_agent VARCHAR(500),
                        is_active BOOLEAN NOT NULL DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                """))
            else:
                connection.execute(text("""
                    CREATE TABLE push_subscriptions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        endpoint TEXT NOT NULL UNIQUE,
                        p256dh VARCHAR(255) NOT NULL,
                        auth VARCHAR(255) NOT NULL,
                        user_agent VARCHAR(500),
                        is_active BOOLEAN NOT NULL DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(user_id) REFERENCES users(id)
                    )
                """))

            connection.execute(text("CREATE INDEX ix_push_subscriptions_user_id ON push_subscriptions (user_id)"))
            logger.info("Created push_subscriptions table")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
