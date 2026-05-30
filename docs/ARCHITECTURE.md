# Architecture Documentation — Apex Retail Store Intelligence

This document provides a detailed architectural specification of the Apex Retail platform. It covers our system components, database schemas, event state transitions, and the data-flow patterns that link our edge deep learning models with the browser-based visualization layer.

---

## 1. System Components

Apex Retail is composed of seven distinct logical layers, each with clean boundaries and interfaces:

```
┌────────────────────────────────────────────────────────────────────────┐
│                              SYSTEM LAYERS                             │
├───────────────────┬────────────────────────────────────────────────────┤
│ 1. Detection      │ YOLOv8n object detection running at edge cameras.  │
│ 2. Tracking       │ ByteTrack ID association + OSNet x0.25 Re-ID.      │
│ 3. Event Gen      │ Emits movements to JSONL & HTTP POST streams.      │
│ 4. API Layer      │ FastAPI backend with asyncpg database connection. │
│ 5. Database Layer │ PostgreSQL database for raw and indexed events.    │
│ 6. Analytics Layer│ In-DB queries calculating metrics & rolling funnels│
│ 7. Dashboard Layer│ Dark-mode Streamlit dashboard & Video Console.    │
└───────────────────┴────────────────────────────────────────────────────┘
```

### A. Detection Pipeline (`pipeline/detect.py`)
* **Role:** Processes raw `.mp4` video files frame-by-frame on CPU or GPU.
* **Mechanism:** Integrates the **YOLOv8n** lightweight convolutional detector. Extracts bounding box coordinates and model confidence scores for class `person` (COCO class `0`).
* **Performance Tuning:** Implements an adjustable frame skipping factor (`--frame_skip`) that executes neural network forward passes only on every $N$-th frame, interpolating bounding boxes linearly on skipped frames to maintain tracker stability while accelerating CPU speeds by up to **30x**.

### B. Tracking Engine (`pipeline/tracker.py`)
* **Role:** Maintains continuous track identities across frames and matches re-entering visitors.
* **Mechanism:**
  * **ByteTrack:** Resolves track IDs by analyzing spatial overlap (IoU) and Kalman filter projections. It keeps lost tracks alive for a sliding window (`REENTRY_TIME_WINDOW_SEC = 300`) to recover IDs after short occlusions.
  * **OSNet Re-ID:** Extracts a 512-dimensional visual embedding for every tracked person. When a person exits the camera view, their embedding is stored in a sliding pool. If a person with high cosine similarity ($>0.65$) re-enters within 5 minutes, their original `visitor_id` is restored.
  * **Staff Classification:** Employs an HSV color space mask to filter employees wearing store uniforms (blue/navy vests, $>35\%$ pixel ratio on cropped bounds).
  * **Zone Entrance Bypass:** Automatically sets `person.entered = True` on internal cameras to bypass entrance line requirements for visitors already deep inside the store.

### C. Event Generator (`pipeline/emit.py`)
* **Role:** Transforms movement states into structured JSON schemas.
* **Mechanism:** Evaluates spatial intersections between person centroids and layout boundaries. Compiles payloads containing UUID `event_id`, timestamps, store/camera IDs, confidence, and custom event metadata (like `dwell_ms` or `queue_depth`), then streams them to local JSONL files and POSTs them to the API.

### D. API Layer (`app/main.py`)
* **Role:** Ingests events and exposes query endpoints.
* **Mechanism:** Built using **FastAPI** and served via **Uvicorn**. Implements asynchronous handlers with **SQLAlchemy + asyncpg** for high-throughput concurrent database writes. Incorporates robust try-except batch validation to support **partial batch success** ingestion.

### E. Database Layer (`app/db/database.py`)
* **Role:** Persistently stores raw event logs.
* **Mechanism:** Relies on **PostgreSQL 15**. Employs a single flat relational table `events` optimized with composite index structures for analytical query patterns.

