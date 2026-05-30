# CHOICES.md — Three Key Decisions

## Decision 1: Detection Model — YOLOv8n + ByteTrack

### Options Considered
- **YOLOv8n (chosen)** — single-stage detector, real-time at 1080p, Ultralytics bundles ByteTrack
- **YOLOv9** — slightly better accuracy but no mature tracking integration at time of writing
- **RT-DETR** — transformer-based, better at crowded scenes but significantly slower
- **MediaPipe** — fast and lightweight but person detection only, no tracking out of the box
- **GPT-4V / Claude Vision** — considered for zone classification and staff detection

### What AI Suggested
When I asked Claude to compare detection models for retail CCTV analytics, it highlighted that YOLOv8 + ByteTrack is the most battle-tested combination for person tracking in crowded indoor scenes, specifically citing ByteTrack's advantage of maintaining track IDs through short occlusions (e.g. someone walking behind a display shelf) by keeping "lost" hypotheses alive for a configurable number of frames. It also noted that RT-DETR would score higher on the billing queue scene (crowded, overlapping people) but at a significant inference cost.

### What I Chose and Why
YOLOv8n with ByteTrack via the Ultralytics `model.track()` API. The main reasons:
1. ByteTrack's lost-track recovery directly handles the partial occlusion edge case from the problem statement
2. The Ultralytics integration means tracking is one line — `model.track(frame, persist=True)` — which reduces the surface area for bugs
3. For staff classification, I deliberately chose an HSV uniform heuristic over a VLM. A VLM (GPT-4V) could classify staff more accurately, but it introduces a per-frame API call that would make the pipeline orders of magnitude slower. The HSV approach processes at native frame rate and is tunable per store by adjusting the hue range constant. The tradeoff: if the store changes uniform color, a developer needs to update one constant. Acceptable for a retail deployment.

### Where I Disagreed With AI
Claude initially suggested using a fine-tuned Re-ID model trained specifically on retail datasets. I overrode this in favour of the pretrained OSNet x0.25 — because fine-tuning requires labelled data from these specific stores, which we don't have. The pretrained model is good enough for the cosine similarity threshold approach used for re-entry detection, and zero labelling effort.

---

## Decision 2: Event Schema Design

### Options Considered
- **Flat schema** — all fields top-level, no nested metadata
- **Nested schema with metadata (chosen)** — core fields top-level, supplementary fields in `metadata`
- **Schema per event type** — separate schemas for ENTRY, ZONE_DWELL, BILLING_QUEUE_JOIN, etc.

### What AI Suggested
I asked Claude to critique the schema from the problem statement. It noted that a single unified schema with a `metadata` bag is a common pattern in event-driven systems (e.g. Segment's Track spec, Snowplow events) because it allows the ingest endpoint to validate all events against one schema while allowing event-specific payloads in the metadata bag. The alternative — separate schemas per event type — would require the API to dispatch on `event_type` before validation, which complicates the ingest endpoint.

### What I Chose and Why
Kept the schema from the problem statement (flat core + `metadata` object). One intentional addition: I emit low-confidence events rather than suppressing them. The `confidence` field is always populated with the true model confidence. This means a 0.18-confidence detection still becomes an event — it's just clearly marked. The API's metrics endpoints filter on `is_staff=false` but do not filter on confidence, which means low-confidence customer events contribute to counts. This is a deliberate trade-off: in production, store operators would want visibility into detection uncertainty rather than silent data gaps. If needed, a confidence threshold can be applied at query time.

### Where I Disagreed With AI
Claude suggested adding a `session_id` field separate from `visitor_id` to distinguish a visitor's first visit from a re-entry within the same day. I chose not to do this — it would require the pipeline to manage session state, which is already handled by the ENTRY/REENTRY event distinction. Adding a separate session_id would be the right call for a production system with long-running sessions but adds complexity not needed for this challenge.

---

## Decision 3: API Storage and Computation Strategy

### Options Considered
- **SQLite** — zero config, but write-lock contention under concurrent ingest
- **PostgreSQL (chosen)** — concurrent writes, good index support, asyncpg for non-blocking I/O
- **Redis** — fast for counters but limited query flexibility
- **TimescaleDB** — excellent for time-series but heavier to operate

### What AI Suggested
Claude recommended PostgreSQL over SQLite for the reason I anticipated: concurrent ingest from multiple camera feeds can cause write contention on SQLite. It also suggested TimescaleDB as the "right" answer for time-series event data at scale (compression, time-bucket queries), but acknowledged this would be over-engineering for a challenge dataset. For the anomaly detection 7-day rolling average, it suggested a materialised view refreshed on a schedule — good advice that I simplified to a live query (acceptable for the data volumes here).

### What I Chose and Why
PostgreSQL with asyncpg (async SQLAlchemy). Two compound indexes cover the main query patterns:
- `(store_id, timestamp)` — all time-range queries on a store
- `(visitor_id, store_id)` — session reconstruction for funnel and deduplication

Metrics are computed at query time rather than pre-aggregated. For the challenge data volumes (20-minute clips, ~5 stores) this is fast enough. At 40 live stores I would introduce a Redis-cached layer with a 30-second TTL to avoid recalculating the same metrics on every dashboard refresh.

The one thing I explicitly disagreed with: Claude suggested using a UUID primary key for the `events` table stored as a `TEXT` column for simplicity. I overrode this in favour of PostgreSQL's native `UUID` type — it's stored as 16 bytes vs 36 bytes for text, which matters when the table grows to tens of millions of rows per store.
