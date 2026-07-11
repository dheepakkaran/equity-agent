"""Quick connectivity test for Neon Postgres.

Run once from project root:
    python scripts/test_db_connection.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402


def main() -> None:
    print("Testing Neon Postgres connection...")
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version();")).scalar()
        db_name = conn.execute(text("SELECT current_database();")).scalar()

    print("Connected successfully")
    print(f"   Database: {db_name}")
    print(f"   Version:  {version}")


if __name__ == "__main__":
    main()
