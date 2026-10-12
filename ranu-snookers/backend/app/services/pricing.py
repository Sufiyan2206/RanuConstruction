"""Pricing & billing engine (pure functions — no I/O, fully unit-tested).

Everything the club charges for time is derived here, on the backend. The
frontend only displays numbers returned by the API.

Model
-----
* A table has a base ``hourly_rate`` (plus optional per-table peak/off-peak rates).
* ``PricingRule`` rows override the rate for matching minutes (time window,
  weekday/weekend/holiday, date range, member segment, game type, table).
* The session's billable timeline is priced minute by minute in the branch's
  local timezone, so a session crossing into happy hour / peak hour is charged
  correctly for each part (legacy behaviour of the RS Sales app).
* Rounding to the billing interval (1/5/10/15/30/60 min) happens *before*
  pricing; the rounded-up tail minutes are priced at the rate in effect then.
* Membership minutes are consumed first (in plan blocks, e.g. 30 min), only the
  overage is priced (legacy "membership hours" behaviour).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from app.core.timeutil import ensure_utc
from app.schemas.settings import BillingSettings, BookingPolicy

TWO = Decimal("0.01")


def q(v: Decimal | float | int) -> Decimal:
    return Decimal(str(v)).quantize(TWO, rounding=ROUND_HALF_UP)


@dataclass
class RuleSpec:
    """Plain copy of a PricingRule (decoupled from the ORM for pure testing)."""

    name: str
    kind: str = "STANDARD"
    table_id: object | None = None
    game_type_id: object | None = None
    day_type: str = "ANY"
    days_of_week: list[int] | None = None
    start_time: str | None = None
    end_time: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    customer_segment: str = "ANY"
    rate_per_hour: Decimal | None = None
    rate_multiplier: float | None = None
    priority: int = 100

    @classmethod
    def from_model(cls, r) -> RuleSpec:
        return cls(
            name=r.name, kind=r.kind, table_id=r.table_id, game_type_id=r.game_type_id, day_type=r.day_type,
            days_of_week=r.days_of_week, start_time=r.start_time, end_time=r.end_time, valid_from=r.valid_from,
            valid_to=r.valid_to, customer_segment=r.customer_segment,
            rate_per_hour=Decimal(str(r.rate_per_hour)) if r.rate_per_hour is not None else None,
            rate_multiplier=r.rate_multiplier, priority=r.priority,
        )


@dataclass
class PricingContext:
    tz: str
    base_rate: Decimal
    table_id: object = None
    game_type_id: object = None
    peak_rate: Decimal | None = None
    off_peak_rate: Decimal | None = None
    rules: list[RuleSpec] = field(default_factory=list)
    holidays: set[date] = field(default_factory=set)
    is_member: bool = False


@dataclass
class PriceSegment:
    start: datetime
    end: datetime
    minutes: int
    rate_per_hour: Decimal
    rule: str
    amount: Decimal


@dataclass
class PriceResult:
    minutes: int
    amount: Decimal
    segments: list[PriceSegment]


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _in_window(local: datetime, start: str | None, end: str | None) -> bool:
    if not start or not end:
        return True
    t = local.time()
    s, e = _parse_hhmm(start), _parse_hhmm(end)
    if s == e:
        return True
    if s < e:
        return s <= t < e
    return t >= s or t < e  # crosses midnight, e.g. 22:00-02:00


def _rule_matches(rule: RuleSpec, ctx: PricingContext, local: datetime) -> bool:
    if rule.table_id is not None and rule.table_id != ctx.table_id:
        return False
    if rule.game_type_id is not None and rule.game_type_id != ctx.game_type_id:
        return False
    if rule.customer_segment == "MEMBER" and not ctx.is_member:
        return False
    if rule.customer_segment == "NON_MEMBER" and ctx.is_member:
        return False
    d = local.date()
    if rule.valid_from and d < rule.valid_from:
        return False
    if rule.valid_to and d > rule.valid_to:
        return False
    weekday = local.weekday()
    is_holiday = d in ctx.holidays
    if rule.day_type == "WEEKDAY" and (weekday >= 5 or is_holiday):
        return False
    if rule.day_type == "WEEKEND" and weekday < 5:
        return False
    if rule.day_type == "HOLIDAY" and not is_holiday:
        return False
    if rule.days_of_week is not None and weekday not in rule.days_of_week:
        return False
    return _in_window(local, rule.start_time, rule.end_time)


def _specificity(rule: RuleSpec) -> int:
    return (2 if rule.table_id is not None else 0) + (1 if rule.game_type_id is not None else 0)


def rate_at(ctx: PricingContext, local: datetime) -> tuple[Decimal, str]:
    """Hourly rate in effect at a local minute, and the rule name that set it."""
    matching = [r for r in ctx.rules if _rule_matches(r, ctx, local)]
    if not matching:
        return ctx.base_rate, "Standard"
    rule = max(matching, key=lambda r: (r.priority, _specificity(r)))
    # Per-table peak / off-peak (happy hour) overrides, like the legacy per-table rates.
    if rule.kind == "PEAK" and ctx.peak_rate is not None:
        return ctx.peak_rate, rule.name
    if rule.kind in ("OFF_PEAK", "HAPPY_HOUR") and ctx.off_peak_rate is not None:
        return ctx.off_peak_rate, rule.name
    if rule.rate_per_hour is not None:
        return rule.rate_per_hour, rule.name
    return q(ctx.base_rate * Decimal(str(rule.rate_multiplier))), rule.name


def price_minutes(ctx: PricingContext, minute_starts: list[datetime]) -> PriceResult:
    """Price a list of billable minute start instants (UTC)."""
    tz = ZoneInfo(ctx.tz)
    segments: list[PriceSegment] = []
    total = Decimal("0")
    for m in minute_starts:
        local = ensure_utc(m).astimezone(tz)
        rate, rule = rate_at(ctx, local)
        seg = segments[-1] if segments else None
        if seg and seg.rate_per_hour == rate and seg.rule == rule and seg.end == m:
            seg.end = m + timedelta(minutes=1)
            seg.minutes += 1
        else:
            segments.append(PriceSegment(m, m + timedelta(minutes=1), 1, rate, rule, Decimal("0")))
    for seg in segments:
        seg.amount = q(seg.rate_per_hour * seg.minutes / Decimal(60))
        total += seg.amount
    return PriceResult(minutes=len(minute_starts), amount=q(total), segments=segments)


def price_interval(ctx: PricingContext, start: datetime, end: datetime) -> PriceResult:
    start = ensure_utc(start).replace(second=0, microsecond=0)
    n = max(0, int((ensure_utc(end) - start).total_seconds() // 60))
    return price_minutes(ctx, [start + timedelta(minutes=i) for i in range(n)])


# --------------------------------------------------------------------------- rounding
def round_billable(actual_minutes: float, cfg: BillingSettings) -> int:
    """Apply grace, interval rounding and minimum charge."""
    if actual_minutes <= cfg.grace_minutes:
        return 0
    step = cfg.interval_minutes
    x = actual_minutes / step
    if cfg.rounding == "UP":
        blocks = math.ceil(x - 1e-9)
    elif cfg.rounding == "DOWN":
        blocks = math.floor(x + 1e-9)
    else:
        blocks = int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return max(blocks * step, cfg.minimum_billable_minutes)


def membership_cover(actual_minutes: float, remaining: int, block: int, daily_left: int | None = None) -> int:
    """Minutes deducted from a membership balance for a session (legacy: 30-minute blocks)."""
    if remaining <= 0 or actual_minutes <= 0:
        return 0
    needed = math.ceil(actual_minutes / block - 1e-9) * block if block > 0 else math.ceil(actual_minutes)
    cover = min(needed, remaining)
    if daily_left is not None:
        cover = min(cover, max(0, daily_left))
    return int(cover)


# --------------------------------------------------------------------------- session timeline
def active_minute_starts(intervals: list[tuple[datetime, datetime]]) -> list[datetime]:
    out: list[datetime] = []
    for s, e in intervals:
        s = ensure_utc(s)
        e = ensure_utc(e)
        n = int((e - s).total_seconds() // 60)
        out.extend(s + timedelta(minutes=i) for i in range(n))
        # a trailing partial minute counts as a started minute
        if (e - s).total_seconds() - n * 60 > 0:
            out.append(s + timedelta(minutes=n))
    return out


def fit_timeline(minutes: list[datetime], target: int, fallback_start: datetime) -> list[datetime]:
    """Trim or extend a minute timeline to exactly `target` minutes (extensions
    continue after the last active minute)."""
    if target <= len(minutes):
        return minutes[:target]
    last = minutes[-1] + timedelta(minutes=1) if minutes else ensure_utc(fallback_start)
    extra = target - len(minutes)
    return minutes + [last + timedelta(minutes=i) for i in range(extra)]


@dataclass
class SessionCharge:
    actual_seconds: int
    actual_minutes: float
    covered_minutes: int
    billed_minutes: int
    time_amount: Decimal
    segments: list[PriceSegment]
    member_discount: Decimal


def compute_session_charge(
    ctx: PricingContext,
    intervals: list[tuple[datetime, datetime]],
    cfg: BillingSettings,
    *,
    membership_remaining: int = 0,
    membership_block: int = 30,
    membership_daily_left: int | None = None,
    member_discount_percent: Decimal = Decimal("0"),
) -> SessionCharge:
    actual_seconds = int(sum((ensure_utc(e) - ensure_utc(s)).total_seconds() for s, e in intervals))
    actual_minutes = actual_seconds / 60
    timeline = active_minute_starts(intervals)
    start = intervals[0][0] if intervals else datetime.now()

    covered = membership_cover(actual_minutes, membership_remaining, membership_block, membership_daily_left)
    overage = max(0.0, actual_minutes - covered)
    billed = round_billable(overage, cfg) if overage > 0 else 0

    full = fit_timeline(timeline, covered + billed, start)
    paid_minutes = full[covered: covered + billed]
    priced = price_minutes(ctx, paid_minutes)
    discount = q(priced.amount * member_discount_percent / Decimal(100)) if member_discount_percent else Decimal("0.00")
    return SessionCharge(
        actual_seconds=actual_seconds, actual_minutes=round(actual_minutes, 2), covered_minutes=covered, billed_minutes=billed,
        time_amount=priced.amount, segments=priced.segments, member_discount=discount,
    )


# --------------------------------------------------------------------------- deposit / tax
def deposit_for(amount: Decimal, policy: BookingPolicy) -> Decimal:
    amount = q(amount)
    if amount <= 0:
        return Decimal("0.00")
    if policy.deposit_mode == "PERCENT":
        dep = max(q(amount * policy.deposit_percent / Decimal(100)), q(policy.deposit_minimum))
    else:
        dep = max(q(policy.deposit_fixed_amount), q(policy.deposit_minimum))
    return min(dep, amount)


def tax_for(amount: Decimal, cfg: BillingSettings) -> Decimal:
    """Tax portion. If prices include tax, returns the included component."""
    if not cfg.tax_percent:
        return Decimal("0.00")
    t = Decimal(str(cfg.tax_percent)) / Decimal(100)
    if cfg.prices_include_tax:
        return q(amount - amount / (1 + t))
    return q(amount * t)
