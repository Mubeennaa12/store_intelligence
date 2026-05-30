# Apex Retail — Live Store Intelligence Platform

Apex Retail is a state-of-the-art, event-driven store intelligence platform that converts raw CCTV security footage into real-time retail analytics. The platform bridges the physical retail space with digital intelligence by processing camera feeds at the edge, extracting customer movement events, and presenting operational insights through an interactive visual dashboard.

---

## 1. Problem Statement: The Offline Retail Analytics Gap

In the digital world, e-commerce platforms (like Shopify or Amazon) have complete visibility into the customer journey. Every click, product view, search query, cart addition, checkout step, and successful purchase is tracked, analyzed, and optimized. E-commerce operators know exactly:
* How many visitors entered their site (traffic).
* Where visitors dropped off (conversion funnel).
* Which pages are most popular (heatmaps).
* When checkout friction is causing lost sales (cart abandonment).

In physical retail, however, store operators are blind. They possess security cameras (CCTV) that record gigabytes of video, but this data is historically used only for loss prevention. Store owners lack answers to fundamental questions:
* *What is our true store conversion rate?*
* *How long are customers waiting in the checkout queue, and do they abandon the queue out of frustration?*
* *Which store zones are dead-zones or active hotspots?*

**Apex Retail solves this gap by transforming passive CCTV networks into an automated e-commerce-style analytics engine.**

---

## 2. Solution Overview & System Architecture

Apex Retail implements an end-to-end pipeline that handles everything from raw pixel inference to interactive browser-based visualization:

```
                  ┌────────────────────────────────────────┐
                  │            CCTV FOOTAGE (.mp4)         │
                  └───────────────────┬────────────────────┘
                                      │ (Raw Video Stream)
                                      ▼
                  ┌────────────────────────────────────────┐
                  │         YOLOv8 OBJECT DETECTION        │
                  │  Identifies customer & staff bounds    │
                  └───────────────────┬────────────────────┘
                                      │ (Bounding Box Centroids)
                                      ▼
                  ┌────────────────────────────────────────┐
                  │          BYTETRACK TRACKING            │
                  │   Assigns and maintains Track IDs      │
                  └───────────────────┬────────────────────┘
                                      │ (Track Trajectories)
                                      ▼
                  ┌────────────────────────────────────────┐
                  │            EVENT GENERATOR             │
                  │ Emits ENTRY, ZONE, QUEUE, EXIT events  │
                  └───────────────────┬────────────────────┘
                                      │ (Lightweight JSON Batches)
                                      ▼
                  ┌────────────────────────────────────────┐
                  │        FASTAPI INGESTION ENGINE        │
                  │ Validates & records events asynchronously│
                  └───────────────────┬────────────────────┘
                                      │ (asyncpg Connection Pool)
                                      ▼
                  ┌────────────────────────────────────────┐
                  │          POSTGRESQL DATABASE           │
                  │ Stores event tables with index designs │
                  └───────────────────┬────────────────────┘
                                      │
                                      ▼
                  ┌────────────────────────────────────────┐
                  │            ANALYTICS ENGINE            │
                  │   Computes funnel and metric KPIs      │
                  └───────────────────┬────────────────────┘
                                      │ (Real-time JSON REST responses)
                                      ▼
                  ┌────────────────────────────────────────┐
                  │          STREAMLIT DASHBOARD           │
                  │ Visualizes live charts & heatmaps      │
                  └────────────────────────────────────────┘
```

---

## 3. Key Features

* **Real-Time Visitor Tracking:** Deep learning-based pedestrian tracking that accurately counts and tracks customers as they traverse the store layout.
* **Re-Entry Suppression:** Uses a pre-trained **OSNet** Re-ID neural network to extract 512-dimensional appearance embeddings, matching and collapsing returning customers into a single continuous session within a 5-minute window.
* **Staff Filtering:** Auto-detects store employees based on an HSV color mask representing blue/navy uniforms (>35% coverage) to exclude employee footprints from customer conversion metrics.
* **Conversion Funnel Analytics:** Displays a dynamic conversion funnel showing drop-offs from Entry → Zone Visit → Billing Queue → Purchase. Supports a dual-mode calculation to align disjoint camera tracks.
* **Queue Depth Monitoring:** Computes real-time checkout queue length by dynamically counting active tracks occupying the billing zone coordinates.
* **Checkout Abandonment Tracking:** Correlates billing queue exits with real-time POS transactions. If no purchase is made within 5 minutes of leaving the queue, it emits a checkout abandonment event.
* **Zone Heatmaps:** Renders an interactive popularity heatmap showing normalized visitor counts, dwell times, and combined popularity scores across different store aisles.
* **Operational Anomaly Detection:** Automated backend alerts that trigger on queue depth spikes ($>5$ customers), conversion drops ($<30\%$), or dead-zones (no customer presence for $>30$ minutes).
* **Live Dashboard Updates:** High-performance Streamlit visual console that pulls real-time analytics from the API every 3 seconds.

---

## 4. Repository Structure

