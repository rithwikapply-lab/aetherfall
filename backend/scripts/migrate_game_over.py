"""Database migration script for Aetherfall.

Adds game-over state and resource limit columns to game_sessions:
- max_hp (INTEGER DEFAULT 100)
- max_focus (INTEGER DEFAULT 50)
- turn_count (INTEGER DEFAULT 0)
- is_game_over (BOOLEAN DEFAULT FALSE/0)
- game_over_reason (VARCHAR(50) NULL)
- game_over_summary (TEXT NULL)

Compatible with both SQLite and PostgreSQL.
"""

import asyncio
import sys
from pathlib import Path

# Ensure backend directory is in sys.path when running script directly
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from sqlalchemy import inspect, text
from app.database import engine


async def run_migration() -> None:
    """Check existing columns on game_sessions and add missing game-over columns."""
    print(f"Checking schema migration on: {engine.url}")
    async with engine.begin() as conn:
        dialect = conn.dialect.name

        def get_existing_columns(sync_conn):
            insp = inspect(sync_conn)
            if not insp.has_table("game_sessions"):
                return []
            return [col["name"] for col in insp.get_columns("game_sessions")]

        cols = await conn.run_sync(get_existing_columns)
        if not cols:
            print("Table 'game_sessions' does not exist yet; create_all will build it.")
            return

        bool_default = "FALSE" if dialect == "postgresql" else "0"

        columns_to_add = [
            ("max_hp", "INTEGER DEFAULT 100"),
            ("max_focus", "INTEGER DEFAULT 50"),
            ("turn_count", "INTEGER DEFAULT 0"),
            ("is_game_over", f"BOOLEAN DEFAULT {bool_default}"),
            ("game_over_reason", "VARCHAR(50)"),
            ("game_over_summary", "TEXT"),
        ]

        added_count = 0
        for col_name, col_def in columns_to_add:
            if col_name not in cols:
                print(f"  [+] Adding column '{col_name}' ({col_def})...")
                await conn.execute(text(f"ALTER TABLE game_sessions ADD COLUMN {col_name} {col_def}"))
                added_count += 1
            else:
                print(f"  [=] Column '{col_name}' already exists.")

        print(f"Migration completed. {added_count} column(s) added.")


if __name__ == "__main__":
    asyncio.run(run_migration())
