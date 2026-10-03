from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import AuthContext, get_club, get_optional_auth, require_csrf
from app.models import Club, NotificationDelivery
from app.schemas.common import MessageOut
from pydantic import BaseModel, EmailStr, Field

from app.services.announcement_service import (
    create_announcement,
    get_announcement,
    list_announcements,
    list_mailing_subscriptions,
    publish_announcement,
    staff_unsubscribe,
    subscribe_mailing_list,
    unsubscribe_mailing_list,
    update_announcement,
)
from app.services.rbac import require_permission
from app.schemas.common import ORMModel
from datetime import datetime
from uuid import UUID

router = APIRouter(tags=["announcements"])


class AnnouncementIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    visibility: str = "public"


class AnnouncementOut(ORMModel):
    id: UUID
    club_id: UUID
    title: str
    body: str
    visibility: str
    status: str
    published_at: datetime | None
    created_at: datetime


class SubscribeIn(BaseModel):
    email: EmailStr


class UnsubscribeIn(BaseModel):
    token: str


@router.get("/clubs/{club_id}/announcements", response_model=list[AnnouncementOut])
def list_club_announcements(
    club: Club = Depends(get_club),
    q: str | None = None,
    limit: int = Query(default=20, le=100),
    offset: int = 0,
    db: Session = Depends(get_db),
    auth: AuthContext | None = Depends(get_optional_auth),
) -> list:
    include_drafts = False
    if auth:
        try:
            require_permission(
                db, club_id=club.id, user_id=auth.user.id, permission="manage_announcements"
            )
            include_drafts = True
        except Exception:
            include_drafts = False
    return list_announcements(
        db,
        club_id=club.id,
        user_id=auth.user.id if auth else None,
        q=q,
        include_drafts=include_drafts,
        limit=limit,
        offset=offset,
    )


@router.get("/clubs/{club_id}/announcements/{announcement_id}", response_model=AnnouncementOut)
def get_one(
    announcement_id: uuid.UUID,
    club: Club = Depends(get_club),
    db: Session = Depends(get_db),
    auth: AuthContext | None = Depends(get_optional_auth),
):
    return get_announcement(
        db,
        club_id=club.id,
        announcement_id=announcement_id,
        user_id=auth.user.id if auth else None,
    )


@router.post("/clubs/{club_id}/announcements", response_model=AnnouncementOut)
def create_one(
    payload: AnnouncementIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    row = create_announcement(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        title=payload.title,
        body=payload.body,
        visibility=payload.visibility,
    )
    db.commit()
    db.refresh(row)
    return row


@router.patch("/clubs/{club_id}/announcements/{announcement_id}", response_model=AnnouncementOut)
def patch_one(
    announcement_id: uuid.UUID,
    payload: AnnouncementIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    row = update_announcement(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        announcement_id=announcement_id,
        title=payload.title,
        body=payload.body,
        visibility=payload.visibility,
    )
    db.commit()
    db.refresh(row)
    return row


@router.post("/clubs/{club_id}/announcements/{announcement_id}/publish", response_model=AnnouncementOut)
def publish_one(
    announcement_id: uuid.UUID,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    row = publish_announcement(
        db, club_id=club.id, actor_user_id=auth.user.id, announcement_id=announcement_id
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("/clubs/{club_id}/announcements/{announcement_id}/deliveries")
def deliveries(
    announcement_id: uuid.UUID,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> list[dict]:
    require_permission(db, club_id=club.id, user_id=auth.user.id, permission="manage_announcements")
    rows = db.scalars(
        select(NotificationDelivery).where(
            NotificationDelivery.club_id == club.id,
            NotificationDelivery.announcement_id == announcement_id,
        )
    ).all()
    return [
        {
            "id": str(r.id),
            "recipient_email": r.recipient_email,
            "status": r.status,
            "attempts": r.attempts,
            "processed_at": r.processed_at.isoformat() if r.processed_at else None,
        }
        for r in rows
    ]


@router.get("/clubs/{club_id}/mailing-list")
def list_subscribers(
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    status: str | None = None,
) -> list[dict]:
    rows = list_mailing_subscriptions(
        db, club_id=club.id, actor_user_id=auth.user.id, status=status
    )
    return [
        {
            "id": str(r.id),
            "email": r.email,
            "status": r.status,
            "consent_at": r.consent_at.isoformat(),
            "created_at": r.created_at.isoformat(),
            "unsubscribed_at": r.unsubscribed_at.isoformat() if r.unsubscribed_at else None,
        }
        for r in rows
    ]


@router.post("/clubs/{club_id}/mailing-list/{subscription_id}/unsubscribe", response_model=MessageOut)
def staff_unsubscribe_endpoint(
    subscription_id: uuid.UUID,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> MessageOut:
    staff_unsubscribe(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        subscription_id=subscription_id,
    )
    db.commit()
    return MessageOut(message="Subscriber marked unsubscribed.")


@router.post("/clubs/{club_id}/mailing-list/subscribe", response_model=MessageOut)
def subscribe(
    payload: SubscribeIn,
    club: Club = Depends(get_club),
    db: Session = Depends(get_db),
) -> MessageOut:
    _, token = subscribe_mailing_list(db, club_id=club.id, email=payload.email)
    db.commit()
    # Always same message; include token only for newly (re)activated subscriptions in demo.
    if token:
        return MessageOut(message=f"Subscribed. Demo unsubscribe token: {token}")
    return MessageOut(message="If this address can be subscribed, it has been recorded.")


@router.post("/mailing-list/unsubscribe", response_model=MessageOut)
def unsubscribe(payload: UnsubscribeIn, db: Session = Depends(get_db)) -> MessageOut:
    unsubscribe_mailing_list(db, token=payload.token)
    db.commit()
    return MessageOut(message="If the subscription existed, it has been cancelled.")
