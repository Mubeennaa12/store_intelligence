# Hackathon Demo Guide — Apex Retail Store Intelligence

This document provides a step-by-step **Demo Script** and **Expected Outputs** to walk a hackathon judge or developer through the entire Apex Retail platform in under 5 minutes.

---

## 1. Interactive Demo Script

Follow these steps to spin up the system, process CCTV clips, and visualize store intelligence live.

### Step 1: Launch the FastAPI Backend
Ensure your database named `store_intelligence` is running in your local PostgreSQL.
Open a terminal and start the Uvicorn web server:
```powershell
$env:PYTHONPATH="app"
uv run uvicorn app.main:app --reload --port 8000
```
* **Expected Output:** The terminal logs will show successful connection to PostgreSQL: `Connected to database: postgresql+asyncpg://postgres:***@localhost:5432/store_intelligence` and start the server on `http://127.0.0.1:8000`.

### Step 2: Launch the Streamlit Web UI Dashboard
Open a new terminal shell and launch the visual dashboard:
```powershell
cd dashboard
uv run streamlit run app.py
```
* **Expected Output:** Your default web browser will automatically open to **http://localhost:8501**, displaying a dark-themed retail dashboard.

### Step 3: Select a CCTV Video Clip in the Sidebar Console
Look at the **Video Processing Console** located on the left sidebar:
1. Under **Select Video Clip**, open the dropdown.
2. Select **`[All Store Cameras]`** (this will queue and process all 5 store cameras sequentially to build a complete store analytics footprint).
3. Set the **Performance Frame Skip** slider to **`30`** (this skip factor tells the YOLOv8 tracking engine to run inference on 1 frame per second, allowing CPU-bound host environments to process the entire store feed in under 30 seconds).

### Step 4: Process Video & Observe Live Progress
Click the **🚀 Process All Cameras** button:
1. The sidebar will initialize a safe, cross-platform background subprocess.
2. An interactive progress bar will appear, showing percentage completion and live console stdout from YOLOv8 and ByteTrack (e.g. *Processing CAM_ENTRY_01, Frame 300/900...*).
3. When the processing reaches 100%, the backend database is populated, and the Streamlit dashboard automatically re-runs and refreshes.

### Step 5: Observe Metrics Update
Look at the top row of **KPI Cards**:
* **Unique Visitors Today:** Displays the total count of non-staff customers who entered the store.
* **Conversion Rate:** Displays the percentage of unique customers who entered the billing queue and completed a POS transaction within the 5-minute checkout window.
* **Active Queue Depth:** Displays the current checkout queue size (active customer tracks inside the checkout polygon coordinates).
* **Checkout Abandonment Rate:** Displays the percentage of customers who queued up but walked away without a matching POS transaction.

### Step 6: Show Conversion Funnel
Look at the **Conversion Funnel (Unique Sessions)** on the left column:
* The funnel renders a visual progress chart tracking unique customer drop-offs from entry, down to zone visits, checkout queue joins, and purchase completion.
* Because the API automatically utilizes **Isolated Batch Mode**, disjoint visitor tracks are capped to preceding stages, maintaining a clean monotonic conversion slope.

### Step 7: Show Zone Heatmap
Look at the **Store Zone Heatmap** on the right column:
* Renders an interactive table showing visitor popularity, visitor count, average dwell time (in seconds), and combined zone popularity scores.
* Areas like `SKINCARE`, `MOISTURISER`, and `BILLING` are styled with a vibrant, relative orange background gradient, showing store hotspots.

### Step 8: Show Queue Analytics & Operational Anomalies
Look at the bottom row of the dashboard:
* **Active Anomalies Warning Desk:** Renders warnings if queue length spikes ($>5$), conversion drops below threshold ($<30\%$), or layout zones are completely neglected (dead-zones with no visitors for $>30$ minutes).

---

## 2. Expected Dashboard Visual Outputs

Below are visual screenshots capturing the Apex Retail visual dashboard at various stages of the demo:

### A. Live Store Analytics & Video Console
The dashboard provides a highly unified operational layout showing real-time metrics, funnels, heatmaps, and active anomaly desks next to the video processing console.

![Apex Retail Live Store Dashboard Mockup](./images/media__1780155918913.png)

---

### B. Conversion Funnel & Popularity Heatmaps
When all 5 cameras are processed, visitor conversion drops and physical heatmaps are calculated dynamically at query time:

![Store Conversion Funnel and Hotspots](./images/media__1780154871462.png)

---

### C. Active Queue Analytics
The queue depth tracker dynamically monitors checkout zone counts to count queue bottlenecks:

![Live Queue Depth Tracking](./images/media__1780155528386.png)

---

### D. Automated Anomaly Warnings
The operational anomalies router automatically flags queue overflows or dead zone bottlenecks:

![Operational Anomaly Alerter Desk](./images/media__1780155244758.png)
