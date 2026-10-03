from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


class ProductPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: str | None = None


class VariantIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    sku: str = Field(min_length=1, max_length=64)
    price: Decimal = Field(ge=0)


class VariantPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    sku: str | None = Field(default=None, min_length=1, max_length=64)
    price: Decimal | None = Field(default=None, ge=0)
    is_active: bool | None = None


class StockReceiveIn(BaseModel):
    quantity: int = Field(ge=1)
    note: str = ""


class StockAdjustIn(BaseModel):
    delta_on_hand: int
    note: str = Field(min_length=1, max_length=2000)


class MerchandiseOrderIn(BaseModel):
    product_variant_id: UUID
    quantity: int = Field(default=1, ge=1, le=20)


class VariantOut(ORMModel):
    id: UUID
    product_id: UUID
    label: str
    sku: str
    price: Decimal
    is_active: bool
    quantity_on_hand: int
    quantity_reserved: int
    quantity_available: int = 0


class ProductOut(ORMModel):
    id: UUID
    club_id: UUID
    name: str
    description: str
    status: str
    created_at: datetime
    updated_at: datetime
    variants: list[VariantOut] = []


class InventoryMovementOut(ORMModel):
    id: UUID
    variant_id: UUID
    delta_on_hand: int
    delta_reserved: int
    reason: str
    order_item_id: UUID | None
    actor_user_id: UUID | None
    note: str
    idempotency_key: str
    created_at: datetime


class MovementPageOut(BaseModel):
    items: list[InventoryMovementOut]
    total: int
    limit: int
    offset: int


class MerchPurchaseOut(ORMModel):
    id: UUID
    order_id: UUID
    product_variant_id: UUID | None
    quantity: int
    unit_price_snapshot: Decimal
    title_snapshot: str
    fulfillment_status: str | None
    order_status: str | None = None
    club_id: UUID | None = None
    expires_at: datetime | None = None
    created_at: datetime | None = None
