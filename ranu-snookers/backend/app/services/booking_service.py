"""Online & staff bookings: availability engine, conflict prevention, checkout
holds, deposits, cancellation/reschedule policy, check-in and no-shows.

Concurrency strategy (works on PostgreSQL, MySQL/InnoDB and SQLite)
-------------------------------------------------------------------
Every write that can create an overlap runs in ONE transaction that first
locks the target ``tables`` row with SELECT ... FOR UPDATE. Two customers
racing for Table 1 at 18:00 are therefore serialised: the second one sees the
first one's HELD booking and receives ``409 BOOKING_CONFLICT``. On PostgreSQL an
exclusion constraint (migration 0002) additionally guarantees it at the
storage level.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import for_update
from app.core.deps import Principal
from app.core.errors import AppError, Conflict, Forbidden, InvalidState, NotFound, ValidationFailed
from app.core.realtime import PendingEvents
from app.core.timeutil import ensure_utc, utcnow
from app.models import Booking, BookingHold, Branch, Customer, GameSession, Membership, Payment, Table
from app.models.base import money
from app.models.enums import (
    BLOCKING_BOOKING_STATUSES,
    OPEN_SESSION_STATUSES,
    BookingSource,
    BookingStatus,
    MembershipStatus,
    PaymentMethod,
    PaymentPurpose,
    PaymentStatus,
    TableStatus,
)
from app.services import customer_service, table_service
from app.services.audit import audit, raise_alert, snapshot
from app.services.common import branch_settings, ensure_branch_access, get_branch, random_code
from app.services.pricing import deposit_for, price_interval, tax_for

BOOKING_FIELDS = ["status", "table_id", "start_at", "end_at", "booking_amount", "deposit_amount", "amount_paid", "remaining_amount", "payment_status"]


# =============================================================================== helpers
def _new_reference(db: Session) -> str:
    for _ in range(20):
        ref = random_code(6, "RB")
        if not db.scalar(select(Booking.id).where(Booking.reference == ref)):
            return ref
    raise AppError("Could not allocate booking reference", status_code=500)


def _active_membership(db: Session, customer_id: uuid.UUID | None, on: date | None = None) -> Membership | None:
    if not customer_id:
        return None
    today = on or utcnow().date()
    return db.scalar(
        select(Membership).where(
            Membership.customer_id == customer_id, Membership.status == MembershipStatus.ACTIVE,
            Membership.starts_on <= today, Membership.expires_on >= today,
        ).order_by(Membership.expires_on.desc())
    )


def expire_stale_holds(db: Session, *, table_id: uuid.UUID | None = None, events: PendingEvents | None = None) -> int:
    now = utcnow()
    stmt = select(Booking).where(Booking.status == BookingStatus.HELD, Booking.hold_expires_at < now)
    if table_id:
        stmt = stmt.where(Booking.table_id == table_id)
    n = 0
    for b in db.scalars(stmt).unique().all():
        b.status = BookingStatus.EXPIRED
        b.payment_status = PaymentStatus.CANCELLED if b.amount_paid == 0 else b.payment_status
        for h in db.scalars(select(BookingHold).where(BookingHold.booking_id == b.id, BookingHold.released_at.is_(None))).all():
            h.released_at, h.outcome = now, "EXPIRED"
        for p in db.scalars(select(Payment).where(Payment.booking_id == b.id, Payment.status == PaymentStatus.PENDING)).all():
            p.status = PaymentStatus.CANCELLED
        n += 1
        if events is not None:
            events.add(b.branch_id, "availability.changed", {"table_id": b.table_id, "booking_id": b.id}, public={"table_id": b.table_id})
    return n


def _conflicts(db: Session, table: Table, start: datetime, end: datetime, *, buffer_min: int, slot_step: int, exclude_id: uuid.UUID | None = None) -> list[str]:
    """Reasons the window is not free (empty list => free)."""
    reasons: list[str] = []
    now = utcnow()
    s = start - timedelta(minutes=buffer_min)
    e = end + timedelta(minutes=buffer_min)
    stmt = select(Booking).where(
        Booking.table_id == table.id,
        Booking.status.in_(BLOCKING_BOOKING_STATUSES),
        Booking.start_at < e,
        Booking.end_at > s,
        or_(Booking.status != BookingStatus.HELD, Booking.hold_expires_at > now),
    )
    if exclude_id:
        stmt = stmt.where(Booking.id != exclude_id)
    if db.scalars(stmt).first():
        reasons.append("BOOKED")
    sess = db.scalar(select(GameSession).where(GameSession.table_id == table.id, GameSession.status.in_(OPEN_SESSION_STATUSES)))
    if sess and (sess.booking_id is None or sess.booking_id != exclude_id):
        busy_until = sess.planned_end_at or (now + timedelta(minutes=slot_step))
        if start < busy_until:
            reasons.append("IN_USE")
    return reasons


def _window(branch: Branch, start: datetime, duration: int, table: Table | None, *, public: bool) -> tuple[datetime, datetime]:
    pol = branch_settings(branch).booking
    start = ensure_utc(start).replace(second=0, microsecond=0)
    end = start + timedelta(minutes=duration)
    now = utcnow()
    if public:
        if start < now + timedelta(minutes=pol.min_advance_minutes):
            raise ValidationFailed(f"Bookings must be made at least {pol.min_advance_minutes} minutes in advance", code="TOO_SOON")
        if start > now + timedelta(days=pol.max_advance_days):
            raise ValidationFailed(f"Bookings can be made up to {pol.max_advance_days} days ahead", code="TOO_FAR")
    elif end <= now:
        raise ValidationFailed("Booking window is in the past")
    if table is not None:
        if duration < table.minimum_booking_duration or duration > table.maximum_booking_duration:
            raise ValidationFailed(
                f"Duration must be between {table.minimum_booking_duration} and {table.maximum_booking_duration} minutes", code="INVALID_DURATION"
            )
    open_utc, close_utc = table_service.local_day_bounds(branch, _business_date(branch, start))
    if start < open_utc or end > close_utc:
        raise ValidationFailed("Requested time is outside opening hours", code="OUTSIDE_HOURS")
    return start, end


def _business_date(branch: Branch, instant: datetime) -> date:
    """The local calendar date whose business day contains `instant` (handles after-midnight closing)."""
    from app.core.timeutil import to_local

    local = to_local(instant, branch.timezone)
    oh, om = map(int, branch.opening_time.split(":"))
    if (local.hour, local.minute) < (oh, om):
        return (local - timedelta(days=1)).date()
    return local.date()


@dataclass
class Quote:
    amount: Decimal
    deposit: Decimal
    tax: Decimal
    segments: list


def quote(db: Session, table: Table, start: datetime, end: datetime, *, is_member: bool) -> Quote:
    branch = db.get(Branch, table.branch_id)
    st = branch_settings(branch)
    ctx = table_service.pricing_context(db, table, is_member=is_member, days=(start.date(), end.date()))
    res = price_interval(ctx, start, end)
    return Quote(res.amount, deposit_for(res.amount, st.booking), tax_for(res.amount, st.billing), res.segments)


# =============================================================================== availability
def availability(db: Session, branch_id: uuid.UUID, *, start: datetime, duration: int, game_type_id: uuid.UUID | None, public: bool = True,
                 customer_id: uuid.UUID | None = None) -> list[dict]:
    branch = get_branch(db, branch_id)
    pol = branch_settings(branch).booking
    start, end = _window(branch, start, duration, None, public=public)
    is_member = _active_membership(db, customer_id) is not None
    out = []
    for t in table_service.list_tables(db, branch_id, game_type_id=game_type_id):
        if public and not t.is_online_bookable:
            continue
        item = {"table": t, "status": "AVAILABLE", "quote": None, "next_available_at": None, "reason": None}
        if t.status in (TableStatus.MAINTENANCE, TableStatus.BLOCKED):
            item["status"] = "MAINTENANCE"
        elif duration < t.minimum_booking_duration or duration > t.maximum_booking_duration:
            item["status"] = "UNAVAILABLE"
            item["reason"] = f"Duration {t.minimum_booking_duration}-{t.maximum_booking_duration} min"
        else:
            reasons = _conflicts(db, t, start, end, buffer_min=pol.buffer_minutes, slot_step=pol.slot_step_minutes)
            if reasons:
                item["status"] = "BOOKED" if "BOOKED" in reasons else "IN_USE"
                item["next_available_at"] = next_available(db, branch, t, start, duration)
            else:
                item["quote"] = quote(db, t, start, end, is_member=is_member)
        out.append(item)
    return out


def busy_intervals(db: Session, table: Table, frm: datetime, to: datetime, slot_step: int) -> list[tuple[datetime, datetime, str]]:
    now = utcnow()
    rows = db.scalars(
        select(Booking).where(
            Booking.table_id == table.id, Booking.status.in_(BLOCKING_BOOKING_STATUSES), Booking.start_at < to, Booking.end_at > frm,
            or_(Booking.status != BookingStatus.HELD, Booking.hold_expires_at > now),
        ).order_by(Booking.start_at)
    ).unique().all()
    out = [(b.start_at, b.end_at, "BOOKED" if b.status != BookingStatus.HELD else "HELD") for b in rows]
    sess = db.scalar(select(GameSession).where(GameSession.table_id == table.id, GameSession.status.in_(OPEN_SESSION_STATUSES)))
    if sess:
        s_start = sess.started_at or sess.created_at
        s_end = sess.planned_end_at or (now + timedelta(minutes=slot_step))
        out.append((s_start, max(s_end, now), "IN_USE"))
    return sorted(out, key=lambda x: x[0])


def next_available(db: Session, branch: Branch, table: Table, after: datetime, duration: int) -> datetime | None:
    """Earliest start >= `after` (aligned to the slot grid) where `duration` fits."""
    pol = branch_settings(branch).booking
    horizon = after + timedelta(days=2)
    busy = busy_intervals(db, table, after - timedelta(hours=12), horizon, pol.slot_step_minutes)
    step = timedelta(minutes=pol.slot_step_minutes)
    buf = timedelta(minutes=pol.buffer_minutes)
    cand = after
    for _ in range(int(48 * 60 / pol.slot_step_minutes)):
        end = cand + timedelta(minutes=duration)
        open_utc, close_utc = table_service.local_day_bounds(branch, _business_date(branch, cand))
        if cand >= open_utc and end <= close_utc and not any(s - buf < end and cand < e + buf for s, e, _ in busy):
            return cand
        cand += step
    return None


def day_timeline(db: Session, branch_id: uuid.UUID, day: date, game_type_id: uuid.UUID | None, *, public: bool = True) -> dict:
    """Per-table busy blocks for a business day + when each table is next free.
    Powers the customer "when will a table be free?" view."""
    branch = get_branch(db, branch_id)
    pol = branch_settings(branch).booking
    open_utc, close_utc = table_service.local_day_bounds(branch, day)
    now = utcnow()
    tables = []
    for t in table_service.list_tables(db, branch_id, game_type_id=game_type_id):
        if public and not t.is_online_bookable:
            continue
        busy = busy_intervals(db, t, open_utc, close_utc, pol.slot_step_minutes)
        probe = max(open_utc, now)
        tables.append({
            "table": t,
            "status": t.status,
            "busy": [{"start": s, "end": e, "kind": k} for s, e, k in busy],
            "next_free_at": None if t.status in (TableStatus.MAINTENANCE, TableStatus.BLOCKED) else next_available(db, branch, t, _align(probe, pol.slot_step_minutes), t.minimum_booking_duration),
        })
    return {"branch_id": branch.id, "date": day, "opens_at": open_utc, "closes_at": close_utc, "slot_minutes": pol.slot_step_minutes, "tables": tables}


def _align(dt: datetime, step: int) -> datetime:
    dt = ensure_utc(dt).replace(second=0, microsecond=0)
    rem = (dt.hour * 60 + dt.minute) % step
    return dt if rem == 0 else dt + timedelta(minutes=step - rem)


# =============================================================================== create
def _lock_table(db: Session, table_id: uuid.UUID) -> Table:
    t = db.scalar(for_update(select(Table).where(Table.id == table_id, Table.deleted_at.is_(None)), db))
    if not t:
        raise NotFound("Table not found")
    return t


def create_hold(db: Session, *, branch_id: uuid.UUID, table_id: uuid.UUID, start: datetime, duration: int, customer: dict,
                coupon_code: str | None = None, principal: Principal | None = None) -> Booking:
    """Public checkout step 1: hold the table for `hold_minutes` pending deposit payment."""
    branch = get_branch(db, branch_id)
    pol = branch_settings(branch).booking
    events = PendingEvents()
    try:
        table = _lock_table(db, table_id)
        if table.branch_id != branch.id or not table.is_active or not table.is_online_bookable:
            raise ValidationFailed("This table cannot be booked online")
        if table.status in (TableStatus.MAINTENANCE, TableStatus.BLOCKED):
            raise Conflict("Table is under maintenance", code="TABLE_UNAVAILABLE")
        start, end = _window(branch, start, duration, table, public=True)
        expire_stale_holds(db, table_id=table.id, events=events)
        if _conflicts(db, table, start, end, buffer_min=pol.buffer_minutes, slot_step=pol.slot_step_minutes):
            raise Conflict("Sorry, this table was just booked for that time. Please pick another table or time.", code="BOOKING_CONFLICT")
        if principal and principal.user.customer_id:
            cust = db.get(Customer, principal.user.customer_id)
        else:
            cust = customer_service.find_or_create(db, branch.organization_id, name=customer["name"], phone=customer["phone"], email=customer.get("email"), branch_id=branch.id)
        q = quote(db, table, start, end, is_member=_active_membership(db, cust.id, start.date()) is not None)
        discount = Decimal("0")
        if coupon_code:
            from app.services import loyalty_service

            discount = loyalty_service.coupon_discount(db, branch.organization_id, coupon_code, q.amount, on=start.date())
        amount = money(q.amount - discount)
        deposit = deposit_for(amount, pol)
        now = utcnow()
        b = Booking(
            branch_id=branch.id, table_id=table.id, customer_id=cust.id, reference=_new_reference(db), source=BookingSource.ONLINE,
            status=BookingStatus.HELD, start_at=start, end_at=end, duration_minutes=duration, hold_expires_at=now + timedelta(minutes=pol.hold_minutes),
            booking_amount=amount, deposit_amount=deposit, discount=money(discount), tax=tax_for(amount, branch_settings(branch).billing),
            remaining_amount=amount, payment_status=PaymentStatus.PENDING, coupon_code=(coupon_code or None),
        )
        db.add(b)
        db.flush()
        db.add(BookingHold(booking_id=b.id, created_at=now, expires_at=b.hold_expires_at))
        audit(db, principal, "booking.hold", "booking", b.id, branch_id=branch.id, after=snapshot(b, BOOKING_FIELDS))
        events.add(branch.id, "availability.changed", {"table_id": table.id, "booking_id": b.id}, public={"table_id": table.id})
        if deposit == 0:
            _confirm(db, b, events, note="No deposit required")
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise Conflict("Sorry, this table was just booked for that time.", code="BOOKING_CONFLICT") from e
    except Exception:
        db.rollback()
        raise
    events.flush()
    return b


def create_staff_booking(db: Session, actor: Principal, *, branch_id: uuid.UUID, table_id: uuid.UUID, start: datetime, duration: int,
                         customer_id: uuid.UUID | None, customer: dict | None, deposit_method: PaymentMethod | None, deposit_amount: Decimal | None,
                         deposit_reference: str | None = None, source: BookingSource = BookingSource.STAFF, notes: str | None = None) -> Booking:
    """Phone / counter booking. Confirmed immediately; deposit optional (cash/UPI/card)."""
    branch = get_branch(db, branch_id)
    ensure_branch_access(actor, branch, "bookings.manage")
    pol = branch_settings(branch).booking
    events = PendingEvents()
    try:
        table = _lock_table(db, table_id)
        if table.branch_id != branch.id:
            raise ValidationFailed("Table does not belong to this branch")
        start, end = _window(branch, start, duration, table, public=False)
        expire_stale_holds(db, table_id=table.id, events=events)
        if _conflicts(db, table, start, end, buffer_min=pol.buffer_minutes, slot_step=pol.slot_step_minutes):
            raise Conflict("Table is already booked or in use for that time", code="BOOKING_CONFLICT")
        if customer_id:
            cust = customer_service.get_customer(db, actor, customer_id)
        elif customer:
            cust = customer_service.find_or_create(db, branch.organization_id, name=customer["name"], phone=customer["phone"], email=customer.get("email"), branch_id=branch.id)
        else:
            raise ValidationFailed("Customer is required")
        q = quote(db, table, start, end, is_member=_active_membership(db, cust.id, start.date()) is not None)
        b = Booking(
            branch_id=branch.id, table_id=table.id, customer_id=cust.id, reference=_new_reference(db), source=source,
            status=BookingStatus.CONFIRMED, start_at=start, end_at=end, duration_minutes=duration, booking_amount=q.amount,
            deposit_amount=money(deposit_amount or 0), tax=q.tax, remaining_amount=q.amount, payment_status=PaymentStatus.PENDING,
            notes=notes, created_by_id=actor.id,
        )
        db.add(b)
        db.flush()
        if deposit_method and deposit_amount and deposit_amount > 0:
            from app.services import shift_service

            p = Payment(
                branch_id=branch.id, purpose=PaymentPurpose.BOOKING_DEPOSIT, method=deposit_method, status=PaymentStatus.PAID,
                amount=money(deposit_amount), booking_id=b.id, customer_id=cust.id, reference=deposit_reference, received_by_id=actor.id,
                paid_at=utcnow(), shift_id=shift_service.current_shift_id(db, actor),
            )
            db.add(p)
            _apply_deposit(b, money(deposit_amount))
        audit(db, actor, "booking.create", "booking", b.id, branch_id=branch.id, after=snapshot(b, BOOKING_FIELDS))
        table_service.recompute_status(db, table, events)
        events.add(branch.id, "booking.created", {"booking_id": b.id, "table_id": table.id, "start_at": start})
        events.add(branch.id, "availability.changed", {"table_id": table.id}, public={"table_id": table.id})
        _notify(db, b, "booking.confirmed")
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise Conflict("Table is already booked for that time", code="BOOKING_CONFLICT") from e
    except Exception:
        db.rollback()
        raise
    events.flush()
    return b


def _apply_deposit(b: Booking, amount: Decimal) -> None:
    b.amount_paid = money(b.amount_paid) + money(amount)
    b.remaining_amount = max(Decimal("0.00"), money(b.booking_amount) - money(b.amount_paid))
    b.payment_status = PaymentStatus.PAID if b.remaining_amount == 0 else PaymentStatus.PARTIALLY_PAID


def _confirm(db: Session, b: Booking, events: PendingEvents, note: str | None = None) -> None:
    b.status = BookingStatus.CONFIRMED
    b.hold_expires_at = None
    for h in db.scalars(select(BookingHold).where(BookingHold.booking_id == b.id, BookingHold.released_at.is_(None))).all():
        h.released_at, h.outcome = utcnow(), "CONFIRMED"
    events.add(b.branch_id, "booking.confirmed", {"booking_id": b.id, "table_id": b.table_id, "reference": b.reference})
    table_service.recompute_status(db, db.get(Table, b.table_id), events)
    _notify(db, b, "booking.confirmed")


def on_deposit_paid(db: Session, payment: Payment, events: PendingEvents) -> str:
    """Called by the payment webhook handler (authoritative), inside its transaction.

    Handles the edge cases: hold already expired (confirm if the slot is still
    free, otherwise refund), booking cancelled meanwhile (refund), duplicate
    notifications (no-op)."""
    b = db.scalar(for_update(select(Booking).where(Booking.id == payment.booking_id), db))
    if b is None:
        return "BOOKING_MISSING"
    table = _lock_table(db, b.table_id)
    if b.status in (BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN, BookingStatus.IN_PROGRESS, BookingStatus.COMPLETED):
        _apply_deposit(b, payment.amount)
        return "ALREADY_CONFIRMED"
    if b.status in (BookingStatus.HELD, BookingStatus.EXPIRED):
        pol = branch_settings(db.get(Branch, b.branch_id)).booking
        if not _conflicts(db, table, b.start_at, b.end_at, buffer_min=pol.buffer_minutes, slot_step=pol.slot_step_minutes, exclude_id=b.id):
            late = b.status == BookingStatus.EXPIRED
            _apply_deposit(b, payment.amount)
            _confirm(db, b, events)
            audit(db, None, "booking.confirm", "booking", b.id, branch_id=b.branch_id, after={"payment_id": payment.id, "late_payment": late})
            return "CONFIRMED_LATE" if late else "CONFIRMED"
    # Slot lost or booking cancelled: money must go back.
    raise_alert(db, b.branch_id, "PAYMENT_WITHOUT_SLOT", f"Deposit received for booking {b.reference} but the slot is no longer available; refund issued.",
                table_id=b.table_id, dedupe_key=f"payslot:{payment.id}", events=events)
    from app.services import payment_service

    payment_service.refund_payment(db, None, payment, payment.amount, "Slot no longer available", events=events, commit=False)
    return "REFUNDED_SLOT_UNAVAILABLE"


# =============================================================================== lifecycle
def get_booking(db: Session, booking_id: uuid.UUID) -> Booking:
    b = db.get(Booking, booking_id)
    if not b:
        raise NotFound("Booking not found")
    return b


def _authorize(actor: Principal, b: Booking, perm: str = "bookings.manage") -> bool:
    """Returns True if acting as the customer themself."""
    if actor.has(perm, b.branch_id):
        return False
    if actor.has("self.bookings") and actor.user.customer_id == b.customer_id:
        return True
    raise Forbidden("Not allowed to modify this booking")


def cancel(db: Session, actor: Principal, booking_id: uuid.UUID, reason: str, refund_override: Decimal | None = None) -> Booking:
    events = PendingEvents()
    b = db.scalar(for_update(select(Booking).where(Booking.id == booking_id), db))
    if not b:
        raise NotFound("Booking not found")
    as_customer = _authorize(actor, b)
    if b.status not in (BookingStatus.HELD, BookingStatus.CONFIRMED):
        raise InvalidState(f"Booking in status {b.status} cannot be cancelled")
    pol = branch_settings(db.get(Branch, b.branch_id)).booking
    before = snapshot(b, BOOKING_FIELDS)
    now = utcnow()
    if refund_override is not None:
        if as_customer or not actor.has("payments.refund", b.branch_id):
            raise Forbidden("Refund override requires payments.refund")
        refund = min(money(refund_override), money(b.amount_paid))
    elif now <= b.start_at - timedelta(hours=pol.free_cancellation_hours):
        refund = money(b.amount_paid)
    else:
        refund = money(money(b.amount_paid) * pol.late_cancellation_refund_percent / Decimal(100))
    b.status = BookingStatus.CANCELLED
    b.cancelled_at = now
    b.cancel_reason = reason
    for h in db.scalars(select(BookingHold).where(BookingHold.booking_id == b.id, BookingHold.released_at.is_(None))).all():
        h.released_at, h.outcome = now, "CANCELLED"
    if refund > 0:
        from app.services import payment_service

        remaining = refund
        for p in db.scalars(select(Payment).where(Payment.booking_id == b.id, Payment.status == PaymentStatus.PAID, Payment.amount > 0)).all():
            part = min(remaining, money(p.amount))
            if part > 0:
                payment_service.refund_payment(db, actor, p, part, f"Booking {b.reference} cancelled", events=events, commit=False,
                                               policy=refund_override is None)
                remaining -= part
        b.refund_amount = refund
        b.payment_status = PaymentStatus.REFUNDED
    elif b.amount_paid == 0:
        b.payment_status = PaymentStatus.CANCELLED
    for p in db.scalars(select(Payment).where(Payment.booking_id == b.id, Payment.status == PaymentStatus.PENDING)).all():
        p.status = PaymentStatus.CANCELLED
    audit(db, actor, "booking.cancel", "booking", b.id, branch_id=b.branch_id, before=before, after=snapshot(b, BOOKING_FIELDS) | {"refund": refund}, reason=reason)
    table_service.recompute_status(db, db.get(Table, b.table_id), events)
    events.add(b.branch_id, "availability.changed", {"table_id": b.table_id}, public={"table_id": b.table_id})
    _notify(db, b, "booking.cancelled")
    db.commit()
    events.flush()
    return b


def reschedule(db: Session, actor: Principal, booking_id: uuid.UUID, *, start: datetime, duration: int | None, table_id: uuid.UUID | None, reason: str | None) -> Booking:
    events = PendingEvents()
    b = db.scalar(for_update(select(Booking).where(Booking.id == booking_id), db))
    if not b:
        raise NotFound("Booking not found")
    as_customer = _authorize(actor, b)
    if b.status != BookingStatus.CONFIRMED:
        raise InvalidState("Only confirmed bookings can be rescheduled")
    branch = db.get(Branch, b.branch_id)
    pol = branch_settings(branch).booking
    if as_customer and utcnow() > b.start_at - timedelta(hours=pol.allow_reschedule_hours):
        raise InvalidState(f"Online rescheduling closes {pol.allow_reschedule_hours}h before start; please call the club")
    duration = duration or b.duration_minutes
    new_table = _lock_table(db, table_id or b.table_id)
    if new_table.id != b.table_id:
        _lock_table(db, b.table_id)
    start, end = _window(branch, start, duration, new_table, public=as_customer)
    if _conflicts(db, new_table, start, end, buffer_min=pol.buffer_minutes, slot_step=pol.slot_step_minutes, exclude_id=b.id):
        raise Conflict("The new time is not available", code="BOOKING_CONFLICT")
    before = snapshot(b, BOOKING_FIELDS)
    old_table_id = b.table_id
    q = quote(db, new_table, start, end, is_member=_active_membership(db, b.customer_id, start.date()) is not None)
    b.table_id, b.start_at, b.end_at, b.duration_minutes = new_table.id, start, end, duration
    b.booking_amount = money(q.amount - money(b.discount))
    b.tax = q.tax
    b.remaining_amount = max(Decimal("0.00"), money(b.booking_amount) - money(b.amount_paid))
    b.reminder_sent_at = None
    audit(db, actor, "booking.reschedule", "booking", b.id, branch_id=b.branch_id, before=before, after=snapshot(b, BOOKING_FIELDS), reason=reason)
    for tid in {old_table_id, new_table.id}:
        table_service.recompute_status(db, db.get(Table, tid), events)
        events.add(b.branch_id, "availability.changed", {"table_id": tid}, public={"table_id": tid})
    db.commit()
    events.flush()
    return b


def check_in(db: Session, actor: Principal, booking_id: uuid.UUID) -> tuple[Booking, GameSession | None, str | None]:
    """Customer arrived. Creates a READY session on the table when it is free."""
    events = PendingEvents()
    b = db.scalar(for_update(select(Booking).where(Booking.id == booking_id), db))
    if not b:
        raise NotFound("Booking not found")
    actor.require("bookings.manage", b.branch_id)
    if b.status != BookingStatus.CONFIRMED:
        raise InvalidState(f"Cannot check in a booking in status {b.status}")
    pol = branch_settings(db.get(Branch, b.branch_id)).booking
    now = utcnow()
    if now < b.start_at - timedelta(minutes=max(pol.allow_early_start_minutes, 60 * 3)):
        raise InvalidState("Too early to check in for this booking")
    table = _lock_table(db, b.table_id)
    b.status = BookingStatus.CHECKED_IN
    b.checked_in_at = now
    warning = None
    session = None
    from app.services import session_service

    if db.scalar(select(GameSession.id).where(GameSession.table_id == table.id, GameSession.status.in_(OPEN_SESSION_STATUSES))):
        warning = "Table is still in use by the previous session; the session will be created when it becomes free."
    else:
        session = session_service.create_ready_session(db, actor, table, booking=b, events=events)
    audit(db, actor, "booking.check_in", "booking", b.id, branch_id=b.branch_id, after={"status": b.status})
    db.commit()
    events.flush()
    return b, session, warning


def mark_no_show(db: Session, actor: Principal | None, booking_id: uuid.UUID, events: PendingEvents | None = None, commit: bool = True) -> Booking:
    own_events = events is None
    events = events or PendingEvents()
    b = db.scalar(for_update(select(Booking).where(Booking.id == booking_id), db))
    if not b:
        raise NotFound("Booking not found")
    if actor:
        actor.require("bookings.manage", b.branch_id)
    if b.status != BookingStatus.CONFIRMED:
        raise InvalidState("Only confirmed bookings can be marked no-show")
    b.status = BookingStatus.NO_SHOW  # deposit is retained per policy
    audit(db, actor, "booking.no_show", "booking", b.id, branch_id=b.branch_id, after={"status": b.status, "deposit_retained": b.amount_paid})
    table_service.recompute_status(db, db.get(Table, b.table_id), events)
    events.add(b.branch_id, "availability.changed", {"table_id": b.table_id}, public={"table_id": b.table_id})
    if commit:
        db.commit()
        if own_events:
            events.flush()
    return b


def process_no_shows(db: Session) -> int:
    """Worker: CONFIRMED bookings past start + grace without check-in → NO_SHOW."""
    n = 0
    now = utcnow()
    for b in db.scalars(select(Booking).where(Booking.status == BookingStatus.CONFIRMED, Booking.start_at < now - timedelta(minutes=5))).unique().all():
        pol = branch_settings(db.get(Branch, b.branch_id)).booking
        if now > b.start_at + timedelta(minutes=pol.no_show_grace_minutes):
            events = PendingEvents()
            mark_no_show(db, None, b.id, events=events, commit=True)
            events.flush()
            n += 1
    return n


def list_bookings(db: Session, actor: Principal, *, branch_id: uuid.UUID | None, status: str | None, frm: datetime | None, to: datetime | None,
                  customer_id: uuid.UUID | None, offset: int, limit: int) -> tuple[list[Booking], int]:
    from sqlalchemy import func

    stmt = select(Booking)
    if actor.has("bookings.view", branch_id):
        allowed = actor.branch_ids()
        if branch_id:
            actor.require("bookings.view", branch_id)
            stmt = stmt.where(Booking.branch_id == branch_id)
        elif allowed is not None:
            stmt = stmt.where(Booking.branch_id.in_(allowed))
        if customer_id:
            stmt = stmt.where(Booking.customer_id == customer_id)
    elif actor.user.customer_id:
        stmt = stmt.where(Booking.customer_id == actor.user.customer_id)
    else:
        raise Forbidden("Not allowed")
    if status:
        stmt = stmt.where(Booking.status.in_(status.split(",")))
    if frm:
        stmt = stmt.where(Booking.end_at > frm)
    if to:
        stmt = stmt.where(Booking.start_at < to)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Booking.start_at.desc()).offset(offset).limit(limit)).unique().all()
    return list(rows), total


def refresh_reserved_statuses(db: Session) -> int:
    """Worker: flip tables to RESERVED shortly before a booking, back to AVAILABLE after."""
    n = 0
    events = PendingEvents()
    for t in db.scalars(select(Table).where(Table.deleted_at.is_(None), Table.is_active.is_(True))).unique().all():
        before = t.status
        table_service.recompute_status(db, t, events)
        n += int(before != t.status)
    db.commit()
    events.flush()
    return n


def _notify(db: Session, b: Booking, event: str) -> None:
    from app.services import notification_service

    notification_service.enqueue_for_booking(db, b, event)


def lookup_public(db: Session, reference: str, phone: str) -> Booking:
    """Guest booking lookup: reference + phone (no account needed)."""
    b = db.scalar(select(Booking).where(Booking.reference == reference.upper().strip()))
    if not b or b.customer.phone != customer_service.normalize_phone(phone):
        raise NotFound("Booking not found")
    return b


def upcoming_for_dashboard(db: Session, branch_id: uuid.UUID, hours: int = 3) -> list[Booking]:
    now = utcnow()
    return list(db.scalars(
        select(Booking).where(
            Booking.branch_id == branch_id, Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN]),
            and_(Booking.start_at < now + timedelta(hours=hours), Booking.end_at > now),
        ).order_by(Booking.start_at)
    ).unique().all())
