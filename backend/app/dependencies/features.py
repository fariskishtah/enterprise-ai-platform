"""Server-side feature control dependencies."""

from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, status

from app.config.settings import Settings, get_settings

FeatureName = Literal[
    "simplified_experience_enabled",
    "operations_workflow_enabled",
    "demo_tools_enabled",
]


def require_feature(feature: FeatureName) -> Callable[..., None]:
    """Return a dependency that fails closed when a feature is disabled."""

    def verify(settings: Annotated[Settings, Depends(get_settings)]) -> None:
        if not getattr(settings, feature):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="This product capability is not enabled.",
            )

    return verify
