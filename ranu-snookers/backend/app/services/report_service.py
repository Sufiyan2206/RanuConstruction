"""Reports & analytics.

Aggregation is done in Python over a bounded date range so the SQL stays
portable across PostgreSQL / MySQL (no date_trunc vs DATE_FORMAT divergence)
and grouping happens in the branch's *local* timezone. For multi-year,
multi-branch analytics add materialised views or a warehouse later.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import Principal
from app.core.timeutil import to_local, utcnow
from app.models import (
    Alert,
    Booking,
    Branch,
    Customer,
    Device,
    Expense,
    GameSession,
    GameType,
    Invoice,
    Membership,
    Order,
    OrderItem,
    Payment,
    Table,
)
from app.models.base import money
from app.models.enums import (
    OPEN_SESSION_STATUSES,
    BookingStatus,
    InvoiceStatus,
    MembershipStatus,
    PaymentPurpose,
    PaymentStatus,
    SessionStatus,
)
from app.services import table_service
from app.services.common import get_branch

REVENUE_PURPOSES = [PaymentPurpose.INVOICE, PaymentPurpose.BOOKING_DEPOSIT, PaymentPurpose.MEMBERSHIP, PaymentPurpose.TOURNAMENT_FEE, PaymentPurpose.REFUND]


def _range_utc(branch: Branch, frm: date, to: date) -> tuple[datetime, datetime]:
    s, _ = table_service.local_day_bounds(branch, frm)
    _, e = table_service.local_day_bounds(branch, to)
    return s, e


def _bucket(d: date, period: str) -> str:
    if period == "daily":
        return d.isoformat()
    if period == "weekly":
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    if period == "monthly":
        return d.strftime("%Y-%m")
    return str(d.year)


def revenue(db: Session, actor: Principal, branch_id: uuid.UUID, frm: date, to: date, period: str = "daily") -> dict:
    """Cash-basis revenue from payments (money actually received, net of refunds);
    CREDIT (due) payments are shown separately as receivable, not cash."""
    actor.require("reports.view", branch_id)
    branch = get_branch(db, branch_id)
    s, e = _range_utc(branch, frm, to)
    rows = db.execute(select(Payment.paid_at, Payment.amount, Payment.method, Payment.purpose).where(
        Payment.branch_id == branch_id, Payment.paid_at >= s, Payment.paid_at < e, Payment.status.in_([PaymentStatus.PAID, PaymentStatus.REFUNDED]),
        Payment.purpose.in_(REVENUE_PURPOSES + [PaymentPurpose.DUE_SETTLEMENT]))).all()
    buckets: dict[str, dict] = defaultdict(lambda: {"collected": Decimal("0"), "credit_given": Decimal("0"), "refunds": Decimal("0")})
    by_method: dict[str, Decimal] = defaultdict(Decimal)
    for paid_at, amount, method, purpose in rows:
        key = _bucket(to_local(paid_at, branch.timezone).date(), period)
        amt = money(amount)
        if method == "CREDIT":
            buckets[key]["credit_given"] += amt
            continue
        if purpose == PaymentPurpose.REFUND:
            buckets[key]["refunds"] += amt
        buckets[key]["collected"] += amt
        by_method[method] += amt
    exp_rows = db.execute(select(Expense.expense_date, Expense.amount).where(Expense.branch_id == branch_id, Expense.expense_date >= frm,
                                                                            Expense.expense_date <= to, Expense.is_void.is_(False))).all()
    expenses: dict[str, Decimal] = defaultdict(Decimal)
    for d, amt in exp_rows:
        expenses[_bucket(d, period)] += money(amt)
    keys = sorted(set(buckets) | set(expenses))
    series = [{"period": k, "collected": buckets[k]["collected"], "refunds": buckets[k]["refunds"], "credit_given": buckets[k]["credit_given"],
               "expenses": expenses[k], "net": buckets[k]["collected"] - expenses[k]} for k in keys]
    total = sum((r["collected"] for r in series), Decimal("0"))
    total_exp = sum((r["expenses"] for r in series), Decimal("0"))
    return {"period": period, "series": series, "by_method": dict(by_method), "total_collected": total, "total_expenses": total_exp, "net": total - total_exp}


def utilization(db: Session, actor: Principal, branch_id: uuid.UUID, frm: date, to: date) -> list[dict]:
    """Played minutes / open minutes per table."""
    actor.require("reports.view", branch_id)
    branch = get_branch(db, branch_id)
    s, e = _range_utc(branch, frm, to)
    days = (to - frm).days + 1
    open_s, open_e = table_service.local_day_bounds(branch, frm)
    open_minutes_per_day = (open_e - open_s).total_seconds() / 60
    played: dict[uuid.UUID, float] = defaultdict(float)
    count: dict[uuid.UUID, int] = defaultdict(int)
    for tid, _st, _en, dur in db.execute(select(GameSession.table_id, GameSession.started_at, GameSession.ended_at, GameSession.duration_seconds).where(
            GameSession.branch_id == branch_id, GameSession.started_at >= s, GameSession.started_at < e,
            GameSession.status.in_([SessionStatus.COMPLETED, SessionStatus.AUTO_CLOSED]))).all():
        played[tid] += (dur or 0) / 60
        count[tid] += 1
    out = []
    for t in table_service.list_tables(db, branch_id, include_inactive=True):
        mins = played.get(t.id, 0.0)
        out.append({"table_id": t.id, "table_number": t.table_number, "name": t.name, "game": t.game_type.name, "sessions": count.get(t.id, 0),
                    "played_minutes": round(mins), "utilization_percent": round(100 * mins / (open_minutes_per_day * days), 1) if open_minutes_per_day else 0})
    return out


def peak_hours(db: Session, actor: Principal, branch_id: uuid.UUID, frm: date, to: date) -> list[dict]:
    """Occupied table-minutes per local hour of day."""
    actor.require("reports.view", branch_id)
    branch = get_branch(db, branch_id)
    s, e = _range_utc(branch, frm, to)
    hours = defaultdict(float)
    for st, en in db.execute(select(GameSession.started_at, GameSession.ended_at).where(
            GameSession.branch_id == branch_id, GameSession.started_at >= s, GameSession.started_at < e, GameSession.ended_at.is_not(None))).all():
        cur = st
        while cur < en:
            nxt = min(en, (cur + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0))
            hours[to_local(cur, branch.timezone).hour] += (nxt - cur).total_seconds() / 60
            cur = nxt
    return [{"hour": h, "label": datetime(2000, 1, 1, h).strftime("%I %p").lstrip("0"), "table_minutes": round(hours.get(h, 0))} for h in range(24)]


def game_report(db: Session, actor: Principal, branch_id: uuid.UUID, frm: date, to: date) -> list[dict]:
    actor.require("reports.view", branch_id)
    branch = get_branch(db, branch_id)
    s, e = _range_utc(branch, frm, to)
    rows = db.execute(
        select(GameType.name, func.count(GameSession.id), func.coalesce(func.sum(GameSession.duration_seconds), 0))
        .join(Table, Table.id == GameSession.table_id).join(GameType, GameType.id == Table.game_type_id)
        .where(GameSession.branch_id == branch_id, GameSession.started_at >= s, GameSession.started_at < e, GameSession.status.in_([SessionStatus.COMPLETED, SessionStatus.AUTO_CLOSED]))
        .group_by(GameType.name)).all()
    rev = dict(db.execute(
        select(GameType.name, func.coalesce(func.sum(Invoice.total), 0)).join(GameSession, GameSession.id == Invoice.session_id)
        .join(Table, Table.id == GameSession.table_id).join(GameType, GameType.id == Table.game_type_id)
        .where(Invoice.branch_id == branch_id, Invoice.issued_at >= s, Invoice.issued_at < e, Invoice.status != InvoiceStatus.VOID).group_by(GameType.name)).all())
    return [{"game": g, "sessions": n, "hours": round(secs / 3600, 1), "billed": money(rev.get(g, 0))} for g, n, secs in rows]


def payment_methods(db: Session, actor: Principal, branch_id: uuid.UUID, frm: date, to: date) -> list[dict]:
    r = revenue(db, actor, branch_id, frm, to, "daily")
    credit = sum((x["credit_given"] for x in r["series"]), Decimal("0"))
    out = [{"method": k, "amount": v} for k, v in sorted(r["by_method"].items(), key=lambda kv: -kv[1])]
    out.append({"method": "CREDIT (due, not collected)", "amount": credit})
    return out


def customers_report(db: Session, actor: Principal, branch_id: uuid.UUID, frm: date, to: date) -> dict:
    actor.require("reports.view", branch_id)
    branch = get_branch(db, branch_id)
    s, e = _range_utc(branch, frm, to)
    new = db.scalar(select(func.count(Customer.id)).where(Customer.organization_id == branch.organization_id, Customer.created_at >= s, Customer.created_at < e)) or 0
    visitors = set(db.scalars(select(GameSession.customer_id).where(GameSession.branch_id == branch_id, GameSession.started_at >= s, GameSession.started_at < e,
                                                                    GameSession.customer_id.is_not(None))).all())
    new_ids = set(db.scalars(select(Customer.id).where(Customer.organization_id == branch.organization_id, Customer.created_at >= s, Customer.created_at < e)).all())
    today = utcnow().date()
    members = set(db.scalars(select(Membership.customer_id).where(Membership.status == MembershipStatus.ACTIVE, Membership.expires_on >= today)).all())
    top = db.execute(select(Customer.id, Customer.name, Customer.phone, func.sum(Invoice.total).label("spend"), func.count(Invoice.id))
                     .join(Invoice, Invoice.customer_id == Customer.id)
                     .where(Invoice.branch_id == branch_id, Invoice.issued_at >= s, Invoice.issued_at < e, Invoice.status != InvoiceStatus.VOID)
                     .group_by(Customer.id, Customer.name, Customer.phone).order_by(func.sum(Invoice.total).desc()).limit(10)).all()
    return {
        "new_customers": new, "visiting_customers": len(visitors), "returning_customers": len(visitors - new_ids),
        "members_visiting": len(visitors & members), "non_members_visiting": len(visitors - members),
        "top_customers": [{"customer_id": i, "name": n, "phone": p, "spend": money(sp), "invoices": c} for i, n, p, sp, c in top],
    }


def product_sales(db: Session, actor: Principal, branch_id: uuid.UUID, frm: date, to: date) -> list[dict]:
    actor.require("reports.view", branch_id)
    branch = get_branch(db, branch_id)
    s, e = _range_utc(branch, frm, to)
    rows = db.execute(select(OrderItem.name, func.sum(OrderItem.quantity), func.sum(OrderItem.amount)).join(Order, Order.id == OrderItem.order_id)
                      .where(Order.branch_id == branch_id, OrderItem.created_at >= s, OrderItem.created_at < e, OrderItem.status == "ACTIVE")
                      .group_by(OrderItem.name).order_by(func.sum(OrderItem.amount).desc())).all()
    return [{"product": n, "quantity": float(q or 0), "amount": money(a)} for n, q, a in rows]


def dashboard(db: Session, actor: Principal, branch_id: uuid.UUID) -> dict:
    """Receptionist home: answers 'what is free / running / arriving / owing / ending / broken' in one call."""
    actor.require("tables.view", branch_id)
    branch = get_branch(db, branch_id)
    today = to_local(utcnow(), branch.timezone).date()
    s, e = table_service.local_day_bounds(branch, today)
    now = utcnow()
    board = table_service.status_board(db, branch_id)
    status_counts: dict[str, int] = defaultdict(int)
    for row in board:
        status_counts[row["table"].status] += 1
    collected = db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(
        Payment.branch_id == branch_id, Payment.paid_at >= s, Payment.paid_at < e, Payment.status.in_([PaymentStatus.PAID, PaymentStatus.REFUNDED]),
        Payment.method != "CREDIT"))
    bookings_today = db.scalar(select(func.count(Booking.id)).where(Booking.branch_id == branch_id, Booking.start_at >= s, Booking.start_at < e,
                                                                   Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN, BookingStatus.IN_PROGRESS, BookingStatus.COMPLETED])))
    pending_invoices = list(db.scalars(select(Invoice).where(Invoice.branch_id == branch_id, Invoice.status.in_([InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID]))
                                       .order_by(Invoice.issued_at.desc()).limit(20)).all())
    ending_soon = [r for r in board if r["session"] and r["session"].planned_end_at and r["session"].planned_end_at - now <= timedelta(minutes=15)]
    open_alerts = list(db.scalars(select(Alert).where(Alert.branch_id == branch_id, Alert.acknowledged_at.is_(None)).order_by(Alert.created_at.desc()).limit(30)).all())
    device_errors = db.scalar(select(func.count(Device.id)).where(Device.branch_id == branch_id, Device.status.in_(["OFFLINE", "ERROR"]))) or 0
    from app.services import booking_service, pos_service

    return {
        "today_revenue": money(collected),
        "today_bookings": bookings_today or 0,
        "active_tables": sum(status_counts[k] for k in ("GAME_STARTED", "PAUSED", "OCCUPIED")),
        "available_tables": status_counts["AVAILABLE"],
        "status_counts": dict(status_counts),
        "active_sessions": db.scalar(select(func.count(GameSession.id)).where(GameSession.branch_id == branch_id, GameSession.status.in_(OPEN_SESSION_STATUSES))) or 0,
        "pending_payments": pending_invoices,
        "upcoming_bookings": booking_service.upcoming_for_dashboard(db, branch_id, 3),
        "ending_soon": [{"table_number": r["table"].table_number, "session_id": r["session"].id, "planned_end_at": r["session"].planned_end_at} for r in ending_soon],
        "device_errors": device_errors,
        "alerts": open_alerts,
        "low_stock": len(pos_service.low_stock(db, branch_id)),
        "board": board,
    }
