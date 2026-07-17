"""Health-check response schema."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Response body for the health endpoint."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"]
