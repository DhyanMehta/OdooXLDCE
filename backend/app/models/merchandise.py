"""Merchandise catalog, variants, and inventory movement ledger."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Product(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="ck_products_status"),
    )

    club_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clubs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)

    variants: Mapped[list[ProductVariant]] = relationship(back_populates="product")


class ProductVariant(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "product_variants"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_product_variants_price_nonneg"),
        CheckConstraint("quantity_on_hand >= 0", name="ck_product_variants_on_hand_nonneg"),
        CheckConstraint("quantity_reserved >= 0", name="ck_product_variants_reserved_nonneg"),
        CheckConstraint(
            "quantity_reserved <= quantity_on_hand",
            name="ck_product_variants_reserved_lte_on_hand",
        ),
        UniqueConstraint("product_id", "sku", name="uq_product_variants_product_sku"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    quantity_on_hand: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quantity_reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    product: Mapped[Product] = relationship(back_populates="variants")
    movements: Mapped[list[InventoryMovement]] = relationship(back_populates="variant")

    @property
    def quantity_available(self) -> int:
        return self.quantity_on_hand - self.quantity_reserved


class InventoryMovement(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint(
            "reason IN ('receive', 'adjust', 'reserve', 'release', 'sale')",
            name="ck_inventory_movements_reason",
        ),
        UniqueConstraint("idempotency_key", name="uq_inventory_movements_idempotency"),
    )

    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("product_variants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    delta_on_hand: Mapped[int] = mapped_column(Integer, nullable=False)
    delta_reserved: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    order_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_items.id", ondelete="RESTRICT")
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    variant: Mapped[ProductVariant] = relationship(back_populates="movements")
