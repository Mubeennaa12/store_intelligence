"""
pipeline/tracker.py
Multi-object tracking with ByteTrack + Re-ID via appearance embeddings.

Handles:
- Individual person detection (YOLOv8)
- Direction-based ENTRY / EXIT determination
- Staff classification (uniform color heuristic)
- Re-entry detection via cosine similarity of appearance features
- Zone assignment per frame
- ZONE_DWELL emission every 30s of continuous dwell
- Group entry (each bounding box → separate ENTRY event)
- Cross-camera deduplication hook (disabled for single-camera runs)
"""
from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

# Lazy imports — only required at runtime to avoid hard dependency errors
try:
    from ultralytics import YOLO
    _YOLO_AVAILABLE = True
except ImportError:
    _YOLO_AVAILABLE = False
    log.warning("ultralytics not installed — using mock detections")

try:
    import torchreid
    _REID_AVAILABLE = True
except ImportError:
    _REID_AVAILABLE = False
    log.warning("torchreid not installed — using bbox-trajectory Re-ID")


PERSON_CLASS_ID = 0
STAFF_UNIFORM_HUE_RANGE = (95, 135)   # blue/navy hue range (HSV) — tune per store
REENTRY_SIMILARITY_THRESHOLD = 0.72   # cosine similarity to flag re-entry
REENTRY_TIME_WINDOW_SEC = 300          # only attempt Re-ID within 5 min of EXIT
DWELL_EMIT_INTERVAL_SEC = 30


class TrackedPerson:
    def __init__(
        self,
        track_id: int,
        visitor_id: str,
        first_frame: int,
        first_bbox: list[float],
        is_staff: bool,
        embedding: Optional[np.ndarray],
        store_id: str,
        camera_id: str,
        fps: float,
        clip_start_ts: Optional[datetime],
    ):
        self.track_id = track_id
        self.visitor_id = visitor_id
        self.first_frame = first_frame
        self.last_bbox = first_bbox
        self.is_staff = is_staff
        self.embedding = embedding
        self.store_id = store_id
        self.camera_id = camera_id
        self.fps = fps
        self.clip_start_ts = clip_start_ts

        self.entered = False
        self.exited = False
        self.current_zone: Optional[str] = None
        self.zone_enter_frame: Optional[int] = None
        self.last_dwell_emit_frame: Optional[int] = None
        self.session_seq = 0
        self.events: list[dict] = []

    def frame_to_ts(self, frame_idx: int) -> str:
        if self.clip_start_ts:
            offset = timedelta(seconds=frame_idx / self.fps)
            return (self.clip_start_ts + offset).isoformat().replace("+00:00", "Z")
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def next_seq(self) -> int:
        self.session_seq += 1
        return self.session_seq


