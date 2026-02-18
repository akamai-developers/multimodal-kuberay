#!/usr/bin/env python3
"""
Brand-Detection Pipeline: YOLO t-shirt tracking → dedup → Ollama VLM.

Captures live webcam frames, tracks clothing with YOLOv8 + BoTSORT,
deduplicates via persistent track IDs so the same garment is only sent
to the VLM once, and queries a remote Ollama instance (qwen3-vl:8b)
to identify the brand.

Usage:
    python pipeline.py --ollama-url http://<VM_IP>:11434 --model qwen3-vl:8b

    # With a fine-tuned YOLO model:
    python pipeline.py --yolo-model tshirt_best.pt --classes tshirt shirt \
                       --ollama-url http://10.0.0.5:11434

Environment variable alternative:
    export OLLAMA_URL=http://10.0.0.5:11434
    python pipeline.py
"""

from __future__ import annotations

import argparse
import base64
import sys
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

try:
    from ultralytics import YOLO
except ImportError:
    sys.exit("ultralytics is required.  pip install ultralytics")

try:
    import httpx
except ImportError:
    sys.exit("httpx is required.  pip install httpx")


# ═══════════════════════════════════════════════════════════════════════════════
# Data types
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Detection:
    """A single YOLO bounding-box with an optional persistent track ID."""
    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float
    class_id: int
    label: str
    track_id: Optional[int] = None  # assigned by BoTSORT tracker


@dataclass
class BrandResult:
    """The brand identified by the VLM for a tracked garment."""
    brand: str
    track_id: int
    timestamp: float


@dataclass
class PipelineConfig:
    """All tunables for the end-to-end pipeline."""
    # YOLO
    yolo_model: str = "yolov8n.pt"
    target_classes: Optional[List[str]] = None
    yolo_conf: float = 0.40
    yolo_iou: float = 0.50

    # Camera / preview
    camera_index: int = 0
    preview_width: int = 960

    # Ollama VLM
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3-vl:8b"
    vlm_timeout: float = 30.0          # seconds

    # Tracking / dedup
    tracker_type: str = "botsort"       # "botsort" or "bytetrack"
    track_ttl: float = 300.0            # seconds before a lost track expires

    # Display
    show_fps: bool = True
    box_color: Tuple[int, int, int] = (0, 255, 0)
    brand_color: Tuple[int, int, int] = (255, 200, 0)
    font_scale: float = 0.6


# ═══════════════════════════════════════════════════════════════════════════════
# Track-ID based dedup (replaces perceptual hashing)
# ═══════════════════════════════════════════════════════════════════════════════

class TrackCache:
    """Maps BoTSORT/ByteTrack track IDs → VLM results.

    The ultralytics tracker assigns a stable integer ID to each object
    across consecutive frames.  We only query the VLM the *first* time
    a track ID appears, making dedup trivially correct regardless of
    how the bounding box shifts, scales, or changes lighting.

    Track entries expire after ``track_ttl`` seconds so that if someone
    leaves and returns (new track ID) or the tracker reassigns IDs, we
    eventually re-query.
    """

    def __init__(self, config: PipelineConfig) -> None:
        self._ttl = config.track_ttl
        # track_id → (BrandResult | None, first_seen_time, is_pending)
        self._cache: Dict[int, Tuple[Optional[BrandResult], float, bool]] = {}
        self._lock = threading.Lock()

    def is_novel(self, track_id: int) -> bool:
        """Return True if this track ID has never been seen (or has expired)."""
        with self._lock:
            self._evict_stale()
            if track_id in self._cache:
                return False
            # Reserve the slot and mark as pending
            self._cache[track_id] = (None, time.time(), True)
            return True

    def store_result(self, track_id: int, result: BrandResult) -> None:
        with self._lock:
            self._cache[track_id] = (result, time.time(), False)

    def get_brand(self, track_id: int) -> Optional[str]:
        with self._lock:
            entry = self._cache.get(track_id)
            if entry and entry[0] is not None:
                return entry[0].brand
            return None

    def _evict_stale(self) -> None:
        now = time.time()
        stale = [k for k, (_, ts, _) in self._cache.items() if now - ts > self._ttl]
        for k in stale:
            del self._cache[k]


# ═══════════════════════════════════════════════════════════════════════════════
# Ollama VLM client
# ═══════════════════════════════════════════════════════════════════════════════

