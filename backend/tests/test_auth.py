"""Auth register / login / me / logout flows."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def test_register_login_me_logout_and_bad_password(client: AsyncClient, db: AsyncSession):
    email = f"auth-{uuid.uuid4().hex[:8]}@test.edu"
    password = "Password123!"

    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Auth User"},
    )
    assert registered.status_code == 200, registered.text
    body = registered.json()
    assert body["user"]["email"] == email.lower()
    assert body["user"]["full_name"] == "Auth User"
    assert body["csrf_token"]

    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == email.lower()

    logged_out = await client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": body["csrf_token"]},
    )
    assert logged_out.status_code == 200, logged_out.text

    anon_me = await client.get("/api/v1/auth/me")
    assert anon_me.status_code == 401

    login_ok = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login_ok.status_code == 200, login_ok.text
    assert login_ok.json()["user"]["email"] == email.lower()

    me_again = await client.get("/api/v1/auth/me")
    assert me_again.status_code == 200

    bad = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "definitely-wrong"},
    )
    assert bad.status_code == 401
