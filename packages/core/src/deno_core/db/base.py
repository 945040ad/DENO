"""Declarative base, id generation and shared column mixins."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

import uuid_utils
from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names so Alembic autogenerate and downgrades are stable.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def new_id() -> uuid.UUID:
    """UUIDv7: time-ordered, so B-tree inserts stay append-mostly."""
    return uuid.UUID(bytes=uuid_utils.uuid7().bytes)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        uuid.UUID: UUID(as_uuid=True),
        datetime: DateTime(timezone=True),
    }
    # Fetch server-generated values (created_at/updated_at defaults) via RETURNING in the
    # same INSERT/UPDATE, so async code never triggers an implicit lazy load afterwards.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 — SQLAlchemy reads this as a plain class attribute


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class TenantMixin:
    """Every row a user owns carries their Supabase auth id, indexed."""

    user_id: Mapped[uuid.UUID] = mapped_column(index=True)


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(default=None)