### F. Analytics Layer (`app/routers/`)
* **Role:** Computes retail metrics and trends at query time.
* **Mechanism:** Consists of modular FastAPI routers:
  * `metrics.py`: Computes unique visitors, conversion rate, average dwell time, active queue size.
  * `funnel.py`: Calculates stage-by-stage customer conversion drop-offs. Implements **dual-mode conversion** logic to support disjoint camera tracking.
  * `heatmap.py`: Generates normalized visitor scores, dwell scores, and combined zones popularity.
  * `anomalies.py`: Runs rolling and static threshold filters to identify active operational bottlenecks.

### G. Dashboard Layer (`dashboard/app.py`)
* **Role:** Renders metrics and handles video processing.
* **Mechanism:** Renders dynamic charts and heatmaps using **Streamlit**, **Pandas**, and **Plotly**. Features a sidebar-integrated console that executes the python edge pipeline asynchronously in safe, cross-platform UTF-8 encoded subprocess streams.

---

## 2. System Data Flow

The following data-flow diagram tracks the journey of CCTV pixels into visual metrics:

```
[Raw CCTV Clip]
       │
       ▼ (OpenCV frame-by-frame)
[YOLOv8n Inference] ──► Bounding Boxes & Confidence Scores
       │
       ▼ (ByteTrack Spatial Kalman Filters)
[Track ID Association] ──► Unique Track IDs
       │
       ├─────────────────────────┐
       ▼ (HSV Hue Mask Check)    ▼ (OSNet x0.25 Similarity Check)
[Staff Classification]    [Re-ID Cosine Matching]
       │                         │
       ▼ (Exclude staff)         ▼ (Collapse returning IDs)
   [Track Centroid Coordinates vs Polygon Boundaries]
       │
       ▼ (Coordinate boundary cross & Dwell accumulators)
[Structured JSON Events]
       │
       ▼ (HTTP POST /events/ingest batch)
[FastAPI Router Ingestion] ──► Granular Pydantic Validation (try-except)
       │
       ├──► Valid rows  ──► [PostgreSQL events Table]
       └──► Invalid rows ──► [Log & Count Ingestion Rejections]
                                 │
                                 ▼ (In-DB Analytical Queries)
                            [GET /stores/{id}/metrics]
                            [GET /stores/{id}/funnel]
                            [GET /stores/{id}/heatmap]
                            [GET /stores/{id}/anomalies]
                                 │
                                 ▼ (JSON response)
                            [Streamlit Visual UI]
```

---

## 3. Database Design & SQL Schema

Apex Retail uses a flat database design for maximum write performance under heavy edge-event spikes. All visitor metrics are computed dynamically at query time using highly optimized indexing strategies.

### A. SQL Table Definition (`events`)

```sql
CREATE TABLE events (
    event_id VARCHAR(36) PRIMARY KEY,      -- Unique UUID4 string
    store_id VARCHAR(50) NOT NULL,         -- Store identifier (e.g. STORE_BLR_002)
    camera_id VARCHAR(50) NOT NULL,        -- Camera source (e.g. CAM_ENTRY_01)
    timestamp TIMESTAMP WITH TIME ZONE,    -- ISO8601 event occurrence time
    event_type VARCHAR(50) NOT NULL,       -- Event type (e.g. ENTRY, ZONE_ENTER)
    visitor_id VARCHAR(50) NOT NULL,       -- Normalized track identifier
    is_staff BOOLEAN DEFAULT FALSE,        -- True if classified as employee
    confidence DOUBLE PRECISION,           -- Detection model confidence (0.0 - 1.0)
    zone_id VARCHAR(50),                   -- Layout zone ID (null for entry/exit)
    dwell_ms INTEGER,                      -- Presence duration (populated for DWELL/EXIT)
    queue_depth INTEGER                    -- Dynamic checkout queue size (populated for JOIN)
);
```

