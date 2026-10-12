#!/usr/bin/env python3
"""Hardware simulator — exercise the detection engine end-to-end without hardware.

Scenarios:
  walk-by   : one motion event (must NOT start billing)
  game      : motion + pressure + camera over ~70 s (should auto-start, HYBRID)
  card      : RFID card tap (starts immediately if card belongs to an active member)
  duplicate : same event_id sent 3 times (server processes once)
  offline   : stale event from 2 hours ago (rejected + alert)

Usage:
  python3 simulate.py --server http://localhost:8000 --device TABLE4_SENSOR --key rdk_... --scenario walk-by
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone


def send(server, device, key, body):
    req = urllib.request.Request(f"{server}/api/v1/devices/ingest/events", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Device-Id": device, "X-Device-Key": key})
    out = json.loads(urllib.request.urlopen(req, timeout=10).read())
    print(json.dumps(out["results"], indent=1))
    return out


def ev(event, **kw):
    return {"event_id": uuid.uuid4().hex, "event": event, "timestamp": datetime.now(timezone.utc).isoformat(), **kw}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://localhost:8000")
    ap.add_argument("--device", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--scenario", default="walk-by", choices=["walk-by", "game", "card", "duplicate", "offline"])
    ap.add_argument("--card", default="04A1B2C3")
    a = ap.parse_args()
    if a.scenario == "walk-by":
        send(a.server, a.device, a.key, ev("ACTIVITY_DETECTED"))
    elif a.scenario == "game":
        for i in range(8):
            send(a.server, a.device, a.key, ev("ACTIVITY_DETECTED" if i % 2 else "GAME_ACTIVITY", confidence=0.93))
            time.sleep(10)
    elif a.scenario == "card":
        send(a.server, a.device, a.key, ev("CARD_TAP", card_uid=a.card))
    elif a.scenario == "duplicate":
        e = ev("ACTIVITY_DETECTED")
        for _ in range(3):
            send(a.server, a.device, a.key, e)
    elif a.scenario == "offline":
        e = ev("ACTIVITY_DETECTED")
        e["timestamp"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        send(a.server, a.device, a.key, e)


if __name__ == "__main__":
    main()
