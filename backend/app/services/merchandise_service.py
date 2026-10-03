"""Merchandise catalog, inventory mutations, and fulfillment helpers."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.db_errors import is_unique_violation
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.models import InventoryMovement, Order, OrderItem, Product, ProductVariant
from app.services.audit import record_audit
from app.services.membership_eligibility import utcnow
from app.services.rbac import require_permission


def available_qty(variant: ProductVariant) -> int:
    return int(variant.quantity_on_hand) - int(variant.quantity_reserved)


async def _get_product(db: AsyncSession, *, club_id: uuid.UUID, product_id: uuid.UUID) -> Product:
    product = await db.scalar(
        select(Product).where(Product.id == product_id, Product.club_id == club_id)
    )
    if product is None:
        raise NotFoundError("Product not found.")
    return product


async def _get_variant_for_club(
    db: AsyncSession, *, club_id: uuid.UUID, variant_id: uuid.UUID, for_update: bool = False
) -> ProductVariant:
    stmt = (
        select(ProductVariant)
        .join(Product, Product.id == ProductVariant.product_id)
        .options(joinedload(ProductVariant.product))
        .where(ProductVariant.id == variant_id, Product.club_id == club_id)
    )
    if for_update:
        stmt = stmt.with_for_update(of=ProductVariant)
    variant = (await db.scalars(stmt)).unique().first()
    if variant is None:
        raise NotFoundError("Product variant not found.")
    return variant


async def create_product(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    name: str,
    description: str = "",
) -> Product:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_merchandise")
    product = Product(
        club_id=club_id,
        name=name.strip(),
        description=description or "",
        status="active",
    )
    db.add(product)
    await db.flush()
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="product.created",
        entity_type="product",
        entity_id=product.id,
    )
    return product


async def patch_product(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    product_id: uuid.UUID,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> Product:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_merchandise")
    product = await db.scalar(
        select(Product).where(Product.id == product_id, Product.club_id == club_id).with_for_update()
    )
    if product is None:
        raise NotFoundError("Product not found.")
    if name is not None:
        product.name = name.strip()
    if description is not None:
        product.description = description
    if status is not None:
        if status not in {"active", "archived"}:
            raise AppError("Invalid product status.")
        product.status = status
    await db.flush()
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="product.updated",
        entity_type="product",
        entity_id=product.id,
        details={"status": product.status},
    )
    return product


async def list_products(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    include_archived: bool = False,
) -> list[Product]:
    stmt = (
        select(Product)
        .options(joinedload(Product.variants))
        .where(Product.club_id == club_id)
        .order_by(Product.name.asc())
    )
    if not include_archived:
        stmt = stmt.where(Product.status == "active")
    return list((await db.scalars(stmt)).unique().all())


async def create_variant(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    product_id: uuid.UUID,
    label: str,
    sku: str,
    price: Decimal,
) -> ProductVariant:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_merchandise")
    product = await _get_product(db, club_id=club_id, product_id=product_id)
    if product.status != "active":
        raise AppError("Cannot add variants to an archived product.")
    variant = ProductVariant(
        product_id=product.id,
        label=label.strip(),
        sku=sku.strip(),
        price=price,
        is_active=True,
        quantity_on_hand=0,
        quantity_reserved=0,
    )
    db.add(variant)
    try:
        await db.flush()
    except Exception as exc:
        if is_unique_violation(exc):
            raise ConflictError("SKU already exists for this product.", code="sku_taken") from exc
        raise
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="product_variant.created",
        entity_type="product_variant",
        entity_id=variant.id,
    )
    return variant


async def patch_variant(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    variant_id: uuid.UUID,
    label: str | None = None,
    sku: str | None = None,
    price: Decimal | None = None,
    is_active: bool | None = None,
) -> ProductVariant:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_merchandise")
    variant = await _get_variant_for_club(db, club_id=club_id, variant_id=variant_id, for_update=True)
    if label is not None:
        variant.label = label.strip()
    if sku is not None:
        variant.sku = sku.strip()
    if price is not None:
        if price < 0:
            raise AppError("Price must be non-negative.")
        variant.price = price
    if is_active is not None:
        variant.is_active = is_active
    try:
        await db.flush()
    except Exception as exc:
        if is_unique_violation(exc):
            raise ConflictError("SKU already exists for this product.", code="sku_taken") from exc
        raise
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="product_variant.updated",
        entity_type="product_variant",
        entity_id=variant.id,
    )
    return variant


async def _apply_movement(
    db: AsyncSession,
    *,
    variant: ProductVariant,
    delta_on_hand: int,
    delta_reserved: int,
    reason: str,
    actor_user_id: uuid.UUID | None,
    note: str = "",
    order_item_id: uuid.UUID | None = None,
    idempotency_key: str,
) -> InventoryMovement | None:
    """Apply counter deltas + ledger row. Returns None when idempotency key already exists."""
    existing = await db.scalar(
        select(InventoryMovement).where(InventoryMovement.idempotency_key == idempotency_key)
    )
    if existing is not None:
        return None

    new_on_hand = int(variant.quantity_on_hand) + delta_on_hand
    new_reserved = int(variant.quantity_reserved) + delta_reserved
    if new_on_hand < 0 or new_reserved < 0 or new_reserved > new_on_hand:
        raise ConflictError("Insufficient inventory for this operation.", code="inventory_insufficient")

    variant.quantity_on_hand = new_on_hand
    variant.quantity_reserved = new_reserved
    movement = InventoryMovement(
        variant_id=variant.id,
        delta_on_hand=delta_on_hand,
        delta_reserved=delta_reserved,
        reason=reason,
        order_item_id=order_item_id,
        actor_user_id=actor_user_id,
        note=note or "",
        idempotency_key=idempotency_key,
    )
    db.add(movement)
    try:
        await db.flush()
    except Exception as exc:
        if is_unique_violation(exc):
            return None
        raise
    return movement


async def receive_stock(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    variant_id: uuid.UUID,
    quantity: int,
    note: str = "",
) -> ProductVariant:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_merchandise")
    if quantity < 1:
        raise AppError("Receive quantity must be at least 1.")
    variant = await _get_variant_for_club(db, club_id=club_id, variant_id=variant_id, for_update=True)
    key = f"receive:{variant.id}:{uuid.uuid4().hex}"
    await _apply_movement(
        db,
        variant=variant,
        delta_on_hand=quantity,
        delta_reserved=0,
        reason="receive",
        actor_user_id=actor_user_id,
        note=note,
        idempotency_key=key,
    )
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="inventory.receive",
        entity_type="product_variant",
        entity_id=variant.id,
        details={"quantity": quantity},
    )
    return variant


async def adjust_stock(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    variant_id: uuid.UUID,
    delta_on_hand: int,
    note: str,
) -> ProductVariant:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_merchandise")
    if not note or not note.strip():
        raise AppError("Adjustment requires a justification note.", code="adjust_note_required")
    if delta_on_hand == 0:
        raise AppError("Adjustment delta must be non-zero.")
    variant = await _get_variant_for_club(db, club_id=club_id, variant_id=variant_id, for_update=True)
    key = f"adjust:{variant.id}:{uuid.uuid4().hex}"
    await _apply_movement(
        db,
        variant=variant,
        delta_on_hand=delta_on_hand,
        delta_reserved=0,
        reason="adjust",
        actor_user_id=actor_user_id,
        note=note.strip(),
        idempotency_key=key,
    )
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="inventory.adjust",
        entity_type="product_variant",
        entity_id=variant.id,
        details={"delta_on_hand": delta_on_hand, "note": note.strip()},
    )
    return variant


async def list_movements(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    variant_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[InventoryMovement], int]:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_merchandise")
    await _get_variant_for_club(db, club_id=club_id, variant_id=variant_id)
    total = await db.scalar(
        select(func.count()).select_from(InventoryMovement).where(InventoryMovement.variant_id == variant_id)
    ) or 0
    rows = list(
        (
            await db.scalars(
                select(InventoryMovement)
                .where(InventoryMovement.variant_id == variant_id)
                .order_by(InventoryMovement.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return rows, int(total)


async def restock_for_refund(
    db: AsyncSession,
    *,
    order_item: OrderItem,
    refund_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> None:
    """Return refunded units to on-hand stock (reason ``adjust``, note ``refund return``).

    Called by the refund workflow, which has already authorized the actor via
    ``record_refunds``; no merchandise permission is required here. Idempotent per
    (refund, order item).
    """
    if order_item.item_kind != "merchandise" or not order_item.product_variant_id:
        return
    variant = await db.scalar(
        select(ProductVariant).where(ProductVariant.id == order_item.product_variant_id).with_for_update()
    )
    if variant is None:
        raise NotFoundError("Product variant not found.")
    await _apply_movement(
        db,
        variant=variant,
        delta_on_hand=order_item.quantity,
        delta_reserved=0,
        reason="adjust",
        actor_user_id=actor_user_id,
        note="refund return",
        order_item_id=order_item.id,
        idempotency_key=f"refund-restock:{refund_id}:{order_item.id}",
    )


async def lock_variants_sorted(
    db: AsyncSession, *, variant_ids: list[uuid.UUID]
) -> dict[uuid.UUID, ProductVariant]:
    """Deterministic FOR UPDATE order by UUID to avoid deadlocks."""
    locked: dict[uuid.UUID, ProductVariant] = {}
    for vid in sorted(set(variant_ids), key=str):
        row = await db.scalar(select(ProductVariant).where(ProductVariant.id == vid).with_for_update())
        if row is None:
            raise NotFoundError("Product variant not found.")
        locked[vid] = row
    return locked


async def release_expired_reservations_for_variants(
    db: AsyncSession, *, variant_ids: list[uuid.UUID]
) -> None:
    """Free reserved counters held by expired pending merch orders for the given variants."""
    if not variant_ids:
        return
    now = utcnow()
    items = (
        await db.scalars(
            select(OrderItem)
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                OrderItem.item_kind == "merchandise",
                OrderItem.product_variant_id.in_(variant_ids),
                OrderItem.fulfillment_status == "reserved",
                Order.status == "pending",
                Order.expires_at.is_not(None),
                Order.expires_at <= now,
            )
            .order_by(OrderItem.id)
        )
    ).all()
    for item in items:
        await release_reservation(db, order_item=item, actor_user_id=None, cancel_item=True)


async def reserve_stock(
    db: AsyncSession,
    *,
    variant: ProductVariant,
    quantity: int,
    order_item_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> None:
    if available_qty(variant) < quantity:
        raise ConflictError("Not enough stock available.", code="inventory_insufficient")
    moved = await _apply_movement(
        db,
        variant=variant,
        delta_on_hand=0,
        delta_reserved=quantity,
        reason="reserve",
        actor_user_id=actor_user_id,
        order_item_id=order_item_id,
        idempotency_key=f"reserve:{order_item_id}",
    )
    if moved is None and available_qty(variant) < 0:
        raise ConflictError("Not enough stock available.", code="inventory_insufficient")


async def release_reservation(
    db: AsyncSession,
    *,
    order_item: OrderItem,
    actor_user_id: uuid.UUID | None,
    cancel_item: bool = True,
) -> None:
    if order_item.item_kind != "merchandise" or not order_item.product_variant_id:
        return
    if order_item.fulfillment_status not in {"reserved", None}:
        # Already sold / collected / cancelled — release is a no-op.
        if order_item.fulfillment_status == "cancelled":
            return
        # awaiting_collection / collected have already consumed reserved via sale.
        return
    variant = await db.scalar(
        select(ProductVariant).where(ProductVariant.id == order_item.product_variant_id).with_for_update()
    )
    if variant is None:
        raise NotFoundError("Product variant not found.")
    await _apply_movement(
        db,
        variant=variant,
        delta_on_hand=0,
        delta_reserved=-order_item.quantity,
        reason="release",
        actor_user_id=actor_user_id,
        order_item_id=order_item.id,
        idempotency_key=f"release:{order_item.id}",
    )
    if cancel_item:
        order_item.fulfillment_status = "cancelled"


async def consume_reservation_as_sale(
    db: AsyncSession,
    *,
    order_item: OrderItem,
    actor_user_id: uuid.UUID,
) -> None:
    """Convert an active reservation into a sale (on_hand↓ reserved↓). Idempotent."""
    if order_item.item_kind != "merchandise" or not order_item.product_variant_id:
        return
    if order_item.fulfillment_status == "awaiting_collection" or order_item.fulfillment_status == "collected":
        return
    if order_item.fulfillment_status != "reserved":
        raise AppError("Merchandise reservation is not active.", code="merch_not_reserved")
    variant = await db.scalar(
        select(ProductVariant).where(ProductVariant.id == order_item.product_variant_id).with_for_update()
    )
    if variant is None:
        raise NotFoundError("Product variant not found.")
    moved = await _apply_movement(
        db,
        variant=variant,
        delta_on_hand=-order_item.quantity,
        delta_reserved=-order_item.quantity,
        reason="sale",
        actor_user_id=actor_user_id,
        order_item_id=order_item.id,
        idempotency_key=f"sale:{order_item.id}",
    )
    if moved is None:
        # Idempotent retry — ensure status is consistent.
        order_item.fulfillment_status = "awaiting_collection"
        return
    order_item.fulfillment_status = "awaiting_collection"


async def mark_collected(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    order_item_id: uuid.UUID,
) -> OrderItem:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="fulfill_merchandise")
    item = await db.scalar(select(OrderItem).where(OrderItem.id == order_item_id).with_for_update())
    if item is None or item.item_kind != "merchandise":
        raise NotFoundError("Merchandise order item not found.")
    order = await db.get(Order, item.order_id)
    if order is None or order.club_id != club_id:
        raise ForbiddenError("Order does not belong to this club.")
    if order.status != "paid":
        raise AppError("Only paid merchandise can be collected.", code="merch_not_paid")
    if item.fulfillment_status == "collected":
        return item
    if item.fulfillment_status != "awaiting_collection":
        raise AppError("Item is not awaiting collection.", code="merch_not_awaiting")
    item.fulfillment_status = "collected"
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="merch.collected",
        entity_type="order_item",
        entity_id=item.id,
    )
    return item


async def list_fulfillment_queue(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> list[OrderItem]:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="fulfill_merchandise")
    return list(
        (
            await db.scalars(
                select(OrderItem)
                .join(Order, Order.id == OrderItem.order_id)
                .where(
                    Order.club_id == club_id,
                    Order.status == "paid",
                    OrderItem.item_kind == "merchandise",
                    OrderItem.fulfillment_status == "awaiting_collection",
                )
                .order_by(Order.created_at.asc())
            )
        ).all()
    )


async def list_my_merchandise_purchases(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    club_id: uuid.UUID | None = None,
) -> list[OrderItem]:
    stmt = (
        select(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.user_id == user_id, OrderItem.item_kind == "merchandise")
        .order_by(Order.created_at.desc())
    )
    if club_id is not None:
        stmt = stmt.where(Order.club_id == club_id)
    return list((await db.scalars(stmt)).all())
