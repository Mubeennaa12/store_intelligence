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
        db_values = {}
        event_type_raw = raw_evt.get("event_type")
        is_new_format = event_type_raw in (
            "entry",
            "exit",
            "zone_entered",
            "zone_exited",
            "queue_completed",
            "queue_abandoned",
        )

        if is_new_format:
            import uuid
            from datetime import datetime, timezone

            # Map event type
            if event_type_raw == "entry":
                evt_type = "ENTRY"
            elif event_type_raw == "exit":
                evt_type = "EXIT"
            elif event_type_raw == "zone_entered":
                evt_type = "ZONE_ENTER"
            elif event_type_raw == "zone_exited":
                evt_type = "ZONE_EXIT"
            elif event_type_raw == "queue_completed":
                evt_type = "BILLING_QUEUE_JOIN"
            elif event_type_raw == "queue_abandoned":
                evt_type = "BILLING_QUEUE_ABANDON"
            else:
                evt_type = event_type_raw.upper()

            # Map visitor_id
            visitor_id = raw_evt.get("id_token") or raw_evt.get("track_id")
            if visitor_id is not None:
                visitor_id = str(visitor_id)
            else:
                visitor_id = "unknown"

            # Map store_id
            store_id = raw_evt.get("store_id") or raw_evt.get("store_code") or "unknown"
            if isinstance(store_id, str):
                if store_id.lower().startswith("store_"):
                    store_id = "ST" + store_id.split("_")[1]

            # Map camera_id
            camera_id = raw_evt.get("camera_id") or "unknown"
            if isinstance(camera_id, str):
                camera_id = camera_id.upper()

            # Map timestamp
            ts_str = (
                raw_evt.get("event_timestamp")
                or raw_evt.get("event_time")
                or raw_evt.get("queue_join_ts")
                or raw_evt.get("queue_exit_ts")
            )
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except ValueError:
                    ts = datetime.now(timezone.utc)
            else:
                ts = datetime.now(timezone.utc)

            # Map event_id
            evt_id_str = raw_evt.get("queue_event_id") or raw_evt.get("event_id")
            if evt_id_str:
                try:
                    evt_id = uuid.UUID(evt_id_str)
                except ValueError:
                    evt_id = uuid.uuid4()
            else:
                evt_id = uuid.uuid4()

            # Map is_staff
            is_staff = bool(raw_evt.get("is_staff", False))

            # Map queue_depth
            queue_depth = raw_evt.get("queue_position_at_join")

            # Map zone_id
            zone_id = raw_evt.get("zone_id")

            # Map dwell_ms (for exit / zone_exited / queue_completed)
            dwell_ms = 0
            if "wait_seconds" in raw_evt and raw_evt["wait_seconds"] is not None:
                dwell_ms = int(raw_evt["wait_seconds"]) * 1000

            db_values = {
                "event_id": evt_id,
                "store_id": store_id,
                "camera_id": camera_id,
                "visitor_id": visitor_id,
                "event_type": evt_type,
                "timestamp": ts,
                "zone_id": zone_id,
                "dwell_ms": dwell_ms,
                "is_staff": is_staff,
                "confidence": 1.0,
                "queue_depth": queue_depth,
                "sku_zone": None,
                "session_seq": None,
            }
        else:
            try:
                evt = StoreEvent(**raw_evt)
                db_values = {
                    "event_id": evt.event_id,
                    "store_id": evt.store_id,
                    "camera_id": evt.camera_id,
                    "visitor_id": evt.visitor_id,
                    "event_type": evt.event_type.value,
                    "timestamp": evt.timestamp,
                    "zone_id": evt.zone_id,
                    "dwell_ms": evt.dwell_ms,
                    "is_staff": evt.is_staff,
                    "confidence": evt.confidence,
                    "queue_depth": evt.metadata.queue_depth,
                    "sku_zone": evt.metadata.sku_zone,
                    "session_seq": evt.metadata.session_seq,
                }
            except Exception as e:
                rejected += 1
                errors.append(
                    {"event_id": str(raw_evt.get("event_id", "unknown")), "error": str(e)}
                )
                logger.warning(
                    "event_rejected",
                    event_id=str(raw_evt.get("event_id", "unknown")),
                    error=str(e),
                )
                continue

        try:
            # Upsert — do nothing on conflict (idempotent)
            stmt = (
                pg_insert(EventRow)
                .values(**db_values)
                .on_conflict_do_nothing(index_elements=["event_id"])
            )
            result = await db.execute(stmt)
            if result.rowcount == 0:
                duplicate += 1
            else:
                accepted += 1
        except Exception as e:
            rejected += 1
            event_id_str = str(db_values.get("event_id", "unknown"))
            errors.append({"event_id": event_id_str, "error": str(e)})
            logger.warning("event_rejected", event_id=event_id_str, error=str(e))

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
