"""Administration: branches & settings, users/roles, alerts, audit, shifts & expenses,
tournaments, reports, notifications."""
from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import PageParams, Principal, get_principal, page_params, require
from app.core.permissions import PERMISSIONS
from app.models import ExpenseCategory, Holiday
from app.schemas.common import Message, Page
from app.schemas.domain import (
    AlertOut,
    AuditOut,
    BranchIn,
    BranchOut,
    BranchUpdateIn,
    ExpenseCategoryOut,
    ExpenseIn,
    ExpenseOut,
    HolidayIn,
    MatchOut,
    PlayerIn,
    PlayerOut,
    PromoIn,
    ReasonIn,
    ResultIn,
    RoleOut,
    ShiftCloseIn,
    ShiftOpenIn,
    ShiftOut,
    TournamentIn,
    TournamentOut,
    UserCreateIn,
    UserUpdateIn,
    UserOut,
    UserWithRolesOut,
)
from app.schemas.settings import BranchSettings
from app.services import admin_service, notification_service, report_service, shift_service, tournament_service
from app.services.common import get_branch

router = APIRouter(tags=["admin"])


# ============================================================================ branches & settings
@router.get("/branches", response_model=list[BranchOut])
def branches(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    allowed = p.branch_ids()
    rows = admin_service.list_branches(db, p.organization_id, active_only=False)
    return rows if allowed is None else [b for b in rows if b.id in allowed]


@router.post("/branches", response_model=BranchOut, status_code=201)
def create_branch(body: BranchIn, p: Principal = Depends(require("org.manage")), db: Session = Depends(get_db)):
    return admin_service.create_branch(db, p, body.model_dump())


@router.patch("/branches/{branch_id}", response_model=BranchOut)
def update_branch(branch_id: uuid.UUID, body: BranchUpdateIn, p: Principal = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    return admin_service.update_branch(db, p, branch_id, body.model_dump(exclude_unset=True))


@router.get("/branches/{branch_id}/settings", response_model=BranchSettings)
def get_settings(branch_id: uuid.UUID, p: Principal = Depends(require("tables.view")), db: Session = Depends(get_db)):
    p.require("tables.view", branch_id)
    return BranchSettings.load(get_branch(db, branch_id).settings)


@router.patch("/branches/{branch_id}/settings", response_model=BranchSettings)
def patch_settings(branch_id: uuid.UUID, body: dict, p: Principal = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    """Partial update, e.g. `{"billing": {"interval_minutes": 15}, "detection": {"auto_start_enabled": false}}`."""
    return admin_service.update_settings(db, p, branch_id, body)


@router.get("/branches/{branch_id}/holidays")
def holidays(branch_id: uuid.UUID, p: Principal = Depends(require("tables.view")), db: Session = Depends(get_db)):
    return [{"id": h.id, "day": h.day, "name": h.name} for h in db.scalars(select(Holiday).where(Holiday.branch_id == branch_id).order_by(Holiday.day)).all()]


@router.post("/branches/{branch_id}/holidays", status_code=201)
def add_holiday(branch_id: uuid.UUID, body: HolidayIn, p: Principal = Depends(require("pricing.manage")), db: Session = Depends(get_db)):
    h = admin_service.add_holiday(db, p, branch_id, body.day, body.name)
    return {"id": h.id, "day": h.day, "name": h.name}


@router.delete("/branches/{branch_id}/holidays/{holiday_id}", response_model=Message)
def remove_holiday(branch_id: uuid.UUID, holiday_id: uuid.UUID, p: Principal = Depends(require("pricing.manage")), db: Session = Depends(get_db)):
    admin_service.remove_holiday(db, p, branch_id, holiday_id)
    return Message(message="Removed")


# ============================================================================ users & roles
def _user_out(u) -> UserWithRolesOut:
    # Validate the plain user fields only; `u.roles` holds UserRole ORM rows, not dicts.
    base = UserOut.model_validate(u).model_dump()
    roles = [{"code": r.role.code, "name": r.role.name, "branch_id": r.branch_id} for r in u.roles]
    return UserWithRolesOut(**base, roles=roles)


@router.get("/users", response_model=list[UserWithRolesOut])
def users(p: Principal = Depends(require("users.manage")), db: Session = Depends(get_db)):
    return [_user_out(u) for u in admin_service.list_users(db, p)]


@router.post("/users", response_model=UserWithRolesOut, status_code=201)
def create_user(body: UserCreateIn, p: Principal = Depends(require("users.manage")), db: Session = Depends(get_db)):
    return _user_out(admin_service.create_user(db, p, body.model_dump()))


@router.patch("/users/{user_id}", response_model=UserWithRolesOut)
def update_user(user_id: uuid.UUID, body: UserUpdateIn, p: Principal = Depends(require("users.manage")), db: Session = Depends(get_db)):
    return _user_out(admin_service.update_user(db, p, user_id, body.model_dump(exclude_unset=True, mode="json")))


@router.get("/roles", response_model=list[RoleOut])
def roles(p: Principal = Depends(require("users.manage")), db: Session = Depends(get_db)):
    return admin_service.list_roles(db, p)


@router.get("/permissions")
def permissions(p: Principal = Depends(require("users.manage"))):
    return [{"code": k, "description": v} for k, v in PERMISSIONS.items()]


@router.put("/roles/{role_id}/permissions", response_model=RoleOut)
def set_permissions(role_id: uuid.UUID, codes: list[str], p: Principal = Depends(require("roles.manage")), db: Session = Depends(get_db)):
    return admin_service.set_role_permissions(db, p, role_id, codes)


# ============================================================================ alerts & audit
@router.get("/branches/{branch_id}/alerts", response_model=list[AlertOut])
def alerts(branch_id: uuid.UUID, open_only: bool = True, p: Principal = Depends(require("tables.view")), db: Session = Depends(get_db)):
    return admin_service.list_alerts(db, p, branch_id, open_only)


@router.post("/alerts/{alert_id}/ack", response_model=AlertOut)
def ack(alert_id: uuid.UUID, p: Principal = Depends(require("tables.view")), db: Session = Depends(get_db)):
    return admin_service.ack_alert(db, p, alert_id)


@router.get("/audit-logs", response_model=Page[AuditOut])
def audit_logs(branch_id: uuid.UUID | None = None, entity_type: str | None = None, entity_id: str | None = None, action: str | None = None,
               user_id: uuid.UUID | None = None, frm: datetime | None = Query(None, alias="from"), to: datetime | None = None,
               page: PageParams = Depends(page_params), p: Principal = Depends(require("audit.view")), db: Session = Depends(get_db)):
    rows, total = admin_service.audit_logs(db, p, branch_id=branch_id, entity_type=entity_type, entity_id=entity_id, action=action, user_id=user_id,
                                           frm=frm, to=to, offset=page.offset, limit=page.size)
    return Page(items=rows, total=total, page=page.page, size=page.size)


# ============================================================================ shifts & expenses
@router.get("/shifts/me")
def my_shift(p: Principal = Depends(require("shifts.operate")), db: Session = Depends(get_db)):
    s = shift_service.my_open_shift(db, p)
    if not s:
        return {"shift": None}
    sm = shift_service.summary(db, s)
    return {"shift": ShiftOut.model_validate(s), "cash_sales": sm["cash_sales"], "cash_expenses": sm["cash_expenses"], "expected_cash": sm["expected_cash"]}


@router.post("/shifts/open", response_model=ShiftOut, status_code=201)
def open_shift(body: ShiftOpenIn, p: Principal = Depends(require("shifts.operate")), db: Session = Depends(get_db)):
    return shift_service.open_shift(db, p, body.branch_id, body.opening_cash, body.notes)


@router.post("/shifts/close", response_model=ShiftOut)
def close_shift(body: ShiftCloseIn, p: Principal = Depends(require("shifts.operate")), db: Session = Depends(get_db)):
    return shift_service.close_shift(db, p, body.counted_cash, body.notes)


@router.get("/branches/{branch_id}/shifts", response_model=list[ShiftOut])
def shifts(branch_id: uuid.UUID, mine: bool = False, p: Principal = Depends(require("shifts.operate")), db: Session = Depends(get_db)):
    return shift_service.list_shifts(db, p, branch_id, mine)


@router.get("/expense-categories", response_model=list[ExpenseCategoryOut])
def expense_categories(p: Principal = Depends(require("expenses.manage")), db: Session = Depends(get_db)):
    return list(db.scalars(select(ExpenseCategory).where(ExpenseCategory.organization_id == p.organization_id, ExpenseCategory.is_active.is_(True))).all())


@router.get("/branches/{branch_id}/expenses", response_model=list[ExpenseOut])
def expenses(branch_id: uuid.UUID, frm: date = Query(..., alias="from"), to: date = Query(...), p: Principal = Depends(require("expenses.manage")), db: Session = Depends(get_db)):
    return shift_service.list_expenses(db, p, branch_id, frm, to)


@router.post("/branches/{branch_id}/expenses", response_model=ExpenseOut, status_code=201)
def add_expense(branch_id: uuid.UUID, body: ExpenseIn, p: Principal = Depends(require("expenses.manage")), db: Session = Depends(get_db)):
    return shift_service.add_expense(db, p, branch_id, body.model_dump())


@router.post("/expenses/{expense_id}/void", response_model=ExpenseOut)
def void_expense(expense_id: uuid.UUID, body: ReasonIn, p: Principal = Depends(require("approvals.resolve")), db: Session = Depends(get_db)):
    return shift_service.void_expense(db, p, expense_id, body.reason)


# ============================================================================ tournaments
@router.get("/branches/{branch_id}/tournaments", response_model=list[TournamentOut])
def tournaments(branch_id: uuid.UUID, p: Principal = Depends(require("tables.view")), db: Session = Depends(get_db)):
    return tournament_service.list_for_branch(db, branch_id)


@router.post("/branches/{branch_id}/tournaments", response_model=TournamentOut, status_code=201)
def create_tournament(branch_id: uuid.UUID, body: TournamentIn, p: Principal = Depends(require("tournaments.manage")), db: Session = Depends(get_db)):
    return tournament_service.create(db, p, branch_id, body.model_dump())


@router.get("/tournaments/{tid}")
def tournament_detail(tid: uuid.UUID, p: Principal = Depends(require("tables.view")), db: Session = Depends(get_db)):
    d = tournament_service.detail(db, tid)
    return {"tournament": TournamentOut.model_validate(d["tournament"]), "players": [PlayerOut.model_validate(x) for x in d["players"]],
            "matches": [MatchOut.model_validate(m) for m in d["matches"]], "leaderboard": d["leaderboard"]}


@router.post("/tournaments/{tid}/players", response_model=PlayerOut, status_code=201)
def add_player(tid: uuid.UUID, body: PlayerIn, p: Principal = Depends(require("tournaments.manage")), db: Session = Depends(get_db)):
    return tournament_service.register_player(db, p, tid, body.customer_id, body.seed, body.fee_paid)


@router.post("/tournaments/{tid}/start", response_model=TournamentOut)
def start_tournament(tid: uuid.UUID, p: Principal = Depends(require("tournaments.manage")), db: Session = Depends(get_db)):
    return tournament_service.start(db, p, tid)


@router.post("/tournament-matches/{match_id}/result", response_model=MatchOut)
def match_result(match_id: uuid.UUID, body: ResultIn, p: Principal = Depends(require("tournaments.manage")), db: Session = Depends(get_db)):
    return tournament_service.record_result(db, p, match_id, body.score1, body.score2, body.table_id)


# ============================================================================ reports
@router.get("/branches/{branch_id}/reports/revenue")
def revenue(branch_id: uuid.UUID, frm: date = Query(..., alias="from"), to: date = Query(...), period: str = Query("daily", pattern="^(daily|weekly|monthly|yearly)$"),
            p: Principal = Depends(require("reports.view")), db: Session = Depends(get_db)):
    return report_service.revenue(db, p, branch_id, frm, to, period)


@router.get("/branches/{branch_id}/reports/utilization")
def utilization(branch_id: uuid.UUID, frm: date = Query(..., alias="from"), to: date = Query(...), p: Principal = Depends(require("reports.view")), db: Session = Depends(get_db)):
    return report_service.utilization(db, p, branch_id, frm, to)


@router.get("/branches/{branch_id}/reports/peak-hours")
def peak(branch_id: uuid.UUID, frm: date = Query(..., alias="from"), to: date = Query(...), p: Principal = Depends(require("reports.view")), db: Session = Depends(get_db)):
    return report_service.peak_hours(db, p, branch_id, frm, to)


@router.get("/branches/{branch_id}/reports/games")
def games(branch_id: uuid.UUID, frm: date = Query(..., alias="from"), to: date = Query(...), p: Principal = Depends(require("reports.view")), db: Session = Depends(get_db)):
    return report_service.game_report(db, p, branch_id, frm, to)


@router.get("/branches/{branch_id}/reports/payments")
def payments(branch_id: uuid.UUID, frm: date = Query(..., alias="from"), to: date = Query(...), p: Principal = Depends(require("reports.view")), db: Session = Depends(get_db)):
    return report_service.payment_methods(db, p, branch_id, frm, to)


@router.get("/branches/{branch_id}/reports/customers")
def customers(branch_id: uuid.UUID, frm: date = Query(..., alias="from"), to: date = Query(...), p: Principal = Depends(require("reports.view")), db: Session = Depends(get_db)):
    return report_service.customers_report(db, p, branch_id, frm, to)


@router.get("/branches/{branch_id}/reports/products")
def product_sales(branch_id: uuid.UUID, frm: date = Query(..., alias="from"), to: date = Query(...), p: Principal = Depends(require("reports.view")), db: Session = Depends(get_db)):
    return report_service.product_sales(db, p, branch_id, frm, to)


@router.get("/branches/{branch_id}/reports/revenue.csv")
def revenue_csv(branch_id: uuid.UUID, frm: date = Query(..., alias="from"), to: date = Query(...), period: str = "daily",
                p: Principal = Depends(require("reports.view")), db: Session = Depends(get_db)):
    r = report_service.revenue(db, p, branch_id, frm, to, period)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["period", "collected", "refunds", "credit_given", "expenses", "net"])
    for row in r["series"]:
        w.writerow([row["period"], row["collected"], row["refunds"], row["credit_given"], row["expenses"], row["net"]])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=revenue_{frm}_{to}.csv"})


# ============================================================================ notifications
@router.post("/branches/{branch_id}/notifications/promotion")
def promotion(branch_id: uuid.UUID, body: PromoIn, p: Principal = Depends(require("notifications.manage")), db: Session = Depends(get_db)):
    return {"queued": notification_service.send_promotion(db, p, branch_id, body.subject, body.message)}
