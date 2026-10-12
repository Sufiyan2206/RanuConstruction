"""Typed, validated branch configuration (stored as JSON on branches.settings).

Nothing here is hard-coded business data: every value is a default that the
club admin can change from Settings in the admin app.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class BillingSettings(BaseModel):
    interval_minutes: Literal[1, 5, 10, 15, 30, 60] = 15  # legacy app billed in 15-minute blocks
    rounding: Literal["UP", "NEAREST", "DOWN"] = "UP"
    minimum_billable_minutes: int = Field(15, ge=0)
    grace_minutes: int = Field(0, ge=0, le=15)  # free minutes before the first block is charged
    tax_percent: Decimal = Field(Decimal("0"), ge=0, le=50)
    tax_label: str = "GST"
    prices_include_tax: bool = True
    staff_discount_limit_percent: Decimal = Field(Decimal("0"), ge=0, le=100)  # above this -> approval


class BookingPolicy(BaseModel):
    slot_step_minutes: int = Field(30, ge=5, le=120)
    hold_minutes: int = Field(10, ge=2, le=60)
    min_advance_minutes: int = Field(30, ge=0)
    max_advance_days: int = Field(30, ge=1, le=365)
    buffer_minutes: int = Field(0, ge=0, le=60)  # cleaning gap between bookings
    deposit_mode: Literal["FIXED", "PERCENT"] = "FIXED"
    deposit_fixed_amount: Decimal = Field(Decimal("100"), ge=0)
    deposit_percent: Decimal = Field(Decimal("20"), ge=0, le=100)
    deposit_minimum: Decimal = Field(Decimal("100"), ge=0)
    free_cancellation_hours: int = Field(4, ge=0)  # cancel before this => deposit refunded
    late_cancellation_refund_percent: Decimal = Field(Decimal("0"), ge=0, le=100)
    no_show_grace_minutes: int = Field(15, ge=0, le=120)
    reserve_lead_minutes: int = Field(30, ge=0, le=240)  # table shows RESERVED this long before start
    allow_early_start_minutes: int = Field(15, ge=0, le=120)
    allow_reschedule_hours: int = Field(2, ge=0)


class DetectionSettings(BaseModel):
    """Hybrid detection engine tuning. See docs/HARDWARE_DETECTION.md."""

    auto_start_enabled: bool = True
    confirmation_threshold: float = Field(0.8, ge=0.1, le=1.0)
    min_activity_seconds: int = Field(60, ge=0, le=900)  # sustained activity before confirming
    min_activity_events: int = Field(3, ge=1, le=100)
    signal_window_seconds: int = Field(180, ge=10, le=1800)
    identification_valid_seconds: int = Field(600, ge=30, le=7200)
    require_identification: bool = False  # true => sensor/camera alone never start billing
    camera_confidence_threshold: float = Field(0.85, ge=0.1, le=1.0)
    rfid_starts_session: bool = True  # card tap = explicit intent to start
    qr_starts_session: bool = True
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "RFID": 0.7, "NFC": 0.7, "QR": 1.0, "MOTION": 0.35, "PRESSURE": 0.5, "IR": 0.45,
            "VIBRATION": 0.5, "CAMERA": 0.8, "BOOKING_CHECKIN": 0.4,
        }
    )
    inactivity_alert_minutes: int = Field(20, ge=5, le=240)
    auto_close_on_inactivity: bool = False
    max_session_hours_alert: int = Field(6, ge=1, le=48)
    reject_events_older_than_seconds: int = Field(900, ge=30)
    clock_skew_tolerance_seconds: int = Field(120, ge=5)


class LoyaltySettings(BaseModel):
    enabled: bool = True
    spend_per_point: Decimal = Field(Decimal("100"), gt=0)  # ₹100 spent = 1 point
    point_value: Decimal = Field(Decimal("1"), ge=0)  # 1 point = ₹1 on redemption
    referral_bonus_points: int = Field(50, ge=0)
    min_redeem_points: int = Field(50, ge=0)


class NotificationSettings(BaseModel):
    booking_reminder_minutes: int = Field(60, ge=5)
    session_ending_reminder_minutes: int = Field(10, ge=1)
    membership_expiry_days: int = Field(7, ge=1)
    channels: list[Literal["EMAIL", "SMS", "WHATSAPP", "PUSH"]] = Field(default_factory=lambda: ["WHATSAPP", "EMAIL"])


class BranchSettings(BaseModel):
    billing: BillingSettings = Field(default_factory=BillingSettings)
    booking: BookingPolicy = Field(default_factory=BookingPolicy)
    detection: DetectionSettings = Field(default_factory=DetectionSettings)
    loyalty: LoyaltySettings = Field(default_factory=LoyaltySettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)

    @classmethod
    def load(cls, raw: dict | None) -> BranchSettings:
        return cls.model_validate(raw or {})
