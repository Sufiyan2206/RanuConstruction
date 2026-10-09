#!/usr/bin/env python3
"""Edge computer-vision activity detector (Option D).

PRIVACY BY DESIGN
  * Frames are processed in memory on the club's own device and discarded.
  * No video/image is stored or uploaded. Only metadata is sent:
        {"event": "GAME_ACTIVITY", "confidence": 0.94, "payload": {"people": 2}}
  * A region-of-interest mask limits analysis to the table area.

Method (no GPU needed)
  1. Background subtraction (MOG2) inside the table ROI -> motion ratio
  2. Optional person detection (ultralytics YOLO, if installed) -> people count
  3. confidence = weighted mix, smoothed over a sliding window
  4. Only when confidence stays high for `sustain_seconds` is GAME_ACTIVITY sent.
     The server applies its own thresholds again (never bills from one frame).

Requirements: pip install opencv-python-headless numpy   [ultralytics optional]
Usage: python3 edge_cv.py --source rtsp://user:pass@cam/stream --device-id TABLE1_CAMERA --key rdk_... --server https://club...
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
import uuid
from collections import deque
from datetime import datetime, timezone


def post(server: str, device_id: str, key: str, path: str, body: dict) -> None:
    req = urllib.request.Request(f"{server.rstrip('/')}{path}", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Device-Id": device_id, "X-Device-Key": key})
    urllib.request.urlopen(req, timeout=8).read()


def main() -> None:
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="0")
    ap.add_argument("--server", required=True)
    ap.add_argument("--device-id", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--roi", default="", help="x,y,w,h of the table area (pixels)")
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--sustain-seconds", type=float, default=20)
    ap.add_argument("--threshold", type=float, default=0.8)
    a = ap.parse_args()

    cap = cv2.VideoCapture(int(a.source) if a.source.isdigit() else a.source)
    sub = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=32, detectShadows=False)
    yolo = None
    try:
        from ultralytics import YOLO  # type: ignore

        yolo = YOLO("yolov8n.pt")
    except Exception:
        pass
    window: deque[float] = deque(maxlen=int(a.sustain_seconds * a.fps))
    last_sent = 0.0
    last_hb = 0.0
    while True:
        ok, frame = cap.read()
        if not ok:
            time.sleep(2)
            continue
        if a.roi:
            x, y, w, h = map(int, a.roi.split(","))
            frame = frame[y:y + h, x:x + w]
        small = cv2.resize(frame, (320, int(320 * frame.shape[0] / frame.shape[1])))
        mask = sub.apply(small)
        motion = float(np.count_nonzero(mask)) / mask.size
        motion_score = min(1.0, motion / 0.02)  # 2% of ROI pixels moving ~ active play
        people = 0
        if yolo is not None:
            res = yolo.predict(small, classes=[0], verbose=False)
            people = int(len(res[0].boxes)) if res else 0
        people_score = min(1.0, people / 2.0) if yolo is not None else motion_score
        conf = 0.6 * motion_score + 0.4 * people_score
        window.append(conf)
        del frame, small, mask  # nothing is retained
        sustained = len(window) == window.maxlen and min(window) >= a.threshold * 0.6 and sum(window) / len(window) >= a.threshold
        now = time.time()
        if sustained and now - last_sent > 30:
            post(a.server, a.device_id, a.key, "/api/v1/devices/ingest/events", {
                "event_id": uuid.uuid4().hex, "event": "GAME_ACTIVITY", "confidence": round(sum(window) / len(window), 3),
                "timestamp": datetime.now(timezone.utc).isoformat(), "payload": {"people": people},
            })
            last_sent = now
        if now - last_hb > 30:
            try:
                post(a.server, a.device_id, a.key, "/api/v1/devices/ingest/heartbeat", {"firmware_version": "edge-cv-1.0"})
            except Exception:
                pass
            last_hb = now
        time.sleep(max(0.0, 1.0 / a.fps))


if __name__ == "__main__":
    main()
