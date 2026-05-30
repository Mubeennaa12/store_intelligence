import pytest
import asyncio
import os
import sys

# Ensure 'app' directory is in PYTHONPATH so imports inside tests work
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app')))

# Ensure the database URL is set for tests if not already present in environment
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:apex@localhost:5432/store_intelligence"

from db.database import engine, Base

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Dispose engine immediately to clean up connections bound to the temp import loop
    await engine.dispose()

# Initialize database tables once
try:
    asyncio.run(init_db())
except Exception as e:
    print(f"Error initializing database: {e}", file=sys.stderr)

@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop to share across all async tests."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(autouse=True)
async def dispose_engine():
    """Dispose of the SQLAlchemy engine pool after each test to prevent event loop issues."""
    yield
    await engine.dispose()
