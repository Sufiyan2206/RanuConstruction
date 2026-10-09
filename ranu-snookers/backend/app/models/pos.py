from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.timeutil import utcnow
from app.models.base import Money, SoftDeleteMixin, TimestampMixin, UTCDateTime, pk
from app.models.enums import InventoryTxnType, OrderStatus, check_in


class ProductCategory(Base, TimestampMixin):
    __tablename__ = "product_categories"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Product(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("organization_id", "sku"), CheckConstraint("price >= 0", name="price"))
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("product_categories.id"))
    sku: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    cost_price: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0, nullable=False)
    track_stock: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    low_stock_threshold: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    category = relationship("ProductCategory", lazy="joined")


class Supplier(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "suppliers"
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(160))
    gstin: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(String(300))


class StockLevel(Base):
    """Cached on-hand quantity per (branch, product) = SUM(inventory_transactions.quantity).
    Updated in the same transaction as the ledger row, under a row lock."""

    __tablename__ = "stock_levels"
    __table_args__ = (UniqueConstraint("branch_id", "product_id"),)
    id: Mapped[uuid.UUID] = pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)


class InventoryTransaction(Base):
    """Inventory ledger (append-only)."""

    __tablename__ = "inventory_transactions"
    __table_args__ = (
        CheckConstraint(check_in("txn_type", InventoryTxnType), name="txn_type"),
        Index("ix_inventory_txn_branch_product", "branch_id", "product_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    txn_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)  # signed
    unit_cost: Mapped[Decimal | None] = mapped_column(Money)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("suppliers.id"))
    order_item_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("order_items.id"))
    reference: Mapped[str | None] = mapped_column(String(80))
    note: Mapped[str | None] = mapped_column(String(300))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class Order(Base, TimestampMixin):
    """POS order — either attached to a running table session ("table tab") or a
    direct counter sale."""

    __tablename__ = "orders"
    __table_args__ = (CheckConstraint(check_in("status", OrderStatus), name="status"),)
    id: Mapped[uuid.UUID] = pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True, nullable=False)
    number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("game_sessions.id"), unique=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("customers.id"))
    status: Mapped[str] = mapped_column(String(12), default=OrderStatus.OPEN, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Money, default=0, nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))

    items = relationship("OrderItem", lazy="selectin", order_by="OrderItem.created_at")


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="qty"),)
    id: Mapped[uuid.UUID] = pk()
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True, nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)  # snapshot
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False)  # snapshot
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="ACTIVE", nullable=False)  # ACTIVE / CANCELLED
    cancel_reason: Mapped[str | None] = mapped_column(String(200))
    cancelled_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    added_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
