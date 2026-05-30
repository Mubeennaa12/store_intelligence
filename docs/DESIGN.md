# Design Decisions & Core Business Logic

This document details the engineering choices, technological selections, and mathematical logic behind the core features of the Apex Retail platform.

---

## 1. Technological Choices (The "Why")

### A. Why YOLOv8?
We selected **YOLOv8n (nano)** by Ultralytics as our primary detection model for the following reasons:
* **Edge Performance:** Running deep learning models on standard CPU-bound environments (such as host laptops or standard retail edge servers) is highly resource-constrained. YOLOv8n has only 3.2M parameters, requiring minimal RAM and offering extremely low inference latencies.
* **Accuracy:** Despite its small size, YOLOv8n achieves high mean Average Precision (mAP) on COCO classes, specifically class `0` (person), making it highly reliable for retail customer detection.
* **Unified API:** Ultralytics provides a unified ecosystem combining object detection, tracking wrappers, and frame manipulation, reducing codebase complexity.

### B. Why ByteTrack?
We chose **ByteTrack** over traditional trackers (like SORT or DeepSORT) due to its unique approach to handling occlusions:
* **Low-Score Association:** Standard trackers immediately discard bounding boxes with low confidence scores (e.g. under $0.5$). In crowded store checkout queues, customers often become partially blocked by shelves or other customers, dropping their detection scores. ByteTrack recovers these low-score boxes by evaluating their spatial overlap (Intersection-over-Union) with high-confidence trajectories.
* **Identity Preservation:** This ability to maintain track identities through partial occlusions reduces "track fragmentation" (where one person receives 5 different track IDs), preserving our unique visitor metrics.

### C. Why PostgreSQL?
We chose **PostgreSQL 15** with the **asyncpg** async driver over SQLite or Redis:
* **Concurrency:** Retail analytics ingest continuous concurrent event batches from multiple store cameras. SQLite's database-level locking causes immediate write-lock bottlenecks. PostgreSQL handles highly concurrent writes out of the box.
* **Query Power:** PostgreSQL's rich support for time-window aggregation, window functions, and distinct intersections lets us calculate metrics, rolling anomalies, and conversion funnels directly inside SQL, maintaining sub-millisecond API response times.
* **Async Driver (`asyncpg`):** FastAPI async endpoints combined with `asyncpg` keep connections open asynchronously without blocking the web server event loop, scaling easily to handle high-frequency batch requests.

### D. Why FastAPI?
We chose **FastAPI** over Flask or Django for the following reasons:
* **Speed:** FastAPI is built on top of Starlette and Pydantic, making it one of the fastest Python frameworks available.
* **Type Safety & Auto-Docs:** Declaring Pydantic models automatically validates JSON payloads and generates interactive OpenAPI docs (`/docs`). This allowed us to build robust schemas and integrate the partial-batch ingestion router safely.
* **Native Asynchronous Support:** Built from the ground up for `async/await` syntax, enabling highly efficient concurrent network operations.

### E. Why Streamlit?
We chose **Streamlit** for our visualization dashboard:
* **Rapid UI Design:** Renders beautifully responsive layouts with native support for Plotly charts, dataframes, and custom dark mode themes directly in Python.
* **Integrated Subprocess Streams:** Streamlit's architecture makes it easy to bind custom sidebar controls to async Python subprocesses, enabling our **Video Processing Console** to run YOLOv8 pipelines locally and output live progress bars to the user in a few lines of code.

---

## 2. Core Business Logic & Algorithms

### A. Re-Entry Suppression Strategy
When a customer leaves the store for a brief moment (e.g. to take a phone call or retrieve an item from their car) and returns, they should not be counted as a new visitor.
* **The Solution:** We integrate **OSNet x0.25**, a lightweight deep learning feature extractor designed specifically for Person Re-identification.
* **The Logic:**
  1. When a person crosses the exit line, their 512-dimensional visual embedding is saved into a sliding `recent_exits` pool.
  2. When a new person is detected in an entry frame, the tracker extracts their embedding and computes the **cosine similarity** against all embeddings in the pool.
  3. If a match is found with a similarity score above the threshold ($>0.65$) within a sliding window of **5 minutes** (`REENTRY_TIME_WINDOW_SEC = 300`):
     * The tracker suppresses the creation of a new ID.
     * The original `visitor_id` is restored.
     * The tracker emits a `REENTRY` event instead of a new `ENTRY` event, preserving visitor metric integrity.

