"""Safe authenticated product-experience configuration."""

from pydantic import BaseModel, ConfigDict


class ProductFeatureFlagsResponse(BaseModel):
    """Non-secret controls used to shape authenticated presentation."""

    model_config = ConfigDict(frozen=True)

    simplified_experience_enabled: bool
    operations_workflow_enabled: bool
    demo_tools_enabled: bool
