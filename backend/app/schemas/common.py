from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MessageOut(BaseModel):
    message: str


class ErrorOut(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class UserOut(ORMModel):
    id: UUID
    email: EmailStr
    full_name: str


class ClubOut(ORMModel):
    id: UUID
    slug: str
    name: str
    description: str


class ClubContextOut(BaseModel):
    club: ClubOut
    permissions: list[str]
    is_member: bool
    has_active_membership: bool
