from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from app.config import settings


class Base(AsyncAttrs, DeclarativeBase):
    """Base declarative class with AsyncAttrs support for async ORM models."""
    pass


connect_args = {"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args=connect_args,
)

async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Initialize database tables via Base metadata create_all and apply column migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Incremental migration check for game_sessions
        dialect = conn.dialect.name

        def get_existing_columns(sync_conn):
            from sqlalchemy import inspect
            insp = inspect(sync_conn)
            if not insp.has_table("game_sessions"):
                return []
            return [col["name"] for col in insp.get_columns("game_sessions")]

        cols = await conn.run_sync(get_existing_columns)
        if cols:
            from sqlalchemy import text
            bool_default = "FALSE" if dialect == "postgresql" else "0"
            columns_to_add = [
                ("max_hp", "INTEGER DEFAULT 100"),
                ("max_focus", "INTEGER DEFAULT 50"),
                ("turn_count", "INTEGER DEFAULT 0"),
                ("is_game_over", f"BOOLEAN DEFAULT {bool_default}"),
                ("game_over_reason", "VARCHAR(50)"),
                ("game_over_summary", "TEXT"),
            ]
            for col_name, col_def in columns_to_add:
                if col_name not in cols:
                    await conn.execute(text(f"ALTER TABLE game_sessions ADD COLUMN {col_name} {col_def}"))

        # Incremental migration check for story_nodes
        def get_story_node_columns(sync_conn):
            from sqlalchemy import inspect
            insp = inspect(sync_conn)
            if not insp.has_table("story_nodes"):
                return []
            return [col["name"] for col in insp.get_columns("story_nodes")]

        story_cols = await conn.run_sync(get_story_node_columns)
        if story_cols:
            story_columns_to_add = [
                ("locations_mentioned", "JSON DEFAULT '[]'"),
            ]
            for col_name, col_def in story_columns_to_add:
                if col_name not in story_cols:
                    await conn.execute(text(f"ALTER TABLE story_nodes ADD COLUMN {col_name} {col_def}"))


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async database session."""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
