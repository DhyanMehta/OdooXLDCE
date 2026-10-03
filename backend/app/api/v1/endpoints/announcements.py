from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError
from app.db.session import get_db
from app.dependencies.auth import AuthContext, get_club, get_optional_auth, require_csrf
from app.models import Club, NotificationDelivery
from app.schemas.announcements import (
    AnnouncementIn,
    AnnouncementOut,
    AnnouncementPageOut,
    AnnouncementPatch,
    DeliveryOut,
    SubscribeIn,
    SubscriberOut,
    SubscriberPageOut,
    TokenIn,
)
from app.schemas.common import MessageOut
from app.services.announcement_service import (
    OPAQUE_SUBSCRIBE_MSG,
    confirm_mailing_list,
    create_announcement,
    get_announcement,
    list_announcements,
    list_mailing_subscriptions,
    publish_announcement,
    send_correction_notification,
    staff_unsubscribe,
    subscribe_mailing_list,
    unsubscribe_mailing_list,
    update_announcement,
)
from app.services.rbac import require_permission

router = APIRouter(tags=["announcements"])


async def _staff_can_manage(db: AsyncSession, club_id: uuid.UUID, auth: AuthContext | None) -> bool:
    if auth is None:
        return False
    try:
        await require_permission(db, club_id=club_id, user_id=auth.user.id, permission="manage_announcements")
        return True
    except ForbiddenError:
        return False


@router.get("/clubs/{club_id}/announcements", response_model=AnnouncementPageOut)
async def list_club_announcements(
    club: Club = Depends(get_club),
    q: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext | None = Depends(get_optional_auth),
) -> AnnouncementPageOut:
    include_drafts = await _staff_can_manage(db, club.id, auth)
    rows, total = await list_announcements(
        db,
        club_id=club.id,
        user_id=auth.user.id if auth else None,
        q=q,
        include_drafts=include_drafts,
        limit=limit,
        offset=offset,
    )
    return AnnouncementPageOut(
        items=[AnnouncementOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/clubs/{club_id}/announcements/{announcement_id}", response_model=AnnouncementOut)
async def get_one(
    announcement_id: uuid.UUID,
    club: Club = Depends(get_club),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext | None = Depends(get_optional_auth),
    preview: bool = False,
) -> AnnouncementOut:
    staff_preview = preview and await _staff_can_manage(db, club.id, auth)
    row = await get_announcement(
        db,
        club_id=club.id,
        announcement_id=announcement_id,
        user_id=auth.user.id if auth else None,
        staff_preview=staff_preview,
    )
    return AnnouncementOut.model_validate(row)


@router.post("/clubs/{club_id}/announcements", response_model=AnnouncementOut)
async def create_one(
    payload: AnnouncementIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> AnnouncementOut:
    row = await create_announcement(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        title=payload.title,
        body=payload.body,
        visibility=payload.visibility,
    )
    await db.commit()
    await db.refresh(row)
    return AnnouncementOut.model_validate(row)


@router.patch("/clubs/{club_id}/announcements/{announcement_id}", response_model=AnnouncementOut)
async def patch_one(
    announcement_id: uuid.UUID,
    payload: AnnouncementPatch,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> AnnouncementOut:
    fields = payload.model_dump(exclude_unset=True)
    row = await update_announcement(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        announcement_id=announcement_id,
        **fields,
    )
    await db.commit()
    await db.refresh(row)
    return AnnouncementOut.model_validate(row)


@router.post("/clubs/{club_id}/announcements/{announcement_id}/publish", response_model=AnnouncementOut)
async def publish_one(
    announcement_id: uuid.UUID,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> AnnouncementOut:
    row = await publish_announcement(
        db, club_id=club.id, actor_user_id=auth.user.id, announcement_id=announcement_id
    )
    await db.commit()
    await db.refresh(row)
    return AnnouncementOut.model_validate(row)


@router.post(
    "/clubs/{club_id}/announcements/{announcement_id}/send-correction",
    response_model=AnnouncementOut,
)
async def send_correction(
    announcement_id: uuid.UUID,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> AnnouncementOut:
    row = await send_correction_notification(
        db, club_id=club.id, actor_user_id=auth.user.id, announcement_id=announcement_id
    )
    await db.commit()
    await db.refresh(row)
    return AnnouncementOut.model_validate(row)


@router.get(
    "/clubs/{club_id}/announcements/{announcement_id}/deliveries",
    response_model=list[DeliveryOut],
)
async def deliveries(
    announcement_id: uuid.UUID,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> list[DeliveryOut]:
    await require_permission(db, club_id=club.id, user_id=auth.user.id, permission="manage_announcements")
    rows = (
        await db.scalars(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.club_id == club.id,
                NotificationDelivery.announcement_id == announcement_id,
            )
            .order_by(NotificationDelivery.created_at.desc())
        )
    ).all()
    return [DeliveryOut.model_validate(r) for r in rows]


@router.get("/clubs/{club_id}/mailing-list", response_model=SubscriberPageOut)
async def list_subscribers(
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
    status: str | None = None,
    q: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> SubscriberPageOut:
    rows, total = await list_mailing_subscriptions(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        status=status,
        q=q,
        limit=limit,
        offset=offset,
    )
    return SubscriberPageOut(
        items=[SubscriberOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/clubs/{club_id}/mailing-list/{subscription_id}/unsubscribe", response_model=MessageOut)
async def staff_unsubscribe_endpoint(
    subscription_id: uuid.UUID,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    await staff_unsubscribe(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        subscription_id=subscription_id,
    )
    await db.commit()
    return MessageOut(message="Subscriber marked unsubscribed.")


@router.post("/clubs/{club_id}/mailing-list/subscribe", response_model=MessageOut)
async def subscribe(
    payload: SubscribeIn,
    club: Club = Depends(get_club),
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    await subscribe_mailing_list(db, club_id=club.id, email=payload.email, consent=payload.consent)
    await db.commit()
    return MessageOut(message=OPAQUE_SUBSCRIBE_MSG)


@router.post("/mailing-list/confirm", response_model=MessageOut)
async def confirm_subscription(payload: TokenIn, db: AsyncSession = Depends(get_db)) -> MessageOut:
    ok = await confirm_mailing_list(db, token=payload.token)
    await db.commit()
    # Opaque-ish: same family of message whether or not token matched.
    if ok:
        return MessageOut(message="Subscription confirmed.")
    return MessageOut(message="If the confirmation link was valid, the subscription is now active.")


@router.post("/mailing-list/unsubscribe", response_model=MessageOut)
async def unsubscribe(payload: TokenIn, db: AsyncSession = Depends(get_db)) -> MessageOut:
    await unsubscribe_mailing_list(db, token=payload.token)
    await db.commit()
    return MessageOut(message="If the subscription existed, it has been cancelled.")
