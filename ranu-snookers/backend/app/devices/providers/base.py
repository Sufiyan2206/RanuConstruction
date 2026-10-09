"""Pluggable detection providers.

A provider turns a raw device event into a normalised ``Signal``. The
TableActivityService (app.services.detection_service) fuses signals from all
providers — it never knows which hardware produced them. Adding new hardware
= adding a provider class and registering it for a DeviceType.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class SignalKind(StrEnum):
    IDENTIFY = "IDENTIFY"  # we know WHO is at the table (card, QR login)
    INTENT = "INTENT"  # explicit "start my game" (QR confirm, card tap, table button)
    ACTIVITY = "ACTIVITY"  # something is happening at the table (sensor/camera)
    IDLE = "IDLE"  # device reports no activity
    STOP_REQUEST = "STOP_REQUEST"
    IGNORE = "IGNORE"


@dataclass
class Signal:
    kind: SignalKind
    source: str  # RFID / NFC / QR / MOTION / PRESSURE / IR / VIBRATION / CAMERA / CONTROLLER / MANUAL
    confidence: float = 1.0  # provider-level confidence 0..1 (camera model score etc.)
    occurred_at: datetime | None = None
    card_uid: str | None = None
    customer_phone: str | None = None
    detail: dict = field(default_factory=dict)


@dataclass
class RawEvent:
    event: str
    occurred_at: datetime
    confidence: float | None = None
    card_uid: str | None = None
    payload: dict = field(default_factory=dict)


class DetectionProvider(Protocol):
    device_types: tuple[str, ...]

    def interpret(self, raw: RawEvent, device_config: dict) -> Signal: ...
