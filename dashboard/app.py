import os
import time
import httpx
import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Streamlit Page Settings
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Apex Retail — Store Intelligence",
    page_icon="🏬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---------------------------------------------------------------------------
# Styling and Theme overrides
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    .main {
        background-color: #0e1117;
        color: #ffffff;
    }
    .stMetric {
        background-color: #1e293b;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
        border: 1px solid #334155;
    }
    .stMetric label {
        color: #94a3b8 !important;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Configuration & API client
# ---------------------------------------------------------------------------
API_URL = os.getenv("API_URL", "http://localhost:8000")

# ---------------------------------------------------------------------------
# Sidebar Controls
# ---------------------------------------------------------------------------
st.sidebar.title("🏬 Apex Retail")
st.sidebar.markdown("Real-time CCTV Analytics Console")

if "store_id_index" not in st.session_state:
    st.session_state["store_id_index"] = 0

store_id = st.sidebar.selectbox(
    "Select Store",
    options=["STORE_BLR_002", "STORE_EMPTY_999"],
    index=st.session_state["store_id_index"]
)

# Sync back session state on selection
if store_id == "STORE_BLR_002":
    st.session_state["store_id_index"] = 0
else:
    st.session_state["store_id_index"] = 1

refresh_rate = st.sidebar.slider(
    "Refresh Interval (seconds)",
    min_value=1,
    max_value=10,
    value=3
)

# ---------------------------------------------------------------------------
# Video Processing Console
# ---------------------------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.subheader("🎥 Video Processing Console")

import sys
import glob
import subprocess

clips_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "clips"))
clip_files = glob.glob(os.path.join(clips_dir, "*.mp4"))

