"""Health-check response schema."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Response body for the health endpoint."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"]


class ReadinessResponse(BaseModel):
    """Response body for the dependency readiness endpoint."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ready"]


class OperationalStatusResponse(BaseModel):
    """Sanitized dependency and asynchronous processing status."""

    model_config = ConfigDict(frozen=True)

    database: Literal["available", "unavailable"]
    redis: Literal["available", "unavailable"]
    queue: Literal["available", "unavailable"]
    training_worker: Literal["available", "unavailable", "unknown"]
    status: Literal["operational", "degraded"]
    timestamp: datetime
