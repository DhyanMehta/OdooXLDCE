from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MessageOut(BaseModel):
    message: str


class AppErrorOut(BaseModel):
    """Shape returned by AppError / IntegrityError / rate-limit handlers."""

    code: str
    message: str


class ValidationErrorOut(BaseModel):
    """Shape returned by the RequestValidationError handler."""

    code: str
    message: str
    fields: dict[str, str] = Field(default_factory=dict)


# Back-compat alias used by OpenAPI docs; matches AppError JSON.
ErrorOut = AppErrorOut


class HealthOut(BaseModel):
    status: str
    service: str


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
