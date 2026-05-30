"""
GET /health
Service status, last event timestamp per store, STALE_FEED warning if >10 min lag.
"""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from sqlalchemy.exc import OperationalError

from db.database import get_db, EventRow

router = APIRouter()

STALE_FEED_MINUTES = 10


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    db_ok = False
    store_feeds = []

    try:
        await db.execute(text("SELECT 1"))
        db_ok = True

        # Last event per store
        rows = await db.execute(
            select(EventRow.store_id, func.max(EventRow.timestamp).label("last_event"))
            .group_by(EventRow.store_id)
        )
        for row in rows.fetchall():
            lag = now - row.last_event.replace(tzinfo=timezone.utc)
            stale = lag > timedelta(minutes=STALE_FEED_MINUTES)
            store_feeds.append({
                "store_id": row.store_id,
                "last_event": row.last_event.isoformat(),
                "lag_seconds": round(lag.total_seconds()),
                "status": "STALE_FEED" if stale else "OK",
            })

    except OperationalError:
        return {
            "status": "DEGRADED",
            "database": "UNAVAILABLE",
            "timestamp": now.isoformat(),
            "stores": [],
        }, 503

    return {
        "status": "OK" if db_ok else "DEGRADED",
        "database": "OK" if db_ok else "UNAVAILABLE",
        "timestamp": now.isoformat(),
        "stores": store_feeds,
    }
