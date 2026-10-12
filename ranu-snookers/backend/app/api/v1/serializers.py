"""Helpers converting ORM objects (+ computed fields) into response models."""
from __future__ import annotations

from app.schemas.domain import BookingOut, MembershipOut, QuoteOut


def booking_out(b) -> BookingOut:
    out = BookingOut.model_validate(b)
    out.customer_name = b.customer.name if b.customer else None
    out.customer_phone = b.customer.phone if b.customer else None
    return out


def quote_out(q) -> QuoteOut | None:
    if q is None:
        return None
    return QuoteOut(amount=q.amount, deposit=q.deposit, tax=q.tax,
                    segments=[{"start": s.start, "end": s.end, "minutes": s.minutes, "rate_per_hour": s.rate_per_hour, "rule": s.rule, "amount": s.amount} for s in q.segments])


def membership_out(m) -> MembershipOut:
    return MembershipOut.model_validate(m)
