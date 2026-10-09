"""Cash shifts and expenses (carried over from the legacy RS Sales & Expense app)."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import for_update
from app.core.deps import Principal
from app.core.errors import Conflict, InvalidState, NotFound, ValidationFailed
from app.core.timeutil import utcnow
from app.models import Expense, ExpenseCategory, Payment, Shift
from app.models.base import money
from app.models.enums import PaymentMethod, PaymentStatus, ShiftStatus
from app.services.audit import audit
from app.services.common import ensure_branch_access, get_branch


def current_shift_id(db: Session, actor: Principal | None) -> uuid.UUID | None:
    if actor is None:
        return None
    return db.scalar(select(Shift.id).where(Shift.open_key == str(actor.id)))


def open_shift(db: Session, actor: Principal, branch_id: uuid.UUID, opening_cash: Decimal, notes: str | None) -> Shift:
    ensure_branch_access(actor, get_branch(db, branch_id), "shifts.operate")
    s = Shift(branch_id=branch_id, user_id=actor.id, open_key=str(actor.id), opened_at=utcnow(), opening_cash=money(opening_cash), notes=notes)
    db.add(s)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise Conflict("You already have an open shift", code="SHIFT_ALREADY_OPEN") from e
    audit(db, actor, "shift.open", "shift", s.id, branch_id=branch_id, after={"opening_cash": opening_cash})
    db.commit()
    return s


def _cash_flow(db: Session, s: Shift, until=None) -> tuple[Decimal, Decimal]:
    until = until or utcnow()
    cash_in = db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(
        Payment.received_by_id == s.user_id, Payment.method == PaymentMethod.CASH, Payment.status.in_([PaymentStatus.PAID, PaymentStatus.REFUNDED]),
        Payment.paid_at >= s.opened_at, Payment.paid_at <= until, Payment.branch_id == s.branch_id))
    cash_out = db.scalar(select(func.coalesce(func.sum(Expense.amount), 0)).where(
        Expense.shift_id == s.id, Expense.method == "CASH", Expense.is_void.is_(False)))
    return money(cash_in), money(cash_out)


def summary(db: Session, s: Shift) -> dict:
    cin, cout = _cash_flow(db, s, s.closed_at)
    return {"shift": s, "cash_sales": cin, "cash_expenses": cout, "expected_cash": money(s.opening_cash + cin - cout)}


def close_shift(db: Session, actor: Principal, counted_cash: Decimal, notes: str | None) -> Shift:
    s = db.scalar(for_update(select(Shift).where(Shift.open_key == str(actor.id)), db))
    if not s:
        raise NotFound("No open shift")
    now = utcnow()
    cin, cout = _cash_flow(db, s, now)
    s.cash_sales, s.cash_expenses = cin, cout
    s.expected_cash = money(s.opening_cash + cin - cout)
    s.counted_cash = money(counted_cash)
    s.variance = money(s.counted_cash - s.expected_cash)
    s.closed_at, s.status, s.open_key = now, ShiftStatus.CLOSED, None
    if notes:
        s.notes = (s.notes + " | " if s.notes else "") + notes
    audit(db, actor, "shift.close", "shift", s.id, branch_id=s.branch_id, after={"expected": s.expected_cash, "counted": s.counted_cash, "variance": s.variance})
    if s.variance != 0:
        from app.services.audit import raise_alert

        raise_alert(db, s.branch_id, "CASH_VARIANCE", f"Shift closed by {actor.user.username} with cash variance {s.variance}", data={"shift_id": str(s.id)})
    db.commit()
    return s


def list_shifts(db: Session, actor: Principal, branch_id: uuid.UUID, mine: bool) -> list[Shift]:
    stmt = select(Shift).where(Shift.branch_id == branch_id)
    if mine or not actor.has("shifts.view_all", branch_id):
        stmt = stmt.where(Shift.user_id == actor.id)
    return list(db.scalars(stmt.order_by(Shift.opened_at.desc()).limit(100)).all())


def my_open_shift(db: Session, actor: Principal) -> Shift | None:
    return db.scalar(select(Shift).where(Shift.open_key == str(actor.id)))


# ------------------------------------------------------------------------------ expenses
def create_expense_category(db: Session, actor: Principal, code: str, name: str, color: str = "#0369a1") -> ExpenseCategory:
    actor.require("settings.manage")
    c = ExpenseCategory(organization_id=actor.organization_id, code=code.upper(), name=name, color=color)
    db.add(c)
    db.commit()
    return c


def add_expense(db: Session, actor: Principal, branch_id: uuid.UUID, data: dict) -> Expense:
    ensure_branch_access(actor, get_branch(db, branch_id), "expenses.manage")
    cat = db.get(ExpenseCategory, data["category_id"])
    if not cat or cat.organization_id != actor.organization_id:
        raise ValidationFailed("Unknown expense category")
    e = Expense(branch_id=branch_id, category_id=cat.id, expense_date=data.get("expense_date") or utcnow().date(), amount=money(data["amount"]),
                description=data["description"], paid_to=data.get("paid_to"), method=data.get("method", "CASH"), shift_id=current_shift_id(db, actor), created_by_id=actor.id)
    db.add(e)
    db.flush()
    audit(db, actor, "expense.create", "expense", e.id, branch_id=branch_id, after={"amount": e.amount, "category": cat.code, "description": e.description})
    db.commit()
    return e


def void_expense(db: Session, actor: Principal, expense_id: uuid.UUID, reason: str) -> Expense:
    e = db.get(Expense, expense_id)
    if not e:
        raise NotFound("Expense not found")
    actor.require("approvals.resolve", e.branch_id)
    if e.is_void:
        raise InvalidState("Already void")
    e.is_void, e.void_reason = True, reason
    audit(db, actor, "expense.void", "expense", e.id, branch_id=e.branch_id, before={"is_void": False}, after={"is_void": True}, reason=reason)
    db.commit()
    return e


def list_expenses(db: Session, actor: Principal, branch_id: uuid.UUID, frm: date, to: date) -> list[Expense]:
    actor.require("expenses.manage", branch_id)
    return list(db.scalars(select(Expense).where(Expense.branch_id == branch_id, Expense.expense_date >= frm, Expense.expense_date <= to)
                           .order_by(Expense.expense_date.desc(), Expense.created_at.desc())).unique().all())
