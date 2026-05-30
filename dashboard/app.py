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

store_id = st.sidebar.selectbox(
    "Select Store",
    options=["STORE_BLR_002", "STORE_EMPTY_999"],
    index=0
)

refresh_rate = st.sidebar.slider(
    "Refresh Interval (seconds)",
    min_value=1,
    max_value=10,
    value=3
)

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
