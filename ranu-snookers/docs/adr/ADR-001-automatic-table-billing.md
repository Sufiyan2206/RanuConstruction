# ADR-001: Automatic start/stop of table billing on a minimum budget

**Status:** Proposed
**Date:** 2026-10-06
**Deciders:** Club owner (Kms), floor manager, the electrician doing the install

## Context

RANU has 14 tables (snooker, pool, billiards, 2 × PS5) and today staff start and stop every game by hand
at the counter. That causes two problems:

1. **Revenue leakage** — a game that is started late, stopped early, or never started is lost money.
2. **Counter load** — at peak time the receptionist is the bottleneck for every start/stop.

We want billing to **start when a game starts, stop when it ends, and be calculated automatically**, with
the cheapest hardware that is still reliable, and without ever charging someone because they walked past a table.

What the software already has (no new work needed):

| Capability | Where |
|---|---|
| Device API with per-device keys, de-duplication, stale/clock-skew checks | `backend/app/api/v1/devices.py`, `device_service` |
| Table **controller** device type: `START_REQUEST` starts a session instantly; `STOP_REQUEST` raises a counter alert | `devices/providers/builtin.py` → `TableControllerProvider` |
| Sensor fusion (PIR / pressure / IR / vibration / camera) that only starts billing on sustained, multi-source activity | `services/detection_service.py` |
| Inactivity alert after 20 min with no activity; optional auto-close at the last activity time | `detection_service.monitor_sessions` |
| Server-side timing and rounding: 15-min blocks, rounded UP, 15-min minimum, optional grace | `BillingSettings` |
| Raspberry Pi gateway with offline queue, ESP32 sensor sketch, simulator | `hardware/` |

What is **missing**: the server cannot *send* anything to a device. Devices can only push events, so there is
no way yet to switch a table light on or off from a session.

**Constraints:** minimum budget; staff are not technical; the club runs on Wi-Fi with the server on the counter
PC; mains wiring (230 V lamps) must be done by a licensed electrician; staff must always be able to override.

## Decision

Fit each table with a **light-interlock table controller**:

- an ESP32 board
- a relay that switches the table lamp
- a **START** and a **STOP** push-button
- an optional PIR motion sensor for idle detection

The table lamp only turns on when a billing session is running. Because cue sports can't be played in the dark,
**no session means no light, which means no unbilled game**. QR codes and member cards stay available as extra
ways to start; manual Start/Stop at the counter always works.

### How it works

```
 Customer holds START 2 s ──▶ ESP32 ──event──▶ Server creates session (server time = billing start)
                                                     │
 ESP32 polls desired state every 2 s ◀──── "light: ON" ┘ ──▶ relay closes ──▶ lamp ON

 During play:  PIR motion ──▶ keeps last_activity fresh;  live bill visible on staff board
               10 min before planned end ──▶ lamp blinks twice (optional)

 Customer holds STOP 2 s ──▶ session stops at press time ──▶ bill generated ──▶ "light: OFF" after 60 s grace
 or staff taps Stop/Collect in the app ──────────────────────▶ same
 or no motion for 20 min ──▶ alert to counter (optionally auto-close at last activity)
```

- **Start:**
  - Triggers: a 2-second press of START, a staff tap in the app, a QR scan, or a member-card tap.
  - The start time is the **server's** clock, never the device's, so a wrong device clock can't affect the bill.
- **Calculate:**
  - Uses the existing pricing engine: per-table rate, happy-hour/weekend rules, 15-minute blocks rounded up, 15-minute minimum.
  - Pauses are excluded automatically.
- **Stop:**
  - Triggers: STOP at the table, staff in the app, or idle auto-close (if enabled).
  - The bill is created at stop time and payment is collected at the counter as today.
- **Long press (2 s)** on both buttons prevents accidental presses. Re-pressing START on a running table does nothing.

## Options Considered

### Option A: Manual start/stop at the counter (today)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low |
| Cost | ₹0 |
| Scalability | Poor — receptionist is the bottleneck |
| Team familiarity | High |

