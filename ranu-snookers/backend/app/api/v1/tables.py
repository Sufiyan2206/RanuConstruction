"""Tables, game types, pricing rules, live board and dashboard."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.serializers import booking_out, quote_out
from app.core.database import get_db
from app.core.deps import Principal, require
from app.schemas.domain import (
    AlertOut,
    GameTypeIn,
    GameTypeOut,
    InvoiceOut,
    PricingRuleIn,
    PricingRuleOut,
    QuoteOut,
    SessionOut,
    TableAdminOut,
    TableIn,
    TableStatusIn,
    TableUpdateIn,
)
from app.services import billing_service, booking_service, report_service, table_service

router = APIRouter(tags=["tables"])


@router.get("/game-types", response_model=list[GameTypeOut])
def list_game_types(p: Principal = Depends(require("tables.view")), db: Session = Depends(get_db)):
    return table_service.list_game_types(db, p.organization_id, active_only=False)


@router.post("/game-types", response_model=GameTypeOut, status_code=201)
def create_game_type(body: GameTypeIn, p: Principal = Depends(require("tables.manage")), db: Session = Depends(get_db)):
    return table_service.create_game_type(db, p, body.model_dump())


@router.get("/branches/{branch_id}/tables", response_model=list[TableAdminOut])
def list_tables(branch_id: uuid.UUID, include_inactive: bool = False, p: Principal = Depends(require("tables.view")), db: Session = Depends(get_db)):
    p.require("tables.view", branch_id)
    return table_service.list_tables(db, branch_id, include_inactive=include_inactive)


@router.post("/branches/{branch_id}/tables", response_model=TableAdminOut, status_code=201)
def create_table(branch_id: uuid.UUID, body: TableIn, p: Principal = Depends(require("tables.manage")), db: Session = Depends(get_db)):
    return table_service.create_table(db, p, branch_id, body.model_dump())


@router.patch("/tables/{table_id}", response_model=TableAdminOut)
def update_table(table_id: uuid.UUID, body: TableUpdateIn, p: Principal = Depends(require("tables.manage")), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    reason = data.pop("reason", None)
    return table_service.update_table(db, p, table_id, data, reason)


@router.post("/tables/{table_id}/status", response_model=TableAdminOut)
def set_table_status(table_id: uuid.UUID, body: TableStatusIn, p: Principal = Depends(require("tables.manage")), db: Session = Depends(get_db)):
    return table_service.set_manual_status(db, p, table_id, body.status, body.reason)


@router.post("/tables/{table_id}/rotate-qr", response_model=TableAdminOut)
def rotate_qr(table_id: uuid.UUID, p: Principal = Depends(require("tables.manage")), db: Session = Depends(get_db)):
    return table_service.rotate_qr(db, p, table_id)


@router.get("/tables/{table_id}/quote", response_model=QuoteOut)
def table_quote(table_id: uuid.UUID, start_at: datetime, duration_minutes: int = Query(60, ge=5, le=720), member: bool = False,
                p: Principal = Depends(require("tables.view")), db: Session = Depends(get_db)):
    from datetime import timedelta

    t = table_service.get_table(db, table_id)
    return quote_out(booking_service.quote(db, t, start_at, start_at + timedelta(minutes=duration_minutes), is_member=member))


@router.get("/branches/{branch_id}/pricing-rules", response_model=list[PricingRuleOut])
def list_rules(branch_id: uuid.UUID, p: Principal = Depends(require("tables.view")), db: Session = Depends(get_db)):
    return table_service.list_pricing_rules(db, branch_id)


@router.post("/branches/{branch_id}/pricing-rules", response_model=PricingRuleOut, status_code=201)
def create_rule(branch_id: uuid.UUID, body: PricingRuleIn, p: Principal = Depends(require("pricing.manage")), db: Session = Depends(get_db)):
    return table_service.upsert_pricing_rule(db, p, branch_id, body.model_dump())


@router.put("/branches/{branch_id}/pricing-rules/{rule_id}", response_model=PricingRuleOut)
def update_rule(branch_id: uuid.UUID, rule_id: uuid.UUID, body: PricingRuleIn, p: Principal = Depends(require("pricing.manage")), db: Session = Depends(get_db)):
    return table_service.upsert_pricing_rule(db, p, branch_id, body.model_dump(), rule_id)


@router.get("/branches/{branch_id}/board")
def board(branch_id: uuid.UUID, p: Principal = Depends(require("tables.view")), db: Session = Depends(get_db)):
    """Live table grid: status, running session with live bill, next booking, device health."""
    p.require("tables.view", branch_id)
    return [_board_row(db, r) for r in table_service.status_board(db, branch_id)]


def _board_row(db: Session, r: dict) -> dict:
    s = r["session"]
    live = None
    if s and s.status in ("ACTIVE", "PAUSED"):
        pv = billing_service.preview(db, s)
        live = {"estimated_total": pv.estimated_total, "time_amount": pv.charge.time_amount, "products_total": pv.products_total,
                "billed_minutes": pv.charge.billed_minutes, "covered_minutes": pv.charge.covered_minutes, "deposit": pv.deposit}
    return {
        "table": TableAdminOut.model_validate(r["table"]).model_dump(),
        "session": SessionOut.model_validate(s).model_dump() if s else None,
        "customer_name": s.customer.name if s and s.customer else None,
        "elapsed_seconds": r["elapsed_seconds"],
        "live_bill": live,
        "next_booking": booking_out(r["next_booking"]).model_dump() if r["next_booking"] else None,
        "devices": r["devices"],
    }


@router.get("/branches/{branch_id}/dashboard")
def dashboard(branch_id: uuid.UUID, p: Principal = Depends(require("tables.view")), db: Session = Depends(get_db)):
    d = report_service.dashboard(db, p, branch_id)
    return {
        **{k: v for k, v in d.items() if k not in ("pending_payments", "upcoming_bookings", "alerts", "board")},
        "pending_payments": [InvoiceOut.model_validate(i).model_dump() for i in d["pending_payments"]],
        "upcoming_bookings": [booking_out(b).model_dump() for b in d["upcoming_bookings"]],
        "alerts": [AlertOut.model_validate(a).model_dump() for a in d["alerts"]],
        "board": [_board_row(db, r) for r in d["board"]],
    }