if clip_files:
    clip_names = ["[All Store Cameras]"] + [os.path.basename(f) for f in clip_files]
    selected_clip_name = st.sidebar.selectbox("Select Video Clip", options=clip_names)

    frame_skip = st.sidebar.slider(
        "Performance Frame Skip",
        min_value=2,
        max_value=60,
        value=30,
        help="Higher skip = dramatically faster CPU processing for demonstrations."
    )

    if selected_clip_name == "[All Store Cameras]":
        st.sidebar.caption("Processes all 5 CCTV feeds sequentially to build the complete store funnel and heatmap.")
        
        if st.sidebar.button("🚀 Process All Cameras", use_container_width=True):
            st.sidebar.markdown("---")
            progress_bar = st.sidebar.progress(0.0)
            status_text = st.sidebar.empty()
            
            pipeline_detect_py = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pipeline", "detect.py"))
            layout_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "store_layout.json"))
            
            start_time = time.time()
            success = True
            
            for idx, clip_path in enumerate(clip_files):
                clip_name = os.path.basename(clip_path)
                filename_no_ext = os.path.splitext(clip_name)[0]
                parts = filename_no_ext.split("__")
                if len(parts) >= 2:
                    clip_store_id = parts[0]
                    clip_camera_id = parts[1]
                else:
                    clip_store_id = store_id
                    clip_camera_id = f"CAM_{idx+1}"
                
                output_jsonl = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "events", f"{filename_no_ext}_events.jsonl"))
                
                status_text.info(f"Processing camera {idx+1}/{len(clip_files)}: `{clip_camera_id}`...")
                
                cmd = [
                    sys.executable,
                    pipeline_detect_py,
                    "--clip", clip_path,
                    "--store_id", clip_store_id,
                    "--camera_id", clip_camera_id,
                    "--layout", layout_path,
                    "--output", output_jsonl,
                    "--api_url", API_URL,
                    "--frame_skip", str(frame_skip)
                ]
                
                try:
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        bufsize=1
                    )
                    
                    while True:
                        line = proc.stdout.readline()
                        if not line:
                            break
                        if "Progress:" in line:
                            try:
                                pct_part = line.split("Progress:")[1].split("%")[0].strip()
                                current_file_pct = float(pct_part) / 100.0
                                overall_pct = (idx + current_file_pct) / len(clip_files)
                                progress_bar.progress(min(overall_pct, 1.0))
                                status_text.info(f"Camera {idx+1}/{len(clip_files)} (`{clip_camera_id}`): {pct_part}% complete")
                            except Exception:
                                pass
                    
                    proc.wait()
                    if proc.returncode != 0:
                        success = False
                        st.sidebar.error(f"❌ Processing failed for camera `{clip_camera_id}`.")
                        break
                except Exception as e:
                    success = False
                    st.sidebar.error(f"❌ Error on camera `{clip_camera_id}`: {str(e)}")
                    break
            
            if success:
                progress_bar.progress(1.0)
                duration = time.time() - start_time
                st.sidebar.success(
                    f"✅ **All 5 Cameras Processed!**\n\n"
                    f"⏱️ **Total Time:** `{duration:.1f} seconds`"
                )
                st.session_state["store_id_index"] = 0
                st.rerun()
                
    else:
        selected_clip_path = os.path.join(clips_dir, selected_clip_name)
        filename_no_ext = os.path.splitext(selected_clip_name)[0]
        parts = filename_no_ext.split("__")
        if len(parts) >= 2:
            clip_store_id = parts[0]
            clip_camera_id = parts[1]
        else:
            clip_store_id = store_id
            clip_camera_id = "CAM_01"

        st.sidebar.caption(f"**Store ID:** `{clip_store_id}` | **Camera ID:** `{clip_camera_id}`")

        if st.sidebar.button("🚀 Process Selected Video", use_container_width=True):
            st.sidebar.markdown("---")
            progress_bar = st.sidebar.progress(0.0)
            status_text = st.sidebar.empty()

            pipeline_detect_py = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pipeline", "detect.py"))
            layout_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "store_layout.json"))
            output_jsonl = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "events", f"{filename_no_ext}_events.jsonl"))

            cmd = [
                sys.executable,
                pipeline_detect_py,
                "--clip", selected_clip_path,
                "--store_id", clip_store_id,
                "--camera_id", clip_camera_id,
                "--layout", layout_path,
                "--output", output_jsonl,
                "--api_url", API_URL,
                "--frame_skip", str(frame_skip)
            ]

            status_text.info("Starting detection pipeline...")
            start_time = time.time()
            
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1
                )
                
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    if "Progress:" in line:
                        try:
                            pct_part = line.split("Progress:")[1].split("%")[0].strip()
                            pct = float(pct_part) / 100.0
                            progress_bar.progress(min(pct, 1.0))
                            status_text.info(f"Processing: {pct_part}% complete")
                        except Exception:
                            pass

                proc.wait()
                duration = time.time() - start_time

                if proc.returncode == 0:
                    progress_bar.progress(1.0)
                    st.sidebar.success(
                        f"✅ **Processing Complete!**\n\n"
                        f"⏱️ **Time:** `{duration:.1f} seconds`"
                    )
                    if clip_store_id == "STORE_BLR_002":
                        st.session_state["store_id_index"] = 0
                    else:
                        st.session_state["store_id_index"] = 1
                    st.rerun()
                else:
                    st.sidebar.error("❌ Pipeline execution failed. See logs.")
            except Exception as e:
                st.sidebar.error(f"❌ Error: {str(e)}")
else:
    st.sidebar.warning("No clips found in `data/clips/`.")

st.sidebar.markdown("---")
st.sidebar.info(
    "💡 **Part E Live Dashboard Bonus**\n\n"
    "This Web UI connects directly to the FastAPI database endpoints and updates "
    "automatically as events stream in from our YOLOv8 / ByteTrack pipeline."
)

# ---------------------------------------------------------------------------
# Live Updates Loop
# ---------------------------------------------------------------------------
placeholder = st.empty()