**Pros:** No hardware; already working.
**Cons:** Leakage depends entirely on staff discipline; busy counter at peak; disputes over start times.

### Option B: QR code self-start only
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low |
| Cost | ~₹20 per table (printed sticker) |
| Scalability | Good |
| Team familiarity | Medium |

**Pros:** Already built; identifies the customer by phone number.
**Cons:** Honour system — nothing stops a group from playing without scanning; needs a smartphone and data.

### Option C: Fully automatic sensor detection (PIR + vibration/pressure, no light control)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium (tuning per table) |
| Cost | ~₹1,000–1,500 per table |
| Scalability | Good |
| Team familiarity | Low |

**Pros:** Truly hands-free; fusion engine already built.
**Cons:**
- It's an *inference*, so it will occasionally start late or miss a start, and it can't tell practice from a paid game.
- Stop detection is slow: it waits for 20 minutes of no motion.
- It still doesn't *prevent* unbilled play.

### Option D: Light-interlock table controller — **chosen**
| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium (one firmware, one small API addition, electrician install) |
| Cost | ~₹1,500–2,400 per table (see bill of materials) |
| Scalability | Good — same box on every table; works for PS5 by switching the TV socket |
| Team familiarity | High for customers (press a button); low for staff (nothing new) |

**Pros:**
- Self-enforcing: you cannot play without starting the clock.
- The start/stop time is exact, as the press time on the server.
- Reuses the existing controller device type.
- Works with or without the internet as long as the counter PC is on the same Wi-Fi.

**Cons:**
- Customers must press a button; this is deliberate, because intent beats inference.
- Needs mains wiring per table.
- Needs a small new "desired state" endpoint and new firmware.
- A dead controller or server needs a manual override.

### Option E: Overhead cameras + edge computer vision
| Dimension | Assessment |
|-----------|------------|
| Complexity | High |
| Cost | ~₹4,000–8,000 per table + ₹15,000–30,000 mini-PC |
| Scalability | Good for large halls |
| Team familiarity | Low |

**Pros:** No customer action; gives video evidence in disputes.
**Cons:**
- 3–5× the cost.
- Privacy notices are needed.
- Lighting, angle and occlusion tuning.
- Still an inference; still can't enforce billing.

## Trade-off Analysis

- **Inference versus enforcement.**
  - Options C and E try to *guess* when a game happens, then bill. Guessing is never perfect, and it does nothing about a group that simply plays.
  - Option D flips the problem: the lamp *is* the game, so the bill and the light can't disagree.
  - Interlocks like this are common for coin-op and timed-light tables because they remove the need for trust.
- **Hands-free versus a button press.** One 2-second press is a small cost for an exact start time and zero false starts.
- **Cost.**
  - D costs about the same per table as C, but removes C's main failure mode (unbilled play) and its slow, idle-based stop.
  - Fitting all 14 tables with D costs less than E on 4 tables.
- **Push versus poll for light commands.**
  - MQTT (Mosquitto broker) would switch lights instantly, but it is another service to install and keep alive.
  - Polling a tiny HTTP endpoint every 2 s from 14 boards on the club LAN is about 7 requests/second, which the existing server handles easily, with no new infrastructure.
  - The ~2 s delay before the lamp turns on is acceptable.
  - Revisit if the server moves to the cloud.

## Bill of materials (per table, Indian retail estimates, Oct 2026 — verify locally)

| Item | Purpose | Approx. ₹ |
|---|---|---|
| ESP32 DevKit (WROOM-32) | Wi-Fi controller | 350–450 |
| Solid-state relay 25 A (zero-cross) + heatsink, *or* 10 A relay module | Switches the 230 V table lamp | 250–450 |
| 2 × illuminated push-buttons (green START, red STOP), 19–22 mm | Customer intent; LED shows state | 150–300 |
| PIR sensor HC-SR501 (optional) | Activity / idle detection | 80–120 |
| 5 V 1–2 A power module (e.g. HLK-5M05) or adapter | Powers the ESP32 | 150–250 |
| ABS enclosure, terminal blocks, wire, fuse | Safe mounting near the lamp | 200–350 |
| Electrician labour | Mains wiring, MCB, testing | 300–600 |
| **Per table** | | **≈ 1,500–2,400** |

