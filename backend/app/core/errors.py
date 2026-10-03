"""Typed application errors mapped to HTTP responses."""

from __future__ import annotations


class AppError(Exception):
    def __init__(self, message: str, *, code: str = "app_error", status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class NotFoundError(AppError):
    def __init__(self, message: str = "Not found") -> None:
        super().__init__(message, code="not_found", status_code=404)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Forbidden") -> None:
        super().__init__(message, code="forbidden", status_code=403)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Authentication required") -> None:
        super().__init__(message, code="unauthorized", status_code=401)


class ConflictError(AppError):
    def __init__(self, message: str, *, code: str = "conflict") -> None:
        super().__init__(message, code=code, status_code=409)
