from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ClubContextOut, UserOut


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class MeOut(BaseModel):
    user: UserOut
    csrf_token: str
    clubs: list[ClubContextOut]
