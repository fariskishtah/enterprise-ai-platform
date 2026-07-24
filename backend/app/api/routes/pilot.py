"""Governed structured prediction and controlled operator pilot routes."""

from __future__ import annotations

import hashlib
import math
from datetime import timedelta
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.ai import predict_registered_model
from app.dependencies.auth import require_roles
from app.dependencies.database import get_db_session
from app.dependencies.rate_limit import enforce_mutation_rate_limit
from app.dependencies.services import (
    get_ai_monitored_prediction_service,
    get_audit_service,
)
from app.ml.composition import PLUGIN_REGISTRY
from app.ml.domain import TaskType
from app.ml.jobs.models import TrainingJobStatus
from app.ml.monitoring import MonitoredPredictionService
from app.ml.monitoring.evaluation_models import (
    MonitoringAlertSeverity,
    MonitoringAlertStatus,
    MonitoringAlertType,
)
from app.ml.plugins import ModelPluginError
from app.models.ai_governance import TrainingJob
from app.models.datasets import Dataset, DatasetVersion
from app.models.manufacturing import Factory, Machine
from app.models.monitoring_orchestration import MonitoringAlertEntity
from app.models.pilot import MachineRiskAssessment, ModelFeatureSchema
from app.models.user import User, UserRole
from app.schemas.ai import GenericRegisteredModelPredictionRequest
from app.schemas.pilot import (
    FeatureDefinition,
    FeatureSchemaResponse,
    FeatureSchemaUpsertRequest,
    MachineRiskAcknowledgeRequest,
    MachineRiskResponse,
    StructuredPredictionRequest,
    StructuredPredictionResponse,
)
from app.services.audit import AuditService
from app.utils.security import utc_now

router = APIRouter(tags=["pilot"])
_MODEL = Path(min_length=3, max_length=128, pattern=r"^[a-z][a-z0-9_]{2,127}$")
_VERSION = Path(min_length=1, max_length=128, pattern=r"^[1-9][0-9]*$")


def _schema_response(entity: ModelFeatureSchema) -> FeatureSchemaResponse:
    metadata = entity.target_metadata
    return FeatureSchemaResponse(
        id=entity.id,
        company_id=entity.company_id,
        registered_model_name=entity.registered_model_name,
        model_version=entity.model_version,
        features=[FeatureDefinition.model_validate(item) for item in entity.features],
        algorithm=str(metadata["algorithm"]),
        task_type=TaskType(str(metadata["task_type"])),
        target_name=(
            str(metadata["target_name"]) if metadata.get("target_name") else None
        ),
        target_unit=(
            str(metadata["target_unit"]) if metadata.get("target_unit") else None
        ),
        training_dataset_version_id=entity.training_dataset_version_id,
        created_by_user_id=entity.created_by_user_id,
        created_at=entity.created_at,
    )


async def _get_schema(
    session: AsyncSession,
    company_id: UUID,
    registered_model_name: str,
    model_version: str,
) -> ModelFeatureSchema:
    entity = (
        await session.execute(
            select(ModelFeatureSchema).where(
                ModelFeatureSchema.company_id == company_id,
                ModelFeatureSchema.registered_model_name == registered_model_name,
                ModelFeatureSchema.model_version == model_version,
            )
        )
    ).scalar_one_or_none()
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Feature schema not found.")
    return entity


async def _require_owned_model_version(
    session: AsyncSession,
    company_id: UUID,
    registered_model_name: str,
    model_version: str,
) -> TrainingJob:
    job = (
        await session.execute(
            select(TrainingJob).where(
                TrainingJob.company_id == company_id,
                TrainingJob.registered_model_name == registered_model_name,
                TrainingJob.registered_model_version == model_version,
                TrainingJob.status == TrainingJobStatus.SUCCEEDED,
            )
        )
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Registered model version not found.",
        )
    return job


@router.put(
    "/ai/models/{registered_model_name}/versions/{model_version}/feature-schema",
    response_model=FeatureSchemaResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def upsert_feature_schema(
    registered_model_name: Annotated[str, _MODEL],
    model_version: Annotated[str, _VERSION],
    payload: FeatureSchemaUpsertRequest,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> FeatureSchemaResponse:
    model_job = await _require_owned_model_version(
        session,
        current_user.company_id,
        registered_model_name,
        model_version,
    )
    try:
        plugin = PLUGIN_REGISTRY.get(payload.algorithm, payload.task_type)
    except ModelPluginError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The feature schema algorithm is not available.",
        ) from exc
    if plugin.key.algorithm is not model_job.algorithm or (
        plugin.key.task_type is not model_job.task_type
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The feature schema does not match the registered model version.",
        )
    if payload.training_dataset_version_id is not None:
        dataset_version = (
            await session.execute(
                select(DatasetVersion)
                .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
                .where(
                    DatasetVersion.id == payload.training_dataset_version_id,
                    Dataset.company_id == current_user.company_id,
                )
            )
        ).scalar_one_or_none()
        if dataset_version is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "Training dataset version not found.",
            )
    entity = (
        await session.execute(
            select(ModelFeatureSchema).where(
                ModelFeatureSchema.company_id == current_user.company_id,
                ModelFeatureSchema.registered_model_name == registered_model_name,
                ModelFeatureSchema.model_version == model_version,
            )
        )
    ).scalar_one_or_none()
    values = {
        "features": [item.model_dump(mode="json") for item in payload.features],
        "target_metadata": {
            "algorithm": payload.algorithm,
            "task_type": payload.task_type.value,
            "target_name": payload.target_name,
            "target_unit": payload.target_unit,
        },
        "training_dataset_version_id": payload.training_dataset_version_id,
    }
    if entity is None:
        entity = ModelFeatureSchema(
            company_id=current_user.company_id,
            registered_model_name=registered_model_name,
            model_version=model_version,
            created_by_user_id=current_user.id,
            **values,
        )
        session.add(entity)
    else:
        entity.features = cast(list[dict[str, object]], values["features"])
        entity.target_metadata = cast(
            dict[str, object],
            values["target_metadata"],
        )
        entity.training_dataset_version_id = payload.training_dataset_version_id
    await session.commit()
    await session.refresh(entity)
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="model.feature_schema_saved",
        resource_type="model_version",
        resource_id=f"{registered_model_name}:{model_version}",
        result="success",
        metadata={"feature_count": len(payload.features)},
    )
    return _schema_response(entity)