```
store-intelligence/
├── pipeline/             # CCTV Tracking & Inference Pipeline
│   ├── detect.py         # YOLOv8 + ByteTrack pipeline execution CLI
│   ├── tracker.py        # Cosine Re-ID, HSV staff detection, & event logic
│   ├── emit.py           # Structured event compilation & API emission
│   └── run.sh            # Automated shell script to batch process all clips
├── app/                  # FastAPI REST API Backend
│   ├── main.py           # Application routing, lifespan, & structlogger
│   ├── models.py         # Pydantic schemas supporting partial batch validation
│   ├── db/
│   │   └── database.py   # PostgreSQL connection pool and ORM schemas
│   └── routers/          # Modularized API endpoints (funnel, metrics, heatmap, etc.)
├── dashboard/            # Visualization Layer
│   ├── app.py            # Streamlit dark-mode analytics console & video processor
│   └── live.py           # Alternate Rich terminal live interface
├── tests/                # Pytest Test Suite
│   ├── conftest.py       # Sync schema setup & autouse pool disposal
│   └── test_*.py         # Tests for pipeline, metrics, and anomalies
├── docs/                 # Architectural & Design Specifications
│   ├── ARCHITECTURE.md   # System component specifications & database schema
│   ├── DESIGN.md         # Rationale behind YOLO, ByteTrack, Postgres, & FastPI
│   ├── DEMO.md           # Visual walkthrough, demo script, and expected outputs
│   └── images/           # Screenshots and demo visual assets
├── docker-compose.yml    # Full Docker services orchestration file
└── README.md             # This document
```

---

## 5. Installation & Setup Guide

### Option A: Local Host Development Setup (Recommended for Windows)

This configuration runs the API, PostgreSQL, and Streamlit Dashboard natively on your host machine.

#### 1. Prerequisites
* **Python 3.11 or 3.12**
* **PostgreSQL** installed locally on your host with:
  * **Database Name:** `store_intelligence`
  * **Username:** `postgres`
  * **Password:** `apex`

#### 2. Install Project Dependencies
We highly recommend using `uv` (a blazing-fast Python package installer) or standard `pip`:
```powershell
# Clone the repository
git clone https://github.com/Mubeennaa12/store_intelligence.git && cd store_intelligence

# Install pipeline and app dependencies
pip install -r pipeline/requirements.txt
pip install -r app/requirements.txt
pip install streamlit pandas plotly httpx rich
```

#### 3. Start the FastAPI API Server
Start the Uvicorn server in reload mode from the root directory:
```powershell
$env:PYTHONPATH="app"
uv run uvicorn app.main:app --reload --port 8000
```
The API docs will be live at: **http://localhost:8000/docs**

#### 4. Launch the Streamlit Dashboard
Open a new shell and start the interactive Streamlit dashboard:
```powershell
cd dashboard
uv run streamlit run app.py
```
The dashboard will open automatically on: **http://localhost:8501**

#### 5. Run the Automated Tests
To run the automated tests at any time and check coverage:
```powershell
uv run pytest tests/ --cov=. -v
```
All **36/36 tests** will execute and pass in under 4 seconds.

---

### Option B: Docker Setup (Multi-Container Deployment)

This configuration spins up all services (PostgreSQL, FastAPI, and Streamlit) inside isolated containers.

```bash
# 1. Start all containers in detached mode
docker compose up --build -d

# 2. Check that the containers are healthy
docker compose ps
```

* **FastAPI Backend:** http://localhost:8000
* **Streamlit Dashboard:** http://localhost:3000

---

## 6. Core REST API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/events/ingest` | Ingests batches of movements with **partial batch success** support (validates row-by-row and reports rejected counts). |
| `GET` | `/stores/{id}/metrics` | Returns store-wide KPI cards: visitors, conversion rate, average dwell time, active queue size. |
| `GET` | `/stores/{id}/funnel` | Computes conversion stages. Supports dual-mode intersection / capped disjoint count sorting. |
| `GET` | `/stores/{id}/heatmap` | Returns visit frequencies, dwell times, and combined zone popularity scores normalized `0-100`. |
| `GET` | `/stores/{id}/anomalies` | Auto-detects queue spikes ($>5$), conversion drops ($<30\%$), and dead zones. |
| `GET` | `/health` | Heartbeat verifying PostgreSQL database connectivity and camera stream latency. |

---

## 7. Integrated Demo Workflow

Apex Retail features an end-to-end **Video Processing Console** integrated directly into the dashboard sidebar:

```
 ┌──────────────────────┐      ┌──────────────────────┐      ┌──────────────────────┐
 │  1. SELECT VIDEO     ├─────►│  2. PROCESS VIDEO    ├─────►│  3. GENERATE EVENTS  │
 │ Select clip or [All] │      │ Click Process button │      │ YOLOv8+ByteTrack runs│
 └──────────────────────┘      └──────────────────────┘      └──────────┬───────────┘
                                                                        │
 ┌──────────────────────┐      ┌──────────────────────┐                 │
 │  5. REFRESH CHARTS   │◄─────┤  4. BULK INGESTION   │◄────────────────┘
 │ Charts update live!  │      │ Events POSTed to API │
 └──────────────────────┘      └──────────────────────┘
```

1. **Select CCTV Clip:** Open the Streamlit dashboard sidebar. Select an individual video clip (e.g. `CAM_ENTRY_01`, `CAM_SKINCARE_02`, `CAM_BILLING_01`) or choose **`[All Store Cameras]`** to run the complete store analytics sequentially.
2. **Process Video:** Click the **🚀 Process All Cameras** button.
3. **Generate Events:** The dashboard launches `pipeline/detect.py` asynchronously. The pipeline executes YOLOv8 object detection, maps tracks using ByteTrack, extracts OSNet Re-ID embeddings, checks uniforms, and maps transactions.
4. **Bulk Ingestion:** Generated events are packaged as JSON arrays and POSTed to `/events/ingest`. Valid rows are stored in PostgreSQL.
5. **Dashboard Updates:** The dashboard captures stdout, displays a real-time progress bar, and automatically refreshes all metrics, funnels, heatmaps, and anomalies in under 45 seconds!
