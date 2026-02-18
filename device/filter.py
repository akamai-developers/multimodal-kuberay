#!/usr/bin/env python3
"""
T-Shirt Detection from Live Video Feed using YOLOv8 + OpenCV.

Captures frames from a webcam, runs YOLOv8 inference to detect
t-shirts (or upper-body clothing), and draws bounding boxes on
a real-time video preview.

Usage:
    # Default – uses YOLOv8n with COCO "person" class as a baseline:
    python filter.py

    # With a custom fine-tuned t-shirt model:
    python filter.py --model path/to/tshirt_best.pt

    # Specify camera index and confidence threshold:
    python filter.py --camera 1 --conf 0.45
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

import cv2
import numpy as np

try:
    from ultralytics import YOLO
except ImportError:
    sys.exit(
        "ultralytics is required.  Install it with:\n"
        "  pip install ultralytics\n"
    )

# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Detection:
    """Single detected bounding box."""
    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float
    class_id: int
    label: str


@dataclass
class FilterConfig:
    """Runtime settings for the t-shirt detector."""
    model_path: str = "yolov8n.pt"          # pretrained or fine-tuned weights
    camera_index: int = 0                    # /dev/video index
    confidence_threshold: float = 0.40       # min confidence to show a box
    iou_threshold: float = 0.50              # NMS IoU threshold
    target_classes: Optional[List[str]] = None  # class names to keep (None = all)
    preview_width: int = 960                 # resize preview to this width
    box_color: tuple = (0, 255, 0)           # BGR green
    box_thickness: int = 2
    font_scale: float = 0.6
    show_fps: bool = True


# ── Detector ──────────────────────────────────────────────────────────────────

class TshirtDetector:
    """YOLOv8-based t-shirt / clothing detector with live preview."""

    # COCO class IDs that relate to "person" (index 0).  When no custom model
    # is provided we fall back to detecting people as a proxy for shirts.
    _COCO_PERSON_ID = 0

    def __init__(self, config: FilterConfig) -> None:
        self.cfg = config
        print(f"[filter] Loading model: {config.model_path}")
        self.model = YOLO(config.model_path)

        # Build a lookup for the class names the model knows about.
        self.class_names: dict[int, str] = self.model.names  # {0: 'person', …}

        # Resolve which class IDs to keep.
        if config.target_classes is not None:
            # User specified explicit class names (e.g. ["tshirt", "shirt"]).
            name_to_id = {v.lower(): k for k, v in self.class_names.items()}
            self._keep_ids: Optional[set[int]] = set()
            for name in config.target_classes:
                cid = name_to_id.get(name.lower())
                if cid is not None:
                    self._keep_ids.add(cid)
                else:
                    print(f"[filter] WARNING: class '{name}' not in model – skipping")
            if not self._keep_ids:
                print("[filter] No matching target classes – will show ALL detections")
                self._keep_ids = None
        else:
            self._keep_ids = None  # keep everything the model predicts

        print(f"[filter] Model classes: {list(self.class_names.values())}")
        print(f"[filter] Filtering to: {config.target_classes or 'ALL classes'}")

    # ── Inference ─────────────────────────────────────────────────────────────

    def detect(self, frame: np.ndarray) -> List[Detection]:
        """Run YOLO inference on a single BGR frame and return detections."""
        results = self.model(
            frame,
            conf=self.cfg.confidence_threshold,
            iou=self.cfg.iou_threshold,
            verbose=False,
        )
        detections: List[Detection] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                cls_id = int(box.cls[0])
                if self._keep_ids is not None and cls_id not in self._keep_ids:
                    continue
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                detections.append(
                    Detection(
                        x1=int(x1), y1=int(y1),
                        x2=int(x2), y2=int(y2),
                        confidence=float(box.conf[0]),
                        class_id=cls_id,
                        label=self.class_names.get(cls_id, str(cls_id)),
                    )
                )
        return detections

    # ── Drawing ───────────────────────────────────────────────────────────────

    def annotate_frame(self, frame: np.ndarray, detections: List[Detection]) -> np.ndarray:
        """Draw bounding boxes and labels onto the frame (in-place)."""
        for det in detections:
            color = self.cfg.box_color
            cv2.rectangle(
                frame,
                (det.x1, det.y1),
                (det.x2, det.y2),
                color,
                self.cfg.box_thickness,
            )
            text = f"{det.label} {det.confidence:.0%}"
            (tw, th), _ = cv2.getTextSize(
                text, cv2.FONT_HERSHEY_SIMPLEX, self.cfg.font_scale, 1
            )
            # Label background
            cv2.rectangle(
                frame,
                (det.x1, det.y1 - th - 8),
                (det.x1 + tw + 4, det.y1),
                color,
                cv2.FILLED,
            )
            cv2.putText(
                frame,
                text,
                (det.x1 + 2, det.y1 - 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                self.cfg.font_scale,
                (0, 0, 0),
                1,
                cv2.LINE_AA,
            )
        return frame

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Open camera, run detection, show live preview. Press 'q' to quit."""
        cap = cv2.VideoCapture(self.cfg.camera_index)
        if not cap.isOpened():
            sys.exit(f"[filter] Cannot open camera index {self.cfg.camera_index}")

        print(f"[filter] Camera opened (index {self.cfg.camera_index}). Press 'q' to quit.")
        fps_smooth = 0.0
        prev_time = time.perf_counter()

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    print("[filter] Failed to grab frame – retrying…")
                    time.sleep(0.1)
                    continue

                # Optionally resize for faster inference / display.
                h, w = frame.shape[:2]
                if w > self.cfg.preview_width:
                    scale = self.cfg.preview_width / w
                    frame = cv2.resize(
                        frame,
                        (self.cfg.preview_width, int(h * scale)),
                        interpolation=cv2.INTER_AREA,
                    )

                # Detect & annotate
                detections = self.detect(frame)
                frame = self.annotate_frame(frame, detections)

                # FPS overlay
                now = time.perf_counter()
                fps_instant = 1.0 / max(now - prev_time, 1e-6)
                fps_smooth = 0.9 * fps_smooth + 0.1 * fps_instant
                prev_time = now
                if self.cfg.show_fps:
                    cv2.putText(
                        frame,
                        f"FPS: {fps_smooth:.1f}  |  Detections: {len(detections)}",
                        (10, 28),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (255, 255, 255),
                        2,
                        cv2.LINE_AA,
                    )

                cv2.imshow("T-Shirt Detector", frame)

                # Quit on 'q' or window close
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
        finally:
            cap.release()
            cv2.destroyAllWindows()
            print("[filter] Stopped.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args(argv: Optional[Sequence[str]] = None) -> FilterConfig:
    p = argparse.ArgumentParser(
        description="Live t-shirt detection with YOLOv8 + OpenCV",
    )
    p.add_argument(
        "--model", default="yolov8n.pt",
        help=(
            "Path to YOLO weights.  Use a COCO checkpoint (yolov8n/s/m/l/x.pt) "
            "for person detection, or supply your own fine-tuned t-shirt model."
        ),
    )
    p.add_argument("--camera", type=int, default=0, help="Camera device index.")
    p.add_argument("--conf", type=float, default=0.40, help="Confidence threshold.")
    p.add_argument("--iou", type=float, default=0.50, help="NMS IoU threshold.")
    p.add_argument(
        "--classes", nargs="*", default=None,
        help=(
            "Class names to filter (space-separated).  "
            "Examples: 'person' for COCO, 'tshirt shirt' for a custom model.  "
            "Omit to show ALL detected classes."
        ),
    )
    p.add_argument("--width", type=int, default=960, help="Preview window width.")
    args = p.parse_args(argv)

    return FilterConfig(
        model_path=args.model,
        camera_index=args.camera,
        confidence_threshold=args.conf,
        iou_threshold=args.iou,
        target_classes=args.classes,
        preview_width=args.width,
    )


def main(argv: Optional[Sequence[str]] = None) -> None:
    config = parse_args(argv)
    detector = TshirtDetector(config)
    detector.run()


if __name__ == "__main__":
    main()