# BRAND_PROMPT = (
#     "You are a Tech brand logo/name identification expert. "
#     "Look at this image of a piece of clothing. "
#     "Identify the tech brand or logo visible on it. "
#     "Reply with ONLY the brand name - nothing else. "
#     "If you cannot identify a brand, reply with 'Unknown'."
# )
PROMPT = (
    "You are in charge of describing what you see in an image of a piece of clothing."
)

class OllamaClient:
    """Synchronous client for the Ollama /api/generate vision endpoint."""

    def __init__(self, config: PipelineConfig) -> None:
        self._base = config.ollama_url.rstrip("/")
        self._model = config.ollama_model
        self._timeout = config.vlm_timeout
        self._client = httpx.Client(timeout=httpx.Timeout(config.vlm_timeout))

    def preflight_check(self) -> None:
        """Verify Ollama is reachable and the model is available."""
        # 1. Server reachable?
        try:
            resp = self._client.get(f"{self._base}/api/tags")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            sys.exit(
                f"[pipeline] Cannot reach Ollama at {self._base}/api/tags\n"
                f"           Error: {exc}\n"
                f"           Make sure Ollama is running and the URL is correct."
            )

        # 2. Model pulled?
        models = [m["name"] for m in resp.json().get("models", [])]
        matched = any(
            self._model == m or self._model.split(":")[0] == m.split(":")[0]
            for m in models
        )
        if not matched:
            print(
                f"[pipeline] WARNING: model '{self._model}' not found in "
                f"available models: {models}\n"
                f"           Ollama may pull it on first request (slow)."
            )
        else:
            print(f"[pipeline] Ollama OK – model '{self._model}' is available.")

    def identify_brand(self, crop_bgr: np.ndarray) -> str:
        """Send a clothing crop to the VLM and return the brand name."""
        # JPEG-encode the crop
        ok, buf = cv2.imencode(".jpg", crop_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return "Unknown"
        img_b64 = base64.b64encode(buf.tobytes()).decode("ascii")

        # Use /api/generate – supported by all Ollama versions.
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": PROMPT,
                    "images": [img_b64],
                }
            ],
            "stream": False,
        }
        try:
            resp = self._client.post(
                f"{self._base}/api/chat", json=payload
            )
            resp.raise_for_status()
            data = resp.json()
            print(f"[pipeline] Ollama response: {data}")
            brand = data.get("response", "Unknown").strip()
            # Sanitise — the model sometimes wraps in quotes or adds filler
            brand = brand.strip('"\'').split("\n")[0].strip()
            return brand if brand else "Unknown"
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            print(f"[pipeline] Ollama error: {exc}")
            return "Unknown"

    def close(self) -> None:
        self._client.close()


# ═══════════════════════════════════════════════════════════════════════════════
# YOLO detector (thin wrapper matching filter.py conventions)
# ═══════════════════════════════════════════════════════════════════════════════

class YOLODetector:
    """Loads a YOLO model and returns tracked + filtered detections.

    Uses ``model.track(persist=True)`` with BoTSORT (default) so each
    detection carries a stable ``track_id`` across frames.
    """

    def __init__(self, config: PipelineConfig) -> None:
        self.cfg = config
        print(f"[pipeline] Loading YOLO model: {config.yolo_model}")
        self.model = YOLO(config.yolo_model)
        self.class_names: dict[int, str] = self.model.names
        self._tracker = config.tracker_type  # "botsort" or "bytetrack"

        self._keep_ids: Optional[set[int]] = None
        if config.target_classes:
            name_to_id = {v.lower(): k for k, v in self.class_names.items()}
            self._keep_ids = set()
            for name in config.target_classes:
                cid = name_to_id.get(name.lower())
                if cid is not None:
                    self._keep_ids.add(cid)
                else:
                    print(f"[pipeline] WARNING: '{name}' not in model classes")
            if not self._keep_ids:
                self._keep_ids = None

        print(f"[pipeline] Model classes: {list(self.class_names.values())}")
        print(f"[pipeline] Keeping: {config.target_classes or 'ALL'}")
        print(f"[pipeline] Tracker: {self._tracker}")

    def track(self, frame: np.ndarray) -> List[Detection]:
        """Run YOLO tracking on a frame; returns detections with track IDs."""
        results = self.model.track(
            frame,
            conf=self.cfg.yolo_conf,
            iou=self.cfg.yolo_iou,
            persist=True,           # keep tracker state across calls
            tracker=f"{self._tracker}.yaml",
            verbose=False,
        )
        dets: List[Detection] = []
        for r in results:
            if r.boxes is None:
                continue
            boxes = r.boxes
            # boxes.id is None when the tracker hasn't assigned IDs yet
            track_ids = boxes.id.cpu().numpy().astype(int).flatten() if boxes.id is not None else [None] * len(boxes)
            for box, tid in zip(boxes, track_ids):
                cid = int(box.cls[0])
                if self._keep_ids is not None and cid not in self._keep_ids:
                    continue
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                dets.append(Detection(
                    x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2),
                    confidence=float(box.conf[0]),
                    class_id=cid,
                    label=self.class_names.get(cid, str(cid)),
                    track_id=int(tid) if tid is not None else None,
                ))
        return dets


