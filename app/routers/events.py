"""
POST /events/ingest
Idempotent by event_id. Partial success on malformed events.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import select
import structlog

from db.database import get_db, EventRow
from models import IngestRequest, IngestResponse, StoreEvent

router = APIRouter()
logger = structlog.get_logger()


@router.post("/ingest", response_model=IngestResponse)
async def ingest_events(payload: IngestRequest, db: AsyncSession = Depends(get_db)):
    accepted = 0
    rejected = 0
    duplicate = 0
    errors = []

    for raw_evt in payload.events:
        try:
            evt = StoreEvent(**raw_evt)
        except Exception as e:
            rejected += 1
            errors.append({"event_id": str(raw_evt.get("event_id", "unknown")), "error": str(e)})
            logger.warning("event_rejected", event_id=str(raw_evt.get("event_id", "unknown")), error=str(e))
            continue

        try:
            # Upsert — do nothing on conflict (idempotent)
            stmt = (
                pg_insert(EventRow)
                .values(
                    event_id=evt.event_id,
                    store_id=evt.store_id,
                    camera_id=evt.camera_id,
                    visitor_id=evt.visitor_id,
                    event_type=evt.event_type.value,
                    timestamp=evt.timestamp,
                    zone_id=evt.zone_id,
                    dwell_ms=evt.dwell_ms,
                    is_staff=evt.is_staff,
                    confidence=evt.confidence,
                    queue_depth=evt.metadata.queue_depth,
                    sku_zone=evt.metadata.sku_zone,
                    session_seq=evt.metadata.session_seq,
                )
                .on_conflict_do_nothing(index_elements=["event_id"])
            )
            result = await db.execute(stmt)
            if result.rowcount == 0:
                duplicate += 1
            else:
                accepted += 1
        except Exception as e:
            rejected += 1
            errors.append({"event_id": str(evt.event_id), "error": str(e)})
            logger.warning("event_rejected", event_id=str(evt.event_id), error=str(e))

    await db.commit()

    logger.info(
        "ingest_complete",
        accepted=accepted,
        rejected=rejected,
        duplicate=duplicate,
    )
    return IngestResponse(
        accepted=accepted, rejected=rejected, duplicate=duplicate, errors=errors
    )
