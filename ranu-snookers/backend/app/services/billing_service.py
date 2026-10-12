"""Billing engine: session → invoice, counter payments (split / due), discounts
with maker-checker approval, adjustments (credit/debit notes) and voids with
full reversal of side effects. Financial rows are never overwritten."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import for_update
from app.core.deps import Principal
from app.core.errors import Conflict, Forbidden, InvalidState, NotFound, ValidationFailed
from app.core.realtime import PendingEvents, hub
from app.core.timeutil import utcnow
from app.models import (
    ApprovalRequest,
    Booking,
    Branch,
    Customer,
    GameSession,
    Invoice,
    InvoiceAdjustment,
    InvoiceLine,
    Membership,
    MembershipTransaction,
    Order,
    Payment,
    Table,
    User,
)
from app.models.base import money
from app.models.enums import (
    ApprovalStatus,
    ApprovalType,
    InvoiceLineType,
    InvoiceStatus,
    LedgerEntryType,
    MembershipTxnType,
    OrderStatus,
    PaymentMethod,
    PaymentPurpose,
    PaymentStatus,
)
from app.services import customer_service, table_service
from app.services.audit import audit
from app.services.common import branch_settings, next_number
from app.services.pricing import SessionCharge, compute_session_charge, q, tax_for


# ============================================================================ charge preview
@dataclass
class ChargePreview:
    charge: SessionCharge
    membership: Membership | None
    products_total: Decimal
    product_discount: Decimal
    deposit: Decimal
    estimated_total: Decimal


def _membership_daily_left(db: Session, m: Membership) -> int | None:
    if not m.plan.max_minutes_per_day:
        return None
    start_of_day = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    used_today = -(db.scalar(select(func.coalesce(func.sum(MembershipTransaction.minutes), 0)).where(
        MembershipTransaction.membership_id == m.id, MembershipTransaction.txn_type == MembershipTxnType.USAGE,
        MembershipTransaction.created_at >= start_of_day)) or 0)
    return max(0, m.plan.max_minutes_per_day - used_today)


def session_charge(db: Session, s: GameSession, until=None) -> tuple[SessionCharge, Membership | None]:
    from app.services.session_service import active_intervals

    table = db.get(Table, s.table_id)
    branch = db.get(Branch, s.branch_id)
    cfg = branch_settings(branch).billing
    m = db.get(Membership, s.membership_id) if s.membership_id else None
    intervals = active_intervals(s, until)
    days = (intervals[0][0].date(), intervals[-1][1].date()) if intervals else None
    ctx = table_service.pricing_context(db, table, is_member=m is not None, days=days)
    charge = compute_session_charge(
        ctx, intervals, cfg,
        membership_remaining=m.minutes_remaining if m else 0,
        membership_block=m.plan.deduction_block_minutes if m else 30,
        membership_daily_left=_membership_daily_left(db, m) if m else None,
        member_discount_percent=Decimal(str(m.plan.table_discount_percent)) if m else Decimal("0"),
    )
    return charge, m


def preview(db: Session, s: GameSession) -> ChargePreview:
    """Live running bill shown on the dashboard (never persisted)."""
    charge, m = session_charge(db, s)
    order = db.scalar(select(Order).where(Order.session_id == s.id))
    products = money(sum((money(i.amount) for i in order.items if i.status == "ACTIVE"), Decimal("0"))) if order else Decimal("0.00")
    pdisc = q(products * Decimal(str(m.plan.product_discount_percent)) / 100) if m and m.plan.product_discount_percent else Decimal("0.00")
    deposit = Decimal("0.00")
    if s.booking_id:
        b = db.get(Booking, s.booking_id)
        deposit = money(b.amount_paid) if b else deposit
    total = money(charge.time_amount - charge.member_discount + products - pdisc)
    return ChargePreview(charge, m, products, pdisc, deposit, total)


# ============================================================================ invoice generation
def _line(inv: Invoice, pos: int, t: InvoiceLineType, desc: str, amount: Decimal, *, qty=Decimal("1"), unit=None, product_id=None, meta=None) -> InvoiceLine:
    ln = InvoiceLine(position=pos, line_type=t, description=desc[:200], quantity=qty, unit_price=money(unit if unit is not None else amount),
                     amount=money(amount), product_id=product_id, meta=meta or {})
    inv.lines.append(ln)
    return ln


def _fmt_minutes(m: int) -> str:
    h, mm = divmod(int(m), 60)
    return f"{h}h {mm:02d}m" if h else f"{mm}m"


def generate_for_session(db: Session, actor: Principal | None, s: GameSession, events: PendingEvents) -> Invoice:
    if db.scalar(select(Invoice.id).where(Invoice.session_id == s.id)):
        raise Conflict("Invoice already generated for this session")
    branch = db.get(Branch, s.branch_id)
    table = db.get(Table, s.table_id)
    cfg = branch_settings(branch).billing
    charge, m = session_charge(db, s, s.ended_at)
    inv = Invoice(branch_id=branch.id, number=next_number(db, branch, "INV", "INV"), status=InvoiceStatus.ISSUED, session_id=s.id,
                  booking_id=s.booking_id, customer_id=s.customer_id, issued_at=utcnow(), issued_by_id=actor.id if actor else None)
    if s.customer_id:
        inv.customer_name = db.get(Customer, s.customer_id).name
    pos = 0
    game = table.game_type.name
    for seg in charge.segments:
        pos += 1
        _line(inv, pos, InvoiceLineType.TABLE_TIME, f"{game} · {table.name} · {seg.rule} ({_fmt_minutes(seg.minutes)} @ ₹{seg.rate_per_hour}/h)",
              seg.amount, qty=Decimal(seg.minutes), unit=q(seg.rate_per_hour / 60),
              meta={"from": seg.start.isoformat(), "to": seg.end.isoformat(), "rate_per_hour": str(seg.rate_per_hour)})
    if not charge.segments and charge.covered_minutes == 0:
        pos += 1
        _line(inv, pos, InvoiceLineType.TABLE_TIME, f"{game} · {table.name} (within grace period)", Decimal("0"))
    if m and charge.covered_minutes:
        pos += 1
        _line(inv, pos, InvoiceLineType.MEMBERSHIP_COVERED, f"Membership {m.code} · {_fmt_minutes(charge.covered_minutes)} covered", Decimal("0"),
              meta={"membership_id": str(m.id), "minutes": charge.covered_minutes})
        locked = db.scalar(for_update(select(Membership).where(Membership.id == m.id), db))
        locked.minutes_used += charge.covered_minutes
        db.add(MembershipTransaction(membership_id=m.id, txn_type=MembershipTxnType.USAGE, minutes=-charge.covered_minutes, session_id=s.id,
                                     created_by_id=actor.id if actor else None, note=f"Table {table.table_number}", created_at=utcnow()))
    discount = Decimal("0")
    if charge.member_discount:
        pos += 1
        _line(inv, pos, InvoiceLineType.DISCOUNT, f"Member discount ({m.plan.table_discount_percent}%)", -charge.member_discount)
        discount += charge.member_discount
    order = db.scalar(select(Order).where(Order.session_id == s.id))
    if order:
        pos = _add_order_lines(inv, order, pos, m)
        order.status = OrderStatus.INVOICED
    # Deposit already received for the booking is applied to the invoice.
    if s.booking_id:
        b = db.get(Booking, s.booking_id)
        if b and b.amount_paid:
            inv.deposit_applied = money(b.amount_paid)
    _recalc(inv, cfg)
    db.add(inv)
    db.flush()
    for p in db.scalars(select(Payment).where(Payment.booking_id == s.booking_id, Payment.status == PaymentStatus.PAID)).all() if s.booking_id else []:
        p.invoice_id = p.invoice_id or inv.id
    audit(db, actor, "invoice.issue", "invoice", inv.id, branch_id=branch.id, after={"number": inv.number, "total": inv.total, "session_id": s.id})
    events.add(branch.id, "invoice.issued", {"invoice_id": inv.id, "number": inv.number, "total": inv.total, "table_id": s.table_id, "balance_due": inv.balance_due})
    return inv


def _add_order_lines(inv: Invoice, order: Order, pos: int, m: Membership | None) -> int:
    products = Decimal("0")
    for it in order.items:
        if it.status != "ACTIVE":
            continue
        pos += 1
        products += money(it.amount)
        _line(inv, pos, InvoiceLineType.PRODUCT, it.name, money(it.amount), qty=it.quantity, unit=money(it.unit_price), product_id=it.product_id)
    if m and m.plan.product_discount_percent and products:
        d = q(products * Decimal(str(m.plan.product_discount_percent)) / 100)
        pos += 1
        _line(inv, pos, InvoiceLineType.DISCOUNT, f"Member discount on F&B ({m.plan.product_discount_percent}%)", -d)
    return pos


def generate_for_order(db: Session, actor: Principal, order: Order) -> Invoice:
    """Direct counter sale (no table)."""
    branch = db.get(Branch, order.branch_id)
    inv = Invoice(branch_id=branch.id, number=next_number(db, branch, "INV", "INV"), status=InvoiceStatus.ISSUED, order_id=order.id,
                  customer_id=order.customer_id, issued_at=utcnow(), issued_by_id=actor.id)
    if order.customer_id:
        inv.customer_name = db.get(Customer, order.customer_id).name
    m = None
    if order.customer_id:
        from app.services.booking_service import _active_membership

        m = _active_membership(db, order.customer_id)
    _add_order_lines(inv, order, 0, m)
    order.status = OrderStatus.INVOICED
    _recalc(inv, branch_settings(branch).billing)
    db.add(inv)
    db.flush()
    audit(db, actor, "invoice.issue", "invoice", inv.id, branch_id=branch.id, after={"number": inv.number, "total": inv.total, "order_id": order.id})
    return inv


def _recalc(inv: Invoice, cfg) -> None:
    """Derive every total from lines + adjustments + payments (single source of truth)."""
    positive = sum((money(ln.amount) for ln in inv.lines if ln.line_type not in (InvoiceLineType.DISCOUNT, InvoiceLineType.TAX)), Decimal("0"))
    discounts = -sum((money(ln.amount) for ln in inv.lines if ln.line_type == InvoiceLineType.DISCOUNT), Decimal("0"))
    adjustments = sum((money(a.amount) for a in inv.adjustments), Decimal("0"))
    base = money(positive - discounts + adjustments)
    tax = tax_for(max(base, Decimal("0")), cfg)
    inv.subtotal = money(positive)
    inv.discount_total = money(discounts)
    inv.adjustments_total = money(adjustments)
    inv.tax_total = tax
    inv.total = base if cfg.prices_include_tax else money(base + tax)
    inv.balance_due = money(inv.total - money(inv.deposit_applied) - money(inv.amount_paid))
    if inv.status == InvoiceStatus.VOID:
        return
    if inv.balance_due <= 0:
        inv.status = InvoiceStatus.PAID
        inv.paid_at = inv.paid_at or utcnow()
    elif money(inv.amount_paid) > 0 or money(inv.deposit_applied) > 0:
        inv.status = InvoiceStatus.PARTIALLY_PAID
    else:
        inv.status = InvoiceStatus.ISSUED


def get_invoice(db: Session, invoice_id: uuid.UUID, *, lock: bool = False) -> Invoice:
    stmt = select(Invoice).where(Invoice.id == invoice_id)
    inv = db.scalar(for_update(stmt, db) if lock else stmt)
    if not inv:
        raise NotFound("Invoice not found")
    return inv


def _cfg(db: Session, inv: Invoice):
    return branch_settings(db.get(Branch, inv.branch_id)).billing


# ============================================================================ payments
def take_payment(db: Session, actor: Principal, invoice_id: uuid.UUID, splits: list[dict], *, idempotency_key: str | None = None) -> Invoice:
    """Counter payment, possibly split across methods (e.g. ₹300 cash + ₹200 UPI).

    CREDIT ("Due") adds the amount to the customer's outstanding ledger — a
    registered customer is mandatory (legacy rule)."""
    events = PendingEvents()
    inv = get_invoice(db, invoice_id, lock=True)
    actor.require("billing.operate", inv.branch_id)
    if idempotency_key and db.scalar(select(Payment.id).where(Payment.idempotency_key == f"{idempotency_key}:0")):
        return inv  # replayed request (double-tap / network retry)
    if inv.status in (InvoiceStatus.PAID, InvoiceStatus.VOID):
        raise InvalidState(f"Invoice is {inv.status}")
    total = money(sum((money(s["amount"]) for s in splits), Decimal("0")))
    if total <= 0:
        raise ValidationFailed("Payment amount must be positive")
    if total > money(inv.balance_due):
        raise ValidationFailed(f"Payment {total} exceeds balance due {inv.balance_due}", code="OVERPAYMENT")
    from app.services import shift_service

    shift_id = shift_service.current_shift_id(db, actor)
    for i, sp in enumerate(splits):
        method = PaymentMethod(sp["method"])
        amt = money(sp["amount"])
        if amt <= 0:
            continue
        cust_id = sp.get("customer_id") or inv.customer_id
        if method == PaymentMethod.CREDIT and not cust_id:
            raise ValidationFailed("Credit (Due) requires a registered customer", code="CUSTOMER_REQUIRED")
        if method in (PaymentMethod.UPI, PaymentMethod.CARD) and not sp.get("reference"):
            raise ValidationFailed(f"{method} payments need a reference / transaction id", code="REFERENCE_REQUIRED")
        p = Payment(branch_id=inv.branch_id, purpose=PaymentPurpose.INVOICE, method=method, status=PaymentStatus.PAID, amount=amt,
                    invoice_id=inv.id, customer_id=cust_id, reference=sp.get("reference"), received_by_id=actor.id, shift_id=shift_id,
                    paid_at=utcnow(), idempotency_key=f"{idempotency_key}:{i}" if idempotency_key else None)
        db.add(p)
        db.flush()
        if method == PaymentMethod.CREDIT:
            customer_service.add_ledger(db, branch_id=inv.branch_id, customer_id=cust_id, entry_type=LedgerEntryType.CREDIT_SALE, amount=amt,
                                        actor=actor, invoice_id=inv.id, payment_id=p.id, note=f"Invoice {inv.number}")
    apply_payment(db, inv.id, events, invoice=inv)
    audit(db, actor, "invoice.payment", "invoice", inv.id, branch_id=inv.branch_id, after={"splits": splits, "balance_due": inv.balance_due})
    db.commit()
    events.flush()
    return inv


def apply_payment(db: Session, invoice_id: uuid.UUID, events: PendingEvents, invoice: Invoice | None = None) -> Invoice:
    inv = invoice or get_invoice(db, invoice_id, lock=True)
    was_paid = inv.status == InvoiceStatus.PAID
    paid = db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(
        Payment.invoice_id == inv.id, Payment.purpose.in_([PaymentPurpose.INVOICE, PaymentPurpose.REFUND]), Payment.status.in_([PaymentStatus.PAID, PaymentStatus.REFUNDED])))
    inv.amount_paid = money(paid)
    _recalc(inv, _cfg(db, inv))
    if inv.status == InvoiceStatus.PAID and not was_paid:
        _on_invoice_settled(db, inv)
        events.add(inv.branch_id, "invoice.paid", {"invoice_id": inv.id, "number": inv.number, "total": inv.total})
    return inv


def _on_invoice_settled(db: Session, inv: Invoice) -> None:
    from app.services import loyalty_service

    play = 0
    if inv.session_id:
        s = db.get(GameSession, inv.session_id)
        play = s.duration_seconds or 0
    customer_service.record_visit(db, inv.customer_id, spend=money(inv.total), play_seconds=play)
    if inv.customer_id:
        loyalty_service.earn_for_invoice(db, inv)


# ============================================================================ discounts / adjustments
def request_or_apply_discount(db: Session, actor: Principal, invoice_id: uuid.UUID, amount: Decimal, reason: str) -> dict:
    """Staff within their limit (or holding billing.discount) apply immediately;
    otherwise an approval request is created for a manager (maker-checker)."""
    inv = get_invoice(db, invoice_id, lock=True)
    actor.require("billing.operate", inv.branch_id)
    amount = money(amount)
    if amount <= 0 or amount > money(inv.balance_due):
        raise ValidationFailed("Discount must be positive and not exceed the balance due")
    cfg = _cfg(db, inv)
    limit = q(money(inv.total) * Decimal(str(cfg.staff_discount_limit_percent)) / 100)
    if actor.has("billing.discount", inv.branch_id) or amount <= limit:
        _add_adjustment(db, actor, inv, -amount, f"Discount: {reason}", approved_by=actor.id)
        db.commit()
        return {"applied": True, "invoice": inv}
    req = ApprovalRequest(branch_id=inv.branch_id, approval_type=ApprovalType.DISCOUNT, invoice_id=inv.id, amount=amount, reason=reason, requested_by_id=actor.id)
    db.add(req)
    db.flush()
    audit(db, actor, "approval.request", "approval_request", req.id, branch_id=inv.branch_id, after={"type": "DISCOUNT", "amount": amount, "invoice": inv.number})
    db.commit()
    hub.publish(inv.branch_id, "approval.requested", {"id": str(req.id), "type": "DISCOUNT", "amount": str(amount)})
    return {"applied": False, "approval_request_id": req.id, "invoice": inv}


def add_adjustment(db: Session, actor: Principal, invoice_id: uuid.UUID, amount: Decimal, reason: str) -> Invoice:
    """Credit (-) / debit (+) note, e.g. correcting a ₹1000 bill to ₹800 = -200 adjustment.
    The original lines remain untouched and visible."""
    inv = get_invoice(db, invoice_id, lock=True)
    actor.require("billing.adjust", inv.branch_id)
    if not reason or len(reason.strip()) < 3:
        raise ValidationFailed("A reason is required for adjustments")
    _add_adjustment(db, actor, inv, money(amount), reason, approved_by=actor.id)
    db.commit()
    return inv


def _add_adjustment(db: Session, actor: Principal, inv: Invoice, amount: Decimal, reason: str, approved_by=None) -> None:
    if inv.status == InvoiceStatus.VOID:
        raise InvalidState("Invoice is void")
    if amount < 0 and -amount > money(inv.balance_due) + Decimal("0.001"):
        raise ValidationFailed("Adjustment exceeds the unpaid balance; issue a refund instead", code="ADJUSTMENT_EXCEEDS_BALANCE")
    before = {"total": inv.total, "balance_due": inv.balance_due}
    adj = InvoiceAdjustment(invoice_id=inv.id, amount=amount, reason=reason, created_by_id=actor.id, approved_by_id=approved_by, created_at=utcnow())
    db.add(adj)
    inv.adjustments.append(adj)
    was_paid = inv.status == InvoiceStatus.PAID
    _recalc(inv, _cfg(db, inv))
    if inv.status == InvoiceStatus.PAID and not was_paid:
        _on_invoice_settled(db, inv)
    audit(db, actor, "invoice.adjust", "invoice", inv.id, branch_id=inv.branch_id, before=before,
          after={"adjustment": amount, "total": inv.total, "balance_due": inv.balance_due}, reason=reason)


def resolve_approval(db: Session, actor: Principal, request_id: uuid.UUID, approve: bool, note: str | None) -> ApprovalRequest:
    req = db.scalar(for_update(select(ApprovalRequest).where(ApprovalRequest.id == request_id), db))
    if not req:
        raise NotFound("Request not found")
    actor.require("approvals.resolve", req.branch_id)
    if req.status != ApprovalStatus.PENDING:
        raise InvalidState("Request already resolved")
    if req.requested_by_id == actor.id and not actor.has("org.manage"):
        raise Forbidden("You cannot approve your own request")
    req.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
    req.resolved_by_id, req.resolved_at, req.resolution_note = actor.id, utcnow(), note
    if approve:
        if req.approval_type == ApprovalType.DISCOUNT and req.invoice_id:
            inv = get_invoice(db, req.invoice_id, lock=True)
            requester = db.get(User, req.requested_by_id)
            _add_adjustment(db, actor, inv, -money(req.amount), f"Discount (approved): {req.reason} — requested by {requester.username}", approved_by=actor.id)
            req.consumed = True
        elif req.approval_type == ApprovalType.CANCEL_ITEM and req.order_item_id:
            from app.services import pos_service

            pos_service.cancel_item_approved(db, actor, req.order_item_id, req.reason)
            req.consumed = True
    audit(db, actor, "approval.resolve", "approval_request", req.id, branch_id=req.branch_id, after={"status": req.status}, reason=note)
    db.commit()
    return req


def void_invoice(db: Session, actor: Principal, invoice_id: uuid.UUID, reason: str) -> Invoice:
    """Void an unpaid invoice and reverse its side effects (membership minutes,
    stock). Paid invoices must be refunded, never voided."""
    inv = get_invoice(db, invoice_id, lock=True)
    actor.require("billing.adjust", inv.branch_id)
    if money(inv.amount_paid) > 0:
        raise InvalidState("Invoice has payments; refund them first")
    before = {"status": inv.status, "total": inv.total}
    inv.status = InvoiceStatus.VOID
    inv.balance_due = Decimal("0.00")
    if inv.session_id:
        for t in db.scalars(select(MembershipTransaction).where(MembershipTransaction.session_id == inv.session_id, MembershipTransaction.txn_type == MembershipTxnType.USAGE)).all():
            m = db.scalar(for_update(select(Membership).where(Membership.id == t.membership_id), db))
            m.minutes_used = max(0, m.minutes_used + t.minutes)
            db.add(MembershipTransaction(membership_id=m.id, txn_type=MembershipTxnType.USAGE_REVERSAL, minutes=-t.minutes, session_id=inv.session_id,
                                         created_by_id=actor.id, note=f"Void {inv.number}", created_at=utcnow()))
    order = db.get(Order, inv.order_id) if inv.order_id else (db.scalar(select(Order).where(Order.session_id == inv.session_id)) if inv.session_id else None)
    if order:
        from app.services import pos_service

        pos_service.reverse_order_stock(db, actor, order, f"Void {inv.number}")
        order.status = OrderStatus.CANCELLED
    audit(db, actor, "invoice.void", "invoice", inv.id, branch_id=inv.branch_id, before=before, after={"status": inv.status}, reason=reason)
    db.commit()
    return inv


def list_invoices(db: Session, actor: Principal, branch_id: uuid.UUID, *, status: str | None, offset: int, limit: int) -> tuple[list[Invoice], int]:
    actor.require("billing.operate", branch_id)
    stmt = select(Invoice).where(Invoice.branch_id == branch_id)
    if status:
        stmt = stmt.where(Invoice.status.in_(status.split(",")))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    return list(db.scalars(stmt.order_by(Invoice.issued_at.desc()).offset(offset).limit(limit)).all()), total


def settle_dues(db: Session, actor: Principal, customer_id: uuid.UUID, branch_id: uuid.UUID, amount: Decimal, method: PaymentMethod, reference: str | None) -> Payment:
    """Customer pays off outstanding "Credit (Due)" balance."""
    actor.require("billing.operate", branch_id)
    customer_service.get_customer(db, actor, customer_id)
    amount = money(amount)
    due = customer_service.outstanding(db, customer_id)
    if amount <= 0 or amount > due:
        raise ValidationFailed(f"Amount must be between 0 and outstanding {due}")
    if method == PaymentMethod.CREDIT:
        raise ValidationFailed("Dues cannot be settled with credit")
    from app.services import shift_service

    p = Payment(branch_id=branch_id, purpose=PaymentPurpose.DUE_SETTLEMENT, method=method, status=PaymentStatus.PAID, amount=amount, customer_id=customer_id,
                reference=reference, received_by_id=actor.id, paid_at=utcnow(), shift_id=shift_service.current_shift_id(db, actor))
    db.add(p)
    db.flush()
    customer_service.add_ledger(db, branch_id=branch_id, customer_id=customer_id, entry_type=LedgerEntryType.PAYMENT, amount=-amount, actor=actor, payment_id=p.id,
                                note=f"Due payment ({method})")
    audit(db, actor, "customer.due_payment", "customer", customer_id, branch_id=branch_id, after={"amount": amount, "method": method})
    db.commit()
    return p
