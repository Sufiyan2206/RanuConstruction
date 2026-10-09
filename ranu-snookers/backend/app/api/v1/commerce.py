"""Customers/CRM, POS & inventory, memberships & loyalty."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import PageParams, Principal, get_principal, page_params, require
from app.models import Coupon, Invoice, ProductCategory, Supplier
from app.schemas.common import Page
from app.schemas.domain import (
    CardIn,
    CategoryIn,
    CategoryOut,
    CounterSaleIn,
    CouponIn,
    CouponOut,
    CustomerCreateIn,
    CustomerOut,
    CustomerProfileOut,
    CustomerUpdateIn,
    DuePaymentIn,
    InventoryTxnOut,
    InvoiceOut,
    LedgerEntryOut,
    MembershipOut,
    MembershipStatusIn,
    MembershipTxnOut,
    MinutesAdjustIn,
    OpeningDueIn,
    OrderItemsIn,
    OrderOut,
    OutstandingRow,
    PaymentOut,
    PlanIn,
    PlanOut,
    ProductIn,
    ProductOut,
    ProductStockOut,
    ProductUpdateIn,
    ReasonIn,
    RedeemIn,
    RenewIn,
    SellMembershipIn,
    StockInIn,
    StockOutIn,
    SupplierIn,
    SupplierOut,
)
from app.services import billing_service, customer_service, loyalty_service, membership_service, pos_service

router = APIRouter(tags=["commerce"])


# ============================================================================ customers
@router.get("/customers", response_model=Page[CustomerOut])
def search_customers(q: str | None = None, page: PageParams = Depends(page_params), p: Principal = Depends(require("customers.view")), db: Session = Depends(get_db)):
    rows, total = customer_service.search(db, p, q, page)
    return Page(items=rows, total=total, page=page.page, size=page.size)


@router.post("/customers", response_model=CustomerOut, status_code=201)
def create_customer(body: CustomerCreateIn, p: Principal = Depends(require("customers.manage")), db: Session = Depends(get_db)):
    return customer_service.create(db, p, body.model_dump())


@router.get("/customers/me/profile", response_model=CustomerProfileOut)
def my_profile(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if not p.user.customer_id:
        from app.core.errors import NotFound

        raise NotFound("No customer profile")
    prof = customer_service.profile(db, _as_self(p), p.user.customer_id)
    return _profile_out(prof)


def _as_self(p: Principal) -> Principal:
    return p  # customer_service.get_customer only checks organisation


def _profile_out(prof: dict) -> dict:
    return {**{k: v for k, v in prof.items() if k not in ("customer", "membership")}, "customer": CustomerOut.model_validate(prof["customer"]),
            "membership": MembershipOut.model_validate(prof["membership"]) if prof["membership"] else None}


@router.get("/customers/{customer_id}", response_model=CustomerProfileOut)
def customer_profile(customer_id: uuid.UUID, p: Principal = Depends(require("customers.view")), db: Session = Depends(get_db)):
    return _profile_out(customer_service.profile(db, p, customer_id))


@router.patch("/customers/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: uuid.UUID, body: CustomerUpdateIn, p: Principal = Depends(require("customers.manage")), db: Session = Depends(get_db)):
    return customer_service.update(db, p, customer_id, body.model_dump(exclude_unset=True))


@router.get("/customers/{customer_id}/ledger", response_model=list[LedgerEntryOut])
def customer_ledger(customer_id: uuid.UUID, p: Principal = Depends(require("customers.view")), db: Session = Depends(get_db)):
    return customer_service.ledger(db, p, customer_id)


@router.post("/customers/{customer_id}/opening-due", response_model=LedgerEntryOut, status_code=201)
def opening_due(customer_id: uuid.UUID, body: OpeningDueIn, p: Principal = Depends(require("customers.manage")), db: Session = Depends(get_db)):
    return customer_service.add_opening_due(db, p, customer_id, body.branch_id, body.amount, body.note)


@router.post("/customers/{customer_id}/pay-dues", response_model=PaymentOut, status_code=201)
def pay_dues(customer_id: uuid.UUID, body: DuePaymentIn, p: Principal = Depends(require("billing.operate")), db: Session = Depends(get_db)):
    return billing_service.settle_dues(db, p, customer_id, body.branch_id, body.amount, body.method, body.reference)


@router.get("/customers/{customer_id}/invoices", response_model=list[InvoiceOut])
def customer_invoices(customer_id: uuid.UUID, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if not (p.has("customers.view") or p.user.customer_id == customer_id):
        from app.core.errors import Forbidden

        raise Forbidden("Not allowed")
    return list(db.scalars(select(Invoice).where(Invoice.customer_id == customer_id).order_by(Invoice.issued_at.desc()).limit(100)).all())


@router.get("/customers/{customer_id}/loyalty")
def customer_loyalty(customer_id: uuid.UUID, p: Principal = Depends(require("customers.view")), db: Session = Depends(get_db)):
    c = customer_service.get_customer(db, p, customer_id)
    return {"points": c.loyalty_points, "history": [{"points": t.points, "reason": t.reason, "invoice_id": t.invoice_id, "created_at": t.created_at}
                                                    for t in loyalty_service.history(db, customer_id)]}


@router.get("/branches/{branch_id}/outstanding", response_model=list[OutstandingRow])
def outstanding(branch_id: uuid.UUID, p: Principal = Depends(require("customers.view")), db: Session = Depends(get_db)):
    return customer_service.outstanding_report(db, p, branch_id)


# ============================================================================ POS / products
@router.get("/product-categories", response_model=list[CategoryOut])
def categories(p: Principal = Depends(require("pos.sell")), db: Session = Depends(get_db)):
    return list(db.scalars(select(ProductCategory).where(ProductCategory.organization_id == p.organization_id).order_by(ProductCategory.sort_order)).all())


@router.post("/product-categories", response_model=CategoryOut, status_code=201)
def create_category(body: CategoryIn, p: Principal = Depends(require("products.manage")), db: Session = Depends(get_db)):
    return pos_service.create_category(db, p, body.name, body.sort_order)


@router.get("/products", response_model=list[ProductStockOut])
def products(branch_id: uuid.UUID | None = None, q: str | None = None, include_inactive: bool = False,
             p: Principal = Depends(require("pos.sell")), db: Session = Depends(get_db)):
    return pos_service.list_products(db, p.organization_id, branch_id, active_only=not include_inactive, q=q)


@router.post("/products", response_model=ProductOut, status_code=201)
def create_product(body: ProductIn, p: Principal = Depends(require("products.manage")), db: Session = Depends(get_db)):
    return pos_service.upsert_product(db, p, body.model_dump())


@router.patch("/products/{product_id}", response_model=ProductOut)
def update_product(product_id: uuid.UUID, body: ProductUpdateIn, p: Principal = Depends(require("products.manage")), db: Session = Depends(get_db)):
    return pos_service.upsert_product(db, p, body.model_dump(exclude_unset=True), product_id)


@router.get("/suppliers", response_model=list[SupplierOut])
def suppliers(p: Principal = Depends(require("inventory.manage")), db: Session = Depends(get_db)):
    return list(db.scalars(select(Supplier).where(Supplier.organization_id == p.organization_id, Supplier.deleted_at.is_(None)).order_by(Supplier.name)).all())


@router.post("/suppliers", response_model=SupplierOut, status_code=201)
def create_supplier(body: SupplierIn, p: Principal = Depends(require("inventory.manage")), db: Session = Depends(get_db)):
    return pos_service.create_supplier(db, p, body.model_dump())


@router.post("/inventory/stock-in", response_model=InventoryTxnOut, status_code=201)
def stock_in(body: StockInIn, p: Principal = Depends(require("inventory.manage")), db: Session = Depends(get_db)):
    return pos_service.stock_in(db, p, body.branch_id, body.product_id, body.quantity, txn_type=body.txn_type, unit_cost=body.unit_cost,
                                supplier_id=body.supplier_id, reference=body.reference, note=body.note)


@router.post("/inventory/stock-out", response_model=InventoryTxnOut, status_code=201)
def stock_out(body: StockOutIn, p: Principal = Depends(require("inventory.manage")), db: Session = Depends(get_db)):
    return pos_service.stock_out(db, p, body.branch_id, body.product_id, body.quantity, txn_type=body.txn_type, reason=body.reason, supplier_id=body.supplier_id)


@router.get("/branches/{branch_id}/inventory/ledger", response_model=Page[InventoryTxnOut])
def inventory_ledger(branch_id: uuid.UUID, product_id: uuid.UUID | None = None, page: PageParams = Depends(page_params),
                     p: Principal = Depends(require("inventory.manage")), db: Session = Depends(get_db)):
    rows, total = pos_service.ledger(db, p, branch_id, product_id, page.offset, page.size)
    return Page(items=rows, total=total, page=page.page, size=page.size)


@router.get("/branches/{branch_id}/inventory/low-stock", response_model=list[ProductStockOut])
def low_stock(branch_id: uuid.UUID, p: Principal = Depends(require("pos.sell")), db: Session = Depends(get_db)):
    return pos_service.low_stock(db, branch_id)


@router.get("/sessions/{session_id}/order", response_model=OrderOut | None)
def session_order(session_id: uuid.UUID, p: Principal = Depends(require("sessions.view")), db: Session = Depends(get_db)):
    return pos_service.session_order(db, session_id)


@router.post("/sessions/{session_id}/order/items", response_model=OrderOut)
def add_items(session_id: uuid.UUID, body: OrderItemsIn, p: Principal = Depends(require("pos.sell")), db: Session = Depends(get_db)):
    return pos_service.add_items_to_session(db, p, session_id, [i.model_dump() for i in body.items])


@router.post("/order-items/{item_id}/cancel")
def cancel_item(item_id: uuid.UUID, body: ReasonIn, p: Principal = Depends(require("pos.sell")), db: Session = Depends(get_db)):
    return pos_service.cancel_item(db, p, item_id, body.reason)


@router.post("/pos/sales", response_model=InvoiceOut, status_code=201)
def counter_sale(body: CounterSaleIn, p: Principal = Depends(require("pos.sell")), db: Session = Depends(get_db)):
    return pos_service.counter_sale(db, p, body.branch_id, [i.model_dump() for i in body.items], body.customer_id)


# ============================================================================ memberships
@router.get("/membership-plans", response_model=list[PlanOut])
def list_plans(p: Principal = Depends(require("customers.view")), db: Session = Depends(get_db)):
    return membership_service.list_plans(db, p.organization_id)


@router.post("/membership-plans", response_model=PlanOut, status_code=201)
def create_plan(body: PlanIn, p: Principal = Depends(require("memberships.manage")), db: Session = Depends(get_db)):
    return membership_service.upsert_plan(db, p, body.model_dump())


@router.put("/membership-plans/{plan_id}", response_model=PlanOut)
def update_plan(plan_id: uuid.UUID, body: PlanIn, p: Principal = Depends(require("memberships.manage")), db: Session = Depends(get_db)):
    return membership_service.upsert_plan(db, p, body.model_dump(), plan_id)


@router.get("/memberships", response_model=list[MembershipOut])
def list_memberships(customer_id: uuid.UUID | None = None, status: str | None = None, expiring_days: int | None = None,
                     p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if not p.has("customers.view"):
        customer_id = p.user.customer_id
        if not customer_id:
            return []
    return membership_service.list_memberships(db, p, customer_id=customer_id, status=status, expiring_days=expiring_days)


@router.post("/memberships", response_model=MembershipOut, status_code=201)
def sell_membership(body: SellMembershipIn, p: Principal = Depends(require("memberships.manage")), db: Session = Depends(get_db)):
    return membership_service.sell(db, p, branch_id=body.branch_id, customer_id=body.customer_id, plan_id=body.plan_id, payment_method=body.payment_method,
                                   amount=body.amount, reference=body.reference, card_uid=body.card_uid)


@router.post("/memberships/{membership_id}/renew", response_model=MembershipOut)
def renew(membership_id: uuid.UUID, body: RenewIn, p: Principal = Depends(require("memberships.manage")), db: Session = Depends(get_db)):
    return membership_service.renew(db, p, membership_id, body.payment_method, body.reference)


@router.post("/memberships/{membership_id}/adjust-minutes", response_model=MembershipOut)
def adjust_minutes(membership_id: uuid.UUID, body: MinutesAdjustIn, p: Principal = Depends(require("memberships.manage")), db: Session = Depends(get_db)):
    return membership_service.adjust_minutes(db, p, membership_id, body.minutes, body.reason)


@router.post("/memberships/{membership_id}/status", response_model=MembershipOut)
def membership_status(membership_id: uuid.UUID, body: MembershipStatusIn, p: Principal = Depends(require("memberships.manage")), db: Session = Depends(get_db)):
    return membership_service.set_status(db, p, membership_id, body.status, body.reason)


@router.post("/memberships/{membership_id}/card", response_model=MembershipOut)
def link_card(membership_id: uuid.UUID, body: CardIn, p: Principal = Depends(require("memberships.manage")), db: Session = Depends(get_db)):
    return membership_service.link_card(db, p, membership_id, body.card_uid)


@router.get("/memberships/{membership_id}/statement")
def statement(membership_id: uuid.UUID, p: Principal = Depends(require("customers.view")), db: Session = Depends(get_db)):
    st = membership_service.statement(db, p, membership_id)
    return {"membership": MembershipOut.model_validate(st["membership"]), "transactions": [MembershipTxnOut.model_validate(t) for t in st["transactions"]]}


# ============================================================================ loyalty & coupons
@router.post("/customers/{customer_id}/loyalty/redeem", response_model=InvoiceOut)
def redeem(customer_id: uuid.UUID, body: RedeemIn, p: Principal = Depends(require("billing.operate")), db: Session = Depends(get_db)):
    return loyalty_service.redeem(db, p, customer_id, body.invoice_id, body.points)


@router.get("/coupons", response_model=list[CouponOut])
def coupons(p: Principal = Depends(require("pricing.manage")), db: Session = Depends(get_db)):
    return list(db.scalars(select(Coupon).where(Coupon.organization_id == p.organization_id).order_by(Coupon.created_at.desc())).all())


@router.post("/coupons", response_model=CouponOut, status_code=201)
def create_coupon(body: CouponIn, p: Principal = Depends(require("pricing.manage")), db: Session = Depends(get_db)):
    return loyalty_service.create_coupon(db, p, body.model_dump())
