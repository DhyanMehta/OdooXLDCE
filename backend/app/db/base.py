"""SQLAlchemy declarative base for future ORM models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared metadata root used by models and Alembic."""
