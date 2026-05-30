"""
GET /stores/{store_id}/metrics
Real-time: unique visitors, conversion rate, avg dwell per zone,
queue depth, abandonment rate. Excludes staff.
"""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, distinct

from db.database import get_db, EventRow

router = APIRouter()


def _today_window():
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, now


@router.get("/{store_id}/metrics")
async def get_metrics(store_id: str, db: AsyncSession = Depends(get_db)):
    start, end = _today_window()
    base = and_(
        EventRow.store_id == store_id,
        EventRow.timestamp >= start,
        EventRow.timestamp <= end,
        EventRow.is_staff == False,
    )

    # --- Unique visitors (ENTRY events, no re-entry double count) ---
    unique_visitors_q = await db.execute(
        select(func.count(distinct(EventRow.visitor_id))).where(
            base, EventRow.event_type == "ENTRY"
        )
    )
    unique_visitors = unique_visitors_q.scalar() or 0

    # --- Conversion: visitors with BILLING_QUEUE_JOIN ---
    converted_q = await db.execute(
        select(func.count(distinct(EventRow.visitor_id))).where(
            base, EventRow.event_type == "BILLING_QUEUE_JOIN"
        )
    )
    converted = converted_q.scalar() or 0
    conversion_rate = round(converted / unique_visitors, 4) if unique_visitors else 0.0

    # --- Avg dwell per zone ---
    dwell_q = await db.execute(
        select(EventRow.zone_id, func.avg(EventRow.dwell_ms).label("avg_dwell"))
        .where(base, EventRow.event_type == "ZONE_DWELL", EventRow.zone_id != None)
        .group_by(EventRow.zone_id)
    )
    avg_dwell_by_zone = {
        row.zone_id: round(row.avg_dwell / 1000, 1) for row in dwell_q.fetchall()
    }

    # --- Current queue depth (latest BILLING_QUEUE_JOIN event) ---
    queue_q = await db.execute(
        select(EventRow.queue_depth)
        .where(base, EventRow.event_type == "BILLING_QUEUE_JOIN", EventRow.queue_depth != None)
        .order_by(EventRow.timestamp.desc())
        .limit(1)
    )
    queue_row = queue_q.fetchone()
    current_queue_depth = queue_row[0] if queue_row else 0

    # --- Abandonment rate ---
    abandon_q = await db.execute(
        select(func.count(distinct(EventRow.visitor_id))).where(
            base, EventRow.event_type == "BILLING_QUEUE_ABANDON"
        )
    )
    abandoned = abandon_q.scalar() or 0
    abandonment_rate = (
        round(abandoned / (converted + abandoned), 4) if (converted + abandoned) else 0.0
    )

    if unique_visitors == 0:
        return {
            "store_id": store_id,
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "unique_visitors": 0,
            "converted_visitors": 0,
            "conversion_rate": 0.0,
            "avg_dwell_seconds_by_zone": {},
            "current_queue_depth": 0,
            "abandonment_rate": 0.0,
            "data_confidence": "LOW",
        }

    return {
        "store_id": store_id,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "unique_visitors": unique_visitors,
        "converted_visitors": converted,
        "conversion_rate": conversion_rate,
        "avg_dwell_seconds_by_zone": avg_dwell_by_zone,
        "current_queue_depth": current_queue_depth,
        "abandonment_rate": abandonment_rate,
        "data_confidence": "HIGH" if unique_visitors >= 20 else "LOW",
    }
