"""Manufacturing domain ORM models."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.sensor import Sensor
    from app.models.user import User


class Company(Base):
    """Manufacturing company."""

    __tablename__ = "companies"
    __table_args__ = (
        Index("ix_companies_normalized_name", "normalized_name", unique=True),
        Index("ix_companies_name", "name"),
        Index("ix_companies_deleted_at", "deleted_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    name: Mapped[str] = mapped_column(String(length=255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(length=255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    factories: Mapped[list[Factory]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    users: Mapped[list[User]] = relationship(back_populates="company")


class Factory(Base):
    """Factory belonging to a company."""

    __tablename__ = "factories"
    __table_args__ = (
        Index("ix_factories_company_id", "company_id"),
        Index("ix_factories_name", "name"),
        Index("ix_factories_deleted_at", "deleted_at"),
        Index("ix_factories_company_deleted", "company_id", "deleted_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(length=255), nullable=False)
    location: Mapped[str | None] = mapped_column(String(length=255))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    company: Mapped[Company] = relationship(back_populates="factories")
    machines: Mapped[list[Machine]] = relationship(
        back_populates="factory",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Machine(Base):
    """Machine belonging to a factory."""

    __tablename__ = "machines"
    __table_args__ = (
        Index("ix_machines_factory_id", "factory_id"),
        Index("ix_machines_name", "name"),
        Index("ix_machines_serial_number", "serial_number"),
        Index("ix_machines_deleted_at", "deleted_at"),
        Index("ix_machines_factory_deleted", "factory_id", "deleted_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    factory_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("factories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(length=255), nullable=False)
    serial_number: Mapped[str | None] = mapped_column(String(length=255))
    manufacturer: Mapped[str | None] = mapped_column(String(length=255))
    model: Mapped[str | None] = mapped_column(String(length=255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    factory: Mapped[Factory] = relationship(back_populates="machines")
    sensors: Mapped[list[Sensor]] = relationship(
        "Sensor",
        back_populates="machine",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
