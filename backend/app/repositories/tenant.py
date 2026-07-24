"""Small repository helpers for deriving non-null tenant scope on worker writes."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_governance import TrainingJob
from app.models.ai_monitoring import PredictionEventEntity
from app.models.manufacturing import Company
from app.models.monitoring_orchestration import ModelMonitoringEvaluationEntity
from app.models.user import User


async def company_for_user(session: AsyncSession, user_id: UUID) -> UUID:
    company_id = await session.scalar(select(User.company_id).where(User.id == user_id))
    if company_id is None:
        raise ValueError("A tenant-scoped user is required.")
    return company_id


async def company_for_training_job(
    session: AsyncSession, training_job_id: UUID
) -> UUID:
    company_id = await session.scalar(
        select(TrainingJob.company_id).where(TrainingJob.id == training_job_id)
    )
    if company_id is None:
        raise ValueError("A tenant-scoped training job is required.")
    return company_id


async def company_for_registered_model(
    session: AsyncSession, registered_model_name: str
) -> UUID:
    company_id = await session.scalar(
        select(TrainingJob.company_id)
        .where(TrainingJob.registered_model_name == registered_model_name)
        .order_by(TrainingJob.created_at.desc())
        .limit(1)
    )
    if company_id is None:
        companies = list((await session.scalars(select(Company.id).limit(2))).all())
        if len(companies) == 1:
            # Supports a migrated single-customer registry whose old MLflow
            # entries predate persisted training lineage. Multiple tenants must
            # never use this compatibility path because the owner is ambiguous.
            return companies[0]
        raise ValueError("A tenant-scoped registered model is required.")
    return company_id


async def company_for_prediction_event(
    session: AsyncSession, prediction_event_id: UUID
) -> UUID:
    company_id = await session.scalar(
        select(PredictionEventEntity.company_id).where(
            PredictionEventEntity.id == prediction_event_id
        )
    )
    if company_id is None:
        raise ValueError("A tenant-scoped prediction event is required.")
    return company_id


async def company_for_monitoring_evaluation(
    session: AsyncSession, evaluation_id: UUID
) -> UUID:
    company_id = await session.scalar(
        select(ModelMonitoringEvaluationEntity.company_id).where(
            ModelMonitoringEvaluationEntity.id == evaluation_id
        )
    )
    if company_id is None:
        raise ValueError("A tenant-scoped monitoring evaluation is required.")
    return company_id
