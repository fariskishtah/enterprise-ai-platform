"""Focused low-cardinality observability and response-security coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from app.api.routes.health import _dataset_storage_status
from app.observability.metrics import (
    configure_metrics,
    record_chatbot_generation,
    record_dataset_lifecycle,
    record_dataset_processing,
    record_process_timeout,
    record_rag_index_lifecycle,
    record_rag_index_processing,
    record_rag_retrieval,
    record_reconciliation_repair,
)
from app.observability.tracing import (
    _safe_domain_attributes,
    _safe_domain_span_name,
)
from app.observability.worker_logging import worker_job_name
from httpx import AsyncClient
from prometheus_client import generate_latest

_ROOT = Path(__file__).resolve().parents[2]
_DASHBOARD = (
    _ROOT / "infrastructure/observability/grafana/dashboards/data-rag-operations.json"
)
_RULES = _ROOT / "infrastructure/observability/prometheus/rules/data-rag-alerts.yml"


def test_data_rag_metric_helpers_use_only_bounded_labels() -> None:
    configure_metrics(
        enabled=True,
        service="data-rag-observability-test",
        environment="test",
    )
    private_value = "private-resource-43b33dd8"

    record_dataset_lifecycle(
        dataset_kind=private_value,
        event=private_value,
        final_status=private_value,
    )
    record_dataset_processing(
        dataset_kind="document_collection",
        stage="extraction",
        final_status="succeeded",
        duration_seconds=0.2,
    )
    record_rag_index_lifecycle(event="build_terminal", final_status="ready")
    record_rag_index_processing(
        stage="embedding", final_status="succeeded", duration_seconds=0.3
    )
    record_rag_retrieval(
        final_status="succeeded", duration_seconds=0.04, retrieved_chunks=3
    )
    record_chatbot_generation(outcome="grounded", duration_seconds=0.12)
    record_process_timeout(workload="rag_indexing")
    record_reconciliation_repair(
        workload="dataset_processing", outcome="repaired", count=2
    )

    rendered = generate_latest().decode("utf-8")
    assert private_value not in rendered
    assert (
        'dataset_lifecycle_total{dataset_kind="unknown",environment="test",'
        'event="unknown",final_status="unknown",'
        'service="data-rag-observability-test"}'
    ) in rendered
    for metric_name in (
        "dataset_processing_duration_seconds_count",
        "rag_index_lifecycle_total",
        "rag_index_duration_seconds_count",
        "rag_retrieval_requests_total",
        "rag_retrieved_chunks_count",
        "chatbot_generation_total",
        "bounded_process_timeouts_total",
        "reconciliation_repairs_total",
    ):
        assert metric_name in rendered


def test_data_rag_trace_vocabulary_drops_resource_and_content_values() -> None:
    private_value = "private-dataset-or-prompt"

    attributes = _safe_domain_attributes(
        {
            "dataset_kind": "document_collection",
            "processing_stage": private_value,
            "provider_type": "local",
            "dataset_id": private_value,
            "prompt": private_value,
        }
    )

    assert _safe_domain_span_name("dataset.version_creation") == (
        "dataset.version_creation"
    )
    assert _safe_domain_span_name("chatbot.generation") == "chatbot.generation"
    assert _safe_domain_span_name(private_value) == "domain.operation"
    assert attributes == {
        "dataset_kind": "document_collection",
        "processing_stage": "unknown",
        "provider_type": "local",
    }
    assert private_value not in str(attributes)


def test_worker_actor_mapping_is_fixed_for_data_rag_workloads() -> None:
    assert worker_job_name("process_dataset_version") == "dataset_processing"
    assert worker_job_name("extract_document") == "document_extraction"
    assert worker_job_name("chunk_document") == "document_chunking"
    assert worker_job_name("embed_dataset_version") == "dataset_embedding"
    assert worker_job_name("reconcile_dataset_processing") == ("dataset_reconciliation")
    assert worker_job_name("build_rag_index") == "rag_indexing"
    assert worker_job_name("reconcile_rag_indexing") == "rag_index_reconciliation"
    assert worker_job_name("generate_chatbot_message") == "chatbot_generation"
    assert worker_job_name("resource-id-controlled-actor") is None


@pytest.mark.anyio
async def test_sensitive_data_rag_namespaces_are_never_cacheable(
    api_client: AsyncClient,
) -> None:
    for path in (
        "/ai/datasets",
        "/ai/rag/knowledge-bases",
        "/ai/chat/conversations",
    ):
        response = await api_client.get(path)
        assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.anyio
async def test_operational_status_separates_optional_data_rag_capabilities(
    api_client: AsyncClient,
) -> None:
    response = await api_client.get("/operational-status")
    payload = response.json()

    assert response.status_code == 200
    assert payload["dataset_storage"] == "available"
    assert payload["embedding_provider"] == "available"
    assert payload["generation_provider"] == "available"
    assert payload["rag_index"] == "available"
    assert payload["status"] in {"operational", "degraded"}


@pytest.mark.anyio
async def test_dataset_storage_probe_does_not_create_temporary_objects(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "datasets"

    assert await _dataset_storage_status(str(storage_root)) == "available"

    assert storage_root.is_dir()
    assert tuple(storage_root.iterdir()) == ()


def test_data_rag_dashboard_and_alerts_use_content_free_metrics() -> None:
    dashboard = json.loads(_DASHBOARD.read_text(encoding="utf-8"))
    rules = yaml.safe_load(_RULES.read_text(encoding="utf-8"))

    assert dashboard["uid"] == "data-rag-operations"
    assert len(dashboard["panels"]) == 8
    rendered_dashboard = json.dumps(dashboard)
    for forbidden in (
        "user_id",
        "dataset_id",
        "study_id",
        "conversation_id",
        "prompt",
        "document_text",
        "error_text",
    ):
        assert forbidden not in rendered_dashboard
    alerts = {rule["alert"] for group in rules["groups"] for rule in group["rules"]}
    assert alerts == {
        "DatasetProcessingFailures",
        "RAGEmbeddingFailures",
        "RAGIndexBuildFailures",
        "RAGRetrievalErrorRate",
        "ChatbotGenerationErrorRate",
        "DataRAGProcessTimeouts",
        "DataRAGReconciliationFailures",
    }
    embedding_alert = next(
        rule
        for group in rules["groups"]
        for rule in group["rules"]
        if rule["alert"] == "RAGEmbeddingFailures"
    )
    assert "rag_index_duration_seconds_count" in embedding_alert["expr"]
    assert 'stage="embedding"' in embedding_alert["expr"]