@router.get(
    "/ai/models/{registered_model_name}/versions/{model_version}/feature-schema",
    response_model=FeatureSchemaResponse,
)
async def get_feature_schema(
    registered_model_name: Annotated[str, _MODEL],
    model_version: Annotated[str, _VERSION],
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FeatureSchemaResponse:
    return _schema_response(
        await _get_schema(
            session, current_user.company_id, registered_model_name, model_version
        )
    )


def _feature_matrix(
    definitions: list[FeatureDefinition], values: dict[str, int | float | None]
) -> tuple[list[list[float]], list[str], list[dict[str, object]]]:
    expected = {item.name for item in definitions}
    unknown = sorted(set(values) - expected)
    missing = sorted(
        item.name
        for item in definitions
        if item.required and values.get(item.name) is None
    )
    if unknown or missing:
        detail = "Feature names do not match the selected model schema."
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"message": detail, "missing": missing, "unknown": unknown},
        )
    row: list[float] = []
    snapshot: list[dict[str, object]] = []
    for item in definitions:
        value = values.get(item.name)
        if value is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Feature '{item.name}' does not support missing values.",
            )
        number = float(value)
        if not math.isfinite(number):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Feature '{item.name}' must be finite.",
            )
        if item.data_type == "integer" and number != int(number):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Feature '{item.name}' must be an integer.",
            )
        if item.minimum is not None and number < item.minimum:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Feature '{item.name}' is below its allowed minimum.",
            )
        if item.maximum is not None and number > item.maximum:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Feature '{item.name}' exceeds its allowed maximum.",
            )
        row.append(number)
        snapshot.append({"name": item.name, "value": number, "unit": item.unit})
    return [row], [item.name for item in definitions], snapshot


