from pathlib import Path

from sqlalchemy import text

from app.database import engine


def main() -> None:
    sql_path = Path(__file__).with_name("db_optimize_indexes.sql")
    sql_script = sql_path.read_text(encoding="utf-8")

    # Use AUTOCOMMIT for DDL/index creation and ANALYZE.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(sql_script))

    print("Database optimization complete: indexes ensured and ANALYZE executed.")


if __name__ == "__main__":
    main()
