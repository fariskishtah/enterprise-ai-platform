"""Domain model package."""

from app.models.ai_governance import ModelPromotionAudit, TrainingJob
from app.models.ai_monitoring import ModelReferenceProfileEntity, PredictionEventEntity
from app.models.ai_retraining import (
    ModelRetrainingAudit,
    ModelRetrainingPolicy,
    ModelRetrainingRequest,
)
from app.models.automl import AutoMLExecutionSlot, AutoMLStudy, AutoMLTrial
from app.models.datasets import (
    Dataset,
    DatasetUsageReference,
    DatasetVersion,
    DocumentChunk,
    DocumentRecord,
)
from app.models.manufacturing import Company, Factory, Machine
from app.models.mlops import (
    Experiment,
    ModelArtifact,
    TrainingRun,
    TrainingRunStatus,
)
from app.models.monitoring_orchestration import (
    ModelMonitoringEvaluationEntity,
    MonitoringAlertEntity,
    MonitoringJobLockEntity,
    PredictionOutcomeEntity,
)
from app.models.rag import (
    RAGChunkEmbedding,
    RAGConversation,
    RAGIndexBuild,
    RAGIndexedChunk,
    RAGKnowledgeBase,
    RAGKnowledgeBaseDatasetVersion,
    RAGMessage,
    RAGMessageCitation,
)
from app.models.sensor import Sensor
from app.models.sensor_data import (
    ReadingQuality,
    ReadingSource,
    SensorReading,
    UploadJob,
    UploadJobStatus,
)
from app.models.user import RefreshToken, User, UserRole

__all__ = [
    "AutoMLExecutionSlot",
    "AutoMLStudy",
    "AutoMLTrial",
    "Company",
    "Dataset",
    "DatasetUsageReference",
    "DatasetVersion",
    "DocumentChunk",
    "DocumentRecord",
    "Experiment",
    "Factory",
    "Machine",
    "ModelPromotionAudit",
    "ModelReferenceProfileEntity",
    "ModelMonitoringEvaluationEntity",
    "ModelRetrainingAudit",
    "ModelRetrainingPolicy",
    "ModelRetrainingRequest",
    "ModelArtifact",
    "MonitoringAlertEntity",
    "MonitoringJobLockEntity",
    "ReadingQuality",
    "ReadingSource",
    "RAGChunkEmbedding",
    "RAGConversation",
    "RAGIndexBuild",
    "RAGIndexedChunk",
    "RAGKnowledgeBase",
    "RAGKnowledgeBaseDatasetVersion",
    "RAGMessage",
    "RAGMessageCitation",
    "RefreshToken",
    "PredictionEventEntity",
    "PredictionOutcomeEntity",
    "Sensor",
    "SensorReading",
    "TrainingRun",
    "TrainingRunStatus",
    "TrainingJob",
    "UploadJob",
    "UploadJobStatus",
    "User",
    "UserRole",
]
