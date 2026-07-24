"""Request-context tenant guard applied to every ORM SELECT for scoped roots."""

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from app.db.tenant_context import current_tenant
from app.models.ai_governance import ModelPromotionAudit, TrainingJob
from app.models.ai_monitoring import ModelReferenceProfileEntity, PredictionEventEntity
from app.models.ai_retraining import (
    ModelRetrainingAudit,
    ModelRetrainingPolicy,
    ModelRetrainingRequest,
)
from app.models.automl import AutoMLStudy
from app.models.datasets import Dataset
from app.models.manufacturing import Company, Factory
from app.models.mlops import Experiment
from app.models.monitoring_orchestration import (
    ModelMonitoringEvaluationEntity,
    MonitoringAlertEntity,
    PredictionOutcomeEntity,
)
from app.models.pilot import MachineRiskAssessment, ModelFeatureSchema
from app.models.rag import RAGConversation, RAGKnowledgeBase
from app.models.sensor_data import UploadJob
from app.models.user import AuditEvent, User

_INSTALLED = False

_SCOPED_MODELS = (
    User,
    Factory,
    Dataset,
    TrainingJob,
    ModelPromotionAudit,
    PredictionEventEntity,
    ModelReferenceProfileEntity,
    AutoMLStudy,
    ModelRetrainingPolicy,
    ModelRetrainingRequest,
    ModelRetrainingAudit,
    ModelMonitoringEvaluationEntity,
    MonitoringAlertEntity,
    PredictionOutcomeEntity,
    RAGKnowledgeBase,
    RAGConversation,
    UploadJob,
    Experiment,
    AuditEvent,
    ModelFeatureSchema,
    MachineRiskAssessment,
)


def install_tenant_guard() -> None:
    """Install the process-wide SELECT guard once."""
    global _INSTALLED
    if _INSTALLED:
        return

    @event.listens_for(Session, "do_orm_execute")
    def _scope_select(execute_state: ORMExecuteState) -> None:
        tenant_id = current_tenant()
        if (
            tenant_id is None
            or not getattr(execute_state, "is_select", False)
            or getattr(execute_state, "execution_options", {}).get(
                "skip_tenant_scope", False
            )
        ):
            return
        statement = execute_state.statement
        statement = statement.options(
            with_loader_criteria(Company, Company.id == tenant_id, include_aliases=True)
        )
        for model in _SCOPED_MODELS:
            statement = statement.options(
                with_loader_criteria(
                    model, model.company_id == tenant_id, include_aliases=True
                )
            )
        execute_state.statement = statement

    _INSTALLED = True


install_tenant_guard()
