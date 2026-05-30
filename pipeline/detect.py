"""
pipeline/detect.py
Main detection + tracking script.
Processes CCTV clips → structured events → emits to API or JSONL file.

Usage:
    python detect.py --clip path/to/clip.mp4 \\
                     --store_id STORE_BLR_002 \\
                     --camera_id CAM_ENTRY_01 \\
                     --layout ../store_layout.json \\
                     --output events.jsonl \\
                     [--api_url http://localhost:8000]
"""
import argparse
import json
import logging
from pathlib import Path

import cv2

from tracker import MultiObjectTracker
from emit import EventEmitter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CONFIDENCE_THRESHOLD = 0.35   # emit events even below this — just flag confidence
ENTRY_LINE_RATIO = 0.5        # horizontal line at 50% of frame height = entry threshold


def load_layout(layout_path: str) -> dict:
    with open(layout_path) as f:
        return json.load(f)


def build_zone_map(layout: dict, store_id: str) -> dict[str, dict]:
    """Return {zone_id: {bbox: [x1,y1,x2,y2], sku_zone: str}} for the store."""
    for store in layout.get("stores", []):
        if store["store_id"] == store_id:
            return {z["zone_id"]: z for z in store.get("zones", [])}
    return {}


def point_in_zone(cx: float, cy: float, zone: dict) -> bool:
    """Check if centroid falls within a zone bounding box (normalised 0-1 coords)."""
    x1, y1, x2, y2 = zone["bbox"]
    return x1 <= cx <= x2 and y1 <= cy <= y2


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def process_clip(
    clip_path: str,
    store_id: str,
    camera_id: str,
    layout: dict,
    output_path: str,
    api_url: str | None,
    clip_start_ts: str | None,
    transactions_path: str | None = None,
    frame_skip: int = 2,
):
    zone_map = build_zone_map(layout, store_id)
    cap = cv2.VideoCapture(clip_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open clip: {clip_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    log.info(f"Clip: {clip_path} | FPS: {fps} | Frames: {total_frames}")

    tracker = MultiObjectTracker(
        store_id=store_id,
        camera_id=camera_id,
        fps=fps,
        zone_map=zone_map,
        entry_line_ratio=ENTRY_LINE_RATIO,
        clip_start_ts=clip_start_ts,
        transactions_path=transactions_path,
    )
    emitter = EventEmitter(output_path=output_path, api_url=api_url)

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_idx += 1
        if frame_idx % frame_skip != 0:
            continue

        events = tracker.process_frame(frame, frame_idx)
        for event in events:
            emitter.emit(event)

        if frame_idx % 300 == 0:
            pct = frame_idx / total_frames * 100
            log.info(f"Progress: {pct:.1f}% ({frame_idx}/{total_frames})")

    # Flush any open sessions as EXIT events at end of clip
    close_events = tracker.flush_sessions(frame_idx)
    for event in close_events:
        emitter.emit(event)

    cap.release()
    emitter.close()
    log.info(f"Done. Events written to {output_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CCTV Detection Pipeline")
    parser.add_argument("--clip", required=True)
    parser.add_argument("--store_id", required=True)
    parser.add_argument("--camera_id", required=True)
    parser.add_argument("--layout", required=True)
    parser.add_argument("--output", default="events.jsonl")
    parser.add_argument("--api_url", default=None)
    parser.add_argument("--clip_start_ts", default=None, help="ISO-8601 UTC start time of clip")
    parser.add_argument("--transactions", default=None, help="Path to POS transactions CSV")
    parser.add_argument("--frame_skip", type=int, default=2, help="Process every Nth frame")
    args = parser.parse_args()

    layout = load_layout(args.layout)
    process_clip(
        clip_path=args.clip,
        store_id=args.store_id,
        camera_id=args.camera_id,
        layout=layout,
        output_path=args.output,
        api_url=args.api_url,
        clip_start_ts=args.clip_start_ts,
        transactions_path=args.transactions,
        frame_skip=args.frame_skip,
    )
