"""POS & inventory: products, table tabs, counter sales and the inventory ledger.

Stock is never "set": every movement is an inventory_transactions row and the
cached stock_levels row is updated under a row lock in the same transaction.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import for_update
from app.core.deps import Principal
from app.core.errors import Conflict, InvalidState, NotFound, ValidationFailed
from app.core.realtime import PendingEvents
from app.core.timeutil import utcnow
from app.models import (
    ApprovalRequest,
    Branch,
    GameSession,
    InventoryTransaction,
    Invoice,
    Order,
    OrderItem,
    Product,
    ProductCategory,
    StockLevel,
    Supplier,
)
from app.models.base import money
from app.models.enums import OPEN_SESSION_STATUSES, ApprovalType, InventoryTxnType, OrderStatus
from app.services.audit import audit, raise_alert, snapshot
from app.services.common import ensure_branch_access, get_branch, next_number

PRODUCT_FIELDS = ["sku", "name", "category_id", "price", "cost_price", "tax_rate", "track_stock", "low_stock_threshold", "is_active"]


# ------------------------------------------------------------------------------ catalogue
def create_category(db: Session, actor: Principal, name: str, sort_order: int = 0) -> ProductCategory:
    actor.require("products.manage")
    c = ProductCategory(organization_id=actor.organization_id, name=name.strip(), sort_order=sort_order)
    db.add(c)
    db.flush()
    audit(db, actor, "product_category.create", "product_category", c.id, after={"name": name})
    db.commit()
    return c


def upsert_product(db: Session, actor: Principal, data: dict, product_id: uuid.UUID | None = None) -> Product:
    actor.require("products.manage")
    if product_id:
        p = db.get(Product, product_id)
        if not p or p.organization_id != actor.organization_id:
            raise NotFound("Product not found")
        before = snapshot(p, PRODUCT_FIELDS)
        for k, v in data.items():
            if k in PRODUCT_FIELDS:
                setattr(p, k, v)
        audit(db, actor, "product.update" if before.get("price") == str(p.price) else "product.price_change", "product", p.id, before=before, after=snapshot(p, PRODUCT_FIELDS))
    else:
        if db.scalar(select(Product.id).where(Product.organization_id == actor.organization_id, Product.sku == data["sku"])):
            raise Conflict("SKU already exists")
        p = Product(organization_id=actor.organization_id, **{k: v for k, v in data.items() if k in PRODUCT_FIELDS})
        db.add(p)
        db.flush()
        audit(db, actor, "product.create", "product", p.id, after=snapshot(p, PRODUCT_FIELDS))
    db.commit()
    return p


def list_products(db: Session, organization_id: uuid.UUID, branch_id: uuid.UUID | None, *, active_only: bool = True, q: str | None = None) -> list[dict]:
    stmt = select(Product).where(Product.organization_id == organization_id, Product.deleted_at.is_(None))
    if active_only:
        stmt = stmt.where(Product.is_active.is_(True))
    if q:
        stmt = stmt.where(func.lower(Product.name).like(f"%{q.lower()}%"))
    products = list(db.scalars(stmt.order_by(Product.name)).unique().all())
    levels = {}
    if branch_id and products:
        levels = {s.product_id: s.quantity for s in db.scalars(select(StockLevel).where(StockLevel.branch_id == branch_id, StockLevel.product_id.in_([p.id for p in products]))).all()}
    return [{"product": p, "stock": levels.get(p.id, Decimal("0")) if p.track_stock else None} for p in products]


def create_supplier(db: Session, actor: Principal, data: dict) -> Supplier:
    actor.require("inventory.manage")
    s = Supplier(organization_id=actor.organization_id, **data)
    db.add(s)
    db.flush()
    audit(db, actor, "supplier.create", "supplier", s.id, after=data)
    db.commit()
    return s


# ------------------------------------------------------------------------------ inventory ledger
def _move(db: Session, *, branch_id, product: Product, txn_type: InventoryTxnType, qty: Decimal, actor: Principal | None, unit_cost=None,
          supplier_id=None, order_item_id=None, reference=None, note=None, allow_negative: bool = True, events: PendingEvents | None = None) -> InventoryTransaction:
    level = db.scalar(for_update(select(StockLevel).where(StockLevel.branch_id == branch_id, StockLevel.product_id == product.id), db))
    if level is None:
        level = StockLevel(branch_id=branch_id, product_id=product.id, quantity=Decimal("0"))
        db.add(level)
        db.flush()
    new_qty = Decimal(str(level.quantity)) + Decimal(str(qty))
    if new_qty < 0 and not allow_negative:
        raise Conflict(f"Only {level.quantity} of {product.name} in stock", code="OUT_OF_STOCK")
    level.quantity = new_qty
    t = InventoryTransaction(branch_id=branch_id, product_id=product.id, txn_type=txn_type, quantity=qty, unit_cost=unit_cost, balance_after=new_qty,
                             supplier_id=supplier_id, order_item_id=order_item_id, reference=reference, note=note,
                             created_by_id=actor.id if actor else None, created_at=utcnow())
    db.add(t)
    if product.track_stock and new_qty <= product.low_stock_threshold and qty < 0:
        raise_alert(db, branch_id, "LOW_STOCK", f"Low stock: {product.name} ({new_qty} left)", dedupe_key=f"lowstock:{branch_id}:{product.id}", events=events)
    return t


def stock_in(db: Session, actor: Principal, branch_id: uuid.UUID, product_id: uuid.UUID, qty: Decimal, *, txn_type: InventoryTxnType = InventoryTxnType.PURCHASE,
             unit_cost: Decimal | None = None, supplier_id: uuid.UUID | None = None, reference: str | None = None, note: str | None = None) -> InventoryTransaction:
    """Opening stock / purchase (receive) / customer return."""
    ensure_branch_access(actor, get_branch(db, branch_id), "inventory.manage")
    if txn_type not in (InventoryTxnType.OPENING, InventoryTxnType.PURCHASE, InventoryTxnType.RETURN):
        raise ValidationFailed("Invalid stock-in type")
    if qty <= 0:
        raise ValidationFailed("Quantity must be positive")
    p = _product(db, actor, product_id)
    t = _move(db, branch_id=branch_id, product=p, txn_type=txn_type, qty=Decimal(str(qty)), actor=actor, unit_cost=unit_cost, supplier_id=supplier_id, reference=reference, note=note)
    if unit_cost is not None and txn_type == InventoryTxnType.PURCHASE:
        p.cost_price = money(unit_cost)
    audit(db, actor, f"inventory.{txn_type.lower()}", "product", p.id, branch_id=branch_id, after={"qty": qty, "unit_cost": unit_cost, "reference": reference})
    db.commit()
    return t


def stock_out(db: Session, actor: Principal, branch_id: uuid.UUID, product_id: uuid.UUID, qty: Decimal, *, txn_type: InventoryTxnType, reason: str,
              supplier_id: uuid.UUID | None = None) -> InventoryTransaction:
    """Damaged / supplier return / signed adjustment (stock count correction)."""
    ensure_branch_access(actor, get_branch(db, branch_id), "inventory.manage")
    if not reason:
        raise ValidationFailed("Reason is required")
    p = _product(db, actor, product_id)
    if txn_type == InventoryTxnType.ADJUSTMENT:
        signed = Decimal(str(qty))
    elif txn_type in (InventoryTxnType.DAMAGED, InventoryTxnType.SUPPLIER_RETURN):
        signed = -abs(Decimal(str(qty)))
    else:
        raise ValidationFailed("Invalid stock-out type")
    t = _move(db, branch_id=branch_id, product=p, txn_type=txn_type, qty=signed, actor=actor, supplier_id=supplier_id, note=reason, allow_negative=False)
    audit(db, actor, "inventory.adjust", "product", p.id, branch_id=branch_id, after={"type": txn_type, "qty": signed}, reason=reason)
    db.commit()
    return t


def ledger(db: Session, actor: Principal, branch_id: uuid.UUID, product_id: uuid.UUID | None, offset: int, limit: int) -> tuple[list[InventoryTransaction], int]:
    actor.require("inventory.manage", branch_id)
    stmt = select(InventoryTransaction).where(InventoryTransaction.branch_id == branch_id)
    if product_id:
        stmt = stmt.where(InventoryTransaction.product_id == product_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    return list(db.scalars(stmt.order_by(InventoryTransaction.created_at.desc()).offset(offset).limit(limit)).all()), total


def low_stock(db: Session, branch_id: uuid.UUID) -> list[dict]:
    rows = db.execute(
        select(Product, StockLevel.quantity).join(StockLevel, StockLevel.product_id == Product.id)
        .where(StockLevel.branch_id == branch_id, Product.track_stock.is_(True), Product.is_active.is_(True), StockLevel.quantity <= Product.low_stock_threshold)
    ).unique().all()
    return [{"product": p, "stock": qty} for p, qty in rows]


def _product(db: Session, actor: Principal, product_id: uuid.UUID) -> Product:
    p = db.get(Product, product_id)
    if not p or p.organization_id != actor.organization_id or p.deleted_at is not None:
        raise NotFound("Product not found")
    return p


# ------------------------------------------------------------------------------ orders
def _order_for_session(db: Session, actor: Principal, session: GameSession) -> Order:
    order = db.scalar(for_update(select(Order).where(Order.session_id == session.id), db))
    if order is None:
        branch = db.get(Branch, session.branch_id)
        order = Order(branch_id=session.branch_id, number=next_number(db, branch, "ORD", "ORD"), session_id=session.id, customer_id=session.customer_id, created_by_id=actor.id)
        db.add(order)
        db.flush()
    return order


def add_items_to_session(db: Session, actor: Principal, session_id: uuid.UUID, items: list[dict]) -> Order:
    """Table tab: 'Table 4 → Coke ₹60, Water ₹30'. Stock is deducted immediately."""
    events = PendingEvents()
    s = db.get(GameSession, session_id)
    if not s:
        raise NotFound("Session not found")
    actor.require("pos.sell", s.branch_id)
    if s.status not in OPEN_SESSION_STATUSES:
        raise InvalidState("Session is closed; add items to a counter sale instead")
    order = _order_for_session(db, actor, s)
    _add_items(db, actor, order, items, events)
    db.commit()
    events.add(s.branch_id, "order.updated", {"session_id": s.id, "table_id": s.table_id, "subtotal": order.subtotal})
    events.flush()
    return order


def _add_items(db: Session, actor: Principal, order: Order, items: list[dict], events: PendingEvents) -> None:
    if not items:
        raise ValidationFailed("No items")
    for it in items:
        p = _product(db, actor, it["product_id"])
        if not p.is_active:
            raise ValidationFailed(f"{p.name} is not available")
        qty = Decimal(str(it.get("quantity", 1)))
        if qty <= 0:
            raise ValidationFailed("Quantity must be positive")
        line = OrderItem(order_id=order.id, product_id=p.id, name=p.name, quantity=qty, unit_price=money(p.price), amount=money(p.price * qty),
                         added_by_id=actor.id, created_at=utcnow())
        db.add(line)
        db.flush()
        if line not in order.items:
            order.items.append(line)
        if p.track_stock:
            _move(db, branch_id=order.branch_id, product=p, txn_type=InventoryTxnType.SALE, qty=-qty, actor=actor, order_item_id=line.id,
                  reference=order.number, allow_negative=False, events=events)
    order.subtotal = money(sum((money(i.amount) for i in order.items if i.status == "ACTIVE"), Decimal("0")))
    audit(db, actor, "order.add_items", "order", order.id, branch_id=order.branch_id, after={"items": [{"product_id": i["product_id"], "qty": i.get("quantity", 1)} for i in items]})


def counter_sale(db: Session, actor: Principal, branch_id: uuid.UUID, items: list[dict], customer_id: uuid.UUID | None) -> Invoice:
    """Direct POS sale (no table) → order + invoice in one transaction."""
    events = PendingEvents()
    branch = get_branch(db, branch_id)
    ensure_branch_access(actor, branch, "pos.sell")
    order = Order(branch_id=branch_id, number=next_number(db, branch, "ORD", "ORD"), customer_id=customer_id, created_by_id=actor.id)
    db.add(order)
    db.flush()
    _add_items(db, actor, order, items, events)
    from app.services import billing_service

    inv = billing_service.generate_for_order(db, actor, order)
    db.commit()
    events.flush()
    return inv


def cancel_item(db: Session, actor: Principal, item_id: uuid.UUID, reason: str) -> dict:
    """Staff cancelling a line needs approval unless they can adjust bills."""
    item = db.get(OrderItem, item_id)
    if not item:
        raise NotFound("Item not found")
    order = db.get(Order, item.order_id)
    actor.require("pos.sell", order.branch_id)
    if order.status != OrderStatus.OPEN:
        raise InvalidState("Order already billed; use an invoice adjustment")
    if actor.has("billing.adjust", order.branch_id):
        cancel_item_approved(db, actor, item_id, reason)
        db.commit()
        return {"cancelled": True}
    req = ApprovalRequest(branch_id=order.branch_id, approval_type=ApprovalType.CANCEL_ITEM, order_item_id=item.id, session_id=order.session_id,
                          amount=item.amount, reason=reason, requested_by_id=actor.id)
    db.add(req)
    db.flush()
    audit(db, actor, "approval.request", "approval_request", req.id, branch_id=order.branch_id, after={"type": "CANCEL_ITEM", "item": item.name})
    db.commit()
    return {"cancelled": False, "approval_request_id": req.id}


def cancel_item_approved(db: Session, actor: Principal, item_id: uuid.UUID, reason: str) -> None:
    item = db.scalar(for_update(select(OrderItem).where(OrderItem.id == item_id), db))
    if item.status != "ACTIVE":
        return
    order = db.get(Order, item.order_id)
    item.status, item.cancel_reason, item.cancelled_by_id = "CANCELLED", reason, actor.id
    p = db.get(Product, item.product_id)
    if p.track_stock:
        _move(db, branch_id=order.branch_id, product=p, txn_type=InventoryTxnType.SALE_REVERSAL, qty=Decimal(str(item.quantity)), actor=actor,
              order_item_id=item.id, reference=order.number, note=reason)
    order.subtotal = money(sum((money(i.amount) for i in order.items if i.status == "ACTIVE"), Decimal("0")))
    audit(db, actor, "order.cancel_item", "order_item", item.id, branch_id=order.branch_id, before={"status": "ACTIVE"}, after={"status": "CANCELLED"}, reason=reason)


def reverse_order_stock(db: Session, actor: Principal, order: Order, note: str) -> None:
    for item in order.items:
        if item.status != "ACTIVE":
            continue
        p = db.get(Product, item.product_id)
        if p.track_stock:
            _move(db, branch_id=order.branch_id, product=p, txn_type=InventoryTxnType.SALE_REVERSAL, qty=Decimal(str(item.quantity)), actor=actor,
                  order_item_id=item.id, reference=order.number, note=note)


def session_order(db: Session, session_id: uuid.UUID) -> Order | None:
    return db.scalar(select(Order).where(Order.session_id == session_id))