**Club-wide extras:**
- 2 spare controllers: about ₹3,000–4,500.
- A UPS for the counter PC and Wi-Fi router: about ₹3,000–5,000.
- A better 2.4 GHz access point, if coverage at the far tables is weak: about ₹1,500–2,500.
- *Optional:* an RC522 RFID reader per table: about ₹200–300.

**All 14 tables:** roughly **₹28,000–45,000** including spares and UPS.

**Safety:** all 230 V work must be inside a closed enclosure, behind an MCB, done by a licensed electrician.
The ESP32 side is 5 V/3.3 V only.

## Failure handling

| Failure | Behaviour |
|---|---|
| ESP32 reboots / power blip | Restores the last light state from flash (NVS) immediately on boot, then confirms with the server — the lamp does not drop mid-game |
| Wi-Fi or server down | Relay keeps its current state; the button LED blinks to show "offline"; the counter uses the existing manual Start/Stop |
| Controller dead | **Override key-switch** per table bypasses the relay. The switch is wired to an ESP32 input, so turning it on raises an `OVERRIDE_ON` alert ("Table lit without a session") — overrides are visible, not silent |
| Accidental STOP | 2-second press + 60 s grace before the lamp goes off; staff can resume the session in the app (audited) |
| Someone leaves the light on and goes | No motion for 20 min → `TABLE_INACTIVE` alert; with `auto_close_on_inactivity` the bill ends at the **last activity**, not at the alert |
| Duplicate / replayed / forged events | Already handled: event de-dup, 15-min stale window, per-device keys, spoofing alerts |

## Consequences

**Easier:**
- Billing becomes exact, and unbilled play is physically blocked.
- The counter no longer has to start or stop games.
- Disputes are settled by press times in the audit log.

**Harder:**
- Every table now has electronics that need power, Wi-Fi coverage and spares.
- The counter PC must stay on during opening hours. Moving the server to the cloud or to a Raspberry Pi later would remove that single point of failure.

**Revisit:**
- Switch to MQTT push if the server moves to the cloud or light latency annoys customers.
- Add RFID for members once membership volume justifies about ₹250 more per table.
- Add cameras only if disputes or hall size demand it.

## Action Items

1. [ ] **API:** add `GET /api/v1/devices/ingest/state` (device-key auth). It returns `{light, blink, session_id, started_at}` for the device's table: light ON while the session is ACTIVE or PAUSED, plus the 60 s grace after a stop.
2. [ ] **Setting:** add `DetectionSettings.controller_stop_ends_session` (default `true`). A controller STOP should then end the session at the press time and generate the bill, instead of only raising `STOP_REQUESTED`.
3. [ ] **Firmware:** add `hardware/esp32/ranu_table_controller.ino`. It covers:
   - 2 s long-press for START and STOP;
   - relay control and the button LED states;
   - PIR activity events;
   - a 2 s state poll and the 30 s heartbeat;
   - NVS restore of the light state at boot;
   - the override-switch input.
4. [ ] **Events:** add an `OVERRIDE_ON` / `OVERRIDE_OFF` event and alert. Add an optional blink warning 10 minutes before the planned end.
5. [ ] **Simulator:** extend `hardware/simulator/simulate.py` with a `controller` scenario (start → activity → stop → light off).
6. [ ] **Pilot:** buy parts for 3 controllers and fit 2 tables.
   - Run one week with `auto_close_on_inactivity = false`.
   - Compare the session log with staff notes.
   - Tune the PIR and grace times.
7. [ ] **Roll out:** fit the remaining 12 tables, including the PS5 TV sockets.
   - Put a "Hold START for 2 s" sticker on each table.
   - Brief staff on the override key and the alerts.
8. [ ] **Infrastructure:** put the counter PC and router on a UPS, and check Wi-Fi signal strength at the farthest table (aim for better than −70 dBm).
