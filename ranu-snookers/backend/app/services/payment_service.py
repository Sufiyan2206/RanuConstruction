"""Payments: online checkout orders, authoritative webhooks (idempotent),
refunds as separate ledger rows, and the mock-provider test harness."""
from __future__ import annotations

import json
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import for_update
from app.core.deps import Principal
from app.core.errors import AppError, Forbidden, InvalidState, NotFound, ValidationFailed
from app.core.realtime import PendingEvents
from app.core.timeutil import utcnow
from app.models import Booking, Membership, Payment, PaymentWebhookEvent
from app.models.base import money
from app.models.enums import BookingStatus, PaymentMethod, PaymentPurpose, PaymentStatus
from app.payments.providers import CheckoutOrder, MockProvider, get_provider
from app.services.audit import audit, raise_alert


def start_booking_checkout(db: Session, booking: Booking) -> tuple[Payment, CheckoutOrder | None]:
    """Create the provider order for a HELD booking's deposit. Called *after* the
    hold transaction committed so no DB lock is held during the HTTP call."""
    if booking.status != BookingStatus.HELD or booking.deposit_amount <= 0:
        return None, None  # type: ignore[return-value]
    existing = db.scalar(select(Payment).where(Payment.booking_id == booking.id, Payment.status == PaymentStatus.PENDING))
    provider = get_provider()
    try:
        order = provider.create_order(
            amount=money(booking.deposit_amount), currency=settings.CURRENCY, reference=booking.reference,
            customer={"name": booking.customer.name, "phone": booking.customer.phone, "email": booking.customer.email},
            metadata={"booking_id": booking.id, "purpose": PaymentPurpose.BOOKING_DEPOSIT},
        )
    except AppError:
        # Provider down: release the hold so the table is not blocked.
        booking.status = BookingStatus.EXPIRED
        db.commit()
        raise
    if existing:
        existing.status = PaymentStatus.CANCELLED
    p = Payment(
        branch_id=booking.branch_id, purpose=PaymentPurpose.BOOKING_DEPOSIT, method=PaymentMethod.ONLINE, status=PaymentStatus.PENDING,
        amount=money(booking.deposit_amount), currency=settings.CURRENCY, booking_id=booking.id, customer_id=booking.customer_id,
        provider=provider.name, provider_order_id=order.provider_order_id,
    )
    db.add(p)
    db.commit()
    return p, order


def handle_webhook(db: Session, provider_name: str, headers: dict[str, str], body: bytes) -> dict:
    """Authoritative payment confirmation. Idempotent on (provider, event_id)."""
    provider = get_provider(provider_name)
    result = provider.verify_webhook({k.lower(): v for k, v in headers.items()}, body)
    events = PendingEvents()
    evt = PaymentWebhookEvent(provider=provider.name, event_id=result.event_id, event_type=result.event_type, payload=result.raw, received_at=utcnow())
    db.add(evt)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"status": "duplicate", "event_id": result.event_id}

    outcome = "IGNORED"
    payment = None
    if result.provider_order_id:
        payment = db.scalar(for_update(select(Payment).where(Payment.provider == provider.name, Payment.provider_order_id == result.provider_order_id), db))
    if payment is None:
        outcome = "UNKNOWN_ORDER"
    elif result.status == "PAID":
        if payment.status == PaymentStatus.PAID:
            outcome = "ALREADY_PAID"
        else:
            if result.amount is not None and money(result.amount) != money(payment.amount):
                raise_alert(db, payment.branch_id, "PAYMENT_AMOUNT_MISMATCH", f"Provider amount {result.amount} != expected {payment.amount}",
                            dedupe_key=f"amt:{payment.id}", events=events)
                payment.amount = money(result.amount)
            payment.status = PaymentStatus.PAID
            payment.provider_payment_id = result.provider_payment_id
            payment.paid_at = utcnow()
            outcome = _on_paid(db, payment, events)
    elif result.status == "FAILED":
        if payment.status == PaymentStatus.PENDING:
            payment.status = PaymentStatus.FAILED
            payment.failure_reason = result.event_type
        outcome = "FAILED"
    elif result.status == "AUTHORIZED":
        if payment.status == PaymentStatus.PENDING:
            payment.status = PaymentStatus.AUTHORIZED
        outcome = "AUTHORIZED"
    evt.processed_at = utcnow()
    evt.result = outcome
    db.commit()
    events.flush()
    return {"status": "processed", "outcome": outcome}


