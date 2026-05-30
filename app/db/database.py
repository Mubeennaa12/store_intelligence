"""
SQLAlchemy async engine + ORM table definitions.
"""
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import (
    Column, String, Boolean, Float, Integer,
    DateTime, Text, Index
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
import uuid

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://apex:apex_secret@localhost:5432/store_intelligence",
)

# asyncpg driver
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

AsyncSessionLocal = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


class EventRow(Base):
    __tablename__ = "events"

    event_id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(String(64), nullable=False, index=True)
    camera_id = Column(String(64), nullable=False)
    visitor_id = Column(String(64), nullable=False, index=True)
    event_type = Column(String(32), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    zone_id = Column(String(64), nullable=True)
    dwell_ms = Column(Integer, default=0)
    is_staff = Column(Boolean, default=False)
    confidence = Column(Float, nullable=False)
    queue_depth = Column(Integer, nullable=True)
    sku_zone = Column(String(64), nullable=True)
    session_seq = Column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_events_store_ts", "store_id", "timestamp"),
        Index("ix_events_visitor", "visitor_id", "store_id"),
    )


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
