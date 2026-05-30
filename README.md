# Store Intelligence — Apex Retail

End-to-end CCTV analytics pipeline: raw video → live store metrics API.

## Quick Start (5 commands)

```bash
git clone <repo-url> store-intelligence && cd store-intelligence
cp -r /path/to/dataset/* data/          # place dataset ZIP contents here
docker compose up --build -d            # start API + DB + dashboard
cd pipeline && pip install -r requirements.txt
./run.sh --api_url http://localhost:8000  # process clips → ingest events
```

The API is live at **http://localhost:8000**  
The dashboard runs at **http://localhost:3000** (or terminal: `python dashboard/live.py`)

---

## Running the Detection Pipeline

### Prerequisites
- Python 3.11+
- pip dependencies: `pip install -r pipeline/requirements.txt`
- Dataset placed in `data/` with structure:
  ```
  data/
  ├── clips/            # *.mp4 files
  ├── store_layout.json
  └── pos_transactions.csv
  ```

### Process all clips (batch mode)
```bash
cd pipeline
CLIPS_DIR=../data/clips LAYOUT=../data/store_layout.json ./run.sh --api_url http://localhost:8000
```

Events are written to `data/events/*.jsonl` and simultaneously POSTed to the API.

### Process a single clip
```bash
python detect.py \
  --clip ../data/clips/STORE_BLR_002__CAM_ENTRY_01.mp4 \
  --store_id STORE_BLR_002 \
  --camera_id CAM_ENTRY_01 \
  --layout ../data/store_layout.json \
  --output ../data/events/blr002_entry.jsonl \
  --api_url http://localhost:8000 \
  --clip_start_ts 2026-03-03T09:00:00Z
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/events/ingest` | Ingest up to 500 events (idempotent) |
| `GET` | `/stores/{id}/metrics` | Visitors, conversion rate, dwell, queue |
| `GET` | `/stores/{id}/funnel` | Entry → Zone → Billing → Purchase |
| `GET` | `/stores/{id}/heatmap` | Zone visit frequency, normalised 0–100 |
| `GET` | `/stores/{id}/anomalies` | Active queue spikes, conversion drops, dead zones |
| `GET` | `/health` | DB status, per-store feed freshness |

### Example
```bash
curl http://localhost:8000/stores/STORE_BLR_002/metrics | jq .
```

---

## Running Tests

```bash
docker compose exec api pytest tests/ --cov=. --cov-report=term-missing -v
```

---

## Repository Structure

```
store-intelligence/
├── pipeline/
│   ├── detect.py        # Detection + tracking entrypoint
│   ├── tracker.py       # YOLOv8 + ByteTrack + Re-ID logic
│   ├── emit.py          # Event schema + JSONL/API emission
│   ├── requirements.txt
│   └── run.sh           # Batch-process all clips
├── app/
│   ├── main.py          # FastAPI app, middleware, lifespan
│   ├── models.py        # Pydantic event schema
│   ├── db/
│   │   └── database.py  # SQLAlchemy + ORM models
│   ├── routers/
│   │   ├── events.py    # POST /events/ingest
│   │   ├── metrics.py   # GET /stores/{id}/metrics
│   │   ├── funnel.py    # GET /stores/{id}/funnel
│   │   ├── heatmap.py   # GET /stores/{id}/heatmap
│   │   ├── anomalies.py # GET /stores/{id}/anomalies
│   │   └── health.py    # GET /health
│   ├── Dockerfile
│   └── requirements.txt
├── tests/
│   ├── test_pipeline.py
│   ├── test_metrics.py
│   └── test_anomalies.py
├── dashboard/
│   ├── live.py          # rich terminal dashboard
│   └── Dockerfile
├── docs/
│   ├── DESIGN.md
│   └── CHOICES.md
├── docker-compose.yml
└── README.md
```

---

## Live Dashboard

Terminal:
```bash
python dashboard/live.py --store_id STORE_BLR_002 --api_url http://localhost:8000
```

Refreshes every 3 seconds showing: visitor count, conversion rate, queue depth, funnel, and active anomalies.

---

## Architecture Notes

See [docs/DESIGN.md](docs/DESIGN.md) for full architecture overview and AI-assisted decisions.  
See [docs/CHOICES.md](docs/CHOICES.md) for model selection, schema design, and API architecture rationale.
