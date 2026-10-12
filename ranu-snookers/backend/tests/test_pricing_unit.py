"""Unit tests: pricing engine, rounding, membership coverage, deposits (pure functions)."""
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.schemas.settings import BillingSettings, BookingPolicy
from app.services.pricing import (
    PricingContext,
    RuleSpec,
    compute_session_charge,
    deposit_for,
    membership_cover,
    price_interval,
    rate_at,
    round_billable,
    tax_for,
)

IST = ZoneInfo("Asia/Kolkata")


def ctx(**kw):
    base = dict(tz="Asia/Kolkata", base_rate=Decimal("150"), off_peak_rate=Decimal("100"), peak_rate=Decimal("180"),
                rules=[RuleSpec(name="Happy Hour", kind="HAPPY_HOUR", start_time="14:00", end_time="18:00", rate_multiplier=0.667, priority=200)])
    base.update(kw)
    return PricingContext(**base)


def at(h, m=0, d=date(2026, 9, 23)):  # Wednesday
    return datetime(d.year, d.month, d.day, h, m, tzinfo=IST)


def test_one_hour_normal_rate():
    r = price_interval(ctx(), at(19), at(20))
    assert r.amount == Decimal("150.00")
    assert r.minutes == 60


def test_session_crossing_into_happy_hour_is_split_per_minute():
    # 13:30-14:30 => 30 min @150 + 30 min @100 (per-table off-peak rate)
    r = price_interval(ctx(), at(13, 30), at(14, 30))
    assert r.amount == Decimal("125.00")
    assert [s.rule for s in r.segments] == ["Standard", "Happy Hour"]


def test_window_crossing_midnight():
    c = ctx(rules=[RuleSpec(name="Late night", start_time="23:00", end_time="02:00", rate_per_hour=Decimal("120"))])
    assert rate_at(c, at(23, 30))[0] == Decimal("120")
    assert rate_at(c, at(1, 0))[0] == Decimal("120")
    assert rate_at(c, at(2, 0))[0] == Decimal("150")


def test_weekend_and_holiday_rules_and_priority():
    rules = [RuleSpec(name="Weekend", kind="WEEKEND", day_type="WEEKEND", rate_per_hour=Decimal("200"), priority=100),
             RuleSpec(name="Holiday", kind="HOLIDAY", day_type="HOLIDAY", rate_per_hour=Decimal("250"), priority=150)]
    c = ctx(rules=rules, holidays={date(2026, 9, 26)})
    assert rate_at(c, at(19, d=date(2026, 9, 23)))[0] == Decimal("150")  # Wed
    assert rate_at(c, at(19, d=date(2026, 9, 27)))[0] == Decimal("200")  # Sun
    assert rate_at(c, at(19, d=date(2026, 9, 26)))[1] == "Holiday"  # Sat + holiday: higher priority wins


def test_member_segment_rule():
    rules = [RuleSpec(name="Member price", customer_segment="MEMBER", rate_per_hour=Decimal("120"), priority=300)]
    assert rate_at(ctx(rules=rules), at(19))[0] == Decimal("150")
    assert rate_at(ctx(rules=rules, is_member=True), at(19))[0] == Decimal("120")


def test_table_specific_rule_beats_generic_same_priority():
    rules = [RuleSpec(name="Generic", rate_per_hour=Decimal("160")), RuleSpec(name="VIP table", table_id="T1", rate_per_hour=Decimal("300"))]
    assert rate_at(ctx(rules=rules, table_id="T1"), at(19))[1] == "VIP table"
    assert rate_at(ctx(rules=rules, table_id="T2"), at(19))[1] == "Generic"