def _on_paid(db: Session, payment: Payment, events: PendingEvents) -> str:
    if payment.purpose == PaymentPurpose.BOOKING_DEPOSIT:
        from app.services import booking_service

        return booking_service.on_deposit_paid(db, payment, events)
    if payment.purpose == PaymentPurpose.MEMBERSHIP and payment.membership_id:
        from app.services import membership_service

        membership_service.activate_after_payment(db, db.get(Membership, payment.membership_id))
        return "MEMBERSHIP_ACTIVATED"
    if payment.purpose == PaymentPurpose.INVOICE and payment.invoice_id:
        from app.services import billing_service

        billing_service.apply_payment(db, payment.invoice_id, events)
        return "INVOICE_PAID"
    return "PAID"


def refund_payment(db: Session, actor: Principal | None, original: Payment, amount: Decimal, reason: str, *,
                   events: PendingEvents | None = None, commit: bool = True, policy: bool = False) -> Payment:
    """Refunds are NEW rows (purpose=REFUND, negative amount) — the original is never edited
    except for its status marker. `policy=True` marks automatic refunds computed by the
    cancellation policy (no discretionary permission needed)."""
    if actor is not None and not policy and not actor.has("payments.refund", original.branch_id):
        raise Forbidden("Missing permission 'payments.refund'")
    amount = money(amount)
    if amount <= 0:
        raise ValidationFailed("Refund amount must be positive")
    already = sum((money(-r.amount) for r in db.scalars(select(Payment).where(Payment.refund_of_id == original.id)).all()), Decimal("0"))
    if amount + already > money(original.amount):
        raise InvalidState("Refund exceeds the refundable amount")
    provider_ref = None
    if original.provider and original.provider_payment_id:
        provider_ref = get_provider(original.provider).refund(provider_payment_id=original.provider_payment_id, amount=amount)
    r = Payment(
        branch_id=original.branch_id, purpose=PaymentPurpose.REFUND, method=original.method, status=PaymentStatus.REFUNDED,
        amount=-amount, currency=original.currency, booking_id=original.booking_id, invoice_id=original.invoice_id,
        customer_id=original.customer_id, provider=original.provider, provider_payment_id=provider_ref, refund_of_id=original.id,
        received_by_id=actor.id if actor else None, paid_at=utcnow(), meta={"reason": reason},
    )
    db.add(r)
    if amount + already == money(original.amount):
        original.status = PaymentStatus.REFUNDED
    audit(db, actor, "payment.refund", "payment", original.id, branch_id=original.branch_id, after={"refund": amount, "provider_ref": provider_ref}, reason=reason)
    if events is not None:
        events.add(original.branch_id, "payment.refunded", {"payment_id": original.id, "amount": amount})
    if commit:
        db.commit()
    return r


def mock_complete(db: Session, provider_order_id: str, *, succeed: bool = True) -> dict:
    """DEV ONLY: emulate the provider calling our webhook after the customer pays."""
    if settings.PAYMENT_PROVIDER != "mock" or settings.ENVIRONMENT == "production":
        raise NotFound("Not available")
    p = db.scalar(select(Payment).where(Payment.provider_order_id == provider_order_id))
    if not p:
        raise NotFound("Order not found")
    body = json.dumps({
        "event_id": f"evt_{uuid.uuid4().hex[:16]}", "type": "payment.captured" if succeed else "payment.failed", "order_id": provider_order_id,
        "payment_id": f"mock_pay_{uuid.uuid4().hex[:14]}", "status": "PAID" if succeed else "FAILED", "amount": str(p.amount),
    }).encode()
    return handle_webhook(db, "mock", {"x-mock-signature": MockProvider.sign(body)}, body)
