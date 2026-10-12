"""Public (unauthenticated or customer) endpoints: the customer website.

Everything here is rate-limited and never exposes other customers' data.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.serializers import booking_out, quote_out
from app.core.database import get_db
from app.core.deps import Principal, get_optional_principal
from app.core.errors import NotFound
from app.core.ratelimit import rate_limit
from app.models import Organization
from app.schemas.domain import (
    AvailabilityOut,
    BookingOut,
    BranchOut,
    CheckoutOut,
    GameTypeOut,
    GuestLookupIn,
    HoldIn,
    PlanOut,
    PublicTableOut,
    QrStartIn,
)
from app.services import admin_service, booking_service, device_service, membership_service, payment_service, table_service

router = APIRouter(prefix="/public", tags=["public"], dependencies=[Depends(rate_limit("public"))])


def _org(db: Session) -> Organization:
    org = db.scalar(select(Organization).order_by(Organization.created_at))
    if not org:
        raise NotFound("Organisation not configured")
    return org


@router.get("/branches", response_model=list[BranchOut])
def branches(db: Session = Depends(get_db)):
    return admin_service.list_branches(db, _org(db).id)


@router.get("/game-types", response_model=list[GameTypeOut])
def game_types(db: Session = Depends(get_db)):
    return table_service.list_game_types(db, _org(db).id)


@router.get("/branches/{branch_id}/tables", response_model=list[PublicTableOut])
def tables(branch_id: uuid.UUID, db: Session = Depends(get_db)):
    return [t for t in table_service.list_tables(db, branch_id) if t.is_online_bookable]


@router.get("/membership-plans", response_model=list[PlanOut])
def plans(db: Session = Depends(get_db)):
    return membership_service.list_plans(db, _org(db).id, public_only=True)


@router.get("/availability", response_model=list[AvailabilityOut])
def availability(
    branch_id: uuid.UUID,
    start_at: datetime = Query(..., description="ISO-8601 with timezone, e.g. 2026-09-23T18:00:00+05:30"),
    duration_minutes: int = Query(60, ge=15, le=720),
    game_type_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    p: Principal | None = Depends(get_optional_principal),
):
    """Which tables are free for the requested slot, with a backend-computed price quote.
    Unavailable tables include `next_available_at` so customers know when they will be free."""
    items = booking_service.availability(db, branch_id, start=start_at, duration=duration_minutes, game_type_id=game_type_id, public=True,
                                         customer_id=p.user.customer_id if p else None)
    return [AvailabilityOut(table=PublicTableOut.model_validate(i["table"]), status=i["status"], quote=quote_out(i["quote"]),
                            next_available_at=i["next_available_at"], reason=i["reason"]) for i in items]


@router.get("/timeline")
def timeline(branch_id: uuid.UUID, day: date, game_type_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    """Busy blocks per table for a business day (no customer data) + next free time."""
    t = booking_service.day_timeline(db, branch_id, day, game_type_id, public=True)
    return {**t, "tables": [{"table": PublicTableOut.model_validate(x["table"]).model_dump(), "status": table_service._public_status(x["status"]),
                             "busy": [{"start": b["start"], "end": b["end"], "kind": "BOOKED" if b["kind"] != "IN_USE" else "IN_USE"} for b in x["busy"]],
                             "next_free_at": x["next_free_at"]} for x in t["tables"]]}


@router.post("/bookings/hold", response_model=CheckoutOut, status_code=201, dependencies=[Depends(rate_limit("hold", 10))])
def hold(body: HoldIn, db: Session = Depends(get_db), p: Principal | None = Depends(get_optional_principal)):
    """Checkout step: hold the table (default 10 min) and create the deposit payment order."""
    b = booking_service.create_hold(db, branch_id=body.branch_id, table_id=body.table_id, start=body.start_at, duration=body.duration_minutes,
                                    customer=body.customer.model_dump(), coupon_code=body.coupon_code, principal=p)
    payment, order = payment_service.start_booking_checkout(db, b)
    db.refresh(b)
    return CheckoutOut(booking=booking_out(b), payment_id=payment.id if payment else None, checkout=order.client_payload if order else None)


@router.post("/bookings/lookup", response_model=BookingOut)
def lookup(body: GuestLookupIn, db: Session = Depends(get_db)):
    return booking_out(booking_service.lookup_public(db, body.reference, body.phone))


@router.post("/payments/mock/{order_id}/complete")
def mock_complete(order_id: str, succeed: bool = True, db: Session = Depends(get_db)):
    """DEV/DEMO ONLY (PAYMENT_PROVIDER=mock): simulates the provider webhook."""
    return payment_service.mock_complete(db, order_id, succeed=succeed)


# ---------------------------------------------------------------- QR code at the table (Option B)
@router.get("/qr/{token}")
def qr_info(token: str, db: Session = Depends(get_db)):
    t = device_service.qr_lookup(db, token)
    from app.services.session_service import open_session_for_table

    s = open_session_for_table(db, t.id)
    return {"table": PublicTableOut.model_validate(t).model_dump(), "branch_id": t.branch_id, "status": table_service._public_status(t.status),
            "session_running": bool(s and s.status in ("ACTIVE", "PAUSED")), "started_at": s.started_at if s else None}


@router.post("/qr/{token}/start", dependencies=[Depends(rate_limit("qr", 6))])
def qr_start(token: str, body: QrStartIn, db: Session = Depends(get_db), p: Principal | None = Depends(get_optional_principal)):
    return device_service.qr_start(db, token, phone=body.phone, name=body.name, customer_id=p.user.customer_id if p else None)
