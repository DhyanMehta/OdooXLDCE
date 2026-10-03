from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy import select

from app.core.errors import ForbiddenError
from app.db.session import get_db
from app.dependencies.auth import AuthContext, get_club, get_current_auth, get_optional_auth, require_csrf
from app.models import Club, Order, Product, ProductVariant
from app.schemas.merchandise import (
    InventoryMovementOut,
    MerchPurchaseOut,
    MerchandiseOrderIn,
    MovementPageOut,
    ProductIn,
    ProductOut,
    ProductPatch,
    StockAdjustIn,
    StockReceiveIn,
    VariantIn,
    VariantOut,
    VariantPatch,
)
from app.schemas.orders import OrderOut
from app.services.merchandise_service import (
    adjust_stock,
    create_product,
    create_variant,
    list_fulfillment_queue,
    list_movements,
    list_my_merchandise_purchases,
    list_products,
    mark_collected,
    patch_product,
    patch_variant,
    receive_stock,
)
from app.services.purchase_service import create_merchandise_order
from app.services.rbac import require_permission

router = APIRouter(tags=["merchandise"])


async def _load_order(db: AsyncSession, order_id: uuid.UUID) -> Order:
    return (
        await db.scalars(
            select(Order)
            .options(joinedload(Order.items), joinedload(Order.payments))
            .where(Order.id == order_id)
        )
    ).unique().one()


async def _order_out(db: AsyncSession, order: Order) -> OrderOut:
    return OrderOut.model_validate(order)


def _variant_out(variant: ProductVariant) -> VariantOut:
    data = VariantOut.model_validate(variant)
    data.quantity_available = variant.quantity_on_hand - variant.quantity_reserved
    return data


def _product_out(product: Product) -> ProductOut:
    data = ProductOut.model_validate(product)
    data.variants = [_variant_out(v) for v in product.variants]
    return data


async def _can_manage_merch(db: AsyncSession, club_id: uuid.UUID, auth: AuthContext | None) -> bool:
    if auth is None:
        return False
    try:
        await require_permission(db, club_id=club_id, user_id=auth.user.id, permission="manage_merchandise")
        return True
    except ForbiddenError:
        return False


@router.get("/clubs/{club_id}/products", response_model=list[ProductOut])
async def get_products(
    club: Club = Depends(get_club),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext | None = Depends(get_optional_auth),
    include_archived: bool = False,
) -> list[ProductOut]:
    staff = include_archived and await _can_manage_merch(db, club.id, auth)
    products = await list_products(db, club_id=club.id, include_archived=staff)
    # Students only see active variants on active products.
    if not staff:
        for p in products:
            p.variants = [v for v in p.variants if v.is_active]
    return [_product_out(p) for p in products]


