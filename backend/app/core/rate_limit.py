"""Simple in-process sliding-window rate limiter for abusive public endpoints.

Not a distributed limiter — sufficient for a single-process demo API.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# path prefix → (max_requests, window_seconds)
LIMITS: dict[str, tuple[int, float]] = {
    "/api/v1/auth/login": (20, 60.0),
    "/api/v1/auth/register": (10, 60.0),
    "/api/v1/clubs/": (30, 60.0),  # narrowed further by path suffix check
}


class _Bucket:
    def __init__(self) -> None:
        self.events: deque[float] = deque()
        self.lock = threading.Lock()


_buckets: dict[str, _Bucket] = defaultdict(_Bucket)
_global_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _limit_for(path: str, method: str) -> tuple[int, float] | None:
    if method.upper() not in {"POST", "PATCH"}:
        return None
    if path.endswith("/mailing-list/subscribe") or path in {
        "/api/v1/mailing-list/unsubscribe",
        "/api/v1/mailing-list/confirm",
    }:
        return (15, 60.0)
    if path.endswith("/orders/tickets") or path.endswith("/orders/membership"):
        return (30, 60.0)
    if path in {"/api/v1/auth/login", "/api/v1/auth/register"}:
        return LIMITS[path]
    return None


def allow(key: str, max_requests: int, window: float) -> bool:
    now = time.monotonic()
    with _global_lock:
        bucket = _buckets[key]
    with bucket.lock:
        while bucket.events and now - bucket.events[0] > window:
            bucket.events.popleft()
        if len(bucket.events) >= max_requests:
            return False
        bucket.events.append(now)
        return True


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        limit = _limit_for(request.url.path, request.method)
        if limit:
            max_req, window = limit
            key = f"{_client_ip(request)}:{request.method}:{request.url.path}"
            if not allow(key, max_req, window):
                return JSONResponse(
                    status_code=429,
                    content={
                        "code": "rate_limited",
                        "message": "Too many requests. Please try again shortly.",
                    },
                )
        return await call_next(request)
