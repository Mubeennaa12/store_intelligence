"""
GET /stores/{store_id}/funnel
Conversion funnel: Entry → Zone Visit → Billing Queue → Purchase
Session is the unit; re-entries must not double-count a visitor.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, distinct, func, and_

from db.database import get_db, EventRow

router = APIRouter()


def _today_window():
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, now


@router.get("/{store_id}/funnel")
async def get_funnel(store_id: str, db: AsyncSession = Depends(get_db)):
    start, end = _today_window()
    base = and_(
        EventRow.store_id == store_id,
        EventRow.timestamp >= start,
        EventRow.timestamp <= end,
        EventRow.is_staff == False,
    )

    # Stage 1: unique visitors who entered (ENTRY only, not REENTRY — deduplicated)
    entered_q = await db.execute(
        select(distinct(EventRow.visitor_id)).where(base, EventRow.event_type == "ENTRY")
    )
    entered_visitors = set(r[0] for r in entered_q.fetchall())
    entered_count = len(entered_visitors)

    # Stage 2: unique visitors who visited at least one zone
    zone_q = await db.execute(
        select(distinct(EventRow.visitor_id)).where(base, EventRow.event_type == "ZONE_ENTER")
    )
    zone_visitors_raw = set(r[0] for r in zone_q.fetchall())
    linked_zone = zone_visitors_raw & entered_visitors
    if len(linked_zone) > 0 or entered_count == 0:
        zone_count = len(linked_zone)
    else:
        zone_count = min(len(zone_visitors_raw), entered_count)

    # Stage 3: unique visitors who reached billing queue
    billing_q = await db.execute(
        select(distinct(EventRow.visitor_id)).where(
            base, EventRow.event_type == "BILLING_QUEUE_JOIN"
        )
    )
    billing_visitors_raw = set(r[0] for r in billing_q.fetchall())
    linked_billing = billing_visitors_raw & entered_visitors
    if len(linked_billing) > 0 or zone_count == 0:
        billing_count = len(linked_billing)
    else:
        billing_count = min(len(billing_visitors_raw), zone_count)

    # Stage 4: unique visitors who did NOT abandon (proxy for purchase)
    abandon_q = await db.execute(
        select(distinct(EventRow.visitor_id)).where(
            base, EventRow.event_type == "BILLING_QUEUE_ABANDON"
        )
    )
    abandoned_visitors_raw = set(r[0] for r in abandon_q.fetchall())
    if len(linked_billing) > 0:
        purchased_visitors = linked_billing - abandoned_visitors_raw
        purchased_count = len(purchased_visitors)
    else:
        purchased_count = max(0, billing_count - len(abandoned_visitors_raw))

    def drop_off(from_count, to_count):
        if from_count == 0:
            return 0.0
        return round((from_count - to_count) / from_count * 100, 1)

    return {
        "store_id": store_id,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "funnel": [
            {
                "stage": "entry",
                "label": "Store Entry",
                "visitors": entered_count,
                "drop_off_pct": 0.0,
            },
            {
                "stage": "zone_visit",
                "label": "Zone Visit",
                "visitors": zone_count,
                "drop_off_pct": drop_off(entered_count, zone_count),
            },
            {
                "stage": "billing_queue",
                "label": "Billing Queue",
                "visitors": billing_count,
                "drop_off_pct": drop_off(zone_count, billing_count),
            },
            {
                "stage": "purchase",
                "label": "Purchase",
                "visitors": purchased_count,
                "drop_off_pct": drop_off(billing_count, purchased_count),
            },
        ],
        "overall_conversion_pct": round(purchased_count / entered_count * 100, 1)
        if entered_count
        else 0.0,
    }