def test_rounding_modes():
    cfg = BillingSettings(interval_minutes=15, rounding="UP", minimum_billable_minutes=15)
    assert round_billable(1, cfg) == 15
    assert round_billable(15, cfg) == 15
    assert round_billable(16, cfg) == 30
    assert round_billable(61, cfg) == 75
    assert round_billable(0, cfg) == 0
    assert round_billable(22, BillingSettings(interval_minutes=15, rounding="NEAREST", minimum_billable_minutes=0)) == 15
    assert round_billable(23, BillingSettings(interval_minutes=15, rounding="NEAREST", minimum_billable_minutes=0)) == 30
    assert round_billable(29, BillingSettings(interval_minutes=15, rounding="DOWN", minimum_billable_minutes=0)) == 15
    assert round_billable(3, BillingSettings(grace_minutes=5)) == 0


def test_automatic_billing_example_from_spec():
    # ₹500/h, game 18:00 → 19:00 = ₹500; at 18:30 = ₹250
    c = ctx(base_rate=Decimal("500"), rules=[])
    cfg = BillingSettings(interval_minutes=1, minimum_billable_minutes=0)
    assert compute_session_charge(c, [(at(18), at(18, 30))], cfg).time_amount == Decimal("250.00")
    assert compute_session_charge(c, [(at(18), at(19))], cfg).time_amount == Decimal("500.00")


def test_pauses_are_not_billed():
    cfg = BillingSettings(interval_minutes=1, minimum_billable_minutes=0)
    r = compute_session_charge(ctx(rules=[]), [(at(19), at(19, 20)), (at(19, 40), at(20))], cfg)
    assert r.billed_minutes == 40
    assert r.time_amount == Decimal("100.00")


def test_membership_cover_then_overage_billed():
    # legacy: 30-min membership blocks; 70 min played with 60 min balance => 60 covered, 10 min overage -> 15 min block billed
    assert membership_cover(70, remaining=60, block=30) == 60
    cfg = BillingSettings(interval_minutes=15, minimum_billable_minutes=15)
    r = compute_session_charge(ctx(rules=[]), [(at(19), at(20, 10))], cfg, membership_remaining=60, membership_block=30)
    assert r.covered_minutes == 60
    assert r.billed_minutes == 15
    assert r.time_amount == Decimal("37.50")


def test_membership_fully_covers():
    cfg = BillingSettings()
    r = compute_session_charge(ctx(rules=[]), [(at(19), at(19, 40))], cfg, membership_remaining=600, membership_block=30)
    assert r.covered_minutes == 60 and r.billed_minutes == 0 and r.time_amount == 0


def test_member_discount_percent():
    cfg = BillingSettings(interval_minutes=60, minimum_billable_minutes=0)
    r = compute_session_charge(ctx(rules=[]), [(at(19), at(20))], cfg, member_discount_percent=Decimal("20"))
    assert r.time_amount == Decimal("150.00") and r.member_discount == Decimal("30.00")


def test_deposit_rules():
    assert deposit_for(Decimal("500"), BookingPolicy(deposit_mode="FIXED", deposit_fixed_amount=Decimal("100"), deposit_minimum=Decimal("100"))) == Decimal("100.00")
    assert deposit_for(Decimal("50"), BookingPolicy(deposit_mode="FIXED", deposit_fixed_amount=Decimal("100"))) == Decimal("50.00")
    assert deposit_for(Decimal("1000"), BookingPolicy(deposit_mode="PERCENT", deposit_percent=Decimal("20"), deposit_minimum=Decimal("100"))) == Decimal("200.00")
    assert deposit_for(Decimal("300"), BookingPolicy(deposit_mode="PERCENT", deposit_percent=Decimal("20"), deposit_minimum=Decimal("100"))) == Decimal("100.00")


def test_tax_inclusive_and_exclusive():
    assert tax_for(Decimal("118"), BillingSettings(tax_percent=Decimal("18"), prices_include_tax=True)) == Decimal("18.00")
    assert tax_for(Decimal("100"), BillingSettings(tax_percent=Decimal("18"), prices_include_tax=False)) == Decimal("18.00")


def test_multi_day_session_segments():
    c = ctx(rules=[RuleSpec(name="Late", start_time="00:00", end_time="02:00", rate_per_hour=Decimal("90"))])
    r = price_interval(c, at(23), at(23) + timedelta(hours=2))
    assert r.amount == Decimal("240.00")  # 60 @150 + 60 @90