### B. Indexing Strategy
To guarantee sub-millisecond API response times during dashboard refreshes, two compound indexes are created on startup:

1. **Composite Query Index:** `(store_id, timestamp)`
   * **Purpose:** Optimizes all time-window filtering. Since every dashboard query filters on a specific `store_id` and filters events between `today_start` and `now`, this index completely avoids full-table scans.
   
2. **Composite Session Index:** `(visitor_id, store_id)`
   * **Purpose:** Optimizes funnel session reconstruction. Calculating customer conversion funnels requires grouping events by `visitor_id` and evaluating step progress. This index dramatically accelerates session joins.

---

## 4. Event Flow & State Machine

Every customer's journey in the physical store is mapped onto a strict event state machine. The system generates exactly six event types to represent customer behaviors:

```
                            [Customer Arrives]
                                    │
                                    ▼
                             ┌──────────────┐
                             │    ENTRY     │  (Triggered on entrance line crossing)
                             └──────┬───────┘
                                    │
                                    ├───► [If re-enters in 5m] ──► [REENTRY]
                                    │
                                    ▼
                             ┌──────────────┐
                             │  ZONE_ENTER  │  (Triggered on entering layout zone)
                             └──────┬───────┘
                                    │
                                    ├────► [Every 30s in zone] ──► [ZONE_DWELL]
                                    │
                                    ▼
                             ┌──────────────┐
                             │  ZONE_EXIT   │  (Triggered on leaving layout zone)
                             └──────┬───────┘
                                    │
                                    ▼ (Entering Checkout Zone)
                       ┌──────────────────────────┐
                       │    BILLING_QUEUE_JOIN    │  (Triggers checkout queue join)
                       └────────────┬─────────────┘
                                    │
                                    ▼ (Queue exit evaluated against transactions)
                                    ├─────► [No transaction in 5m] ──► [BILLING_QUEUE_ABANDON]
                                    │
                                    ▼ (Transaction matches in 5m)
                             ┌──────────────┐
                             │   PURCHASE   │  (Triggers successful conversion)
                             └──────┬───────┘
                                    │
                                    ▼
                             ┌──────────────┐
                             │     EXIT     │  (Triggered on exiting store door line)
                             └──────────────┘
```

1. **`ENTRY` / `REENTRY`:**
   * **Trigger:** Emitted when a track centroid crosses the designated entry-line coordinates in an inbound direction, or when a track is matched via OSNet embeddings to a recent exit session within 5 minutes.
   * **Metadata:** `is_staff = False`.
2. **`ZONE_ENTER`:**
   * **Trigger:** Emitted when a customer crosses the bounding box coordinate of an active store aisle (e.g. Skincare, Moisturisers).
   * **Metadata:** `zone_id`.
3. **`ZONE_DWELL`:**
   * **Trigger:** Emitted at periodic intervals (`DWELL_EMIT_INTERVAL_SEC = 30`) as long as a customer remains continuously inside the zone coordinates.
   * **Metadata:** `zone_id`, `dwell_ms` (accumulated duration).
4. **`BILLING_QUEUE_JOIN`:**
   * **Trigger:** Emitted specifically when a customer crosses the coordinates of the `"BILLING"` zone.
   * **Metadata:** `zone_id="BILLING"`, `queue_depth` (count of concurrent active tracks in the zone).
5. **`PURCHASE` / `BILLING_QUEUE_ABANDON`:**
   * **Trigger:** When a customer exits the checkout zone or their track is lost, the exit timestamp is checked against transaction logs.
     * **`PURCHASE`:** Fired if a POS transaction is recorded for the store within 5 minutes.
     * **`BILLING_QUEUE_ABANDON`:** Fired if no transaction is recorded for the store within 5 minutes.
6. **`EXIT`:**
   * **Trigger:** Emitted when a customer crosses the door line coordinates in an outbound direction or their track is cleanly lost near the door exit area.
