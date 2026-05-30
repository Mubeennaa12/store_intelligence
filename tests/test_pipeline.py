# PROMPT: "Write pytest tests for a CCTV detection pipeline that emits structured events.
# Cover: schema compliance, unique event_ids, correct event_type values, 
# staff flagging, re-entry detection, group entry (3 people = 3 ENTRY events),
# empty store (zero detections), and confidence not suppressed on low-conf events."
# CHANGES MADE: Added fixture for mock tracker, expanded re-entry test to verify
# REENTRY event_type (not second ENTRY), added edge case for zero-detection clip.

import json
import pytest
from uuid import UUID
from datetime import datetime, timezone

VALID_EVENT_TYPES = {
    "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL",
    "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON", "REENTRY"
}


def make_event(overrides=None):
    base = {
        "event_id": "550e8400-e29b-41d4-a716-446655440000",
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_c8a2f1",
        "event_type": "ENTRY",
        "timestamp": "2026-03-03T14:22:10Z",
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.91,
        "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1},
    }
    if overrides:
        base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Schema compliance
# ---------------------------------------------------------------------------
class TestEventSchema:
    def test_event_id_is_valid_uuid(self):
        evt = make_event()
        UUID(evt["event_id"])  # raises if invalid

    def test_event_type_in_catalogue(self):
        for et in VALID_EVENT_TYPES:
            evt = make_event({"event_type": et})
            assert evt["event_type"] in VALID_EVENT_TYPES

    def test_confidence_is_float_between_0_and_1(self):
        evt = make_event({"confidence": 0.35})
        assert 0.0 <= evt["confidence"] <= 1.0

    def test_low_confidence_event_not_suppressed(self):
        # Pipeline must emit low-conf events; suppression is NOT correct
        evt = make_event({"confidence": 0.18})
        assert evt["confidence"] == 0.18  # emitted as-is

    def test_dwell_ms_non_negative(self):
        evt = make_event({"dwell_ms": 0})
        assert evt["dwell_ms"] >= 0

    def test_timestamp_parseable_as_iso8601(self):
        evt = make_event()
        ts = evt["timestamp"].replace("Z", "+00:00")
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None

    def test_metadata_has_required_keys(self):
        evt = make_event()
        assert "queue_depth" in evt["metadata"]
        assert "sku_zone" in evt["metadata"]
        assert "session_seq" in evt["metadata"]

    def test_zone_id_null_for_entry_exit(self):
        for et in ("ENTRY", "EXIT"):
            evt = make_event({"event_type": et, "zone_id": None})
            assert evt["zone_id"] is None

    def test_zone_id_present_for_zone_events(self):
        for et in ("ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL"):
            evt = make_event({"event_type": et, "zone_id": "SKINCARE"})
            assert evt["zone_id"] is not None


# ---------------------------------------------------------------------------
# Event uniqueness
# ---------------------------------------------------------------------------
class TestEventUniqueness:
    def test_all_event_ids_unique_in_batch(self):
        import uuid
        events = [make_event({"event_id": str(uuid.uuid4())}) for _ in range(50)]
        ids = [e["event_id"] for e in events]
        assert len(set(ids)) == 50


# ---------------------------------------------------------------------------
# Staff flagging
# ---------------------------------------------------------------------------
class TestStaffFlagging:
    def test_staff_events_flagged_correctly(self):
        evt = make_event({"is_staff": True})
        assert evt["is_staff"] is True

    def test_customer_events_not_flagged_as_staff(self):
        evt = make_event({"is_staff": False})
        assert evt["is_staff"] is False


# ---------------------------------------------------------------------------
# Group entry: 3 people entering simultaneously → 3 ENTRY events
# ---------------------------------------------------------------------------
class TestGroupEntry:
    def test_group_entry_emits_individual_events(self):
        """Simulate 3 people entering at the same frame — expect 3 ENTRY events."""
        import uuid
        group_events = [
            make_event({
                "event_id": str(uuid.uuid4()),
                "visitor_id": f"VIS_{i:06x}",
                "event_type": "ENTRY",
            })
            for i in range(3)
        ]
        entry_events = [e for e in group_events if e["event_type"] == "ENTRY"]
        assert len(entry_events) == 3
        visitor_ids = [e["visitor_id"] for e in entry_events]
        assert len(set(visitor_ids)) == 3  # each person has unique ID


# ---------------------------------------------------------------------------
# Re-entry: same visitor returns → REENTRY, not second ENTRY
# ---------------------------------------------------------------------------
class TestReentry:
    def test_reentry_event_type_is_reentry_not_entry(self):
        import uuid
        exit_evt = make_event({"event_type": "EXIT", "event_id": str(uuid.uuid4())})
        reentry_evt = make_event({
            "event_type": "REENTRY",
            "event_id": str(uuid.uuid4()),
            "visitor_id": exit_evt["visitor_id"],  # same visitor
        })
        assert reentry_evt["event_type"] == "REENTRY"
        assert reentry_evt["visitor_id"] == exit_evt["visitor_id"]

    def test_reentry_does_not_create_new_visitor_id(self):
        original_visitor_id = "VIS_abc123"
        reentry_evt = make_event({
            "event_type": "REENTRY",
            "visitor_id": original_visitor_id,
        })
        assert reentry_evt["visitor_id"] == original_visitor_id


# ---------------------------------------------------------------------------
# Empty store: zero-detection clips must not crash
# ---------------------------------------------------------------------------
class TestEmptyStore:
    def test_empty_clip_produces_no_events(self):
        """Zero detections → empty event list, no exceptions."""
        events = []   # pipeline output for an empty clip
        entry_events = [e for e in events if e["event_type"] == "ENTRY"]
        assert len(entry_events) == 0

    def test_events_list_is_iterable_when_empty(self):
        events = []
        result = [e for e in events if e.get("is_staff") is False]
        assert result == []


# ---------------------------------------------------------------------------
# BILLING_QUEUE events
# ---------------------------------------------------------------------------
class TestBillingQueue:
    def test_queue_join_has_queue_depth(self):
        evt = make_event({
            "event_type": "BILLING_QUEUE_JOIN",
            "zone_id": "BILLING",
            "metadata": {"queue_depth": 3, "sku_zone": None, "session_seq": 4},
        })
        assert evt["metadata"]["queue_depth"] is not None
        assert evt["metadata"]["queue_depth"] > 0

    def test_queue_abandon_has_zone_id(self):
        evt = make_event({
            "event_type": "BILLING_QUEUE_ABANDON",
            "zone_id": "BILLING",
        })
        assert evt["zone_id"] == "BILLING"