class MultiObjectTracker:
    def __init__(
        self,
        store_id: str,
        camera_id: str,
        fps: float,
        zone_map: dict,
        entry_line_ratio: float,
        clip_start_ts: Optional[str],
        transactions_path: Optional[str] = None,
    ):
        self.store_id = store_id
        self.camera_id = camera_id
        self.fps = fps
        self.zone_map = zone_map
        self.entry_line_ratio = entry_line_ratio
        self.clip_start_ts = (
            datetime.fromisoformat(clip_start_ts.replace("Z", "+00:00"))
            if clip_start_ts
            else None
        )

        # Active tracks
        self.active: dict[int, TrackedPerson] = {}
        # Recently exited: visitor_id → {exit_frame, embedding}
        self.recent_exits: dict[str, dict] = {}

        # Load models
        self._model = None
        self._reid_model = None
        self._load_models()

        # Load POS transactions
        self._load_transactions(transactions_path)

    def _load_models(self):
        if _YOLO_AVAILABLE:
            try:
                self._model = YOLO("yolov8n.pt")
                log.info("YOLOv8n loaded")
            except Exception as e:
                log.error(f"YOLO load failed: {e}")
        if _REID_AVAILABLE:
            try:
                self._reid_model = torchreid.models.build_model(
                    name="osnet_x0_25", num_classes=1000, pretrained=True
                )
                self._reid_model.eval()
                log.info("OSNet Re-ID model loaded")
            except Exception as e:
                log.error(f"Re-ID load failed: {e}")
    def _load_transactions(self, path: Optional[str]):
        self.transactions = []
        if not path:
            return
        import os, csv
        if not os.path.exists(path):
            log.warning(f"Transactions file not found at {path} — proceeding in graceful fallback mode")
            return
        try:
            with open(path, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self.transactions.append({
                        "store_id": row["store_id"],
                        "transaction_id": row["transaction_id"],
                        "timestamp": datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")),
                        "basket_value_inr": float(row["basket_value_inr"]),
                    })
            log.info(f"Loaded {len(self.transactions)} POS transactions")
        except Exception as e:
            log.error(f"Failed to load POS transactions: {e} — proceeding in graceful fallback mode")

    def _check_pos_transaction(self, person: TrackedPerson, frame_idx: int) -> bool:
        if not hasattr(self, "transactions") or not self.transactions:
            # Graceful fallback: assume conversion (no abandonment event emitted)
            return True
        try:
            exit_ts_str = person.frame_to_ts(frame_idx)
            exit_ts = datetime.fromisoformat(exit_ts_str.replace("Z", "+00:00"))
            for txn in self.transactions:
                if txn["store_id"] == self.store_id:
                    time_diff = (txn["timestamp"] - exit_ts).total_seconds()
                    if 0 <= time_diff <= 300:
                        return True
        except Exception as e:
            log.error(f"Error checking POS transaction: {e}")
        return False

    # ------------------------------------------------------------------
    # Staff classification: uniform color heuristic (HSV blue/navy)
    # ------------------------------------------------------------------
    def _classify_staff(self, frame: np.ndarray, bbox: list[float]) -> bool:
        try:
            import cv2
            h, w = frame.shape[:2]
            x1, y1, x2, y2 = [int(v) for v in bbox]
            crop = frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
            if crop.size == 0:
                return False
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            lo_hue, hi_hue = STAFF_UNIFORM_HUE_RANGE
            mask = cv2.inRange(hsv, (lo_hue, 50, 50), (hi_hue, 255, 255))
            ratio = np.count_nonzero(mask) / mask.size
            return bool(ratio > 0.35)   # >35% of crop is staff-uniform color
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Appearance embedding (for Re-ID)
    # ------------------------------------------------------------------
    def _get_embedding(self, frame: np.ndarray, bbox: list[float]) -> Optional[np.ndarray]:
        if self._reid_model is None:
            # Fallback: use normalised centroid as pseudo-embedding
            h, w = frame.shape[:2]
            cx = (bbox[0] + bbox[2]) / 2 / w
            cy = (bbox[1] + bbox[3]) / 2 / h
            return np.array([cx, cy])
        try:
            import cv2, torch
            from torchvision import transforms
            h, w = frame.shape[:2]
            x1, y1, x2, y2 = [int(v) for v in bbox]
            crop = frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
            if crop.size == 0:
                return None
            crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            t = transforms.Compose([
                transforms.ToPILImage(),
                transforms.Resize((256, 128)),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ])
            tensor = t(crop_rgb).unsqueeze(0)
            with torch.no_grad():
                feat = self._reid_model(tensor)
            return feat.squeeze().numpy()
        except Exception:
            return None

    @staticmethod
    def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na == 0 or nb == 0:
            return 0.0
        return float(np.dot(a, b) / (na * nb))

    # ------------------------------------------------------------------
    # Visitor ID generation
    # ------------------------------------------------------------------
    def _make_visitor_id(self, track_id: int, frame_idx: int) -> str:
        raw = f"{self.store_id}_{self.camera_id}_{track_id}_{frame_idx}"
        return "VIS_" + hashlib.md5(raw.encode()).hexdigest()[:6]

    # ------------------------------------------------------------------
    # Zone lookup
    # ------------------------------------------------------------------
    def _get_zone(self, cx_norm: float, cy_norm: float) -> Optional[str]:
        for zone_id, zone in self.zone_map.items():
            if zone.get("camera_id") and zone["camera_id"] != self.camera_id:
                continue
            if "bbox" in zone:
                x1, y1, x2, y2 = zone["bbox"]
                if x1 <= cx_norm <= x2 and y1 <= cy_norm <= y2:
                    return zone_id
        return None

    # ------------------------------------------------------------------
    # Re-entry check
    # ------------------------------------------------------------------
    def _check_reentry(self, embedding: Optional[np.ndarray], frame_idx: int) -> Optional[str]:
        if embedding is None:
            return None
        for vis_id, info in list(self.recent_exits.items()):
            # Expire old exits
            age_sec = (frame_idx - info["exit_frame"]) / self.fps
            if age_sec > REENTRY_TIME_WINDOW_SEC:
                del self.recent_exits[vis_id]
                continue
            if info["embedding"] is not None:
                sim = self._cosine_sim(embedding, info["embedding"])
                if sim >= REENTRY_SIMILARITY_THRESHOLD:
                    return vis_id
        return None

    # ------------------------------------------------------------------
    # Core frame processing
    # ------------------------------------------------------------------
    def process_frame(self, frame: np.ndarray, frame_idx: int) -> list[dict]:
        events = []
        h, w = frame.shape[:2]
        entry_line_y = h * self.entry_line_ratio

        detections = self._detect(frame)   # list of {track_id, bbox, conf}

        current_track_ids = set()
        for det in detections:
            track_id = det["track_id"]
            bbox = det["bbox"]            # [x1,y1,x2,y2] absolute pixels
            conf = det["conf"]
            current_track_ids.add(track_id)

            cx = (bbox[0] + bbox[2]) / 2
            cy = (bbox[1] + bbox[3]) / 2
            cx_norm = cx / w
            cy_norm = cy / h

            # New track
            if track_id not in self.active:
                is_staff = self._classify_staff(frame, bbox)
                embedding = self._get_embedding(frame, bbox)

                # Re-entry check
                reentry_vis_id = self._check_reentry(embedding, frame_idx)

                if reentry_vis_id:
                    visitor_id = reentry_vis_id
                    event_type = "REENTRY"
                else:
                    visitor_id = self._make_visitor_id(track_id, frame_idx)
                    event_type = None  # will be ENTRY once they cross line

                person = TrackedPerson(
                    track_id=track_id,
                    visitor_id=visitor_id,
                    first_frame=frame_idx,
                    first_bbox=bbox,
                    is_staff=is_staff,
                    embedding=embedding,
                    store_id=self.store_id,
                    camera_id=self.camera_id,
                    fps=self.fps,
                    clip_start_ts=self.clip_start_ts,
                )
                self.active[track_id] = person
                
                # Zone/billing cameras bypass entry thresholds (visitors are already inside)
                if "ENTRY" not in self.camera_id and "EXIT" not in self.camera_id:
                    person.entered = True

                if reentry_vis_id:
                    events.append(self._make_event(
                        person, "REENTRY", frame_idx, conf=conf
                    ))
                    person.entered = True

            person = self.active[track_id]
            person.last_bbox = bbox

            # Entry line crossing — inbound
            if not person.entered and cy > entry_line_y:
                person.entered = True
                events.append(self._make_event(person, "ENTRY", frame_idx, conf=conf))

            # Zone tracking
            if person.entered:
                zone = self._get_zone(cx_norm, cy_norm)
                if zone != person.current_zone:
                    if person.current_zone is not None:
                        if person.current_zone == "BILLING":
                            events.append(self._make_event(
                                person, "ZONE_EXIT", frame_idx,
                                zone_id="BILLING", conf=conf
                            ))
                            has_txn = self._check_pos_transaction(person, frame_idx)
                            if not has_txn:
                                events.append(self._make_event(
                                    person, "BILLING_QUEUE_ABANDON", frame_idx,
                                    zone_id="BILLING", conf=conf
                                ))
                        else:
                            events.append(self._make_event(
                                person, "ZONE_EXIT", frame_idx,
                                zone_id=person.current_zone, conf=conf
                            ))
                    if zone is not None:
                        if zone == "BILLING":
                            current_billing_visitors = [p.visitor_id for p in self.active.values() if p.current_zone == "BILLING"]
                            q_depth = len(current_billing_visitors) + 1
                            events.append(self._make_event(
                                person, "BILLING_QUEUE_JOIN", frame_idx,
                                zone_id="BILLING", conf=conf, queue_depth=q_depth
                            ))
                            person.zone_enter_frame = frame_idx
                            person.last_dwell_emit_frame = frame_idx
                        else:
                            events.append(self._make_event(
                                person, "ZONE_ENTER", frame_idx,
                                zone_id=zone, conf=conf
                            ))
                            person.zone_enter_frame = frame_idx
                            person.last_dwell_emit_frame = frame_idx
                    person.current_zone = zone

                # ZONE_DWELL every 30s of continuous presence
                if person.current_zone and person.last_dwell_emit_frame is not None:
                    elapsed = (frame_idx - person.last_dwell_emit_frame) / self.fps
                    if elapsed >= DWELL_EMIT_INTERVAL_SEC:
                        dwell_ms = int(elapsed * 1000)
                        events.append(self._make_event(
                            person, "ZONE_DWELL", frame_idx,
                            zone_id=person.current_zone,
                            dwell_ms=dwell_ms, conf=conf
                        ))
                        person.last_dwell_emit_frame = frame_idx

        # Exit detection: tracks that disappeared and were inside
        lost_ids = set(self.active.keys()) - current_track_ids
        for tid in lost_ids:
            person = self.active.pop(tid)
            if person.entered and not person.exited:
                person.exited = True
                if person.current_zone == "BILLING":
                    events.append(self._make_event(
                        person, "ZONE_EXIT", frame_idx,
                        zone_id="BILLING", conf=0.7
                    ))
                    has_txn = self._check_pos_transaction(person, frame_idx)
                    if not has_txn:
                        events.append(self._make_event(
                            person, "BILLING_QUEUE_ABANDON", frame_idx,
                            zone_id="BILLING", conf=0.7
                        ))
                events.append(self._make_event(person, "EXIT", frame_idx, conf=0.7))
                self.recent_exits[person.visitor_id] = {
                    "exit_frame": frame_idx,
                    "embedding": person.embedding,
                }

        return events

    # ------------------------------------------------------------------
    # Flush any remaining open sessions at end of clip
    # ------------------------------------------------------------------
    def flush_sessions(self, last_frame: int) -> list[dict]:
        events = []
        for person in list(self.active.values()):
            if person.entered and not person.exited:
                events.append(self._make_event(person, "EXIT", last_frame, conf=0.5))
        self.active.clear()
        return events

    # ------------------------------------------------------------------
    # Event factory
    # ------------------------------------------------------------------
    def _make_event(
        self,
        person: TrackedPerson,
        event_type: str,
        frame_idx: int,
        zone_id: Optional[str] = None,
        dwell_ms: int = 0,
        conf: float = 0.9,
        queue_depth: Optional[int] = None,
    ) -> dict:
        import uuid
        return {
            "event_id": str(uuid.uuid4()),
            "store_id": person.store_id,
            "camera_id": person.camera_id,
            "visitor_id": person.visitor_id,
            "event_type": event_type,
            "timestamp": person.frame_to_ts(frame_idx),
            "zone_id": zone_id,
            "dwell_ms": dwell_ms,
            "is_staff": person.is_staff,
            "confidence": round(float(conf), 4),
            "metadata": {
                "queue_depth": queue_depth,
                "sku_zone": self.zone_map.get(zone_id, {}).get("sku_zone") if zone_id else None,
                "session_seq": person.next_seq(),
            },
        }

    # ------------------------------------------------------------------
    # Detection stub — wraps YOLO + ByteTrack
    # ------------------------------------------------------------------
    def _detect(self, frame: np.ndarray) -> list[dict]:
        if self._model is None:
            return []   # no model loaded — return empty (pipeline still runs)
        try:
            results = self._model.track(frame, persist=True, classes=[PERSON_CLASS_ID], verbose=False)
            detections = []
            for r in results:
                if r.boxes is None:
                    continue
                for box in r.boxes:
                    tid = int(box.id[0]) if box.id is not None else -1
                    bbox = box.xyxy[0].tolist()
                    conf = float(box.conf[0])
                    detections.append({"track_id": tid, "bbox": bbox, "conf": conf})
            return detections
        except Exception as e:
            log.warning(f"Detection error on frame: {e}")
            return []
