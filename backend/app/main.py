"""CampusOS FastAPI application entrypoint."""

from __future__ import annotations

import re
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import IntegrityError

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.db_errors import translate_integrity_error
from app.core.errors import AppError
from app.core.rate_limit import RateLimitMiddleware
from app.db.session import dispose_engine, get_engine
from app.schemas.common import AppErrorOut, ValidationErrorOut
import app.models  # noqa: F401 - register metadata

_NON_ALNUM = re.compile(r"[^a-zA-Z0-9_]+")


def generate_operation_id(route: APIRoute) -> str:
    """Deterministic OpenAPI operationId: ``{tag}_{name}`` (sanitized)."""
    tag = route.tags[0] if route.tags else "api"
    raw = f"{tag}_{route.name}"
    cleaned = _NON_ALNUM.sub("_", raw).strip("_").lower()
    return cleaned or "operation"


def assert_unique_operation_ids(application: FastAPI) -> None:
    """Fail fast if two routes would share an operationId."""
    by_id: dict[str, list[str]] = defaultdict(list)
    for route in application.routes:
        if not isinstance(route, APIRoute):
            continue
        op_id = generate_operation_id(route)
        methods = ",".join(sorted(route.methods or []))
        by_id[op_id].append(f"{methods} {route.path}")
    dupes = {k: v for k, v in by_id.items() if len(v) > 1}
    if dupes:
        detail = "; ".join(f"{oid} -> {paths}" for oid, paths in sorted(dupes.items()))
        raise RuntimeError(f"Duplicate OpenAPI operationIds detected: {detail}")


@asynccontextmanager
async def lifespan(_application: FastAPI):
    # Eager-create engine so misconfiguration fails at startup, not first request.
    get_engine()
    try:
        yield
    finally:
        await dispose_engine()


_APP_ERROR_RESPONSE = {"model": AppErrorOut, "description": "Application error"}
_VALIDATION_RESPONSE = {
    "model": ValidationErrorOut,
    "description": "Request validation failed",
}


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        generate_unique_id_function=generate_operation_id,
        responses={
            400: _APP_ERROR_RESPONSE,
            401: _APP_ERROR_RESPONSE,
            403: _APP_ERROR_RESPONSE,
            404: _APP_ERROR_RESPONSE,
            409: _APP_ERROR_RESPONSE,
            422: _VALIDATION_RESPONSE,
            429: _APP_ERROR_RESPONSE,
        },
    )

    application.add_middleware(RateLimitMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        )

    @application.exception_handler(IntegrityError)
    async def integrity_handler(_: Request, exc: IntegrityError) -> JSONResponse:
        mapped = translate_integrity_error(exc)
        return JSONResponse(
            status_code=mapped.status_code,
            content={"code": mapped.code, "message": mapped.message},
        )

    @application.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields: dict[str, str] = {}
        messages: list[str] = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
            msg = err.get("msg", "Invalid value")
            if loc:
                fields[loc] = msg
            messages.append(f"{loc}: {msg}" if loc else msg)
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "; ".join(messages) if messages else "Validation failed",
                "fields": fields,
            },
        )

    application.include_router(api_router, prefix=settings.api_v1_prefix)
    assert_unique_operation_ids(application)
    return application


app = create_app()
