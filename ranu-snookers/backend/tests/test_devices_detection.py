"""Integration tests: device API, hybrid detection, idempotency, anti-fraud, QR, tournaments."""
import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app.core.timeutil import utcnow
from app.models import Alert, GameSession
from tests.conftest import Api, advance, freeze_at, local_dt, table_id


def dev(client, seeded, device_id):
    return {"X-Device-Id": device_id, "X-Device-Key": seeded["device_keys"][device_id]}


def send(client, seeded, device_id, **event):
    r = client.post("/api/v1/devices/ingest/events", json=event, headers=dev(client, seeded, device_id))
    assert r.status_code == 200, r.text
    return r.json()["results"][0]


def test_single_motion_event_does_not_start_billing(client, seeded, db):
    freeze_at(local_dt(0, 19))
    out = send(client, seeded, "TABLE4_SENSOR", event_id="e1", event="ACTIVITY_DETECTED", timestamp=utcnow().isoformat(), table_id=4)
    assert out["outcome"] == "ACTIVITY_RECORDED"
    assert db.scalar(select(func.count(GameSession.id))) == 0


def test_duplicate_event_is_idempotent(client, seeded, db):
    freeze_at(local_dt(0, 19))
    a = send(client, seeded, "TABLE4_SENSOR", event_id="dup-1", event="MOTION", timestamp=utcnow().isoformat())
    b = send(client, seeded, "TABLE4_SENSOR", event_id="dup-1", event="MOTION", timestamp=utcnow().isoformat())
    assert a["outcome"] == "ACTIVITY_RECORDED" and b["outcome"] == "DUPLICATE"


def test_rfid_card_tap_starts_session_with_member(client, seeded, reception, db, branch_id):
    freeze_at(local_dt(0, 19))
    cust = reception.post("/customers", {"name": "Card Holder", "phone": "9876522222"}).json()
    plan = next(p for p in reception.get("/membership-plans").json() if p["code"] == "H30")
    reception.post("/memberships", {"branch_id": branch_id, "customer_id": cust["id"], "plan_id": plan["id"], "payment_method": "CASH", "card_uid": "04DEADBEEF"})
    out = send(client, seeded, "TABLE4_RFID", event_id="tap-1", event="CARD_TAP", card_uid="04deadbeef", timestamp=utcnow().isoformat())
    assert out["outcome"] == "SESSION_STARTED" and out["method"] == "RFID"
    s = db.scalar(select(GameSession).where(GameSession.status == "ACTIVE"))
    assert str(s.customer_id) == cust["id"] and s.membership_id is not None
    # second tap and sensor noise never create a second session
    out2 = send(client, seeded, "TABLE4_RFID", event_id="tap-2", event="CARD_TAP", card_uid="04DEADBEEF", timestamp=utcnow().isoformat())
    assert out2["outcome"] == "SESSION_ALREADY_ACTIVE"
    assert db.scalar(select(func.count(GameSession.id))) == 1


def test_unknown_card_raises_alert_not_session(client, seeded, db):
    freeze_at(local_dt(0, 19))
    out = send(client, seeded, "TABLE4_RFID", event_id="tap-x", event="CARD_TAP", card_uid="FFFF0000", timestamp=utcnow().isoformat())
    assert out["outcome"] == "AWAITING_STAFF_CONFIRMATION"
    assert db.scalar(select(Alert).where(Alert.alert_type == "UNKNOWN_CARD"))


