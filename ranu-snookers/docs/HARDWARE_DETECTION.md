# Automatic Game Detection — Options, Hardware & How It Works

> Goal: when a game actually starts on a table, billing should start automatically —
> **without ever billing someone because a person walked past the table.**
> Staff can always Start / Stop / Adjust manually, so hardware failure never stops the club.

This document gives you **six practical ways** to capture "a game has started", what each
costs, how to install it, and how the software combines them.

---

## 1. The options at a glance

| # | Method | What triggers it | Identifies the customer? | Approx. cost / table (INR) | Reliability | Best for |
|---|--------|------------------|--------------------------|----------------------------|-------------|----------|
| A | **RFID / NFC card or wristband** | Member taps card on reader at table | ✅ Yes (card → membership) | ₹800 – ₹1,500 (reader + ESP32) + ₹20–₹60 per card | ★★★★★ | Members, prepaid hours |
| B | **QR code on the table** | Customer scans QR → taps *Start game* on phone | ✅ Yes (phone number) | ₹0 (printed sticker) | ★★★★☆ | MVP, walk-ins, zero budget |
| C | **Physical sensors** (PIR motion, IR break-beam, pressure mat, vibration) | People/balls moving at the table | ❌ No | ₹300 – ₹900 per sensor + ₹400 ESP32 | ★★★☆☆ alone, ★★★★★ fused | Automatic, privacy-friendly |
| D | **Camera + edge computer vision** | People around the table + motion on the cloth | ❌ No (by design — no face ID) | ₹3,000 – ₹8,000 camera + shared mini-PC | ★★★★☆ | Large halls, dispute evidence |
| E | **Table controller / smart light relay** | Start button, or table light switched ON | Optional (with card) | ₹600 – ₹1,200 | ★★★★★ | *Enforcing* billing — no light without a session |
| F | **Hybrid (recommended long-term)** | A + C + D (+ B, manual) combined | ✅ when card/QR used | Mix | ★★★★★ | Accuracy + fraud resistance |

**Recommended roll-out (spec §51):**

1. **Now – MVP:** QR + manual start (already working, no hardware).
2. **Phase 2:** RFID/NFC member cards on busy tables (members start their own games; membership minutes deducted automatically).
3. **Phase 3:** One pressure mat or IR break-beam + PIR per table via an ESP32 or a Raspberry Pi gateway.
4. **Phase 4:** Overhead cameras with the edge-CV script for halls with 6+ tables.
5. **Long-term:** Hybrid engine tuned per club; optionally a light relay so tables cannot be played unbilled.

---

## 2. Option details

### A. RFID / NFC member card
*Hardware:* RC522 / PN532 reader (13.56 MHz, works with NFC phones too) wired to an ESP32, **or** a
USB "keyboard-emulation" reader plugged into the Raspberry Pi gateway (`reader: "keyboard"` in `gateway.json`).
*Flow:* card tap → `CARD_TAP {card_uid}` → server finds the membership by `card_uid` → starts the session
with that customer and membership → membership minutes are deducted in 30-minute blocks at the end.
*Unknown / expired card:* no session is started; an **UNKNOWN_CARD** alert appears on the dashboard.
*Link a card:* Admin → Memberships → *Link card* (tap the card on a USB reader with the field focused).

### B. QR code at the table
Every table has a secret `qr_token`. Admin → Tables → *Tables & QR* → **Print QR**. The code opens
`https://<your-domain>/t/<token>`; the customer enters name + mobile and taps **Start game**.
If *QR starts game* is switched off in Settings → Auto detection, the tap only alerts the counter
("start requested"). Tokens can be rotated any time if a photo of the QR is being misused.

### C. Physical sensors
| Sensor | Where to mount | Event sent | Notes |
|--------|----------------|------------|-------|
| PIR motion (HC-SR501) | Ceiling above table, narrow lens | `ACTIVITY_DETECTED` | Cheapest; noisy alone |
| IR break-beam | Across a pocket or ball-return | `BEAM_BREAK` | Fires only when balls are potted — strong signal |
| Pressure mat / FSR | Floor at the break end, or under cue rack | `PRESSURE` | Detects a player standing to play |
| Vibration (SW-420 / accelerometer) | Under the cushion rail | `VIBRATION` | Detects ball strikes; set `noise_floor` |
Wiring for an ESP32 node is in `hardware/esp32/ranu_table_sensor.ino`.

### D. Camera + computer vision (privacy by design)
Run `hardware/camera/edge_cv.py` on a mini-PC / Raspberry Pi 5 inside the club. It reads the RTSP
stream, analyses only the **table region**, computes an activity confidence (motion ratio + optional
person count with YOLOv8n) and sends **only numbers**:
```json
{"event": "GAME_ACTIVITY", "confidence": 0.94, "payload": {"people": 2}}
```
No frames are stored or uploaded. Put a visible CCTV notice in the hall. Confidence below
`camera_confidence_threshold` (default 0.85) is ignored.

