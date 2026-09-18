"""Database migration script for Aetherfall Stage B.

Adds chapter progression tracking columns to game_sessions:
- chapter_number (INTEGER DEFAULT 1 NOT NULL)
- completed_chapters (JSON/TEXT DEFAULT '[]')

Explicitly initializes existing sessions with chapter_number = 1 and completed_chapters = '[]'
so advancement lookup on the first turn is guaranteed to succeed.

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
    """Check existing columns on game_sessions and add missing chapter progression columns."""
    print(f"Checking Stage B chapter migration on: {engine.url}")
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

        json_type = "JSONB" if dialect == "postgresql" else "JSON"

        columns_to_add = [
            ("chapter_number", "INTEGER DEFAULT 1"),
            ("completed_chapters", f"{json_type} DEFAULT '[]'"),
        ]

        added_count = 0
        for col_name, col_def in columns_to_add:
            if col_name not in cols:
                print(f"  [+] Adding column '{col_name}' ({col_def})...")
                await conn.execute(text(f"ALTER TABLE game_sessions ADD COLUMN {col_name} {col_def}"))
                added_count += 1
            else:
                print(f"  [=] Column '{col_name}' already exists.")

        # Explicitly backfill null values for existing sessions
        print("  [*] Ensuring existing sessions have chapter_number = 1, completed_chapters initialized, and chapter display synced...")
        await conn.execute(text("UPDATE game_sessions SET chapter_number = 1 WHERE chapter_number IS NULL"))
        await conn.execute(text("UPDATE game_sessions SET completed_chapters = '[]' WHERE completed_chapters IS NULL"))
        await conn.execute(text("UPDATE game_sessions SET chapter = 'Chapter 1: The Drowned Road' WHERE chapter IS NULL"))

        print(f"Migration completed. {added_count} column(s) added, existing rows backfilled.")


if __name__ == "__main__":
    asyncio.run(run_migration())
