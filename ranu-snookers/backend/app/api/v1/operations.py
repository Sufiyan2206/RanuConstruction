"""Bookings, sessions, billing, payments and approvals (staff + customer self-service)."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.serializers import booking_out
from app.core.database import get_db
from app.core.deps import PageParams, Principal, get_principal, page_params, require
from app.core.errors import Forbidden
from app.models import ApprovalRequest, Payment, SessionEvent
from app.schemas.common import Page
from app.schemas.domain import (
    AdjustmentIn,
    AdjustSessionIn,
    ApprovalOut,
    BookingOut,
    CancelIn,
    DiscountIn,
    ExtendIn,
    InvoiceOut,
    LiveChargeOut,
    PayIn,
    PaymentOut,
    ReasonIn,
    RescheduleIn,
    ResolveIn,
    SessionEventOut,
    SessionOut,
    SessionStartIn,
    StaffBookingIn,
    StopOut,
)
from app.services import billing_service, booking_service, customer_service, session_service

router = APIRouter(tags=["operations"])


# ============================================================================ bookings
@router.get("/bookings", response_model=Page[BookingOut])
def list_bookings(branch_id: uuid.UUID | None = None, status: str | None = None, frm: datetime | None = Query(None, alias="from"),
                  to: datetime | None = None, customer_id: uuid.UUID | None = None, page: PageParams = Depends(page_params),
                  p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    rows, total = booking_service.list_bookings(db, p, branch_id=branch_id, status=status, frm=frm, to=to, customer_id=customer_id, offset=page.offset, limit=page.size)
    return Page(items=[booking_out(b) for b in rows], total=total, page=page.page, size=page.size)


@router.post("/bookings", response_model=BookingOut, status_code=201)
def create_booking(body: StaffBookingIn, p: Principal = Depends(require("bookings.manage")), db: Session = Depends(get_db)):
    b = booking_service.create_staff_booking(db, p, branch_id=body.branch_id, table_id=body.table_id, start=body.start_at, duration=body.duration_minutes,
                                             customer_id=body.customer_id, customer=body.customer.model_dump() if body.customer else None,
                                             deposit_method=body.deposit_method, deposit_amount=body.deposit_amount, deposit_reference=body.deposit_reference,
                                             source=body.source, notes=body.notes)
    return booking_out(b)


@router.get("/bookings/{booking_id}", response_model=BookingOut)
def get_booking(booking_id: uuid.UUID, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    b = booking_service.get_booking(db, booking_id)
    if not (p.has("bookings.view", b.branch_id) or p.user.customer_id == b.customer_id):
        raise Forbidden("Not allowed")
    return booking_out(b)


@router.post("/bookings/{booking_id}/cancel", response_model=BookingOut)
def cancel_booking(booking_id: uuid.UUID, body: CancelIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return booking_out(booking_service.cancel(db, p, booking_id, body.reason, body.refund_amount))


@router.post("/bookings/{booking_id}/reschedule", response_model=BookingOut)
def reschedule(booking_id: uuid.UUID, body: RescheduleIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return booking_out(booking_service.reschedule(db, p, booking_id, start=body.start_at, duration=body.duration_minutes, table_id=body.table_id, reason=body.reason))


@router.post("/bookings/{booking_id}/check-in")
def check_in(booking_id: uuid.UUID, p: Principal = Depends(require("bookings.manage")), db: Session = Depends(get_db)):
    b, s, warning = booking_service.check_in(db, p, booking_id)
    return {"booking": booking_out(b), "session": SessionOut.model_validate(s) if s else None, "warning": warning}


@router.post("/bookings/{booking_id}/no-show", response_model=BookingOut)
def no_show(booking_id: uuid.UUID, p: Principal = Depends(require("bookings.manage")), db: Session = Depends(get_db)):
    return booking_out(booking_service.mark_no_show(db, p, booking_id))


@router.get("/bookings/{booking_id}/payments", response_model=list[PaymentOut])
def booking_payments(booking_id: uuid.UUID, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    b = booking_service.get_booking(db, booking_id)
    if not (p.has("bookings.view", b.branch_id) or p.user.customer_id == b.customer_id):
        raise Forbidden("Not allowed")
    return list(db.scalars(select(Payment).where(Payment.booking_id == b.id).order_by(Payment.created_at)).all())


# ============================================================================ sessions
@router.post("/sessions/start", response_model=SessionOut, status_code=201)
def start_session(body: SessionStartIn, p: Principal = Depends(require("sessions.operate")), db: Session = Depends(get_db)):
    """Walk-in or booked start (manual). Hardware-triggered starts use the device API."""
    cust_id = body.customer_id
    if not cust_id and body.customer:
        from app.models import Table

        t = db.get(Table, body.table_id)
        cust_id = customer_service.find_or_create(db, p.organization_id, name=body.customer.name, phone=body.customer.phone, email=body.customer.email,
                                                  branch_id=t.branch_id if t else None).id
    s, _ = session_service.start(db, p, body.table_id, customer_id=cust_id, booking_id=body.booking_id, planned_minutes=body.planned_minutes,
                                 player_count=body.player_count, override_reservation=body.override_reservation)
    return s


@router.get("/branches/{branch_id}/sessions/open", response_model=list[SessionOut])
def open_sessions(branch_id: uuid.UUID, p: Principal = Depends(require("sessions.view")), db: Session = Depends(get_db)):
    p.require("sessions.view", branch_id)
    return session_service.list_open_sessions(db, branch_id)


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session(session_id: uuid.UUID, p: Principal = Depends(require("sessions.view")), db: Session = Depends(get_db)):
    s = session_service.get_session(db, session_id)
    p.require("sessions.view", s.branch_id)
    return s


@router.get("/sessions/{session_id}/events", response_model=list[SessionEventOut])
def session_events(session_id: uuid.UUID, p: Principal = Depends(require("sessions.view")), db: Session = Depends(get_db)):
    s = session_service.get_session(db, session_id)
    p.require("sessions.view", s.branch_id)
    return list(db.scalars(select(SessionEvent).where(SessionEvent.session_id == s.id).order_by(SessionEvent.created_at)).all())


@router.get("/sessions/{session_id}/live", response_model=LiveChargeOut)
def live_charge(session_id: uuid.UUID, p: Principal = Depends(require("sessions.view")), db: Session = Depends(get_db)):
    s = session_service.get_session(db, session_id)
    p.require("sessions.view", s.branch_id)
    pv = billing_service.preview(db, s)
    return LiveChargeOut(session_id=s.id, elapsed_seconds=session_service.billable_seconds(s), billed_minutes=pv.charge.billed_minutes,
                         covered_minutes=pv.charge.covered_minutes, time_amount=pv.charge.time_amount, member_discount=pv.charge.member_discount,
                         products_total=pv.products_total, product_discount=pv.product_discount, deposit=pv.deposit, estimated_total=pv.estimated_total,
                         segments=[{"start": x.start, "end": x.end, "minutes": x.minutes, "rate_per_hour": x.rate_per_hour, "rule": x.rule, "amount": x.amount} for x in pv.charge.segments],
                         membership_code=pv.membership.code if pv.membership else None,
                         membership_minutes_remaining=pv.membership.minutes_remaining if pv.membership else None)


@router.post("/sessions/{session_id}/pause", response_model=SessionOut)
def pause(session_id: uuid.UUID, body: ReasonIn | None = None, p: Principal = Depends(require("sessions.operate")), db: Session = Depends(get_db)):
    return session_service.pause(db, p, session_id, body.reason if body else None)


@router.post("/sessions/{session_id}/resume", response_model=SessionOut)
def resume(session_id: uuid.UUID, p: Principal = Depends(require("sessions.operate")), db: Session = Depends(get_db)):
    return session_service.resume(db, p, session_id)


@router.post("/sessions/{session_id}/extend", response_model=SessionOut)
def extend(session_id: uuid.UUID, body: ExtendIn, p: Principal = Depends(require("sessions.operate")), db: Session = Depends(get_db)):
    return session_service.extend(db, p, session_id, body.minutes)


@router.post("/sessions/{session_id}/stop", response_model=StopOut)
def stop(session_id: uuid.UUID, p: Principal = Depends(require("sessions.operate")), db: Session = Depends(get_db)):
    s, inv = session_service.stop(db, p, session_id)
    return StopOut(session=SessionOut.model_validate(s), invoice=InvoiceOut.model_validate(inv))


@router.post("/sessions/{session_id}/cancel", response_model=SessionOut)
def cancel_session(session_id: uuid.UUID, body: ReasonIn, p: Principal = Depends(require("sessions.operate")), db: Session = Depends(get_db)):
    return session_service.cancel(db, p, session_id, body.reason)


@router.post("/sessions/{session_id}/adjust", response_model=SessionOut)
def adjust(session_id: uuid.UUID, body: AdjustSessionIn, p: Principal = Depends(require("sessions.adjust")), db: Session = Depends(get_db)):
    return session_service.adjust_times(db, p, session_id, started_at=body.started_at, reason=body.reason)


# ============================================================================ invoices & payments
@router.get("/branches/{branch_id}/invoices", response_model=Page[InvoiceOut])
def list_invoices(branch_id: uuid.UUID, status: str | None = None, page: PageParams = Depends(page_params),
                  p: Principal = Depends(require("billing.operate")), db: Session = Depends(get_db)):
    rows, total = billing_service.list_invoices(db, p, branch_id, status=status, offset=page.offset, limit=page.size)
    return Page(items=rows, total=total, page=page.page, size=page.size)


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
def get_invoice(invoice_id: uuid.UUID, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    inv = billing_service.get_invoice(db, invoice_id)
    if not (p.has("billing.operate", inv.branch_id) or (p.user.customer_id and p.user.customer_id == inv.customer_id)):
        raise Forbidden("Not allowed")
    return inv


@router.get("/invoices/{invoice_id}/payments", response_model=list[PaymentOut])
def invoice_payments(invoice_id: uuid.UUID, p: Principal = Depends(require("billing.operate")), db: Session = Depends(get_db)):
    inv = billing_service.get_invoice(db, invoice_id)
    p.require("billing.operate", inv.branch_id)
    return list(db.scalars(select(Payment).where(Payment.invoice_id == inv.id).order_by(Payment.created_at)).all())


@router.post("/invoices/{invoice_id}/pay", response_model=InvoiceOut)
def pay(invoice_id: uuid.UUID, body: PayIn, idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
        p: Principal = Depends(require("billing.operate")), db: Session = Depends(get_db)):
    """Split payments supported. Send an Idempotency-Key header to make retries safe."""
    return billing_service.take_payment(db, p, invoice_id, [s.model_dump() for s in body.splits], idempotency_key=idempotency_key)


@router.post("/invoices/{invoice_id}/discount")
def discount(invoice_id: uuid.UUID, body: DiscountIn, p: Principal = Depends(require("billing.operate")), db: Session = Depends(get_db)):
    r = billing_service.request_or_apply_discount(db, p, invoice_id, body.amount, body.reason)
    return {"applied": r["applied"], "approval_request_id": r.get("approval_request_id"), "invoice": InvoiceOut.model_validate(r["invoice"])}


@router.post("/invoices/{invoice_id}/adjustments", response_model=InvoiceOut)
def adjustment(invoice_id: uuid.UUID, body: AdjustmentIn, p: Principal = Depends(require("billing.adjust")), db: Session = Depends(get_db)):
    return billing_service.add_adjustment(db, p, invoice_id, body.amount, body.reason)


@router.post("/invoices/{invoice_id}/void", response_model=InvoiceOut)
def void(invoice_id: uuid.UUID, body: ReasonIn, p: Principal = Depends(require("billing.adjust")), db: Session = Depends(get_db)):
    return billing_service.void_invoice(db, p, invoice_id, body.reason)


@router.post("/payments/{payment_id}/refund", response_model=PaymentOut)
def refund(payment_id: uuid.UUID, body: AdjustmentIn, p: Principal = Depends(require("payments.refund")), db: Session = Depends(get_db)):
    from app.services import payment_service

    orig = db.get(Payment, payment_id)
    if not orig:
        from app.core.errors import NotFound

        raise NotFound("Payment not found")
    return payment_service.refund_payment(db, p, orig, abs(body.amount), body.reason)


# ============================================================================ approvals
@router.get("/branches/{branch_id}/approvals", response_model=list[ApprovalOut])
def approvals(branch_id: uuid.UUID, status: str = "PENDING", p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    stmt = select(ApprovalRequest).where(ApprovalRequest.branch_id == branch_id)
    if status:
        stmt = stmt.where(ApprovalRequest.status == status)
    if not p.has("approvals.resolve", branch_id):
        stmt = stmt.where(ApprovalRequest.requested_by_id == p.id)
    return list(db.scalars(stmt.order_by(ApprovalRequest.created_at.desc()).limit(200)).all())


@router.post("/approvals/{request_id}/resolve", response_model=ApprovalOut)
def resolve(request_id: uuid.UUID, body: ResolveIn, p: Principal = Depends(require("approvals.resolve")), db: Session = Depends(get_db)):
    return billing_service.resolve_approval(db, p, request_id, body.approve, body.note)

