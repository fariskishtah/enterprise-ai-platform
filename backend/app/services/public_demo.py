"""Idempotent preparation of isolated synthetic public-demo workspaces."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.manufacturing import Company, Factory, Machine
from app.models.sensor import Sensor
from app.models.sensor_data import (
    ReadingQuality,
    ReadingSource,
    SensorReading,
)
from app.models.user import User
from app.repositories.sensors import normalize_sensor_name
from app.utils.security import as_utc


class PublicDemoWorkspaceError(ValueError):
    """Raised when a non-demo tenant attempts public workspace preparation."""


@dataclass(frozen=True, slots=True)
class PublicDemoWorkspaceResult:
    status: str
    factory_count: int
    machine_count: int
    sensor_count: int
    reading_count: int


@dataclass(frozen=True, slots=True)
class _SensorDefinition:
    name: str
    sensor_type: str
    unit: str
    minimum: float
    maximum: float
    baseline: float
    step: float


_FACTORY_NAME = "Cairo Smart Plant"
_MACHINES = ("CNC-01", "PRESS-02", "PUMP-03")
_SENSORS = (
    _SensorDefinition("temperature_c", "temperature", "°C", 0, 120, 58, 1.4),
    _SensorDefinition("vibration_mm_s", "vibration", "mm/s", 0, 15, 2.2, 0.18),
    _SensorDefinition("pressure_bar", "pressure", "bar", 0, 20, 6.4, 0.22),
    _SensorDefinition("power_kw", "power", "kW", 0, 200, 42, 2.5),
    _SensorDefinition("rpm", "rotational_speed", "rpm", 0, 6000, 3150, 110),
    _SensorDefinition(
        "production_rate_units_h",
        "production_rate",
        "units/h",
        0,
        500,
        118,
        4.5,
    ),
    _SensorDefinition(
        "quality_score_pct",
        "quality_score",
        "%",
        0,
        100,
        97.2,
        -0.25,
    ),
)
_READINGS_PER_SENSOR = 6


class PublicDemoWorkspaceService:
    """Create only bounded synthetic records inside a marked demo tenant."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def prepare(self, user: User) -> PublicDemoWorkspaceResult:
        company = await self._session.scalar(
            select(Company).where(Company.id == user.company_id).with_for_update()
        )
        if company is None or not company.is_public_demo:
            raise PublicDemoWorkspaceError(
                "Workspace preparation is available only for public demo accounts."
            )

        factory = await self._session.scalar(
            select(Factory)
            .where(
                Factory.company_id == company.id,
                Factory.name == _FACTORY_NAME,
                Factory.deleted_at.is_(None),
            )
            .limit(1)
        )
        if factory is None:
            factory = Factory(
                company_id=company.id,
                name=_FACTORY_NAME,
                location="Cairo, Egypt",
                description="Synthetic manufacturing site for isolated product demos.",
            )
            self._session.add(factory)
            await self._session.flush()

        machines: list[Machine] = []
        for machine_index, machine_name in enumerate(_MACHINES):
            machine = await self._session.scalar(
                select(Machine)
                .where(
                    Machine.factory_id == factory.id,
                    Machine.name == machine_name,
                    Machine.deleted_at.is_(None),
                )
                .limit(1)
            )
            if machine is None:
                machine = Machine(
                    factory_id=factory.id,
                    name=machine_name,
                    serial_number=f"DEMO-{machine_index + 1:03d}",
                    manufacturer="Synthetic Factory Systems",
                    model="FactoryMind Demonstrator",
                )
                self._session.add(machine)
                await self._session.flush()
            machines.append(machine)

        sensors: list[tuple[int, Sensor, _SensorDefinition]] = []
        for machine_index, machine in enumerate(machines):
            for definition in _SENSORS:
                normalized_name = normalize_sensor_name(definition.name)
                sensor = await self._session.scalar(
                    select(Sensor)
                    .where(
                        Sensor.machine_id == machine.id,
                        Sensor.normalized_name == normalized_name,
                        Sensor.deleted_at.is_(None),
                    )
                    .limit(1)
                )
                if sensor is None:
                    sensor = Sensor(
                        machine_id=machine.id,
                        name=definition.name,
                        normalized_name=normalized_name,
                        sensor_type=definition.sensor_type,
                        unit=definition.unit,
                        sampling_rate=1.0,
                        min_value=definition.minimum,
                        max_value=definition.maximum,
                        description=(
                            "Synthetic bounded reading stream for product demos."
                        ),
                    )
                    self._session.add(sensor)
                    await self._session.flush()
                sensors.append((machine_index, sensor, definition))

        anchor = as_utc(company.created_at).replace(second=0, microsecond=0)
        for machine_index, sensor, definition in sensors:
            timestamps = tuple(
                anchor + timedelta(minutes=5 * index)
                for index in range(_READINGS_PER_SENSOR)
            )
            existing = set(
                (
                    await self._session.scalars(
                        select(SensorReading.timestamp).where(
                            SensorReading.sensor_id == sensor.id,
                            SensorReading.source == ReadingSource.SIMULATION,
                            SensorReading.timestamp.in_(timestamps),
                        )
                    )
                ).all()
            )
            for index, timestamp in enumerate(timestamps):
                if timestamp in existing or timestamp.replace(tzinfo=None) in existing:
                    continue
                value = definition.baseline + machine_index * definition.step * 0.75
                value += definition.step * (index - 2)
                value = min(definition.maximum, max(definition.minimum, value))
                self._session.add(
                    SensorReading(
                        sensor_id=sensor.id,
                        timestamp=timestamp,
                        value=round(value, 3),
                        quality=ReadingQuality.GOOD,
                        source=ReadingSource.SIMULATION,
                        batch_id=None,
                    )
                )

        await self._session.commit()
        persisted_readings = int(
            await self._session.scalar(
                select(func.count(SensorReading.id)).where(
                    SensorReading.sensor_id.in_(
                        [sensor.id for _, sensor, _ in sensors]
                    ),
                    SensorReading.source == ReadingSource.SIMULATION,
                )
            )
            or 0
        )
        return PublicDemoWorkspaceResult(
            status="ready",
            factory_count=1,
            machine_count=len(machines),
            sensor_count=len(sensors),
            reading_count=persisted_readings,
        )
