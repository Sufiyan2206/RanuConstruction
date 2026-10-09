"""Integration/API tests: sessions, billing, POS/inventory, membership, approvals, shifts, RBAC."""
from decimal import Decimal

from sqlalchemy import select

from app.models import AuditLog, GameSession, InventoryTransaction, Product
from tests.conftest import advance, freeze_at, local_dt, table_id


def _walk_in(api, db, number, phone="9811111111", **extra):
    r = api.post("/sessions/start", {"table_id": table_id(db, number), "customer": {"name": "Walk In", "phone": phone}, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_walk_in_session_billing_and_split_payment(reception, db):
    freeze_at(local_dt(0, 19))
    s = _walk_in(reception, db, 1)
    assert s["status"] == "ACTIVE"
    board = reception.get(f"/branches/{s['branch_id']}/board").json()
    assert next(r for r in board if r["table"]["table_number"] == 1)["table"]["status"] == "GAME_STARTED"
    advance(61)  # 61 min -> 75 min billed in 15-min blocks @150 = 187.50
    live = reception.get(f"/sessions/{s['id']}/live").json()
    assert live["estimated_total"] == "187.50"
    r = reception.post(f"/sessions/{s['id']}/stop")
    assert r.status_code == 200, r.text
    inv = r.json()["invoice"]
    assert inv["total"] == "187.50" and inv["status"] == "ISSUED"
    pay = reception.post(f"/invoices/{inv['id']}/pay", {"splits": [{"method": "CASH", "amount": "100"}, {"method": "UPI", "amount": "87.50", "reference": "UPI123"}]},
                         headers={"Idempotency-Key": "k1"})
    assert pay.json()["status"] == "PAID" and pay.json()["balance_due"] == "0.00"
    again = reception.post(f"/invoices/{inv['id']}/pay", {"splits": [{"method": "CASH", "amount": "100"}]}, headers={"Idempotency-Key": "k1"})
    assert again.status_code == 200  # replay is harmless
    cust = reception.get(f"/customers/{s['customer_id']}").json()
    assert cust["total_visits"] == 1 and cust["total_spend"] == "187.50"


def test_upi_requires_reference_and_overpayment_blocked(reception, db):
    freeze_at(local_dt(0, 19))
    s = _walk_in(reception, db, 2)
    advance(30)
    inv = reception.post(f"/sessions/{s['id']}/stop").json()["invoice"]
    assert reception.post(f"/invoices/{inv['id']}/pay", {"splits": [{"method": "UPI", "amount": "10"}]}).json()["error"]["code"] == "REFERENCE_REQUIRED"
    assert reception.post(f"/invoices/{inv['id']}/pay", {"splits": [{"method": "CASH", "amount": "9999"}]}).json()["error"]["code"] == "OVERPAYMENT"


def test_one_active_session_per_table(reception, staff, db):
    freeze_at(local_dt(0, 19))
    _walk_in(reception, db, 3)
    r = staff.post("/sessions/start", {"table_id": table_id(db, 3)})
    assert r.status_code == 409 and r.json()["error"]["code"] == "SESSION_ALREADY_ACTIVE"
    assert db.scalar(select(GameSession).where(GameSession.status == "ACTIVE").limit(2)) is not None


def test_pause_resume_excludes_paused_time(reception, db):
    freeze_at(local_dt(0, 19))
    s = _walk_in(reception, db, 4)
    advance(20)
    reception.post(f"/sessions/{s['id']}/pause", {"reason": "Tea break"})
    advance(30)
    reception.post(f"/sessions/{s['id']}/resume")
    advance(10)
    inv = reception.post(f"/sessions/{s['id']}/stop").json()["invoice"]
    assert inv["total"] == "75.00"  # 30 active min @150
    assert reception.post(f"/sessions/{s['id']}/resume").status_code == 409


def test_table_orders_and_inventory_ledger(reception, db):
    freeze_at(local_dt(0, 19))
    s = _walk_in(reception, db, 5)
    coke = db.scalar(select(Product).where(Product.sku == "COKE"))
    water = db.scalar(select(Product).where(Product.sku == "WATER1L"))
    r = reception.post(f"/sessions/{s['id']}/order/items", {"items": [{"product_id": str(coke.id), "quantity": 2}, {"product_id": str(water.id)}]})
    assert r.status_code == 200 and r.json()["subtotal"] == "150.00"
    advance(60)
    inv = reception.post(f"/sessions/{s['id']}/stop").json()["invoice"]
    assert inv["total"] == "300.00"  # 150 time + 120 coke + 30 water
    assert {ln["line_type"] for ln in inv["lines"]} == {"TABLE_TIME", "PRODUCT"}
    ledger = db.scalars(select(InventoryTransaction).where(InventoryTransaction.product_id == coke.id).order_by(InventoryTransaction.created_at)).all()
    assert [str(t.txn_type) for t in ledger] == ["OPENING", "SALE"] and ledger[-1].balance_after == Decimal("46")


def test_out_of_stock_blocked(reception, admin, db, branch_id):
    freeze_at(local_dt(0, 19))
    chalk = db.scalar(select(Product).where(Product.sku == "CHALK"))
    r = admin.post("/inventory/stock-out", {"branch_id": branch_id, "product_id": str(chalk.id), "quantity": 48, "txn_type": "DAMAGED", "reason": "Water damage"})
    assert r.status_code == 201
    s = _walk_in(reception, db, 6)
    r = reception.post(f"/sessions/{s['id']}/order/items", {"items": [{"product_id": str(chalk.id)}]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "OUT_OF_STOCK"


def test_counter_sale_and_credit_due(reception, db, branch_id):
    freeze_at(local_dt(0, 19))
    cust = reception.post("/customers", {"name": "Regular", "phone": "9876500000"}).json()
    chips = db.scalar(select(Product).where(Product.sku == "CHIPS"))
    inv = reception.post("/pos/sales", {"branch_id": branch_id, "customer_id": cust["id"], "items": [{"product_id": str(chips.id), "quantity": 3}]}).json()
    assert inv["total"] == "120.00"
    reception.post(f"/invoices/{inv['id']}/pay", {"splits": [{"method": "CREDIT", "amount": "120"}]})
    out = reception.get(f"/branches/{branch_id}/outstanding").json()
    assert out[0]["balance"] == "120.00"
    reception.post(f"/customers/{cust['id']}/pay-dues", {"branch_id": branch_id, "amount": "70", "method": "CASH"})
    assert reception.get(f"/branches/{branch_id}/outstanding").json()[0]["balance"] == "50.00"


def test_booking_checkin_start_deposit_applied(public, reception, db, branch_id):
    freeze_at(local_dt(0, 12))
    h = public.post("/public/bookings/hold", {"branch_id": branch_id, "table_id": table_id(db, 7), "start_at": local_dt(0, 18).isoformat(), "duration_minutes": 60,
                                               "customer": {"name": "Booked", "phone": "9000011111"}}).json()
    public.post(f"/public/payments/mock/{h['checkout']['order_id']}/complete")
    freeze_at(local_dt(0, 17, 55))
    ci = reception.post(f"/bookings/{h['booking']['id']}/check-in").json()
    assert ci["session"]["status"] == "CREATED"
    freeze_at(local_dt(0, 18))  # (starting at 17:55 would bill 5 happy-hour minutes at ₹100/h)
    s = reception.post("/sessions/start", {"table_id": table_id(db, 7)}).json()
    assert s["booking_id"] == h["booking"]["id"] and s["planned_end_at"]
    advance(60)
    inv = reception.post(f"/sessions/{s['id']}/stop").json()["invoice"]
    assert inv["total"] == "150.00" and inv["deposit_applied"] == "100.00" and inv["balance_due"] == "50.00"
    assert inv["status"] == "PARTIALLY_PAID"


def test_walk_in_cannot_steal_reserved_table(reception, db, branch_id):
    freeze_at(local_dt(0, 12))
    reception.post("/bookings", {"branch_id": branch_id, "table_id": table_id(db, 8), "start_at": local_dt(0, 13).isoformat(), "duration_minutes": 60,
                                 "customer": {"name": "Res", "phone": "9123400001"}})
    freeze_at(local_dt(0, 12, 50))
    r = reception.post("/sessions/start", {"table_id": table_id(db, 8), "customer": {"name": "Other", "phone": "9000099999"}})
    assert r.status_code == 409 and r.json()["error"]["code"] == "TABLE_RESERVED"


def test_extension_blocked_by_next_booking(reception, db, branch_id):
    freeze_at(local_dt(0, 17))
    s = _walk_in(reception, db, 9, planned_minutes=60)
    reception.post("/bookings", {"branch_id": branch_id, "table_id": table_id(db, 9), "start_at": local_dt(0, 18, 15).isoformat(), "duration_minutes": 60,
                                 "customer": {"name": "Next", "phone": "9123400002"}})
    r = reception.post(f"/sessions/{s['id']}/extend", {"minutes": 30})
    assert r.status_code == 409 and r.json()["error"]["code"] == "EXTENSION_UNAVAILABLE"
    s2 = _walk_in(reception, db, 10, phone="9811111112", planned_minutes=60)
    assert reception.post(f"/sessions/{s2['id']}/extend", {"minutes": 30}).status_code == 200


def test_membership_hours_deducted_and_reversed_on_void(admin, reception, db, branch_id):
    freeze_at(local_dt(0, 19))
    cust = reception.post("/customers", {"name": "Member", "phone": "9876511111"}).json()
    plan = next(p for p in reception.get("/membership-plans").json() if p["code"] == "H30")
    m = reception.post("/memberships", {"branch_id": branch_id, "customer_id": cust["id"], "plan_id": plan["id"], "payment_method": "UPI", "reference": "U1",
                                        "card_uid": "04A1B2C3"}).json()
    assert m["minutes_remaining"] == 1800
    s = reception.post("/sessions/start", {"table_id": table_id(db, 1), "customer_id": cust["id"]}).json()
    assert s["membership_id"] == m["id"]
    advance(40)
    inv = reception.post(f"/sessions/{s['id']}/stop").json()["invoice"]
    assert inv["total"] == "0.00" and inv["status"] == "PAID"
    mm = reception.get("/memberships", params={"customer_id": cust["id"]}).json()[0]
    assert mm["minutes_used"] == 60  # 30-min blocks
    s2 = reception.post("/sessions/start", {"table_id": table_id(db, 2), "customer_id": cust["id"]}).json()
    advance(10)
    inv2 = reception.post(f"/sessions/{s2['id']}/stop").json()["invoice"]
    admin.post(f"/invoices/{inv2['id']}/void", {"reason": "Test void"})
    mm = reception.get("/memberships", params={"customer_id": cust["id"]}).json()[0]
    assert mm["minutes_used"] == 60


def test_discount_needs_approval_for_staff(reception, admin, db, branch_id):
    freeze_at(local_dt(0, 19))
    s = _walk_in(reception, db, 3)
    advance(60)
    inv = reception.post(f"/sessions/{s['id']}/stop").json()["invoice"]
    r = reception.post(f"/invoices/{inv['id']}/discount", {"amount": "50", "reason": "Regular customer"}).json()
    assert r["applied"] is False
    pending = admin.get(f"/branches/{branch_id}/approvals").json()
    assert len(pending) == 1
    admin.post(f"/approvals/{pending[0]['id']}/resolve", {"approve": True, "note": "ok"})
    after = reception.get(f"/invoices/{inv['id']}").json()
    assert after["total"] == "100.00" and after["adjustments"][0]["amount"] == "-50.00"
    # original line untouched (financial immutability)
    assert after["lines"][0]["amount"] == "150.00"


def test_rbac_staff_cannot_change_prices_or_adjust(staff, db):
    r = staff.patch(f"/tables/{table_id(db, 1)}", {"hourly_rate": "10"})
    assert r.status_code == 403
    assert staff.get("/audit-logs").status_code == 403
    assert staff.post("/branches", {"code": "X", "name": "X"}).status_code == 403


def test_price_change_is_audited(admin, db):
    r = admin.patch(f"/tables/{table_id(db, 1)}", {"hourly_rate": "200", "reason": "New season"})
    assert r.status_code == 200
    log = db.scalar(select(AuditLog).where(AuditLog.action == "table.price_change"))
    assert log and log.before["hourly_rate"] == "150.00" and log.after["hourly_rate"] == "200" and log.reason == "New season"


def test_shift_cash_reconciliation(reception, db, branch_id):
    freeze_at(local_dt(0, 18))
    reception.post("/shifts/open", {"branch_id": branch_id, "opening_cash": "500"})
    assert reception.post("/shifts/open", {"branch_id": branch_id, "opening_cash": "1"}).status_code == 409
    s = _walk_in(reception, db, 4)
    advance(60)
    inv = reception.post(f"/sessions/{s['id']}/stop").json()["invoice"]
    reception.post(f"/invoices/{inv['id']}/pay", {"splits": [{"method": "CASH", "amount": "150"}]})
    cat = reception.get("/expense-categories").json()[0]
    reception.post(f"/branches/{branch_id}/expenses", {"category_id": cat["id"], "amount": "40", "description": "Milk"})
    closed = reception.post("/shifts/close", {"counted_cash": "600"}).json()
    assert closed["expected_cash"] == "610.00" and closed["variance"] == "-10.00"


def test_pin_login_and_refresh_rotation(client):
    r = client.post("/api/v1/auth/pin-login", json={"username": "reception", "pin": "1234"})
    assert r.status_code == 200
    rt = r.json()["refresh_token"]
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": rt})
    assert r2.status_code == 200
    reuse = client.post("/api/v1/auth/refresh", json={"refresh_token": rt})
    assert reuse.status_code == 401 and reuse.json()["error"]["code"] == "REFRESH_REUSED"
    # whole family revoked after reuse
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": r2.json()["refresh_token"]}).status_code == 401


def test_lockout_after_failed_logins(client):
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"identifier": "staff1", "password": "wrong"})
    r = client.post("/api/v1/auth/login", json={"identifier": "staff1", "password": "Ranu@12345"})
    assert r.json()["error"]["code"] == "ACCOUNT_LOCKED"


def test_dashboard_and_reports(reception, admin, db, branch_id):
    freeze_at(local_dt(0, 19))
    s = _walk_in(reception, db, 1)
    advance(60)
    inv = reception.post(f"/sessions/{s['id']}/stop").json()["invoice"]
    reception.post(f"/invoices/{inv['id']}/pay", {"splits": [{"method": "CASH", "amount": "150"}]})
    d = reception.get(f"/branches/{branch_id}/dashboard").json()
    assert float(d["today_revenue"]) == 150 and d["available_tables"] >= 13
    day = local_dt(0, 12).date().isoformat()
    rev = admin.get(f"/branches/{branch_id}/reports/revenue", params={"from": day, "to": day}).json()
    assert float(rev["total_collected"]) == 150 and float(rev["by_method"]["CASH"]) == 150
    util = admin.get(f"/branches/{branch_id}/reports/utilization", params={"from": day, "to": day}).json()
    assert next(u for u in util if u["table_number"] == 1)["played_minutes"] == 60
    peak = admin.get(f"/branches/{branch_id}/reports/peak-hours", params={"from": day, "to": day}).json()
    assert peak[19]["table_minutes"] == 60
    assert admin.get(f"/branches/{branch_id}/reports/games", params={"from": day, "to": day}).json()[0]["game"] == "Snooker"
    assert admin.get(f"/branches/{branch_id}/reports/revenue.csv", params={"from": day, "to": day}).text.startswith("period,")
