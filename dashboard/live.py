"""
dashboard/live.py
Live terminal dashboard using rich.
Shows real-time store metrics updating as events flow in.

Usage:
    python live.py --store_id STORE_BLR_002 --api_url http://localhost:8000
"""
import argparse
import time
from datetime import datetime

import httpx
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
from rich.columns import Columns
from rich import box

console = Console()


def fetch_metrics(api_url: str, store_id: str) -> dict:
    try:
        r = httpx.get(f"{api_url}/stores/{store_id}/metrics", timeout=5)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


def fetch_anomalies(api_url: str, store_id: str) -> list:
    try:
        r = httpx.get(f"{api_url}/stores/{store_id}/anomalies", timeout=5)
        return r.json().get("anomalies", []) if r.status_code == 200 else []
    except Exception:
        return []


def fetch_funnel(api_url: str, store_id: str) -> dict:
    try:
        r = httpx.get(f"{api_url}/stores/{store_id}/funnel", timeout=5)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


SEVERITY_COLOR = {"INFO": "blue", "WARN": "yellow", "CRITICAL": "red"}


def build_layout(store_id: str, metrics: dict, anomalies: list, funnel: dict) -> Panel:
    ts = datetime.now().strftime("%H:%M:%S")

    # ---- Metrics table ----
    m_table = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
    m_table.add_column("Metric", style="dim", width=28)
    m_table.add_column("Value", style="bold green")

    uv = metrics.get("unique_visitors", "—")
    cr = metrics.get("conversion_rate", 0.0)
    qd = metrics.get("current_queue_depth", "—")
    ar = metrics.get("abandonment_rate", 0.0)

    m_table.add_row("👥 Unique Visitors", str(uv))
    m_table.add_row("💳 Conversion Rate", f"{cr:.1%}")
    m_table.add_row("🛒 Queue Depth", str(qd))
    m_table.add_row("🚪 Abandonment Rate", f"{ar:.1%}")
    m_table.add_row("📊 Data Confidence", metrics.get("data_confidence", "—"))

    metrics_panel = Panel(m_table, title="[bold]Live Metrics[/bold]", border_style="green")

    # ---- Funnel table ----
    f_table = Table(box=box.SIMPLE, pad_edge=False)
    f_table.add_column("Stage", style="dim")
    f_table.add_column("Visitors", justify="right")
    f_table.add_column("Drop-off", justify="right", style="red")

    for stage in funnel.get("funnel", []):
        f_table.add_row(
            stage.get("label", ""),
            str(stage.get("visitors", 0)),
            f"{stage.get('drop_off_pct', 0):.1f}%",
        )
    funnel_panel = Panel(f_table, title="[bold]Conversion Funnel[/bold]", border_style="blue")

    # ---- Anomalies ----
    a_lines = []
    for a in anomalies[:5]:
        color = SEVERITY_COLOR.get(a.get("severity", "INFO"), "white")
        a_lines.append(
            f"[{color}][{a['severity']}][/{color}] {a['type']}: {a.get('detail', '')}"
        )
    anomaly_text = "\n".join(a_lines) if a_lines else "[dim]No active anomalies ✓[/dim]"
    anomaly_panel = Panel(anomaly_text, title="[bold]Active Anomalies[/bold]", border_style="yellow")

    header = f"[bold cyan]Apex Retail — Store Intelligence[/bold cyan]  |  Store: [yellow]{store_id}[/yellow]  |  [dim]{ts}[/dim]"

    from rich.layout import Layout
    layout = Layout()
    layout.split_column(
        Layout(Panel(header, border_style="cyan"), size=3),
        Layout(name="main"),
        Layout(anomaly_panel, size=8),
    )
    layout["main"].split_row(
        Layout(metrics_panel),
        Layout(funnel_panel),
    )
    return layout


def run_dashboard(store_id: str, api_url: str, refresh_secs: float = 3.0):
    with Live(console=console, refresh_per_second=1, screen=True) as live:
        while True:
            metrics = fetch_metrics(api_url, store_id)
            anomalies = fetch_anomalies(api_url, store_id)
            funnel = fetch_funnel(api_url, store_id)
            live.update(build_layout(store_id, metrics, anomalies, funnel))
            time.sleep(refresh_secs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--store_id", default="STORE_BLR_002")
    parser.add_argument("--api_url", default="http://localhost:8000")
    parser.add_argument("--refresh", type=float, default=3.0)
    args = parser.parse_args()
    run_dashboard(args.store_id, args.api_url, args.refresh)
