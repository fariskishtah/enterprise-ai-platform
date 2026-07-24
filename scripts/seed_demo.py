"""Idempotently seed a small, local-only platform demonstration."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.config.settings import Settings
from app.models.user import User, UserRole
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

API_BASE_URL = os.getenv("DEMO_API_BASE_URL", "http://backend:8000").rstrip("/")
DEMO_EMAIL = os.getenv("DEMO_EMAIL", "demo@example.com")
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "LocalDemoPassword1!")
MODEL_NAME = "demo_predictive_maintenance_regression"
PREDICTION_CORRELATION_ID = "local-demo-prediction-v1"
POLL_TIMEOUT_SECONDS = 90.0
POLL_INTERVAL_SECONDS = 1.0

COMPANY_NAME = "Northstar Demo Manufacturing"
FACTORY_NAME = "Alexandria Smart Factory"
MACHINE_NAME = "CNC Mill DEMO-01"
SENSOR_NAME = "Spindle Temperature DEMO-01"
VIBRATION_SENSOR_NAME = "Spindle Vibration DEMO-01"
TRAINING_DATASET_NAME = "DEMO Predictive Maintenance History"
DOCUMENT_DATASET_NAME = "DEMO Maintenance Procedures"
KNOWLEDGE_BASE_NAME = "DEMO Maintenance Knowledge"

READINGS = tuple(
    (
        f"2026-07-01T08:{minute:02d}:00Z",
        value,
    )
    for minute, value in enumerate(
        (68.2, 69.1, 70.4, 72.0, 74.3, 76.8, 78.1, 77.4, 75.6, 73.8, 72.1, 70.7)
    )
)
VIBRATION_READINGS = tuple(
    (
        f"2026-07-01T08:{minute:02d}:00Z",
        value,
    )
    for minute, value in enumerate(
        (2.1, 2.2, 2.4, 2.8, 3.3, 4.0, 4.8, 4.5, 3.9, 3.4, 2.9, 2.5)
    )
)
TRAINING_CSV = b"""temperature_c,vibration_mm_s,risk_score,split
62.0,1.40,0.040,train
63.0,1.68,0.075,train
64.0,1.96,0.110,train
65.0,2.24,0.145,train
66.0,2.52,0.180,evaluation
67.0,2.80,0.215,train
68.0,3.08,0.250,train
69.0,3.36,0.285,train
70.0,3.64,0.320,train
71.0,3.92,0.355,evaluation
72.0,4.20,0.390,train
73.0,4.48,0.425,train
74.0,4.76,0.460,train
75.0,5.04,0.495,train
76.0,5.32,0.530,evaluation
77.0,5.60,0.565,train
78.0,5.88,0.600,train
79.0,6.16,0.635,train
80.0,6.44,0.670,train
81.0,6.72,0.705,evaluation
82.0,7.00,0.740,train
83.0,7.28,0.775,train
84.0,7.56,0.810,train
85.0,7.84,0.845,train
"""
MAINTENANCE_DOCUMENT = b"""DEMO CNC spindle maintenance procedure