@router.post("/clubs/{club_id}/products", response_model=ProductOut)
async def post_product(
    payload: ProductIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> ProductOut:
    product = await create_product(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        name=payload.name,
        description=payload.description,
    )
    await db.commit()
    loaded = (
        await db.scalars(
            select(Product).options(joinedload(Product.variants)).where(Product.id == product.id)
        )
    ).unique().one()
    return _product_out(loaded)


@router.patch("/clubs/{club_id}/products/{product_id}", response_model=ProductOut)
async def patch_product_endpoint(
    product_id: uuid.UUID,
    payload: ProductPatch,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> ProductOut:
    await patch_product(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        product_id=product_id,
        **payload.model_dump(exclude_unset=True),
    )
    await db.commit()
    loaded = (
        await db.scalars(
            select(Product).options(joinedload(Product.variants)).where(Product.id == product_id)
        )
    ).unique().one()
    return _product_out(loaded)


@router.post("/clubs/{club_id}/products/{product_id}/variants", response_model=VariantOut)
async def post_variant(
    product_id: uuid.UUID,
    payload: VariantIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> VariantOut:
    variant = await create_variant(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        product_id=product_id,
        label=payload.label,
        sku=payload.sku,
        price=payload.price,
    )
    await db.commit()
    await db.refresh(variant)
    return _variant_out(variant)


@router.patch("/clubs/{club_id}/variants/{variant_id}", response_model=VariantOut)
async def patch_variant_endpoint(
    variant_id: uuid.UUID,
    payload: VariantPatch,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> VariantOut:
    variant = await patch_variant(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        variant_id=variant_id,
        **payload.model_dump(exclude_unset=True),
    )
    await db.commit()
    await db.refresh(variant)
    return _variant_out(variant)


@router.post("/clubs/{club_id}/variants/{variant_id}/receive", response_model=VariantOut)
async def post_receive(
    variant_id: uuid.UUID,
    payload: StockReceiveIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> VariantOut:
    variant = await receive_stock(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        variant_id=variant_id,
        quantity=payload.quantity,
        note=payload.note,
    )
    await db.commit()
    await db.refresh(variant)
    return _variant_out(variant)


@router.post("/clubs/{club_id}/variants/{variant_id}/adjust", response_model=VariantOut)
async def post_adjust(
    variant_id: uuid.UUID,
    payload: StockAdjustIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> VariantOut:
    variant = await adjust_stock(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        variant_id=variant_id,
        delta_on_hand=payload.delta_on_hand,
        note=payload.note,
    )
    await db.commit()
    await db.refresh(variant)
    return _variant_out(variant)


@router.get("/clubs/{club_id}/variants/{variant_id}/movements", response_model=MovementPageOut)
async def get_movements(
    variant_id: uuid.UUID,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> MovementPageOut:
    rows, total = await list_movements(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        variant_id=variant_id,
        limit=limit,
        offset=offset,
    )
    return MovementPageOut(
        items=[InventoryMovementOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/clubs/{club_id}/orders/merchandise", response_model=OrderOut)
async def buy_merchandise(
    payload: MerchandiseOrderIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> OrderOut:
    order = await create_merchandise_order(
        db,
        club_id=club.id,
        user_id=auth.user.id,
        product_variant_id=payload.product_variant_id,
        quantity=payload.quantity,
    )
    await db.commit()
    return await _order_out(db, await _load_order(db, order.id))


@router.get("/me/merchandise", response_model=list[MerchPurchaseOut])
async def my_merchandise(
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
    club_id: uuid.UUID | None = None,
) -> list[MerchPurchaseOut]:
    items = await list_my_merchandise_purchases(db, user_id=auth.user.id, club_id=club_id)
    out: list[MerchPurchaseOut] = []
    for item in items:
        order = await db.get(Order, item.order_id)
        row = MerchPurchaseOut.model_validate(item)
        if order:
            row.order_status = order.status
            row.club_id = order.club_id
            row.expires_at = order.expires_at
            row.created_at = order.created_at
        out.append(row)
    return out


@router.get("/clubs/{club_id}/merchandise/fulfillment", response_model=list[MerchPurchaseOut])
async def fulfillment_queue(
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> list[MerchPurchaseOut]:
    items = await list_fulfillment_queue(db, club_id=club.id, actor_user_id=auth.user.id)
    out: list[MerchPurchaseOut] = []
    for item in items:
        order = await db.get(Order, item.order_id)
        row = MerchPurchaseOut.model_validate(item)
        if order:
            row.order_status = order.status
            row.club_id = order.club_id
            row.expires_at = order.expires_at
            row.created_at = order.created_at
        out.append(row)
    return out


@router.post("/clubs/{club_id}/merchandise/collect/{order_item_id}", response_model=MerchPurchaseOut)
async def collect_merchandise(
    order_item_id: uuid.UUID,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> MerchPurchaseOut:
    item = await mark_collected(
        db, club_id=club.id, actor_user_id=auth.user.id, order_item_id=order_item_id
    )
    await db.commit()
    order = await db.get(Order, item.order_id)
    row = MerchPurchaseOut.model_validate(item)
    if order:
        row.order_status = order.status
        row.club_id = order.club_id
        row.expires_at = order.expires_at
        row.created_at = order.created_at
    return row
