#!/usr/bin/env python3
"""RANU edge gateway — runs on a Raspberry Pi (or any Linux box) inside the club.

Responsibilities
  * read local hardware (PIR/IR/pressure/vibration via GPIO, USB RFID/NFC readers)
  * debounce noisy sensors
  * give every event a unique event_id (server de-duplicates on it)
  * store events in a local SQLite queue FIRST, then send in batches
    -> internet/server outages never lose events; they are flushed on reconnect
  * send heartbeats (with queue depth) so the dashboard shows ONLINE/OFFLINE

Only the Python standard library is required. GPIO support uses `gpiozero`
when installed; `--simulate` generates synthetic events for commissioning.

Usage
  python3 ranu_gateway.py --config gateway.json
  python3 ranu_gateway.py --config gateway.json --simulate
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

log = logging.getLogger("ranu-gateway")
VERSION = "1.0.0"


# ----------------------------------------------------------------------------- durable queue
class EventQueue:
    def __init__(self, path: str) -> None:
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS q (id INTEGER PRIMARY KEY, device_id TEXT, body TEXT, tries INTEGER DEFAULT 0)")
        self.lock = threading.Lock()

    def put(self, device_id: str, event: dict) -> None:
        with self.lock:
            self.db.execute("INSERT INTO q (device_id, body) VALUES (?, ?)", (device_id, json.dumps(event)))

    def batch(self, device_id: str, n: int = 100) -> list[tuple[int, dict]]:
        with self.lock:
            rows = self.db.execute("SELECT id, body FROM q WHERE device_id=? ORDER BY id LIMIT ?", (device_id, n)).fetchall()
        return [(r[0], json.loads(r[1])) for r in rows]

    def ack(self, ids: list[int]) -> None:
        if ids:
            with self.lock:
                self.db.execute(f"DELETE FROM q WHERE id IN ({','.join('?' * len(ids))})", ids)

    def depth(self, device_id: str) -> int:
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM q WHERE device_id=?", (device_id,)).fetchone()[0]


# ----------------------------------------------------------------------------- server client
class Api:
    def __init__(self, base_url: str, timeout: float = 8.0) -> None:
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def post(self, path: str, device: dict, body: dict) -> dict:
        req = urllib.request.Request(
            f"{self.base}{path}", data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json", "X-Device-Id": device["device_id"], "X-Device-Key": device["api_key"]},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read() or b"{}")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ----------------------------------------------------------------------------- gateway
class Gateway:
    def __init__(self, cfg: dict, simulate: bool) -> None:
        self.cfg = cfg
        self.api = Api(cfg["server_url"])
        self.queue = EventQueue(cfg.get("queue_path", "ranu_queue.db"))
        self.devices = {d["device_id"]: d for d in cfg["devices"]}
        self.simulate = simulate
        self.last_emit: dict[str, float] = {}
        self.stop = threading.Event()
        self.started = time.time()

    def emit(self, device_id: str, event: str, *, confidence: float | None = None, card_uid: str | None = None, payload: dict | None = None) -> None:
        dev = self.devices[device_id]
        debounce = float(dev.get("debounce_seconds", 10 if event not in ("CARD_TAP", "START_REQUEST") else 1))
        key = f"{device_id}:{event}"
        t = time.time()
        if t - self.last_emit.get(key, 0) < debounce:
            return
        self.last_emit[key] = t
        body = {"event_id": uuid.uuid4().hex, "event": event, "timestamp": now_iso(), "payload": payload or {}}
        if confidence is not None:
            body["confidence"] = round(confidence, 3)
        if card_uid:
            body["card_uid"] = card_uid
        self.queue.put(device_id, body)
        log.info("queued %s %s", device_id, event)

    # -- sender --------------------------------------------------------------
    def sender_loop(self) -> None:
        backoff = 1.0
        while not self.stop.is_set():
            sent_any = False
            for device_id, dev in self.devices.items():
                items = self.queue.batch(device_id)
                if not items:
                    continue
                try:
                    res = self.api.post("/api/v1/devices/ingest/events", dev, {"events": [b for _, b in items]})
                    self.queue.ack([i for i, _ in items])  # DUPLICATE results are fine too
                    for r in res.get("results", []):
                        if r.get("outcome") in ("SESSION_STARTED",):
                            log.info("server started session on %s (%s)", device_id, r.get("method"))
                    sent_any = True
                    backoff = 1.0
                except (urllib.error.URLError, TimeoutError, OSError) as e:
                    log.warning("send failed (%s); %d events kept in queue", e, self.queue.depth(device_id))
                    backoff = min(backoff * 2, 60)
            self.stop.wait(0.5 if sent_any else backoff)

    def heartbeat_loop(self) -> None:
        interval = float(self.cfg.get("heartbeat_seconds", 30))
        while not self.stop.is_set():
            for device_id, dev in self.devices.items():
                try:
                    self.api.post("/api/v1/devices/ingest/heartbeat", dev, {
                        "firmware_version": f"gateway-{VERSION}", "uptime_seconds": int(time.time() - self.started),
                        "queue_depth": self.queue.depth(device_id),
                    })
                except Exception as e:  # server unreachable: device shows OFFLINE, staff use manual mode
                    log.debug("heartbeat failed: %s", e)
            self.stop.wait(interval)

    # -- inputs --------------------------------------------------------------
    def start_gpio(self) -> None:
        try:
            from gpiozero import DigitalInputDevice  # type: ignore
        except ImportError:
            log.warning("gpiozero not installed; GPIO sensors disabled (use --simulate to test)")
            return
        for device_id, dev in self.devices.items():
            if "gpio_pin" not in dev:
                continue
            pin = DigitalInputDevice(dev["gpio_pin"], pull_up=dev.get("pull_up", False))
            event = dev.get("event", "ACTIVITY_DETECTED")
            pin.when_activated = lambda d=device_id, e=event: self.emit(d, e)
            if dev.get("idle_event"):
                pin.when_deactivated = lambda d=device_id, e=dev["idle_event"]: self.emit(d, e)
            log.info("GPIO %s -> %s", dev["gpio_pin"], device_id)

    def start_rfid_keyboard(self) -> None:
        """Most USB RFID/NFC readers act as a keyboard: they 'type' the card UID + Enter."""
        readers = [d for d in self.devices.values() if d.get("reader") == "keyboard"]
        if not readers:
            return
        dev = readers[0]

        def loop():
            for line in sys.stdin:
                uid = line.strip()
                if uid:
                    self.emit(dev["device_id"], "CARD_TAP", card_uid=uid)

        threading.Thread(target=loop, daemon=True).start()

    def simulate_loop(self) -> None:
        while not self.stop.is_set():
            dev = random.choice(list(self.devices.values()))
            if dev.get("type") == "RFID_READER":
                self.emit(dev["device_id"], "CARD_TAP", card_uid=dev.get("test_card_uid", "04A1B2C3"))
            elif dev.get("type") == "CAMERA":
                self.emit(dev["device_id"], "GAME_ACTIVITY", confidence=random.uniform(0.7, 0.99), payload={"people": 2})
            else:
                self.emit(dev["device_id"], dev.get("event", "ACTIVITY_DETECTED"))
            self.stop.wait(random.uniform(3, 12))

    def run(self) -> None:
        threading.Thread(target=self.sender_loop, daemon=True).start()
        threading.Thread(target=self.heartbeat_loop, daemon=True).start()
        if self.simulate:
            threading.Thread(target=self.simulate_loop, daemon=True).start()
        else:
            self.start_gpio()
            self.start_rfid_keyboard()
        log.info("gateway running with %d devices -> %s", len(self.devices), self.cfg["server_url"])
        try:
            while not self.stop.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop.set()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="gateway.json")
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.v else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with open(a.config) as f:
        cfg = json.load(f)
    Gateway(cfg, a.simulate).run()


if __name__ == "__main__":
    main()