while True:
    try:
        with httpx.Client(timeout=3.0) as client:
            # Parallel query endpoints
            metrics_resp = client.get(f"{API_URL}/stores/{store_id}/metrics")
            funnel_resp = client.get(f"{API_URL}/stores/{store_id}/funnel")
            heatmap_resp = client.get(f"{API_URL}/stores/{store_id}/heatmap")
            anomalies_resp = client.get(f"{API_URL}/stores/{store_id}/anomalies")
            health_resp = client.get(f"{API_URL}/health")

            metrics = metrics_resp.json() if metrics_resp.status_code == 200 else {}
            funnel_data = funnel_resp.json() if funnel_resp.status_code == 200 else {}
            heatmap_data = heatmap_resp.json() if heatmap_resp.status_code == 200 else {}
            anomalies_data = anomalies_resp.json() if anomalies_resp.status_code == 200 else {}
            health = health_resp.json() if health_resp.status_code == 200 else {}

        with placeholder.container():
            # Title & Header
            st.title("🏬 Apex Retail — Live Store Intelligence")
            st.markdown(f"**Connected to:** `{API_URL}` | **Store ID:** `{store_id}` | **Latest Refresh:** `{time.strftime('%H:%M:%S')}`")
            st.markdown("---")

            # 1. KPI Cards Row
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric(
                    label="Unique Visitors Today",
                    value=metrics.get("unique_visitors", 0)
                )
            with col2:
                st.metric(
                    label="Conversion Rate",
                    value=f"{metrics.get('conversion_rate', 0.0) * 100:.1f}%"
                )
            with col3:
                st.metric(
                    label="Active Queue Depth",
                    value=metrics.get("current_queue_depth", 0)
                )
            with col4:
                st.metric(
                    label="Checkout Abandonment Rate",
                    value=f"{metrics.get('abandonment_rate', 0.0) * 100:.1f}%"
                )

            st.markdown("<br>", unsafe_allow_html=True)

            # 2. Funnel & Heatmap Split
            left_col, right_col = st.columns(2)

            with left_col:
                st.subheader("📊 Conversion Funnel (Unique Sessions)")
                funnel_stages = funnel_data.get("funnel", [])
                if funnel_stages:
                    max_visitors = funnel_stages[0]["visitors"] or 1
                    for stage in funnel_stages:
                        visitors = stage["visitors"]
                        drop_off = stage["drop_off_pct"]
                        pct_of_entry = visitors / max_visitors
                        
                        st.markdown(f"**{stage['label']}** ({visitors} visitors)")
                        st.progress(pct_of_entry)
                        if stage["stage"] != "entry":
                            st.caption(f"📉 Drop-off from previous stage: **{drop_off}%**")
                else:
                    st.info("No visitor sessions recorded yet.")

            with right_col:
                st.subheader("🔥 Store Zone Heatmap")
                zones = heatmap_data.get("zones", [])
                if zones:
                    heatmap_df = pd.DataFrame(zones)
                    # format table for display
                    display_df = heatmap_df[[
                        "zone_id", "visit_count", "avg_dwell_seconds", "combined_score"
                    ]].copy()
                    display_df.columns = [
                        "Zone Name", "Visit Count", "Avg Dwell (seconds)", "Combined Popularity"
                    ]
                    st.dataframe(
                        display_df.style.background_gradient(cmap="Oranges"),
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.info("No customer zone activity detected.")

            st.markdown("<br>", unsafe_allow_html=True)

            # 3. Anomalies Section
            st.subheader("🚨 Active Operational Anomalies")
            anomalies = anomalies_data.get("anomalies", [])
            if anomalies:
                for anom in anomalies:
                    sev = anom["severity"]
                    if sev == "CRITICAL":
                        st.error(
                            f"⚠️ **CRITICAL: {anom['type']}**\n\n"
                            f"**Details:** {anom['detail']}\n\n"
                            f"👉 **Suggested Action:** *{anom['suggested_action']}*"
                        )
                    elif sev == "WARN":
                        st.warning(
                            f"⚡ **WARNING: {anom['type']}**\n\n"
                            f"**Details:** {anom['detail']}\n\n"
                            f"👉 **Suggested Action:** *{anom['suggested_action']}*"
                        )
                    else:
                        st.info(
                            f"ℹ️ **INFO: {anom['type']}**\n\n"
                            f"**Details:** {anom['detail']}\n\n"
                            f"👉 **Suggested Action:** *{anom['suggested_action']}*"
                        )
            else:
                st.success("✅ No operational anomalies detected in the store.")

            # 4. Footer & Health
            st.markdown("---")
            foot_left, foot_right = st.columns(2)
            with foot_left:
                st.markdown(f"**Data Confidence Quality:** `{metrics.get('data_confidence', 'LOW')}`")
            with foot_right:
                db_status = health.get("database", "UNKNOWN")
                st.markdown(f"**FastAPI Server Status:** `OK` | **Database connection:** `{db_status}`")

    except httpx.HTTPError:
        with placeholder.container():
            st.title("🏬 Apex Retail — Live Store Intelligence")
            st.markdown("---")
            st.error(
                "🛑 **Connection Lost to Store Intelligence API**\n\n"
                f"Could not connect to FastAPI server at `{API_URL}`.\n\n"
                "Please verify that the backend is running (e.g. `docker compose up --build`) and check your networks."
            )
            st.info("🔄 Dashboard is currently attempting to reconnect automatically...")

    time.sleep(refresh_rate)
