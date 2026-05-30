"""
GET /stores/{store_id}/anomalies
Active anomalies: queue spike, conversion drop, dead zone.
Severity: INFO / WARN / CRITICAL.
"""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, distinct

from db.database import get_db, EventRow

router = APIRouter()

QUEUE_SPIKE_THRESHOLD = 5       # queue depth considered a spike
DEAD_ZONE_MINUTES = 30          # no zone visits = dead zone
CONVERSION_DROP_THRESHOLD = 0.3 # 30% drop vs 7-day avg = anomaly


def _now():
    return datetime.now(timezone.utc)


@router.get("/{store_id}/anomalies")
async def get_anomalies(store_id: str, db: AsyncSession = Depends(get_db)):
    now = _now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    base_today = and_(
        EventRow.store_id == store_id,
        EventRow.timestamp >= today_start,
        EventRow.is_staff == False,
    )

    anomalies = []

    # -----------------------------------------------------------------------
    # 1. BILLING_QUEUE_SPIKE — latest queue_depth > threshold
    # -----------------------------------------------------------------------
    queue_q = await db.execute(
        select(EventRow.queue_depth, EventRow.timestamp)
        .where(base_today, EventRow.event_type == "BILLING_QUEUE_JOIN", EventRow.queue_depth != None)
        .order_by(EventRow.timestamp.desc())
        .limit(1)
    )
    queue_row = queue_q.fetchone()
    if queue_row and queue_row[0] >= QUEUE_SPIKE_THRESHOLD:
        anomalies.append({
            "type": "BILLING_QUEUE_SPIKE",
            "severity": "CRITICAL" if queue_row[0] >= 8 else "WARN",
            "detail": f"Queue depth is {queue_row[0]} at {queue_row[1].isoformat()}",
            "suggested_action": "Open an additional billing counter immediately.",
            "detected_at": now.isoformat(),
        })

    # -----------------------------------------------------------------------
    # 2. CONVERSION_DROP — today vs 7-day rolling average
    # -----------------------------------------------------------------------
    def _conversion(start, end):
        return and_(EventRow.store_id == store_id, EventRow.timestamp >= start,
                    EventRow.timestamp <= end, EventRow.is_staff == False)

    today_entry_q = await db.execute(
        select(func.count(distinct(EventRow.visitor_id))).where(
            _conversion(today_start, now), EventRow.event_type == "ENTRY"
        )
    )
    today_billing_q = await db.execute(
        select(func.count(distinct(EventRow.visitor_id))).where(
            _conversion(today_start, now), EventRow.event_type == "BILLING_QUEUE_JOIN"
        )
    )
    hist_entry_q = await db.execute(
        select(func.count(distinct(EventRow.visitor_id))).where(
            _conversion(week_ago, today_start), EventRow.event_type == "ENTRY"
        )
    )
    hist_billing_q = await db.execute(
        select(func.count(distinct(EventRow.visitor_id))).where(
            _conversion(week_ago, today_start), EventRow.event_type == "BILLING_QUEUE_JOIN"
        )
    )

    t_entry = today_entry_q.scalar() or 0
    t_billing = today_billing_q.scalar() or 0
    h_entry = hist_entry_q.scalar() or 0
    h_billing = hist_billing_q.scalar() or 0

    today_conv = t_billing / t_entry if t_entry else None
    hist_conv = h_billing / h_entry if h_entry else None

    if today_conv is not None and hist_conv is not None and hist_conv > 0:
        drop = (hist_conv - today_conv) / hist_conv
        if drop >= CONVERSION_DROP_THRESHOLD:
            anomalies.append({
                "type": "CONVERSION_DROP",
                "severity": "CRITICAL" if drop >= 0.5 else "WARN",
                "detail": f"Conversion {today_conv:.1%} vs 7-day avg {hist_conv:.1%} ({drop:.0%} drop)",
                "suggested_action": "Review promotions and staff positioning on floor.",
                "detected_at": now.isoformat(),
            })

    # -----------------------------------------------------------------------
    # 3. DEAD_ZONE — zone with no visits in last 30 min
    # -----------------------------------------------------------------------
    cutoff = now - timedelta(minutes=DEAD_ZONE_MINUTES)
    recent_zones_q = await db.execute(
        select(distinct(EventRow.zone_id)).where(
            base_today, EventRow.event_type == "ZONE_ENTER",
            EventRow.timestamp >= cutoff, EventRow.zone_id != None,
        )
    )
    active_zones = set(r[0] for r in recent_zones_q.fetchall())

    all_zones_q = await db.execute(
        select(distinct(EventRow.zone_id)).where(
            base_today, EventRow.event_type == "ZONE_ENTER", EventRow.zone_id != None
        )
    )
    all_zones = set(r[0] for r in all_zones_q.fetchall())
    dead_zones = all_zones - active_zones

    for zone in dead_zones:
        anomalies.append({
            "type": "DEAD_ZONE",
            "severity": "INFO",
            "detail": f"Zone '{zone}' has had no visitor traffic in the last {DEAD_ZONE_MINUTES} minutes.",
            "suggested_action": f"Check display or signage in zone {zone}. Consider repositioning staff.",
            "detected_at": now.isoformat(),
        })

    return {
        "store_id": store_id,
        "evaluated_at": now.isoformat(),
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
    }