### E. Table controller / light relay
A relay (SSR) in series with the table light, controlled by an ESP32: staff or the system switch it on
when a session starts. Pressing the table's **Start** button sends `START_REQUEST`; **Stop** raises a
"customer pressed stop" alert for the counter. This is the strongest *anti-leakage* option: no light → no play.

### F. Hybrid engine (how the software decides)
Implemented in `backend/app/services/detection_service.py`.

```
IDLE ──activity──▶ ACTIVITY_DETECTED ──more signals──▶ CONFIRMING ──confirmed──▶ GAME_STARTED ──▶ billing
```
A game is **confirmed** only when *all* of these are true (all values editable in Settings → Auto detection):

| Condition | Default |
|-----------|---------|
| Fused confidence ≥ `confirmation_threshold` | 0.80 |
| Activity sustained for ≥ `min_activity_seconds` | 60 s |
| At least `min_activity_events` activity signals | 3 |
| (optional) `require_identification`: card/QR/checked-in booking in last `identification_valid_seconds` | off |

**Fused confidence** combines *different* sources so one noisy sensor can never reach the threshold:

```
score = 1 − Π over sources ( 1 − weight_source × best_confidence_source )
```

| Source | Default weight |
|--------|---------------|
| QR confirm | 1.0 (explicit intent → starts immediately) |
| Camera | 0.8 × model confidence |
| RFID / NFC | 0.7 (explicit tap → starts immediately if card is valid) |
| Pressure / Vibration | 0.5 |
| IR break-beam | 0.45 |
| Checked-in booking at table | 0.4 |
| Motion (PIR) | 0.35 |

Examples: one PIR event → 0.35 → *not billed*. 50 PIR events in 2 minutes → still 0.35 → *not billed*.
PIR + pressure + camera 0.94 over 90 s → 0.92 → **game starts (method HYBRID, confidence 92%)**.

---

## 3. Reliability & anti-fraud built in

| Risk | Protection |
|------|-----------|
| Same event sent twice (retries) | `event_id` is unique per device → second copy returns `DUPLICATE` |
| Two receptionists + sensor start the same table | Row lock + UNIQUE `active_table_key` → exactly one session |
| Fake device posting events | Per-device API key (hashed); wrong key → 401 + **DEVICE_SPOOFING** alert |
| Device clock wrong / replaying old events | Events older than 15 min ignored (**STALE_DEVICE_EVENT**); future-dated → **DEVICE_CLOCK_SKEW** |
| Device claims another table | Server uses the table the device is registered to; mismatch → alert |
| Sensor/Wi-Fi offline | Heartbeats every 30 s; after 90 s → **DEVICE_OFFLINE** alert; staff use manual Start/Stop |
| Internet down at the club | Pi gateway stores events in a local SQLite queue and flushes in batches later |
| Game left running / table idle | **TABLE_INACTIVE** alert after 20 min without activity (optional auto-close at last activity) |
| Very long session | **EXCESSIVE_SESSION** alert after 6 h |
| Session started without customer | **SESSION_WITHOUT_CUSTOMER** info alert |
| Staff cancelling a running game | Needs `sessions.adjust`; audited + alert |

---

## 4. Installing the Raspberry Pi gateway
1. Admin → Devices → **Register** each sensor/reader, choose its table, copy the key (shown once).
2. On the Pi: `sudo apt install python3-gpiozero`; copy `hardware/gateway/` to `/opt/ranu`.
3. Copy `gateway.example.json` → `gateway.json`; fill `server_url`, device ids, keys, GPIO pins.
4. Test: `python3 ranu_gateway.py --config gateway.json --simulate` and watch Admin → Devices → Event log.
5. Run as a service (`systemd`), `Restart=always`. Keep the Pi on a UPS; sync time with NTP.

## 5. Commissioning & tuning
* Admin → Devices → **Detection** shows each table's live state, score and signals.
* Use the **Simulator** (same code path as real hardware) to rehearse: send MOTION → PRESSURE → CAMERA.
* Start conservative: `auto_start_enabled = false` for the first week — the system only raises
  "Game activity detected — start the session?" alerts. Compare with actual games, then enable.
* `hardware/simulator/simulate.py` scripts the scenarios `walk-by`, `game`, `card`, `duplicate`, `offline` against a live server.

## 6. Adding a new kind of hardware (developers)
Create a provider in `backend/app/devices/providers/builtin.py` that turns the raw event into a
`Signal(kind, source, confidence)`, register it in `provider_for()`, give the new `source` a weight in
`DetectionSettings.weights`. Nothing in bookings, sessions or billing changes. For MQTT, write a small
bridge that subscribes to topics and calls `device_service.ingest_events()` with the same payload.