@router.post(
    "/ai/models/{registered_model_name}/versions/{model_version}/structured-prediction",
    response_model=StructuredPredictionResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def run_structured_prediction(
    registered_model_name: Annotated[str, _MODEL],
    model_version: Annotated[str, _VERSION],
    payload: StructuredPredictionRequest,
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    prediction_service: Annotated[
        MonitoredPredictionService, Depends(get_ai_monitored_prediction_service)
    ],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    correlation_id: Annotated[
        str | None, Header(alias="X-Correlation-ID", max_length=128)
    ] = None,
) -> StructuredPredictionResponse:
    schema = await _get_schema(
        session, current_user.company_id, registered_model_name, model_version
    )
    definitions = [FeatureDefinition.model_validate(item) for item in schema.features]
    matrix, feature_order, snapshot = _feature_matrix(definitions, payload.values)
    metadata = schema.target_metadata
    result = await predict_registered_model(
        payload=GenericRegisteredModelPredictionRequest(
            registered_model_name=registered_model_name,
            version_or_alias=model_version,
            features=matrix,
            algorithm=str(metadata["algorithm"]),
            task_type=str(metadata["task_type"]),
        ),
        current_user=current_user,
        service=prediction_service,
        correlation_id=correlation_id,
    )
    prediction = result.predictions[0]
    assessment: MachineRiskAssessment | None = None
    if payload.machine_id is not None:
        machine = (
            await session.execute(
                select(Machine)
                .join(Factory, Factory.id == Machine.factory_id)
                .where(
                    Machine.id == payload.machine_id,
                    Factory.company_id == current_user.company_id,
                    Machine.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if machine is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Machine not found.")
        score = max(0.0, min(1.0, float(prediction)))
        risk_state = (
            "critical"
            if score >= 0.85
            else "warning" if score >= 0.65 else "observe" if score >= 0.4 else "normal"
        )
        recommendation = {
            "normal": "Continue standard operation and scheduled inspection.",
            "observe": "Review sensor trend during the next operator round.",
            "warning": (
                "Notify an engineer and inspect the machine before the next shift."
            ),
            "critical": (
                "Follow site safety procedure and request immediate engineering review."
            ),
        }[risk_state]
        assessment = MachineRiskAssessment(
            company_id=current_user.company_id,
            factory_id=machine.factory_id,
            machine_id=machine.id,
            registered_model_name=result.model_name,
            model_version=result.model_version,
            risk_state=risk_state,
            risk_score=score,
            sensor_values=snapshot,
            data_freshness_seconds=0,
            recommended_action=recommendation,
            monitoring_status="available",
            assessed_at=utc_now(),
        )
        if risk_state in {"warning", "critical"}:
            now = utc_now()
            deduplication_key = hashlib.sha256(
                (
                    f"{current_user.company_id}:{machine.id}:"
                    f"{result.model_name}:{result.model_version}:machine-risk"
                ).encode()
            ).hexdigest()
            alert = (
                await session.execute(
                    select(MonitoringAlertEntity).where(
                        MonitoringAlertEntity.company_id == current_user.company_id,
                        MonitoringAlertEntity.deduplication_key == deduplication_key,
                        MonitoringAlertEntity.status != MonitoringAlertStatus.RESOLVED,
                    )
                )
            ).scalar_one_or_none()
            if alert is None:
                alert = MonitoringAlertEntity(
                    company_id=current_user.company_id,
                    factory_id=machine.factory_id,
                    machine_id=machine.id,
                    alert_type=MonitoringAlertType.MACHINE_RISK,
                    severity=(
                        MonitoringAlertSeverity.CRITICAL
                        if risk_state == "critical"
                        else MonitoringAlertSeverity.WARNING
                    ),
                    registered_model_name=result.model_name,
                    model_version=result.model_version,
                    monitoring_evaluation_id=None,
                    title=f"{risk_state.title()} machine risk indication",
                    safe_summary=(
                        "A governed model risk threshold was reached. "
                        "Review current sensor values and site procedure."
                    ),
                    deduplication_key=deduplication_key,
                    status=MonitoringAlertStatus.OPEN,
                    first_detected_at=now,
                    last_detected_at=now,
                    occurrence_count=1,
                    cooldown_until=now + timedelta(hours=1),
                )
                session.add(alert)
                await session.flush()
            elif alert.cooldown_until is None or alert.cooldown_until <= now:
                alert.last_detected_at = now
                alert.occurrence_count += 1
                alert.cooldown_until = now + timedelta(hours=1)
            assessment.alert_id = alert.id
        session.add(assessment)
        await session.commit()
        await session.refresh(assessment)
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="prediction.structured_executed",
        resource_type="model_version",
        resource_id=f"{registered_model_name}:{model_version}",
        result="success",
        metadata={
            "feature_count": len(feature_order),
            "machine_linked": assessment is not None,
        },
    )
    return StructuredPredictionResponse(
        model_name=result.model_name,
        model_version=result.model_version,
        prediction=prediction,
        feature_order=feature_order,
        assessment_id=assessment.id if assessment else None,
        risk_state=assessment.risk_state if assessment else None,
    )


@router.get("/pilot/machines/{machine_id}/risk", response_model=MachineRiskResponse)
async def get_machine_risk(
    machine_id: UUID,
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MachineRiskResponse:
    entity = (
        await session.execute(
            select(MachineRiskAssessment)
            .where(
                MachineRiskAssessment.company_id == current_user.company_id,
                MachineRiskAssessment.machine_id == machine_id,
            )
            .order_by(MachineRiskAssessment.assessed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Machine risk is unavailable.")
    return MachineRiskResponse.model_validate(entity, from_attributes=True)


@router.post(
    "/pilot/machine-risk/{assessment_id}/acknowledge",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def acknowledge_machine_risk(
    assessment_id: UUID,
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    payload: MachineRiskAcknowledgeRequest | None = None,
) -> Response:
    entity = await session.get(MachineRiskAssessment, assessment_id)
    if entity is None or entity.company_id != current_user.company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Machine risk is unavailable.")
    now = utc_now()
    entity.acknowledged_at = now
    entity.acknowledged_by_user_id = current_user.id
    alert_acknowledged = False
    if entity.alert_id is not None:
        alert = await session.get(MonitoringAlertEntity, entity.alert_id)
        if alert is not None and alert.company_id == current_user.company_id:
            if alert.status == MonitoringAlertStatus.OPEN:
                alert.status = MonitoringAlertStatus.ACKNOWLEDGED
                alert.acknowledged_at = now
                alert.acknowledged_by_user_id = current_user.id
                alert_acknowledged = True
            if payload is not None and payload.operator_note is not None:
                alert.operator_note = payload.operator_note
    await session.commit()
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="machine_risk.acknowledged",
        resource_type="machine_risk",
        resource_id=assessment_id,
        result="success",
        metadata={"linked_alert_acknowledged": alert_acknowledged},
    )
    if alert_acknowledged and entity.alert_id is not None:
        await audit.record(
            company_id=current_user.company_id,
            actor=current_user,
            action="alert.acknowledged",
            resource_type="monitoring_alert",
            resource_id=entity.alert_id,
            result="success",
            metadata={"source": "machine_risk"},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
