import json
import logging
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(title="Store Intelligence — Local Mock API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Load generated events from local pipeline run to populate real-time metrics
# ---------------------------------------------------------------------------
EVENTS_FILE = "../pipeline/test_billing_events.jsonl"

def get_session_stats():
    unique_visitors = set()
    queue_joins = 0
    max_queue_depth = 0
    reentries = 0
    
    try:
        with open(EVENTS_FILE, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                evt = json.loads(line)
                visitor_id = evt.get("visitor_id")
                event_type = evt.get("event_type")
                
                unique_visitors.add(visitor_id)
                if event_type == "BILLING_QUEUE_JOIN":
                    queue_joins += 1
                    qd = evt.get("metadata", {}).get("queue_depth", 0)
                    if qd > max_queue_depth:
                        max_queue_depth = qd
                elif event_type == "REENTRY":
                    reentries += 1
    except FileNotFoundError:
        # Fallback dummy data if pipeline hasn't been run yet
        return {
            "unique_visitors": 24,
            "converted_visitors": 18,
            "conversion_rate": 0.75,
            "current_queue_depth": 3,
            "abandonment_rate": 0.12,
            "data_confidence": "HIGH"
        }
        
    return {
        "unique_visitors": len(unique_visitors),
        "converted_visitors": queue_joins,
        "conversion_rate": round(queue_joins / len(unique_visitors), 2) if unique_visitors else 0.0,
        "current_queue_depth": max_queue_depth,
        "abandonment_rate": 0.0, # no POS file yet means no abandonment
        "data_confidence": "HIGH" if len(unique_visitors) >= 20 else "LOW"
    }

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/stores/{store_id}/metrics")
async def get_metrics(store_id: str):
    if store_id == "STORE_EMPTY_999":
        return {
            "store_id": store_id,
            "unique_visitors": 0,
            "converted_visitors": 0,
            "conversion_rate": 0.0,
            "avg_dwell_seconds_by_zone": {},
            "current_queue_depth": 0,
            "abandonment_rate": 0.0,
            "data_confidence": "LOW",
        }
        
    stats = get_session_stats()
    return {
        "store_id": store_id,
        "unique_visitors": stats["unique_visitors"],
        "converted_visitors": stats["converted_visitors"],
        "conversion_rate": stats["conversion_rate"],
        "avg_dwell_seconds_by_zone": {"SKINCARE": 45.2, "MOISTURISER": 32.8, "BILLING": 84.5},
        "current_queue_depth": stats["current_queue_depth"],
        "abandonment_rate": stats["abandonment_rate"],
        "data_confidence": stats["data_confidence"],
    }

@app.get("/stores/{store_id}/funnel")
async def get_funnel(store_id: str):
    stats = get_session_stats()
    v = stats["unique_visitors"]
    return {
        "store_id": store_id,
        "funnel": [
            {"stage": "entry", "label": "Store Entry", "visitors": v, "drop_off_pct": 0.0},
            {"stage": "zone_visit", "label": "Zone Visit", "visitors": int(v * 0.9), "drop_off_pct": 10.0},
            {"stage": "billing_queue", "label": "Billing Queue", "visitors": stats["converted_visitors"], "drop_off_pct": 20.0},
            {"stage": "purchase", "label": "Purchase", "visitors": stats["converted_visitors"], "drop_off_pct": 0.0},
        ],
        "overall_conversion_pct": round(stats["conversion_rate"] * 100, 1)
    }

@app.get("/stores/{store_id}/heatmap")
async def get_heatmap(store_id: str):
    stats = get_session_stats()
    return {
        "store_id": store_id,
        "zones": [
            {"zone_id": "BILLING", "visit_count": stats["converted_visitors"], "avg_dwell_seconds": 84.5, "visit_score": 95.0, "dwell_score": 90.0, "combined_score": 92.5},
            {"zone_id": "SKINCARE", "visit_count": int(stats["unique_visitors"] * 0.8), "avg_dwell_seconds": 45.2, "visit_score": 80.0, "dwell_score": 60.0, "combined_score": 70.0},
            {"zone_id": "MOISTURISER", "visit_count": int(stats["unique_visitors"] * 0.6), "avg_dwell_seconds": 32.8, "visit_score": 60.0, "dwell_score": 45.0, "combined_score": 52.5},
        ]
    }

@app.get("/stores/{store_id}/anomalies")
async def get_anomalies(store_id: str):
    stats = get_session_stats()
    anomalies = []
    if stats["current_queue_depth"] >= 5:
        anomalies.append({
            "type": "BILLING_QUEUE_SPIKE",
            "severity": "CRITICAL" if stats["current_queue_depth"] >= 8 else "WARN",
            "detail": f"Active queue depth is {stats['current_queue_depth']}.",
            "suggested_action": "Open an additional billing counter immediately.",
            "detected_at": datetime.now(timezone.utc).isoformat(),
        })
    return {
        "store_id": store_id,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
    }

@app.get("/health")
async def health():
    return {
        "status": "OK",
        "database": "OK (MOCK MODE)",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stores": [{"store_id": "STORE_BLR_002", "last_event": datetime.now(timezone.utc).isoformat(), "lag_seconds": 0, "status": "OK"}]
    }
