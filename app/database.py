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


def ensure_runtime_schema() -> None:
    """Apply additive schema updates for existing deployments."""
    with engine.begin() as connection:
        inspector = inspect(connection)

        if inspector.has_table("members"):
            member_columns = {column["name"]: column for column in inspector.get_columns("members")}
            if "notes" not in member_columns:
                connection.execute(text("ALTER TABLE members ADD COLUMN notes TEXT"))

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

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
