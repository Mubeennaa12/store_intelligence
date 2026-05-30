# DESIGN.md — Store Intelligence System Architecture

## Overview

This system converts raw CCTV footage from Apex Retail stores into a live analytics API. The pipeline has four stages: detection, event streaming, intelligence API, and a live dashboard.

## System Architecture

```
CCTV Clips (.mp4)
       │
       ▼
┌─────────────────┐
│  Detection Layer │  YOLOv8n + ByteTrack (via Ultralytics)
│  pipeline/       │  OSNet Re-ID for re-entry matching
│  detect.py       │  Staff classification via HSV uniform heuristic
└────────┬────────┘
         │  Structured events (JSONL + HTTP batch)
         ▼
┌─────────────────────────────────────┐
│  POST /events/ingest                │
│  PostgreSQL — EventRow table        │
│  Idempotent upsert on event_id      │
└────────┬────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────┐
│  Intelligence API (FastAPI)                       │
│  GET /stores/{id}/metrics     — real-time counts  │
│  GET /stores/{id}/funnel      — session funnel    │
│  GET /stores/{id}/heatmap     — zone dwell map    │
│  GET /stores/{id}/anomalies   — threshold rules   │
│  GET /health                  — feed freshness    │
└────────┬─────────────────────────────────────────┘
         │
         ▼
┌──────────────────────┐
│  Terminal Dashboard  │  rich Live layout, 3s refresh
└──────────────────────┘
```

## Component Decisions

### Detection Layer
YOLOv8n was chosen for its balance of speed and accuracy at 1080p 15fps. The Ultralytics library bundles ByteTrack, which handles occlusion significantly better than SORT-based approaches by keeping track hypotheses alive for short disappearances. For Re-ID, OSNet x0.25 from torchreid was chosen — it's lightweight (1.3M params) and purpose-built for person re-identification.

Staff classification uses an HSV hue range mask on the cropped bounding box. This is a deliberate heuristic rather than a trained classifier — it's interpretable, fast, and tunable per store by adjusting `STAFF_UNIFORM_HUE_RANGE` in tracker.py.

### Event Schema
The schema follows the problem statement exactly. One intentional design decision: low-confidence detections are emitted with their true confidence rather than suppressed. This preserves data integrity — the API consumer or downstream system can apply its own threshold. Silently dropping events would make it impossible to audit detection quality.

### Storage
PostgreSQL with two composite indexes: `(store_id, timestamp)` for time-range queries and `(visitor_id, store_id)` for session reconstruction. SQLite would work for a single instance but was ruled out because concurrent ingest from multiple camera feeds can produce lock contention. The async SQLAlchemy driver (asyncpg) keeps API latency low during ingest bursts.

### API Computation Strategy
Metrics are computed at query time from raw events rather than from pre-aggregated views. For 40 stores and the event volumes in the challenge dataset this is fast enough. At production scale (40 live stores, continuous ingest), this would need materialised views updated on ingest — noted in the follow-up design notes below.

## AI-Assisted Decisions

### 1. Re-entry time window (REENTRY_TIME_WINDOW_SEC = 300)
I asked Claude to reason about the distribution of typical re-entry durations in retail — e.g. a customer steps outside to take a call and returns. The suggestion was 3–5 minutes as the natural window before it becomes a genuinely new session. I chose 5 minutes (300s) as the upper bound, which I can tune down if we see too many false RE-ENTRY flags in the footage.

### 2. Conversion rate definition
The problem statement defines conversion as "visitor in billing zone in the 5-minute window before a POS transaction." I asked Claude whether proximity-to-transaction was a better proxy than actual BILLING_QUEUE_JOIN events. The AI suggested using BILLING_QUEUE_JOIN as the primary signal (since it's an explicit event we emit) and POS correlation as a secondary validation. I agreed — this keeps the funnel self-consistent without requiring POS data to be present for every query.

### 3. Anomaly detection approach
I considered using a rolling z-score for queue depth anomalies vs a hard threshold. Claude argued that for an MVP, a hard threshold is more debuggable and explainable to non-technical retail operators, whereas z-score requires enough historical data to be meaningful. I agreed and went with hard thresholds (configurable constants at the top of anomalies.py), noting that the z-score approach would be the natural next iteration.

## Production Scale Notes

At 40 live stores sending events in real time:
- The ingest endpoint would need a message queue (Kafka or Redis Streams) to buffer bursts
- Metrics would need materialised views refreshed on a 30s cadence
- The Re-ID cross-camera deduplication hook in tracker.py (currently a no-op for single-camera runs) would need a shared embedding store (Redis with vector similarity)
- The anomaly detection would benefit from a proper time-series store (TimescaleDB or InfluxDB) for the 7-day rolling averages