### B. Staff Filtering Heuristic
Employee movements in a store are highly repetitive, which would skew conversion and dwell analytics if counted as customer journeys.
* **The Solution:** We run an **HSV color space uniform mask** on cropped person bounding boxes.
* **The Logic:**
  1. Store staff wear blue/navy uniforms. We define a standard hue coordinate range representing this uniform color: `STAFF_UNIFORM_HUE_RANGE = [90, 130]`.
  2. For every newly tracked person, the tracker crops their bounding box, converts it from BGR to HSV, and applies a color mask.
  3. If the masked uniform pixels exceed **35%** of the total cropped bounding box size (`ratio > 0.35`), the track is flagged as `is_staff = True`.
  4. The API metrics routers filter out all events where `is_staff == True`, ensuring employee actions never skew customer metrics.

### C. Queue Depth Calculation Logic
Checkout queue size is calculated dynamically using real-time spatial analytics rather than historical predictions.
* **The Logic:**
  1. We define the `"BILLING"` checkout area boundary as a coordinate polygon in `store_layout.json`.
  2. When a track's centroid is inside this polygon, they are marked as active in the billing zone.
  3. The pipeline tracker tracks all concurrent active, non-staff tracks currently inside the billing zone.
  4. When a new customer enters, the system counts the total active tracks present inside the zone coordinates and emits a `BILLING_QUEUE_JOIN` event with:
     $$\text{queue\_depth} = \text{Count of Active Tracks inside BILLING Zone}$$
  5. The API `/metrics` endpoint returns the current checkout queue depth by fetching the latest `BILLING_QUEUE_JOIN` queue depth value.

### D. Conversion Funnel Logic
Calculating conversion funnels in a multi-camera store environment presents a tracking challenge: since cameras are isolated, a single customer receives a different track ID on each camera angle (e.g. entry, aisle, and checkout). A strict session ID intersection would evaluate to `0`.
* **The Solution (Dual-Mode Conversion Funnel):**
  1. **Strict Mode (Fully Integrated Tracking):** Computes unique visitor intersections across stages:
     $$\text{Entry} \cap \text{Zone Visit} \cap \text{Billing Queue} \cap \text{Purchase}$$
  2. **Isolated Batch Mode (Capped Disjoint Stage Totals):** Calculates independent stage totals (total unique entries, total unique zone visits, total checkout joins, total purchases). It then applies a capping function ensuring that each stage cannot exceed the size of the preceding stage:
     $$\text{stage}_i = \min(\text{stage}_i, \text{stage}_{i-1})$$
     This guarantees mathematical monotonicity ($\text{stage}_i \le \text{stage}_{i-1}$) and aligns the funnel charts with actual store conversion metrics, preventing misleading zero-counts.

### E. Checkout Abandonment Detection
Checkout queue abandonment is a critical retail friction point. We evaluate queue exits against transaction logs to detect abandonments:
* **The Logic:**
  1. The tracker loads a cached array of successful transactions from `pos_transactions.csv` (containing `store_id`, `timestamp`, `transaction_id`).
  2. When a customer exits the `"BILLING"` zone coordinates or their track is lost within that zone, the tracker fetches their exit timestamp.
  3. The tracker searches the transaction logs for a transaction made under the same `store_id` completed between **0 and 300 seconds (5 minutes)** following the customer's exit.
  4. If a matching transaction is found, they are counted as a successful converter.
  5. If **no** matching transaction is found within this 5-minute window, the customer is flagged as having abandoned the queue out of frustration, and the tracker emits a `BILLING_QUEUE_ABANDON` event.
