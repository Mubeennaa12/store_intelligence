"""
GET /stores/{store_id}/heatmap
Zone visit frequency + avg dwell, normalised 0-100.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, distinct

from db.database import get_db, EventRow

router = APIRouter()


def _today_window():
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, now


def _normalise(values: list[float]) -> list[float]:
    if not values:
        return values
    mn, mx = min(values), max(values)
    if mx == mn:
        return [50.0] * len(values)
    return [round((v - mn) / (mx - mn) * 100, 1) for v in values]


@router.get("/{store_id}/heatmap")
async def get_heatmap(store_id: str, db: AsyncSession = Depends(get_db)):
    start, end = _today_window()
    base = and_(
        EventRow.store_id == store_id,
        EventRow.timestamp >= start,
        EventRow.timestamp <= end,
        EventRow.is_staff == False,
        EventRow.zone_id != None,
    )

    # Visit counts per zone
    visit_q = await db.execute(
        select(
            EventRow.zone_id,
            func.count(distinct(EventRow.visitor_id)).label("visit_count"),
            func.avg(EventRow.dwell_ms).label("avg_dwell_ms"),
        )
        .where(base, EventRow.event_type.in_(["ZONE_ENTER", "ZONE_DWELL"]))
        .group_by(EventRow.zone_id)
    )
    rows = visit_q.fetchall()

    # Unique sessions for confidence flag
    sessions_q = await db.execute(
        select(func.count(distinct(EventRow.visitor_id))).where(
            base, EventRow.event_type == "ZONE_ENTER"
        )
    )
    total_sessions = sessions_q.scalar() or 0

    zones = [
        {"zone_id": r.zone_id, "visit_count": r.visit_count, "avg_dwell_ms": r.avg_dwell_ms or 0}
        for r in rows
    ]

    visit_counts = [z["visit_count"] for z in zones]
    dwell_vals = [z["avg_dwell_ms"] for z in zones]
    norm_visits = _normalise(visit_counts)
    norm_dwell = _normalise(dwell_vals)

    heatmap_data = [
        {
            "zone_id": z["zone_id"],
            "visit_count": z["visit_count"],
            "avg_dwell_seconds": round(z["avg_dwell_ms"] / 1000, 1),
            "visit_score": norm_visits[i],
            "dwell_score": norm_dwell[i],
            "combined_score": round((norm_visits[i] + norm_dwell[i]) / 2, 1),
        }
        for i, z in enumerate(zones)
    ]

    return {
        "store_id": store_id,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "data_confidence": "HIGH" if total_sessions >= 20 else "LOW",
        "zones": sorted(heatmap_data, key=lambda x: x["combined_score"], reverse=True),
    }
