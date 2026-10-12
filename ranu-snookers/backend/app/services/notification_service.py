"""Notification outbox: business code enqueues (in its own transaction);
a worker delivers with retries. Templates come from the DB with sane defaults."""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import to_local, utcnow
from app.models import Booking, Branch, Customer, GameSession, Membership, Notification, NotificationTemplate
from app.models.enums import MembershipStatus, NotificationStatus, SessionStatus
from app.notifications.providers import get_channel_provider
from app.services.common import branch_settings

log = logging.getLogger("app.notifications")

DEFAULT_TEMPLATES: dict[str, tuple[str, str]] = {
    "booking.confirmed": ("Booking confirmed – {ref}", "Hi {name}, your {game} booking {ref} at {branch} is confirmed for {when} on {table}. Deposit paid: ₹{paid}. See you!"),
    "booking.reminder": ("Reminder – {ref}", "Hi {name}, reminder: {table} at {branch} is booked for you at {when}. Booking {ref}."),
    "booking.cancelled": ("Booking cancelled – {ref}", "Hi {name}, booking {ref} for {when} was cancelled. Refund: ₹{refund}."),
    "session.started": ("Game started", "Hi {name}, your game on {table} started at {when}. Enjoy!"),
    "session.ending": ("Session ending soon", "Hi {name}, your time on {table} ends at {when}. Ask the counter to extend."),
    "invoice.issued": ("Your bill {number}", "Hi {name}, your bill {number} is ₹{total}. Thank you for playing at {branch}!"),
    "membership.purchased": ("Welcome to {plan}", "Hi {name}, your membership {code} ({plan}) is active until {expires_on}."),
    "membership.expiring": ("Membership expiring", "Hi {name}, your membership {code} expires on {expires_on}. Renew at the counter or online."),
    "promo": ("{subject}", "{message}"),
}


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render(db: Session, organization_id: uuid.UUID, event: str, channel: str, context: dict) -> tuple[str | None, str]:
    t = db.scalar(select(NotificationTemplate).where(NotificationTemplate.organization_id == organization_id, NotificationTemplate.event == event,
                                                     NotificationTemplate.channel == channel, NotificationTemplate.is_active.is_(True)))
    subject, body = (t.subject, t.body) if t else DEFAULT_TEMPLATES.get(event, (event, "{message}"))
    ctx = _SafeDict({k: v for k, v in context.items()})
    return (subject.format_map(ctx) if subject else None), body.format_map(ctx)


def enqueue(db: Session, *, event: str, customer: Customer | None, branch_id: uuid.UUID | None, context: dict, dedupe: str | None = None) -> list[Notification]:
    if customer is None:
        return []
    channels = ["WHATSAPP", "EMAIL"]
    if branch_id:
        channels = branch_settings(db.get(Branch, branch_id)).notifications.channels
    out = []
    for ch in channels:
        recipient = customer.email if ch == "EMAIL" else customer.phone
        if not recipient:
            continue
        key = f"{dedupe}:{ch}" if dedupe else None
        if key and db.scalar(select(Notification.id).where(Notification.dedupe_key == key)):
            continue
        subject, body = render(db, customer.organization_id, event, ch, context)
        n = Notification(branch_id=branch_id, customer_id=customer.id, event=event, channel=ch, recipient=recipient, subject=subject, body=body,
                         dedupe_key=key, created_at=utcnow())
        db.add(n)
        out.append(n)
    return out


def _booking_ctx(db: Session, b: Booking) -> dict:
    branch = db.get(Branch, b.branch_id)
    local = to_local(b.start_at, branch.timezone)
    return {"name": b.customer.name, "ref": b.reference, "branch": branch.name, "table": b.table.name, "game": b.table.game_type.name,
            "when": local.strftime("%d %b %Y, %I:%M %p"), "paid": b.amount_paid, "refund": b.refund_amount}


def enqueue_for_booking(db: Session, b: Booking, event: str) -> None:
    enqueue(db, event=event, customer=b.customer, branch_id=b.branch_id, context=_booking_ctx(db, b), dedupe=f"{event}:{b.id}:{b.start_at.isoformat()}")


def enqueue_for_session(db: Session, s: GameSession, event: str, when=None) -> None:
    if not s.customer_id:
        return
    branch = db.get(Branch, s.branch_id)
    c = db.get(Customer, s.customer_id)
    at = when or s.started_at or utcnow()
    enqueue(db, event=event, customer=c, branch_id=s.branch_id, dedupe=f"{event}:{s.id}",
            context={"name": c.name, "table": s.table.name, "when": to_local(at, branch.timezone).strftime("%I:%M %p")})


def dispatch_pending(db: Session, batch: int = 50) -> int:
    rows = db.scalars(select(Notification).where(Notification.status == NotificationStatus.QUEUED, Notification.attempts < 5)
                      .order_by(Notification.created_at).limit(batch)).all()
    sent = 0
    for n in rows:
        n.attempts += 1
        try:
            get_channel_provider(n.channel).send(n.recipient, n.subject, n.body)
            n.status, n.sent_at = NotificationStatus.SENT, utcnow()
            sent += 1
        except Exception as e:  # provider failure => retry later
            n.last_error = str(e)[:300]
            if n.attempts >= 5:
                n.status = NotificationStatus.FAILED
            log.warning("notification_failed", extra={"id": str(n.id), "error": str(e)[:200]})
    db.commit()
    return sent


def schedule_reminders(db: Session) -> int:
    """Worker: booking reminders, session-ending reminders, membership expiry."""
    now = utcnow()
    n = 0
    for b in db.scalars(select(Booking).where(Booking.status == "CONFIRMED", Booking.reminder_sent_at.is_(None), Booking.start_at > now,
                                              Booking.start_at < now + timedelta(hours=6))).unique().all():
        mins = branch_settings(db.get(Branch, b.branch_id)).notifications.booking_reminder_minutes
        if b.start_at - now <= timedelta(minutes=mins):
            enqueue_for_booking(db, b, "booking.reminder")
            b.reminder_sent_at = now
            n += 1
    for s in db.scalars(select(GameSession).where(GameSession.status == SessionStatus.ACTIVE, GameSession.planned_end_at.is_not(None),
                                                  GameSession.planned_end_at > now)).unique().all():
        mins = branch_settings(db.get(Branch, s.branch_id)).notifications.session_ending_reminder_minutes
        if s.planned_end_at - now <= timedelta(minutes=mins):
            enqueue_for_session(db, s, "session.ending", when=s.planned_end_at)
            n += 1
    for m in db.scalars(select(Membership).where(Membership.status == MembershipStatus.ACTIVE, Membership.expiry_notified_at.is_(None),
                                                 Membership.expires_on <= (now + timedelta(days=7)).date())).unique().all():
        enqueue(db, event="membership.expiring", customer=m.customer, branch_id=m.branch_id, dedupe=f"mexp:{m.id}:{m.expires_on}",
                context={"name": m.customer.name, "code": m.code, "expires_on": m.expires_on.isoformat()})
        m.expiry_notified_at = now
        n += 1
    db.commit()
    return n


def send_promotion(db: Session, actor, branch_id: uuid.UUID, subject: str, message: str) -> int:
    actor.require("notifications.manage", branch_id)
    count = 0
    for c in db.scalars(select(Customer).where(Customer.organization_id == actor.organization_id, Customer.marketing_opt_in.is_(True), Customer.deleted_at.is_(None))).all():
        count += len(enqueue(db, event="promo", customer=c, branch_id=branch_id, context={"subject": subject, "message": message, "name": c.name},
                             dedupe=f"promo:{subject}:{c.id}"))
    db.commit()
    return count
