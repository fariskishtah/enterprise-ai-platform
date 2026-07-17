"""Sensor ORM model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base
from app.models.manufacturing import Machine

if TYPE_CHECKING:
    from app.models.sensor_data import SensorReading


class Sensor(Base):
    """Sensor attached to a machine."""

    __tablename__ = "sensors"
    __table_args__ = (
        Index(
            "ix_sensors_machine_normalized_name",
            "machine_id",
            "normalized_name",
            unique=True,
        ),
        Index("ix_sensors_machine_id", "machine_id"),
        Index("ix_sensors_name", "name"),
        Index("ix_sensors_sensor_type", "sensor_type"),
        Index("ix_sensors_deleted_at", "deleted_at"),
        Index("ix_sensors_machine_deleted", "machine_id", "deleted_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    machine_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("machines.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(length=255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(length=255), nullable=False)
    sensor_type: Mapped[str | None] = mapped_column(String(length=255))
    unit: Mapped[str | None] = mapped_column(String(length=64))
    sampling_rate: Mapped[float] = mapped_column(Float, nullable=False)
    min_value: Mapped[float] = mapped_column(Float, nullable=False)
    max_value: Mapped[float] = mapped_column(Float, nullable=False)
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

    machine: Mapped[Machine] = relationship("Machine", back_populates="sensors")
    readings: Mapped[list[SensorReading]] = relationship(
        "SensorReading",
        back_populates="sensor",
    )