def test_camera_plus_sensor_sustained_activity_auto_starts(client, seeded, admin, db, branch_id):
    freeze_at(local_dt(0, 19))
    t1 = table_id(db, 1)
    # add a pressure sensor to table 1 (camera already there)
    r = admin.post(f"/branches/{branch_id}/devices", {"device_id": "TABLE1_PRESSURE", "name": "T1 pressure", "device_type": "PRESSURE_SENSOR", "table_id": t1})
    key = r.json()["api_key"]
    hp = {"X-Device-Id": "TABLE1_PRESSURE", "X-Device-Key": key}
    send(client, seeded, "TABLE1_CAMERA", event_id="c1", event="GAME_ACTIVITY", confidence=0.94, timestamp=utcnow().isoformat())
    advance(0.5)
    client.post("/api/v1/devices/ingest/events", json={"event_id": "p1", "event": "PRESSURE", "timestamp": utcnow().isoformat()}, headers=hp)
    advance(0.6)
    out = send(client, seeded, "TABLE1_CAMERA", event_id="c2", event="GAME_ACTIVITY", confidence=0.95, timestamp=utcnow().isoformat())
    assert out["outcome"] == "SESSION_STARTED", out
    s = db.scalar(select(GameSession).where(GameSession.table_id == uuid.UUID(t1)))
    assert s.detection_method == "HYBRID" and s.confidence_score >= 0.8


def test_low_confidence_camera_alone_never_starts(client, seeded, db):
    freeze_at(local_dt(0, 19))
    for i in range(10):
        send(client, seeded, "TABLE1_CAMERA", event_id=f"lc{i}", event="GAME_ACTIVITY", confidence=0.5, timestamp=utcnow().isoformat())
        advance(0.3)
    assert db.scalar(select(func.count(GameSession.id))) == 0


def test_auto_start_disabled_creates_staff_alert(client, seeded, admin, db, branch_id):
    freeze_at(local_dt(0, 19))
    admin.patch(f"/branches/{branch_id}/settings", {"detection": {"auto_start_enabled": False, "min_activity_seconds": 0, "min_activity_events": 1,
                                                                  "confirmation_threshold": 0.5}})
    out = send(client, seeded, "TABLE1_CAMERA", event_id="c1", event="GAME_ACTIVITY", confidence=0.95, timestamp=utcnow().isoformat())
    assert out["outcome"] == "GAME_ACTIVITY_CONFIRMED_AWAITING_STAFF"
    assert db.scalar(select(Alert).where(Alert.alert_type == "GAME_ACTIVITY_CONFIRMED"))


def test_spoofed_device_key_rejected_and_alerted(client, db):
    r = client.post("/api/v1/devices/ingest/events", json={"event_id": "x", "event": "MOTION"}, headers={"X-Device-Id": "TABLE4_SENSOR", "X-Device-Key": "rdk_fake"})
    assert r.status_code == 401
    assert db.scalar(select(Alert).where(Alert.alert_type == "DEVICE_SPOOFING"))


def test_stale_and_future_events(client, seeded, db):
    freeze_at(local_dt(0, 19))
    old = send(client, seeded, "TABLE4_SENSOR", event_id="old", event="MOTION", timestamp=(utcnow() - timedelta(hours=2)).isoformat())
    assert old["outcome"] == "IGNORED_STALE"
    send(client, seeded, "TABLE4_SENSOR", event_id="fut", event="MOTION", timestamp=(utcnow() + timedelta(hours=1)).isoformat())
    assert db.scalar(select(Alert).where(Alert.alert_type == "DEVICE_CLOCK_SKEW"))


def test_heartbeat_and_offline_detection(client, seeded, reception, db, branch_id):
    freeze_at(local_dt(0, 19))
    r = client.post("/api/v1/devices/ingest/heartbeat", json={"firmware_version": "1.2.0", "queue_depth": 0}, headers=dev(client, seeded, "TABLE4_SENSOR"))
    assert r.json()["status"] == "ONLINE"
    advance(5)
    from app.services.device_service import mark_offline_devices

    assert mark_offline_devices(db) == 1
    devices = reception.get(f"/branches/{branch_id}/devices").json()
    assert next(d for d in devices if d["device_id"] == "TABLE4_SENSOR")["status"] == "OFFLINE"
    # hardware failure never blocks manual operation
    assert reception.post("/sessions/start", {"table_id": table_id(db, 4)}).status_code == 201


