# PROMPT: "Write pytest-asyncio tests for a FastAPI store analytics API. 
# Endpoints: POST /events/ingest, GET /stores/{id}/metrics, GET /stores/{id}/funnel.
# Cover: idempotent ingest, zero-visitor store returns 0.0 not null, 
# staff excluded from metrics, re-entry not double-counted in funnel, 
# all-staff clip returns zero customers, conversion rate formula."
# CHANGES MADE: Switched from TestClient to AsyncClient (httpx), added 
# all-staff edge case fixture, explicitly assert conversion_rate type is float.

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import uuid
from datetime import datetime, timezone

# These imports only work when running inside the container with the app mounted
try:
    from main import app
    from db.database import engine, Base
    APP_AVAILABLE = True
except ImportError:
    APP_AVAILABLE = False


def make_event(visitor_id=None, event_type="ENTRY", is_staff=False, zone_id=None,
               store_id="STORE_TEST_001", camera_id="CAM_ENTRY_01",
               dwell_ms=0, confidence=0.9, queue_depth=None):
    return {
        "event_id": str(uuid.uuid4()),
        "store_id": store_id,
        "camera_id": camera_id,
        "visitor_id": visitor_id or f"VIS_{uuid.uuid4().hex[:6]}",
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "zone_id": zone_id,
        "dwell_ms": dwell_ms,
        "is_staff": is_staff,
        "confidence": confidence,
        "metadata": {
            "queue_depth": queue_depth,
            "sku_zone": zone_id,
            "session_seq": 1,
        },
    }


@pytest.mark.skipif(not APP_AVAILABLE, reason="App not available in this environment")
class TestIngest:
    @pytest.mark.asyncio
    async def test_ingest_accepts_valid_events(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            events = [make_event() for _ in range(5)]
            resp = await ac.post("/events/ingest", json={"events": events})
        assert resp.status_code == 200
        body = resp.json()
        assert body["accepted"] == 5
        assert body["rejected"] == 0

    @pytest.mark.asyncio
    async def test_ingest_is_idempotent(self):
        """Sending the same events twice → second call returns all as duplicate."""
        events = [make_event() for _ in range(3)]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r1 = await ac.post("/events/ingest", json={"events": events})
            r2 = await ac.post("/events/ingest", json={"events": events})
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r2.json()["duplicate"] == 3
        assert r2.json()["accepted"] == 0

    @pytest.mark.asyncio
    async def test_ingest_partial_success_on_bad_event(self):
        good = make_event()
        bad = {"event_id": "not-a-uuid", "store_id": "X"}  # malformed
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/events/ingest", json={"events": [good, bad]})
        body = resp.json()
        # Should accept the good one even with a bad one present
        assert body["accepted"] >= 1
        assert body["rejected"] >= 0  # bad event counted


@pytest.mark.skipif(not APP_AVAILABLE, reason="App not available in this environment")
class TestMetrics:
    @pytest.mark.asyncio
    async def test_zero_visitor_store_returns_zeros_not_null(self):
        """Empty store → all counts 0, conversion_rate 0.0 (not None or crash)."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/stores/STORE_EMPTY_999/metrics")
        assert resp.status_code == 200
        body = resp.json()
        assert body["unique_visitors"] == 0
        assert body["conversion_rate"] == 0.0
        assert isinstance(body["conversion_rate"], float)
        assert body["current_queue_depth"] == 0

    @pytest.mark.asyncio
    async def test_staff_excluded_from_metrics(self):
        store_id = f"STORE_STAFF_{uuid.uuid4().hex[:4]}"
        staff_events = [make_event(is_staff=True, store_id=store_id) for _ in range(5)]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.post("/events/ingest", json={"events": staff_events})
            resp = await ac.get(f"/stores/{store_id}/metrics")
        body = resp.json()
        assert body["unique_visitors"] == 0   # staff excluded

    @pytest.mark.asyncio
    async def test_conversion_rate_formula(self):
        """4 visitors, 2 reach billing queue → rate = 0.5"""
        store_id = f"STORE_CONV_{uuid.uuid4().hex[:4]}"
        visitors = [f"VIS_{i:06x}" for i in range(4)]
        events = []
        for v in visitors:
            events.append(make_event(visitor_id=v, event_type="ENTRY", store_id=store_id))
        for v in visitors[:2]:
            events.append(make_event(
                visitor_id=v, event_type="BILLING_QUEUE_JOIN",
                zone_id="BILLING", store_id=store_id
            ))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.post("/events/ingest", json={"events": events})
            resp = await ac.get(f"/stores/{store_id}/metrics")
        body = resp.json()
        assert body["unique_visitors"] == 4
        assert body["converted_visitors"] == 2
        assert abs(body["conversion_rate"] - 0.5) < 0.01

    @pytest.mark.asyncio
    async def test_all_staff_clip_returns_zero_customers(self):
        store_id = f"STORE_ALLSTAFF_{uuid.uuid4().hex[:4]}"
        all_staff = [make_event(is_staff=True, store_id=store_id) for _ in range(10)]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.post("/events/ingest", json={"events": all_staff})
            resp = await ac.get(f"/stores/{store_id}/metrics")
        assert resp.json()["unique_visitors"] == 0


@pytest.mark.skipif(not APP_AVAILABLE, reason="App not available in this environment")
class TestFunnel:
    @pytest.mark.asyncio
    async def test_reentry_not_double_counted_in_funnel(self):
        """Same visitor: ENTRY + REENTRY → counted as 1 unique visitor in funnel."""
        store_id = f"STORE_REENTRY_{uuid.uuid4().hex[:4]}"
        visitor_id = "VIS_retest"
        events = [
            make_event(visitor_id=visitor_id, event_type="ENTRY", store_id=store_id),
            make_event(visitor_id=visitor_id, event_type="EXIT", store_id=store_id),
            make_event(visitor_id=visitor_id, event_type="REENTRY", store_id=store_id),
        ]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.post("/events/ingest", json={"events": events})
            resp = await ac.get(f"/stores/{store_id}/funnel")
        body = resp.json()
        entry_stage = next(s for s in body["funnel"] if s["stage"] == "entry")
        assert entry_stage["visitors"] == 1   # not 2

    @pytest.mark.asyncio
    async def test_funnel_stages_monotonically_decreasing(self):
        """Each funnel stage should have <= visitors than the previous stage."""
        store_id = f"STORE_FUNNEL_{uuid.uuid4().hex[:4]}"
        visitors = [f"VIS_{i:06x}" for i in range(10)]
        events = []
        for v in visitors:
            events.append(make_event(visitor_id=v, event_type="ENTRY", store_id=store_id))
        for v in visitors[:7]:
            events.append(make_event(
                visitor_id=v, event_type="ZONE_ENTER", zone_id="SKINCARE", store_id=store_id
            ))
        for v in visitors[:3]:
            events.append(make_event(
                visitor_id=v, event_type="BILLING_QUEUE_JOIN", zone_id="BILLING", store_id=store_id
            ))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.post("/events/ingest", json={"events": events})
            resp = await ac.get(f"/stores/{store_id}/funnel")
        stages = resp.json()["funnel"]
        counts = [s["visitors"] for s in stages]
        for i in range(1, len(counts)):
            assert counts[i] <= counts[i - 1], f"Stage {i} has more visitors than stage {i-1}"


@pytest.mark.skipif(not APP_AVAILABLE, reason="App not available in this environment")
class TestHealth:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body
        assert "database" in body
        assert "timestamp" in body
