"""Unit tests: session state machine and detection fusion (spec §39, §52)."""
from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import InvalidState
from app.devices.providers.base import RawEvent, SignalKind
from app.devices.providers.builtin import CameraProvider, CardReaderProvider, PhysicalSensorProvider
from app.models.enums import SessionStatus
from app.schemas.settings import DetectionSettings
from app.services.detection_service import fuse
from app.services.session_service import assert_transition

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


def sig(source, conf, secs_ago):
    return {"source": source, "confidence": conf, "at": (NOW - timedelta(seconds=secs_ago)).isoformat()}


@pytest.mark.parametrize("frm,to", [
    (SessionStatus.CREATED, SessionStatus.ACTIVE), (SessionStatus.ACTIVE, SessionStatus.PAUSED), (SessionStatus.PAUSED, SessionStatus.ACTIVE),
    (SessionStatus.ACTIVE, SessionStatus.COMPLETED), (SessionStatus.PAUSED, SessionStatus.COMPLETED), (SessionStatus.ACTIVE, SessionStatus.AUTO_CLOSED),
])
def test_valid_transitions(frm, to):
    assert_transition(frm, to)


@pytest.mark.parametrize("frm,to", [
    (SessionStatus.CREATED, SessionStatus.COMPLETED), (SessionStatus.COMPLETED, SessionStatus.ACTIVE), (SessionStatus.CANCELLED, SessionStatus.ACTIVE),
    (SessionStatus.CREATED, SessionStatus.PAUSED), (SessionStatus.AUTO_CLOSED, SessionStatus.PAUSED),
])
def test_invalid_transitions(frm, to):
    with pytest.raises(InvalidState):
        assert_transition(frm, to)


def test_single_movement_never_confirms():
    cfg = DetectionSettings()
    r = fuse([sig("MOTION", 1.0, 0)], cfg, NOW, identified=False, booking_checked_in=False, first_activity_at=NOW, activity_events=1)
    assert not r.confirmed


def test_many_events_from_one_motion_sensor_cannot_reach_threshold():
    cfg = DetectionSettings()
    signals = [sig("MOTION", 1.0, s) for s in range(0, 120, 5)]
    r = fuse(signals, cfg, NOW, identified=False, booking_checked_in=False, first_activity_at=NOW - timedelta(seconds=120), activity_events=len(signals))
    assert r.score < cfg.confirmation_threshold and not r.confirmed


def test_hybrid_sustained_activity_confirms():
    cfg = DetectionSettings()
    signals = [sig("MOTION", 1.0, 90), sig("PRESSURE", 1.0, 60), sig("CAMERA", 0.94, 30), sig("MOTION", 1.0, 0)]
    r = fuse(signals, cfg, NOW, identified=False, booking_checked_in=False, first_activity_at=NOW - timedelta(seconds=90), activity_events=4)
    assert r.confirmed, r.reason
    assert r.score >= cfg.confirmation_threshold


def test_not_sustained_long_enough():
    cfg = DetectionSettings(min_activity_seconds=60)
    signals = [sig("CAMERA", 0.99, 10), sig("PRESSURE", 1.0, 5), sig("MOTION", 1.0, 0)]
    r = fuse(signals, cfg, NOW, identified=True, booking_checked_in=False, first_activity_at=NOW - timedelta(seconds=10), activity_events=3)
    assert not r.confirmed and "sustained" in r.reason


def test_require_identification():
    cfg = DetectionSettings(require_identification=True)
    signals = [sig("MOTION", 1.0, 90), sig("PRESSURE", 1.0, 60), sig("CAMERA", 0.95, 0)]
    kw = dict(first_activity_at=NOW - timedelta(seconds=90), activity_events=3)
    assert not fuse(signals, cfg, NOW, identified=False, booking_checked_in=False, **kw).confirmed
    assert fuse(signals, cfg, NOW, identified=True, booking_checked_in=False, **kw).confirmed


def test_low_confidence_camera_ignored():
    cfg = DetectionSettings(camera_confidence_threshold=0.85)
    signals = [sig("CAMERA", 0.6, 90), sig("CAMERA", 0.7, 0)]
    r = fuse(signals, cfg, NOW, identified=False, booking_checked_in=False, first_activity_at=NOW - timedelta(seconds=90), activity_events=2)
    assert "CAMERA" not in r.sources


def test_old_signals_outside_window_ignored():
    cfg = DetectionSettings(signal_window_seconds=60)
    r = fuse([sig("PRESSURE", 1.0, 600)], cfg, NOW, identified=False, booking_checked_in=False, first_activity_at=None, activity_events=1)
    assert r.sources == []


def test_providers_normalise_events():
    card = CardReaderProvider().interpret(RawEvent("CARD_TAP", NOW, card_uid=" ab12cd "), {})
    assert card.kind == SignalKind.INTENT and card.card_uid == "AB12CD"
    motion = PhysicalSensorProvider("MOTION_SENSOR").interpret(RawEvent("ACTIVITY_DETECTED", NOW), {})
    assert motion.kind == SignalKind.ACTIVITY and motion.source == "MOTION"
    noise = PhysicalSensorProvider("VIBRATION_SENSOR").interpret(RawEvent("VIBRATION", NOW, confidence=0.1), {"noise_floor": 0.3})
    assert noise.kind == SignalKind.IGNORE
    cam = CameraProvider().interpret(RawEvent("GAME_ACTIVITY", NOW, confidence=0.94, payload={"people": 2}), {})
    assert cam.kind == SignalKind.ACTIVITY and cam.confidence == 0.94
