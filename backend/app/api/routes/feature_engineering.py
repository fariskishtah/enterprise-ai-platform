"""Feature engineering routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies.auth import require_roles
from app.dependencies.services import get_feature_engineering_service
from app.models.user import User, UserRole
from app.schemas.feature_engineering import (
    FeatureDatasetExportRequest,
    FeatureDatasetExportResponse,
)
from app.services.exceptions import InvalidFeatureDatasetError
from app.services.feature_engineering import FeatureEngineeringService

router = APIRouter(prefix="/feature-datasets", tags=["feature-datasets"])


def _invalid_dataset(exc: InvalidFeatureDatasetError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    )


@router.post(
    "",
    response_model=FeatureDatasetExportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Export a feature dataset",
)
async def export_feature_dataset(
    payload: FeatureDatasetExportRequest,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[
        FeatureEngineeringService,
        Depends(get_feature_engineering_service),
    ],
) -> FeatureDatasetExportResponse:
    """Generate a versioned Parquet feature dataset."""
    try:
        result = await service.export_feature_dataset(
            sensor_id=payload.sensor_id,
            timestamp_from=payload.timestamp_from,
            timestamp_to=payload.timestamp_to,
        )
    except InvalidFeatureDatasetError as exc:
        raise _invalid_dataset(exc) from exc
    return FeatureDatasetExportResponse(
        dataset_name=result.dataset_name,
        version=result.version,
        file_path=str(result.file_path),
        rows=result.rows,
        columns=result.columns,
        created_at=result.created_at,
    )
