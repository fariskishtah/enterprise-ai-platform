"""Idempotently seed a small, local-only platform demonstration."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
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
MODEL_NAME = "demo_random_forest_regression"
PREDICTION_CORRELATION_ID = "local-demo-prediction-v1"
POLL_TIMEOUT_SECONDS = 90.0
POLL_INTERVAL_SECONDS = 1.0

COMPANY_NAME = "Northstar Demo Manufacturing"
FACTORY_NAME = "Alexandria Smart Factory"
MACHINE_NAME = "CNC Mill DEMO-01"
SENSOR_NAME = "Spindle Temperature DEMO-01"

READINGS = tuple(
    (
        f"2026-07-01T08:{minute:02d}:00Z",
        value,
    )
    for minute, value in enumerate(
        (68.2, 69.1, 70.4, 72.0, 74.3, 76.8, 78.1, 77.4, 75.6, 73.8, 72.1, 70.7)
    )
)


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
        params: Mapping[str, str | int] | None = None,
    ) -> ApiResponse:
        """Send one bounded JSON request and retain HTTP error responses."""
        query = f"?{urlencode(params)}" if params else ""
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request_headers = {**self.headers, **(headers or {})}
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}{query}",
            data=body,
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


def seed_domain(client: ApiClient) -> tuple[dict[str, Any], dict[str, bool]]:
    """Create or reuse the one bounded manufacturing hierarchy."""
    company, company_created = get_or_create(
        client,
        path="/companies",
        name=COMPANY_NAME,
        payload={
            "name": COMPANY_NAME,
            "description": "Local-only enterprise AI manufacturing demonstration",
        },
    )
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
    return sensor, {
        "company": company_created,
        "factory": factory_created,
        "machine": machine_created,
        "sensor": sensor_created,
    }


def seed_readings(client: ApiClient, sensor_id: str) -> int:
    """Insert only missing fixed-timestamp readings."""
    existing = list_items(
        client,
        "/sensor-readings",
        params={
            "sensor_id": sensor_id,
            "timestamp_from": READINGS[0][0],
            "timestamp_to": READINGS[-1][0],
        },
    )
    existing_timestamps = {item["timestamp"] for item in existing}
    created_count = 0
    for timestamp, value in READINGS:
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


def train_model(client: ApiClient) -> tuple[str, str, bool]:
    """Submit or reuse one deterministic background training job."""
    payload = {
        "training_features": [[68.0], [71.0], [75.0], [79.0]],
        "training_targets": [0.10, 0.18, 0.42, 0.75],
        "evaluation_features": [[70.0], [77.0]],
        "evaluation_targets": [0.15, 0.58],
        "hyperparameters": {"n_estimators": 3, "n_jobs": 1},
        "random_seed": 17,
        "experiment_name": "Local Demo Predictive Maintenance",
        "run_name": "local-demo-regression-v1",
        "registered_model_name": MODEL_NAME,
        "tags": {"purpose": "local-demo"},
        "model_description": "Local-only bounded demo model",
    }
    response = require_response(
        client.post(
            "/ai/training-jobs/random-forest/regression",
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
            "/ai/predictions/random-forest/regression",
            headers={"X-Correlation-ID": PREDICTION_CORRELATION_ID},
            json={
                "registered_model_name": MODEL_NAME,
                "version_or_alias": version,
                "features": [[76.5]],
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
    with ApiClient(base_url=API_BASE_URL, timeout=15.0) as anonymous:
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

    with ApiClient(base_url=API_BASE_URL, timeout=15.0) as anonymous:
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
        timeout=15.0,
    ) as client:
        sensor, created = seed_domain(client)
        readings_created = seed_readings(client, str(sensor["id"]))
        job_id, version, job_created = train_model(client)
        prediction_created = ensure_prediction_audit(client, version)

    created_resources = (
        ", ".join(name for name, was_created in created.items() if was_created)
        or "none"
    )
    print("Demo seed complete")
    print(f"  API: {API_BASE_URL}")
    print(f"  User: {DEMO_EMAIL} ({'created' if user_created else 'reused'})")
    print(f"  Domain resources created: {created_resources}")
    print(
        f"  Sensor readings created: {readings_created} (total target: {len(READINGS)})"
    )
    print(f"  Training job: {job_id} ({'created' if job_created else 'reused'})")
    print(f"  Model: {MODEL_NAME} version {version}")
    print(f"  Prediction audit: {'created' if prediction_created else 'reused'}")


if __name__ == "__main__":
    try:
        run()
    except DemoSeedError as error:
        print(f"Demo seed failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
