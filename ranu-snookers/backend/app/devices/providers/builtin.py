"""Built-in providers for the hardware options described in docs/HARDWARE_DETECTION.md:

  Option A  RFID / NFC card or wristband tap  -> CardReaderProvider
  Option B  QR code at the table              -> handled by QR endpoint (QrSignal helper)
  Option C  IR / pressure / motion / vibration / break-beam sensors -> PhysicalSensorProvider
  Option D  Camera + edge computer vision     -> CameraProvider
  Option E  Hybrid                            -> fusion in TableActivityService
  Extra     Table controller (start button / smart light relay) -> TableControllerProvider
"""
from __future__ import annotations

from app.devices.providers.base import RawEvent, Signal, SignalKind

ACTIVITY_EVENTS = {"ACTIVITY_DETECTED", "MOTION", "MOTION_DETECTED", "PRESSURE", "OCCUPIED", "BEAM_BREAK", "VIBRATION", "BALL_STRIKE", "CUE_STRIKE"}
IDLE_EVENTS = {"NO_ACTIVITY", "IDLE", "VACANT", "CLEAR"}


class CardReaderProvider:
    device_types = ("RFID_READER", "NFC_READER")

    def interpret(self, raw: RawEvent, cfg: dict) -> Signal:
        src = "NFC" if raw.payload.get("reader") == "NFC" or cfg.get("kind") == "NFC" else "RFID"
        if raw.event in ("CARD_TAP", "CARD_DETECTED", "TAG_READ") and raw.card_uid:
            return Signal(SignalKind.INTENT, src, 1.0, raw.occurred_at, card_uid=raw.card_uid.strip().upper())
        if raw.event in ("CARD_REMOVED",):
            return Signal(SignalKind.IDLE, src, 1.0, raw.occurred_at)
        return Signal(SignalKind.IGNORE, src, 0.0, raw.occurred_at, detail={"reason": f"unknown card event {raw.event}"})


class PhysicalSensorProvider:
    device_types = ("MOTION_SENSOR", "PRESSURE_SENSOR", "IR_SENSOR", "VIBRATION_SENSOR")
    _source = {"MOTION_SENSOR": "MOTION", "PRESSURE_SENSOR": "PRESSURE", "IR_SENSOR": "IR", "VIBRATION_SENSOR": "VIBRATION"}

    def __init__(self, device_type: str = "MOTION_SENSOR") -> None:
        self.device_type = device_type

    def interpret(self, raw: RawEvent, cfg: dict) -> Signal:
        src = self._source.get(self.device_type, "MOTION")
        if raw.event in ACTIVITY_EVENTS:
            # Analog sensors may send an intensity 0..1; below the device's noise floor => ignore
            level = raw.confidence if raw.confidence is not None else 1.0
            if level < float(cfg.get("noise_floor", 0.0)):
                return Signal(SignalKind.IGNORE, src, level, raw.occurred_at, detail={"reason": "below noise floor"})
            return Signal(SignalKind.ACTIVITY, src, level, raw.occurred_at)
        if raw.event in IDLE_EVENTS:
            return Signal(SignalKind.IDLE, src, 1.0, raw.occurred_at)
        return Signal(SignalKind.IGNORE, src, 0.0, raw.occurred_at, detail={"reason": f"unknown sensor event {raw.event}"})


class CameraProvider:
    """Consumes METADATA from an edge CV service (no video leaves the club):
    {"event": "GAME_ACTIVITY", "confidence": 0.94, "people": 2}."""

    device_types = ("CAMERA",)

    def interpret(self, raw: RawEvent, cfg: dict) -> Signal:
        conf = float(raw.confidence or 0.0)
        if raw.event in ("GAME_ACTIVITY", "PEOPLE_DETECTED", "CUE_ACTIVITY", "TABLE_OCCUPIED", "ACTIVITY_DETECTED"):
            threshold = float(cfg.get("confidence_threshold", 0))  # per-camera override; branch threshold applied by the engine
            if conf < threshold:
                return Signal(SignalKind.IGNORE, "CAMERA", conf, raw.occurred_at, detail={"reason": "below camera threshold"})
            return Signal(SignalKind.ACTIVITY, "CAMERA", conf, raw.occurred_at, detail={"people": raw.payload.get("people")})
        if raw.event in IDLE_EVENTS or raw.event == "TABLE_EMPTY":
            return Signal(SignalKind.IDLE, "CAMERA", conf or 1.0, raw.occurred_at)
        return Signal(SignalKind.IGNORE, "CAMERA", conf, raw.occurred_at, detail={"reason": f"unknown camera event {raw.event}"})


class TableControllerProvider:
    """A physical 'Start' button / smart-light controller mounted at the table."""

    device_types = ("TABLE_CONTROLLER", "CUSTOM")

    def interpret(self, raw: RawEvent, cfg: dict) -> Signal:
        if raw.event in ("START_REQUEST", "BUTTON_START", "LIGHT_ON"):
            return Signal(SignalKind.INTENT, "CONTROLLER", 1.0, raw.occurred_at, card_uid=raw.card_uid)
        if raw.event in ("STOP_REQUEST", "BUTTON_STOP", "LIGHT_OFF"):
            return Signal(SignalKind.STOP_REQUEST, "CONTROLLER", 1.0, raw.occurred_at)
        if raw.event in ACTIVITY_EVENTS:
            return Signal(SignalKind.ACTIVITY, "CONTROLLER", raw.confidence or 1.0, raw.occurred_at)
        return Signal(SignalKind.IGNORE, "CONTROLLER", 0.0, raw.occurred_at)


def provider_for(device_type: str):
    if device_type in CardReaderProvider.device_types:
        return CardReaderProvider()
    if device_type in PhysicalSensorProvider.device_types:
        return PhysicalSensorProvider(device_type)
    if device_type in CameraProvider.device_types:
        return CameraProvider()
    return TableControllerProvider()