# ═══════════════════════════════════════════════════════════════════════════════
# Main pipeline
# ═══════════════════════════════════════════════════════════════════════════════

class BrandPipeline:
    """
    End-to-end loop:

      camera frame
        → YOLOv8 + BoTSORT tracking (bounding boxes + persistent IDs)
          → crop each box
            → track-ID dedup (TrackCache)
              → if new ID: send to Ollama VLM in background thread
              → overlay brand label on preview
    """

    def __init__(self, config: PipelineConfig) -> None:
        self.cfg = config
        self.detector = YOLODetector(config)
        self.cache = TrackCache(config)
        self.ollama = OllamaClient(config)
        self.ollama.preflight_check()

        self._lock = threading.Lock()

    # ── VLM dispatch (background thread) ──────────────────────────────────────

    def _query_brand_async(self, crop: np.ndarray, track_id: int) -> None:
        """Called in a daemon thread so the preview loop never blocks."""
        brand = self.ollama.identify_brand(crop)
        result = BrandResult(brand=brand, track_id=track_id, timestamp=time.time())
        self.cache.store_result(track_id, result)
        print(f"[pipeline] Track #{track_id} → brand: {brand}")

    # ── Drawing helpers ───────────────────────────────────────────────────────

    def _draw_detections(
        self,
        frame: np.ndarray,
        detections: List[Detection],
    ) -> np.ndarray:
        for det in detections:
            # Bounding box
            cv2.rectangle(
                frame, (det.x1, det.y1), (det.x2, det.y2),
                self.cfg.box_color, 2,
            )

            # Track ID + confidence label (bottom of box)
            tid_str = f"#{det.track_id}" if det.track_id is not None else "?"
            conf_text = f"{tid_str} {det.label} {det.confidence:.0%}"
            cv2.putText(
                frame, conf_text, (det.x1 + 2, det.y2 - 6),
                cv2.FONT_HERSHEY_SIMPLEX, self.cfg.font_scale,
                self.cfg.box_color, 1, cv2.LINE_AA,
            )

            # Brand label (if resolved) — top of box
            brand = self.cache.get_brand(det.track_id) if det.track_id is not None else None
            if brand:
                tag = f"Brand: {brand}"
                (tw, th_), _ = cv2.getTextSize(
                    tag, cv2.FONT_HERSHEY_SIMPLEX, self.cfg.font_scale, 2
                )
                # Background pill
                cv2.rectangle(
                    frame,
                    (det.x1, det.y1 - th_ - 10),
                    (det.x1 + tw + 8, det.y1),
                    self.cfg.brand_color, cv2.FILLED,
                )
                cv2.putText(
                    frame, tag, (det.x1 + 4, det.y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, self.cfg.font_scale,
                    (0, 0, 0), 2, cv2.LINE_AA,
                )
            elif det.track_id is not None:
                # Pending indicator
                cv2.putText(
                    frame, "Identifying...", (det.x1 + 2, det.y1 - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (200, 200, 200), 1, cv2.LINE_AA,
                )
        return frame

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        cap = cv2.VideoCapture(self.cfg.camera_index)
        if not cap.isOpened():
            sys.exit(f"[pipeline] Cannot open camera {self.cfg.camera_index}")

        print(
            f"[pipeline] Camera opened. Ollama at {self.cfg.ollama_url} "
            f"model={self.cfg.ollama_model}. Press 'q' to quit."
        )
        fps_smooth = 0.0
        prev_time = time.perf_counter()

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.05)
                    continue

                # Resize for preview / faster inference
                h, w = frame.shape[:2]
                if w > self.cfg.preview_width:
                    scale = self.cfg.preview_width / w
                    frame = cv2.resize(
                        frame,
                        (self.cfg.preview_width, int(h * scale)),
                        interpolation=cv2.INTER_AREA,
                    )

                # ── Track ─────────────────────────────────────────────────────
                detections = self.detector.track(frame)

                # ── Dedup & dispatch (by track ID) ────────────────────────────
                for det in detections:
                    if det.track_id is None:
                        continue  # tracker hasn't assigned an ID yet

                    if not self.cache.is_novel(det.track_id):
                        continue  # already queried or in-flight

                    # Crop the detected region (clamp to frame bounds)
                    fh, fw = frame.shape[:2]
                    x1 = max(det.x1, 0)
                    y1 = max(det.y1, 0)
                    x2 = min(det.x2, fw)
                    y2 = min(det.y2, fh)
                    crop = frame[y1:y2, x1:x2]
                    if crop.size == 0:
                        continue

                    # Fire-and-forget in a daemon thread
                    t = threading.Thread(
                        target=self._query_brand_async,
                        args=(crop.copy(), det.track_id),
                        daemon=True,
                    )
                    t.start()

                # ── Annotate ──────────────────────────────────────────────────
                frame = self._draw_detections(frame, detections)

                # FPS overlay
                now = time.perf_counter()
                fps_instant = 1.0 / max(now - prev_time, 1e-6)
                fps_smooth = 0.9 * fps_smooth + 0.1 * fps_instant
                prev_time = now
                if self.cfg.show_fps:
                    cv2.putText(
                        frame,
                        f"FPS: {fps_smooth:.1f}  |  Detections: {len(detections)}",
                        (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (255, 255, 255), 2, cv2.LINE_AA,
                    )

                cv2.imshow("Brand Detection Pipeline", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

        finally:
            cap.release()
            cv2.destroyAllWindows()
            self.ollama.close()
            print("[pipeline] Stopped.")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def parse_args(argv: Optional[Sequence[str]] = None) -> PipelineConfig:
    import os

    p = argparse.ArgumentParser(
        description="Live clothing brand detection: YOLO → dedup → Ollama VLM",
    )
    # YOLO
    p.add_argument("--yolo-model", default="yolov8n.pt", help="YOLO weights path.")
    p.add_argument("--classes", nargs="*", default=None,
                   help="YOLO class names to keep (e.g. 'person' or 'tshirt shirt').")
    p.add_argument("--yolo-conf", type=float, default=0.40, help="YOLO confidence.")
    p.add_argument("--yolo-iou", type=float, default=0.50, help="YOLO NMS IoU.")

    # Camera
    p.add_argument("--camera", type=int, default=0, help="Camera index.")
    p.add_argument("--width", type=int, default=960, help="Preview width.")

    # Ollama
    p.add_argument(
        "--ollama-url",
        default=os.getenv("OLLAMA_URL", "http://localhost:11434"),
        help="Ollama server URL (or set OLLAMA_URL env var).",
    )
    p.add_argument(
        "--model", default="qwen3-vl:8b",
        help="Ollama vision-language model for brand identification.",
    )
    p.add_argument("--vlm-timeout", type=float, default=30.0,
                   help="Timeout (sec) for each VLM request.")

    # Tracking
    p.add_argument("--tracker", default="botsort",
                   choices=["botsort", "bytetrack"],
                   help="Object tracker algorithm (default: botsort).")
    p.add_argument("--track-ttl", type=float, default=300.0,
                   help="Seconds before a lost track expires from cache.")

    a = p.parse_args(argv)
    return PipelineConfig(
        yolo_model=a.yolo_model,
        target_classes=a.classes,
        yolo_conf=a.yolo_conf,
        yolo_iou=a.yolo_iou,
        camera_index=a.camera,
        preview_width=a.width,
        ollama_url=a.ollama_url,
        ollama_model=a.model,
        vlm_timeout=a.vlm_timeout,
        tracker_type=a.tracker,
        track_ttl=a.track_ttl,
    )


def main(argv: Optional[Sequence[str]] = None) -> None:
    config = parse_args(argv)
    pipeline = BrandPipeline(config)
    pipeline.run()


if __name__ == "__main__":
    main()