def test_gateway_batch_flush(client, seeded):
    freeze_at(local_dt(0, 19))
    now = utcnow()
    batch = {"events": [{"event_id": f"q{i}", "event": "MOTION", "timestamp": (now - timedelta(seconds=60 - i * 10)).isoformat()} for i in range(5)]}
    r = client.post("/api/v1/devices/ingest/events", json=batch, headers=dev(client, seeded, "TABLE4_SENSOR"))
    assert [x["outcome"] for x in r.json()["results"]] == ["ACTIVITY_RECORDED"] * 5


def test_qr_start_flow(client, public, reception, db, branch_id):
    freeze_at(local_dt(0, 19))
    tables = reception.get(f"/branches/{branch_id}/tables").json()
    t2 = next(t for t in tables if t["table_number"] == 2)
    info = public.get(f"/public/qr/{t2['qr_token']}").json()
    assert info["session_running"] is False
    out = public.post(f"/public/qr/{t2['qr_token']}/start", {"name": "QR Guest", "phone": "9876533333"}).json()
    assert out["outcome"] == "SESSION_STARTED" and out["method"] == "QR"
    assert public.get(f"/public/qr/{t2['qr_token']}").json()["session_running"] is True


def test_simulator_and_detection_state(admin, db, branch_id):
    freeze_at(local_dt(0, 19))
    r = admin.post("/devices/simulate", {"table_id": table_id(db, 3), "source": "MOTION", "confidence": 1})
    assert r.json()["outcome"] == "ACTIVITY_RECORDED"
    st = admin.get(f"/branches/{branch_id}/detection-state").json()
    assert any(t["table_number"] == 3 and t["state"] in ("ACTIVITY_DETECTED", "CONFIRMING") for t in st["tables"])


def test_inactivity_alert(client, seeded, db):
    freeze_at(local_dt(0, 19))
    from app.models import Device
    from app.services.device_service import heartbeat

    d = db.scalar(select(Device).where(Device.device_id == "TABLE4_SENSOR"))
    heartbeat(db, d, {}, None)
    Api(client)  # noqa
    from app.services import session_service

    session_service.start(db, None, d.table_id, method="SENSOR")
    advance(25)
    d.last_seen_at = utcnow()
    db.commit()
    from app.services.detection_service import monitor_sessions

    monitor_sessions(db)
    assert db.scalar(select(Alert).where(Alert.alert_type == "TABLE_INACTIVE"))


def test_knockout_tournament(admin, db, branch_id):
    gts = admin.get("/game-types").json()
    t = admin.post(f"/branches/{branch_id}/tournaments", {"game_type_id": gts[0]["id"], "name": "Monsoon Cup", "format": "KNOCKOUT", "entry_fee": "200"}).json()
    ids = [admin.post("/customers", {"name": f"P{i}", "phone": f"98000000{i:02d}"}).json()["id"] for i in range(5)]
    for i, cid in enumerate(ids):
        admin.post(f"/tournaments/{t['id']}/players", {"customer_id": cid, "seed": i + 1 if i < 2 else None})
    admin.post(f"/tournaments/{t['id']}/start")
    detail = admin.get(f"/tournaments/{t['id']}").json()
    assert len(detail["matches"]) == 7  # bracket of 8 -> 4 + 2 + 1
    while True:
        playable = [m for m in admin.get(f"/tournaments/{t['id']}").json()["matches"] if m["status"] == "SCHEDULED" and m["player1_id"] and m["player2_id"]]
        if not playable:
            break
        admin.post(f"/tournament-matches/{playable[0]['id']}/result", {"score1": 3, "score2": 1})
    final = admin.get(f"/tournaments/{t['id']}").json()
    assert final["tournament"]["status"] == "COMPLETED" and final["tournament"]["winner_player_id"]