For an Observe risk indication, review temperature and vibration trends during
the next operator round. For Warning, notify an engineer and inspect lubrication,
bearing noise, and spindle balance before the next shift. For Critical, follow
site safety and lockout procedures and request immediate engineering review.
This local demo guidance does not replace the customer's approved procedures.
"""


class DemoSeedError(RuntimeError):
    """Raised when a demo operation cannot complete safely."""


class ApiResponse:
    """Small response wrapper for the standard-library HTTP transport."""

    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self.text = body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        """Decode a JSON response body."""
        return json.loads(self.text)


class ApiClient:
    """Minimal JSON API client requiring no non-runtime dependency."""

    def __init__(
        self,
        *,
        base_url: str,
        headers: Mapping[str, str] | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = base_url
        self.headers = dict(headers or {})
        self.timeout = timeout

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        payload: object | None = None,
        body: bytes | None = None,
        params: Mapping[str, str | int] | None = None,
    ) -> ApiResponse:
        """Send one bounded JSON request and retain HTTP error responses."""
        query = f"?{urlencode(params)}" if params else ""
        if payload is not None and body is not None:
            raise DemoSeedError("request cannot contain JSON and a raw body")
        request_body = (
            json.dumps(payload).encode("utf-8") if payload is not None else body
        )
        request_headers = {**self.headers, **(headers or {})}
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}{query}",
            data=request_body,
            headers=request_headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return ApiResponse(response.status, response.read())
        except HTTPError as error:
            return ApiResponse(error.code, error.read())
        except URLError as error:
            raise DemoSeedError(f"API request failed: {error.reason}") from error

    def get(
        self,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
    ) -> ApiResponse:
        return self.request("GET", path, params=params)

    def post(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        json: object | None = None,
    ) -> ApiResponse:
        return self.request("POST", path, headers=headers, payload=json)

    def put(self, path: str, *, json: object | None = None) -> ApiResponse:
        return self.request("PUT", path, payload=json)

    def patch(self, path: str, *, json: object | None = None) -> ApiResponse:
        return self.request("PATCH", path, payload=json)

    def post_file(
        self,
        path: str,
        *,
        filename: str,
        media_type: str,
        content: bytes,
        fields: Mapping[str, str] | None = None,
    ) -> ApiResponse:
        boundary = f"----fk-demo-{uuid.uuid4().hex}"
        parts: list[bytes] = []
        for name, value in (fields or {}).items():
            parts.extend(
                (
                    f"--{boundary}\r\n".encode(),
                    (f'Content-Disposition: form-data; name="{name}"\r\n\r\n').encode(),
                    value.encode(),
                    b"\r\n",
                )
            )
        parts.extend(
            (
                f"--{boundary}\r\n".encode(),
                (
                    'Content-Disposition: form-data; name="file"; '
                    f'filename="{filename}"\r\n'
                ).encode(),
                f"Content-Type: {media_type}\r\n\r\n".encode(),
                content,
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            )
        )
        return self.request(
            "POST",
            path,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            body=b"".join(parts),
        )


def require_response(
    response: ApiResponse,
    expected_statuses: set[int],
    operation: str,
) -> ApiResponse:
    """Validate one API result without exposing request credentials."""
    if response.status_code not in expected_statuses:
        detail = response.text[:500]
        raise DemoSeedError(
            f"{operation} failed with HTTP {response.status_code}: {detail}"
        )
    return response


async def grant_demo_engineer_role() -> None:
    """Grant the registered local demo user enough access to seed API data."""
    settings = Settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(
                select(User.id, User.role).where(User.email == DEMO_EMAIL.lower())
            )
            row = result.one_or_none()
            if row is None:
                raise DemoSeedError("registered demo user was not found")
            if row.role is not UserRole.ENGINEER:
                await connection.execute(
                    User.__table__.update()
                    .where(User.id == row.id)
                    .values(role=UserRole.ENGINEER)
                )
    finally:
        await engine.dispose()


def exact_named(items: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Return an exact named API resource from a bounded list response."""
    return next((item for item in items if item.get("name") == name), None)


def list_items(
    client: ApiClient,
    path: str,
    *,
    params: Mapping[str, str | int] | None = None,
) -> list[dict[str, Any]]:
    """Return a bounded page of API resources."""
    response = require_response(
        client.get(path, params={"limit": 100, **(params or {})}),
        {200},
        f"list {path}",
    )
    return response.json()["items"]


