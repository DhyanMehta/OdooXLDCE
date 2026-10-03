from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMModel


class AnnouncementIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    visibility: str = "public"


class AnnouncementPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1)
    visibility: str | None = None


class AnnouncementOut(ORMModel):
    id: UUID
    club_id: UUID
    title: str
    body: str
    visibility: str
    status: str
    published_at: datetime | None
    created_at: datetime
    correction_seq: int = 0


class AnnouncementPageOut(BaseModel):
    items: list[AnnouncementOut]
    total: int
    limit: int
    offset: int


class DeliveryOut(ORMModel):
    id: UUID
    recipient_email: str
    status: str
    kind: str
    attempts: int
    last_error: str | None = None
    processed_at: datetime | None = None


class SubscribeIn(BaseModel):
    email: EmailStr
    consent: bool = False


class TokenIn(BaseModel):
    token: str = Field(min_length=8)


class SubscriberOut(ORMModel):
    id: UUID
    email: str
    status: str
    consent_at: datetime
    created_at: datetime
    unsubscribed_at: datetime | None = None


class SubscriberPageOut(BaseModel):
    items: list[SubscriberOut]
    total: int
    limit: int
    offset: int
