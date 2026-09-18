import pytest
from sqlalchemy.ext.asyncio import create_async_engine

import app.database as app_database
from app.database import Base, get_db
from app.main import app as fastapi_app


@pytest.fixture(autouse=True)
async def isolate_database(tmp_path):
    """Provide a fresh, isolated SQLite database in tmp_path for every test.

    Reconfigures the shared async_session_maker in-place so all modules,
    dependencies, and tests bind to the ephemeral per-test SQLite file.
    Ensures zero data leakage between tests, leaves the dev database untouched,
    and cleanly unlinks test database files on teardown so no files accumulate.
    """
    test_db_path = tmp_path / "test_aetherfall.db"
    test_db_url = f"sqlite+aiosqlite:///{test_db_path}"
    test_engine = create_async_engine(
        test_db_url,
        echo=False,
        connect_args={"check_same_thread": False},
    )

    # Initialize tables on isolated test engine
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Reconfigure existing async_session_maker to use test_engine
    orig_bind = app_database.async_session_maker.kw.get("bind")
    orig_engine = app_database.engine
    app_database.async_session_maker.configure(bind=test_engine)
    app_database.engine = test_engine

    # Override FastAPI get_db dependency
    async def override_get_db():
        async with app_database.async_session_maker() as session:
            try:
                yield session
            finally:
                await session.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db

    yield app_database.async_session_maker

    fastapi_app.dependency_overrides.clear()
    if orig_bind:
        app_database.async_session_maker.configure(bind=orig_bind)
    app_database.engine = orig_engine

    await test_engine.dispose()
    if test_db_path.exists():
        test_db_path.unlink()
