"""
Pydantic models mirroring the required event schema from the problem statement.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class EventType(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    ZONE_ENTER = "ZONE_ENTER"
    ZONE_EXIT = "ZONE_EXIT"
    ZONE_DWELL = "ZONE_DWELL"
    BILLING_QUEUE_JOIN = "BILLING_QUEUE_JOIN"
    BILLING_QUEUE_ABANDON = "BILLING_QUEUE_ABANDON"
    REENTRY = "REENTRY"


class EventMetadata(BaseModel):
    queue_depth: Optional[int] = None
    sku_zone: Optional[str] = None
    session_seq: Optional[int] = None


class StoreEvent(BaseModel):
    event_id: UUID
    store_id: str = Field(..., example="STORE_BLR_002")
    camera_id: str = Field(..., example="CAM_ENTRY_01")
    visitor_id: str = Field(..., example="VIS_c8a2f1")
    event_type: EventType
    timestamp: datetime
    zone_id: Optional[str] = None
    dwell_ms: int = Field(default=0, ge=0)
    is_staff: bool = False
    confidence: float = Field(..., ge=0.0, le=1.0)
    metadata: EventMetadata = Field(default_factory=EventMetadata)

    @field_validator("zone_id")
    @classmethod
    def zone_required_for_zone_events(cls, v, info):
        # zone_id must be present for zone-related events
        event_type = info.data.get("event_type")
        if event_type in (
            EventType.ZONE_ENTER,
            EventType.ZONE_EXIT,
            EventType.ZONE_DWELL,
            EventType.BILLING_QUEUE_JOIN,
            EventType.BILLING_QUEUE_ABANDON,
        ) and v is None:
            raise ValueError(f"zone_id required for event_type={event_type}")
        return v


class IngestRequest(BaseModel):
    events: list[StoreEvent] = Field(..., max_length=500)


class IngestResponse(BaseModel):
    accepted: int
    rejected: int
    duplicate: int
    errors: list[dict] = []