def get_or_create(
    client: ApiClient,
    *,
    path: str,
    name: str,
    payload: dict[str, Any],
    list_params: Mapping[str, str | int] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Reuse an exact named resource or create it once through the API."""
    existing = exact_named(
        list_items(client, path, params={"search": name, **(list_params or {})}),
        name,
    )
    if existing is not None:
        return existing, False
    created = require_response(
        client.post(path, json=payload),
        {201},
        f"create {name}",
    )
    return created.json(), True


def seed_domain(
    client: ApiClient,
) -> tuple[dict[str, dict[str, Any]], dict[str, bool]]:
    """Create or reuse the one bounded manufacturing hierarchy."""
    companies = list_items(client, "/companies")
    if len(companies) != 1:
        raise DemoSeedError("the demo user must have exactly one tenant company")
    company = companies[0]
    company_created = company["name"] != COMPANY_NAME
    if company_created:
        company = require_response(
            client.patch(
                f"/companies/{company['id']}",
                json={
                    "name": COMPANY_NAME,
                    "description": (
                        "Local-only enterprise AI manufacturing demonstration"
                    ),
                },
            ),
            {200},
            "configure demo tenant company",
        ).json()
    factory, factory_created = get_or_create(
        client,
        path="/factories",
        name=FACTORY_NAME,
        list_params={"company_id": company["id"]},
        payload={
            "company_id": company["id"],
            "name": FACTORY_NAME,
            "location": "Alexandria, Egypt",
            "description": "Deterministic smart-factory demo line",
        },
    )
    machine, machine_created = get_or_create(
        client,
        path="/machines",
        name=MACHINE_NAME,
        list_params={"factory_id": factory["id"]},
        payload={
            "factory_id": factory["id"],
            "name": MACHINE_NAME,
            "serial_number": "DEMO-CNC-001",
            "manufacturer": "Northstar Industrial",
            "model": "PrecisionMill X1",
        },
    )
    sensor, sensor_created = get_or_create(
        client,
        path="/sensors",
        name=SENSOR_NAME,
        list_params={"machine_id": machine["id"]},
        payload={
            "machine_id": machine["id"],
            "name": SENSOR_NAME,
            "sensor_type": "temperature",
            "unit": "celsius",
            "sampling_rate": 1.0,
            "min_value": 0.0,
            "max_value": 120.0,
            "description": "CNC spindle bearing temperature",
        },
    )
    vibration_sensor, vibration_sensor_created = get_or_create(
        client,
        path="/sensors",
        name=VIBRATION_SENSOR_NAME,
        list_params={"machine_id": machine["id"]},
        payload={
            "machine_id": machine["id"],
            "name": VIBRATION_SENSOR_NAME,
            "sensor_type": "vibration",
            "unit": "mm/s",
            "sampling_rate": 1.0,
            "min_value": 0.0,
            "max_value": 30.0,
            "description": "CNC spindle vibration velocity",
        },
    )
    return {
        "company": company,
        "factory": factory,
        "machine": machine,
        "temperature_sensor": sensor,
        "vibration_sensor": vibration_sensor,
    }, {
        "company": company_created,
        "factory": factory_created,
        "machine": machine_created,
        "sensor": sensor_created,
        "vibration_sensor": vibration_sensor_created,
    }


def seed_readings(
    client: ApiClient,
    sensor_id: str,
    readings: tuple[tuple[str, float], ...],
) -> int:
    """Insert only missing fixed-timestamp readings."""
    existing = list_items(
        client,
        "/sensor-readings",
        params={
            "sensor_id": sensor_id,
            "timestamp_from": readings[0][0],
            "timestamp_to": readings[-1][0],
        },
    )
    existing_timestamps = {item["timestamp"] for item in existing}
    created_count = 0
    for timestamp, value in readings:
        normalized_timestamp = timestamp.replace("Z", "+00:00")
        if (
            timestamp in existing_timestamps
            or normalized_timestamp in existing_timestamps
        ):
            continue
        require_response(
            client.post(
                "/sensor-readings",
                json={
                    "sensor_id": sensor_id,
                    "timestamp": timestamp,
                    "value": value,
                    "quality": "GOOD",
                    "source": "API",
                },
            ),
            {201},
            f"create sensor reading at {timestamp}",
        )
        created_count += 1
    return created_count


def _wait_for_status(
    client: ApiClient,
    path: str,
    *,
    successful: set[str],
    failed: set[str],
    operation: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = require_response(client.get(path), {200}, operation).json()
        state = str(last.get("status"))
        if state in successful:
            return last
        if state in failed:
            raise DemoSeedError(f"{operation} ended as {state}")
        time.sleep(POLL_INTERVAL_SECONDS)
    raise DemoSeedError(
        f"{operation} exceeded {POLL_TIMEOUT_SECONDS:.0f} seconds "
        f"(last status={last.get('status', 'unknown')})"
    )


def seed_dataset_version(
    client: ApiClient,
    *,
    name: str,
    kind: str,
    filename: str,
    media_type: str,
    content: bytes,
    fields: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], bool]:
    dataset = exact_named(list_items(client, "/ai/datasets"), name)
    if dataset is None:
        dataset = require_response(
            client.post(
                "/ai/datasets",
                json={
                    "name": name,
                    "description": "Deterministic local-only pilot fixture",
                    "kind": kind,
                },
            ),
            {201},
            f"create dataset {name}",
        ).json()
    versions = list_items(client, f"/ai/datasets/{dataset['id']}/versions")
    matching = next(
        (
            version
            for version in versions
            if version.get("original_filename") == filename
            and version.get("status") in {"pending", "processing", "ready"}
        ),
        None,
    )
    created = matching is None
    if matching is None:
        matching = require_response(
            client.post_file(
                f"/ai/datasets/{dataset['id']}/versions",
                filename=filename,
                media_type=media_type,
                content=content,
                fields=fields,
            ),
            {202},
            f"upload dataset version {name}",
        ).json()
    if matching["status"] != "ready":
        matching = _wait_for_status(
            client,
            f"/ai/datasets/{dataset['id']}/versions/{matching['id']}",
            successful={"ready"},
            failed={"failed", "archived"},
            operation=f"process dataset {name}",
        )
    return matching, created


def seed_knowledge_base(
    client: ApiClient, document_version_id: str
) -> tuple[str, bool]:
    knowledge_base = exact_named(
        list_items(client, "/ai/rag/knowledge-bases"),
        KNOWLEDGE_BASE_NAME,
    )
    created = knowledge_base is None
    if knowledge_base is None:
        knowledge_base = require_response(
            client.post(
                "/ai/rag/knowledge-bases",
                json={
                    "name": KNOWLEDGE_BASE_NAME,
                    "description": "Local-only demo maintenance guidance",
                    "chunk_size": 400,
                    "chunk_overlap": 40,
                },
            ),
            {201},
            "create demo knowledge base",
        ).json()
    knowledge_base_id = str(knowledge_base["knowledge_base_id"])
    detail = require_response(
        client.get(f"/ai/rag/knowledge-bases/{knowledge_base_id}"),
        {200},
        "load demo knowledge base",
    ).json()
    attached = {str(item["dataset_version_id"]) for item in detail["dataset_versions"]}
    if document_version_id not in attached:
        require_response(
            client.post(
                f"/ai/rag/knowledge-bases/{knowledge_base_id}/dataset-versions",
                json={"dataset_version_id": document_version_id},
            ),
            {201},
            "attach demo document dataset",
        )
    if detail["status"] != "ready":
        builds = list_items(
            client,
            f"/ai/rag/knowledge-bases/{knowledge_base_id}/builds",
        )
        active = next(
            (item for item in builds if item.get("status") in {"queued", "running"}),
            None,
        )
        if active is None:
            require_response(
                client.post(f"/ai/rag/knowledge-bases/{knowledge_base_id}/build"),
                {202},
                "build demo knowledge base",
            )
        _wait_for_status(
            client,
            f"/ai/rag/knowledge-bases/{knowledge_base_id}",
            successful={"ready"},
            failed={"failed", "archived"},
            operation="build demo knowledge base",
        )
    return knowledge_base_id, created


def train_model(
    client: ApiClient, training_dataset_version_id: str
) -> tuple[str, str, bool]:
    """Submit or reuse one deterministic background training job."""
    payload = {
        "task_type": "regression",
        "algorithm": "ridge_regression",
        "dataset_version_id": training_dataset_version_id,
        "hyperparameters": {
            "alpha": 0.001,
            "fit_intercept": True,
        },
        "preprocessing": {"scaler": "standard", "imputer": "none"},
        "random_seed": 17,
        "experiment_name": "Local Demo Predictive Maintenance",
        "run_name": "local-demo-regression-v1",
        "registered_model_name": MODEL_NAME,
        "tags": {"purpose": "local-demo"},
        "model_description": "Local-only bounded demo model",
    }
    response = require_response(
        client.post(
            "/ai/training-jobs",
            headers={"Idempotency-Key": "local-demo-regression-v1"},
            json=payload,
        ),
        {200, 202},
        "submit demo training job",
    )
    submission = response.json()
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    last_status = submission["status"]
    while time.monotonic() < deadline:
        job_response = require_response(
            client.get(submission["status_url"]),
            {200},
            "poll demo training job",
        )
        job = job_response.json()
        last_status = job["status"]
        if last_status == "succeeded":
            version = str(job["registered_model_version"])
            require_response(
                client.get(f"/ai/models/{MODEL_NAME}/versions/{version}"),
                {200},
                "resolve demo model version",
            )
            evaluation = require_response(
                client.get(f"/ai/training-jobs/{submission['job_id']}/evaluation"),
                {200},
                "load demo model evaluation",
            ).json()
            if not evaluation.get("metrics"):
                raise DemoSeedError("demo model evaluation returned no metrics")
            return submission["job_id"], version, response.status_code == 202
        if last_status in {"failed", "cancelled"}:
            raise DemoSeedError(
                "demo training job ended as "
                f"{last_status} (error={job.get('error_code')})"
            )
        time.sleep(POLL_INTERVAL_SECONDS)
    raise DemoSeedError(
        f"demo training job exceeded 90 seconds (last status={last_status})"
    )


def ensure_model_governance(
    client: ApiClient,
    *,
    version: str,
    training_dataset_version_id: str,
) -> bool:
    schema_path = f"/ai/models/{MODEL_NAME}/versions/{version}/feature-schema"
    schema = client.get(schema_path)
    if schema.status_code == 404:
        schema = require_response(
            client.put(
                schema_path,
                json={
                    "features": [
                        {
                            "name": "temperature_c",
                            "data_type": "float",
                            "required": True,
                            "unit": "celsius",
                            "minimum": 0.0,
                            "maximum": 120.0,
                            "missing_value_behavior": "reject",
                        },
                        {
                            "name": "vibration_mm_s",
                            "data_type": "float",
                            "required": True,
                            "unit": "mm/s",
                            "minimum": 0.0,
                            "maximum": 30.0,
                            "missing_value_behavior": "reject",
                        },
                    ],
                    "algorithm": "ridge_regression",
                    "task_type": "regression",
                    "target_name": "risk_score",
                    "training_dataset_version_id": training_dataset_version_id,
                },
            ),
            {200},
            "save demo feature schema",
        )
    else:
        schema = require_response(schema, {200}, "load demo feature schema")
    schema_body = schema.json()
    if (
        [feature["name"] for feature in schema_body["features"]]
        != ["temperature_c", "vibration_mm_s"]
        or schema_body["algorithm"] != "ridge_regression"
        or schema_body["task_type"] != "regression"
        or schema_body["training_dataset_version_id"] != training_dataset_version_id
    ):
        raise DemoSeedError("demo feature schema was not persisted")

    aliases = require_response(
        client.get(f"/ai/models/{MODEL_NAME}/aliases"),
        {200},
        "list demo model aliases",
    ).json()["aliases"]
    if any(
        item["alias"] == "challenger" and str(item["version"]) == version
        for item in aliases
    ):
        return False
    require_response(
        client.post(
            f"/ai/models/{MODEL_NAME}/versions/{version}/promotions/challenger",
            json={},
        ),
        {200},
        "approve demo challenger alias",
    )
    return True


def ensure_structured_risk_cases(
    client: ApiClient, *, version: str, machine_id: str
) -> tuple[int, str]:
    created = 0
    cases = (
        (
            "local-demo-risk-normal-v1",
            {"temperature_c": 68.0, "vibration_mm_s": 2.2},
        ),
        (
            "local-demo-risk-warning-v1",
            {"temperature_c": 84.0, "vibration_mm_s": 7.4},
        ),
    )
    existing_events = list_items(
        client,
        "/ai/monitoring/prediction-events",
        params={
            "registered_model_name": MODEL_NAME,
            "resolved_model_version": version,
        },
    )
    existing_correlations = {event.get("correlation_id") for event in existing_events}
    for correlation_id, values in cases:
        if correlation_id in existing_correlations:
            continue
        response = require_response(
            client.post(
                f"/ai/models/{MODEL_NAME}/versions/{version}/structured-prediction",
                headers={"X-Correlation-ID": correlation_id},
                json={"machine_id": machine_id, "values": values},
            ),
            {200},
            f"run {correlation_id}",
        ).json()
        if response.get("assessment_id") is None:
            raise DemoSeedError("structured demo prediction created no assessment")
        created += 1

    risk = require_response(
        client.get(f"/pilot/machines/{machine_id}/risk"),
        {200},
        "load demo machine risk",
    ).json()
    if risk["risk_state"] not in {"warning", "critical"}:
        raise DemoSeedError(
            "the bounded high-risk demo case did not reach an alert threshold"
        )
    alert_id = risk.get("alert_id")
    if not alert_id:
        raise DemoSeedError("the high-risk demo case produced no alert")
    if risk["acknowledged_at"] is None:
        require_response(
            client.post(
                f"/pilot/machine-risk/{risk['id']}/acknowledge",
                json={
                    "operator_note": (
                        "DEMO acknowledgement: engineer inspection requested."
                    )
                },
            ),
            {204},
            "acknowledge demo machine risk",
        )
    return created, str(alert_id)


def ensure_prediction_audit(client: ApiClient, version: str) -> bool:
    """Create one prediction only when its deterministic audit is absent."""
    events = list_items(
        client,
        "/ai/monitoring/prediction-events",
        params={
            "registered_model_name": MODEL_NAME,
            "resolved_model_version": version,
        },
    )
    if any(
        event.get("correlation_id") == PREDICTION_CORRELATION_ID for event in events
    ):
        return False
    prediction = require_response(
        client.post(
            "/ai/predictions",
            headers={"X-Correlation-ID": PREDICTION_CORRELATION_ID},
            json={
                "registered_model_name": MODEL_NAME,
                "version_or_alias": version,
                "features": [[76.5, 4.2]],
                "algorithm": "ridge_regression",
                "task_type": "regression",
            },
        ),
        {200},
        "run demo prediction",
    ).json()
    if prediction.get("model_version") != version:
        raise DemoSeedError("prediction did not use the expected exact model version")
    return True


def run() -> None:
    """Execute the complete idempotent local demo seed flow."""
    with ApiClient(base_url=API_BASE_URL, timeout=60.0) as anonymous:
        health = require_response(anonymous.get("/health"), {200}, "backend health")
        if health.json().get("status") not in {"ok", "healthy"}:
            raise DemoSeedError("backend health response was not healthy")
        registration = anonymous.post(
            "/auth/register",
            json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
        )
        require_response(registration, {201, 409}, "register demo user")
        user_created = registration.status_code == 201
        require_response(
            anonymous.post(
                "/auth/login",
                json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
            ),
            {200},
            "verify demo user credentials",
        )

    asyncio.run(grant_demo_engineer_role())

    with ApiClient(base_url=API_BASE_URL, timeout=60.0) as anonymous:
        login = require_response(
            anonymous.post(
                "/auth/login",
                json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
            ),
            {200},
            "login demo user",
        ).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    with ApiClient(
        base_url=API_BASE_URL,
        headers=headers,
        timeout=60.0,
    ) as client:
        domain, created = seed_domain(client)
        temperature_readings_created = seed_readings(
            client,
            str(domain["temperature_sensor"]["id"]),
            READINGS,
        )
        vibration_readings_created = seed_readings(
            client,
            str(domain["vibration_sensor"]["id"]),
            VIBRATION_READINGS,
        )
        training_version, training_dataset_created = seed_dataset_version(
            client,
            name=TRAINING_DATASET_NAME,
            kind="tabular",
            filename="demo-predictive-maintenance-v1.csv",
            media_type="text/csv",
            content=TRAINING_CSV,
            fields={
                "target_column": "risk_score",
                "split_column": "split",
                "evaluation_fraction": "0.25",
            },
        )
        document_version, document_dataset_created = seed_dataset_version(
            client,
            name=DOCUMENT_DATASET_NAME,
            kind="document_collection",
            filename="demo-maintenance-procedure-v1.txt",
            media_type="text/plain",
            content=MAINTENANCE_DOCUMENT,
        )
        knowledge_base_id, knowledge_base_created = seed_knowledge_base(
            client, str(document_version["id"])
        )
        job_id, version, job_created = train_model(client, str(training_version["id"]))
        alias_created = ensure_model_governance(
            client,
            version=version,
            training_dataset_version_id=str(training_version["id"]),
        )
        prediction_created = ensure_prediction_audit(client, version)
        risk_cases_created, alert_id = ensure_structured_risk_cases(
            client,
            version=version,
            machine_id=str(domain["machine"]["id"]),
        )

    created_resources = (
        ", ".join(name for name, was_created in created.items() if was_created)
        or "none"
    )
    print("Demo seed complete")
    print(f"  API: {API_BASE_URL}")
    print(f"  User: {DEMO_EMAIL} ({'created' if user_created else 'reused'})")
    print(f"  Domain resources created: {created_resources}")
    print(
        "  Sensor readings created: "
        f"{temperature_readings_created + vibration_readings_created} "
        f"(total target: {len(READINGS) + len(VIBRATION_READINGS)})"
    )
    print(
        "  Dataset versions: "
        f"training={'created' if training_dataset_created else 'reused'}, "
        f"documents={'created' if document_dataset_created else 'reused'}"
    )
    print(
        f"  Knowledge base: {knowledge_base_id} "
        f"({'created' if knowledge_base_created else 'reused'})"
    )
    print(f"  Training job: {job_id} ({'created' if job_created else 'reused'})")
    print(f"  Model: {MODEL_NAME} version {version}")
    print(f"  Challenger alias: {'assigned' if alias_created else 'reused'}")
    print(f"  Prediction audit: {'created' if prediction_created else 'reused'}")
    print(f"  Structured risk cases created: {risk_cases_created}")
    print(f"  Acknowledged pilot alert: {alert_id}")


if __name__ == "__main__":
    try:
        run()
    except DemoSeedError as error:
        print(f"Demo seed failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
