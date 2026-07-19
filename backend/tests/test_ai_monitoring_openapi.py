"""Monitoring OpenAPI coverage and response privacy tests."""

from app.config.settings import Settings
from app.core.application import create_app


def test_monitoring_openapi_documents_routes_roles_and_privacy(
    settings: Settings,
) -> None:
    """Monitoring paths are described and event schemas cannot carry raw matrices."""
    schema: dict[str, object] = create_app(settings).openapi()
    paths = schema["paths"]
    assert isinstance(paths, dict)
    expected = {
        "/ai/monitoring/prediction-events",
        "/ai/monitoring/prediction-events/{event_id}",
        (
            "/ai/monitoring/models/{registered_model_name}/versions/"
            "{version_or_alias}/operations"
        ),
        (
            "/ai/monitoring/models/{registered_model_name}/versions/"
            "{version_or_alias}/data-quality"
        ),
        (
            "/ai/monitoring/models/{registered_model_name}/versions/"
            "{version_or_alias}/drift"
        ),
        (
            "/ai/monitoring/models/{registered_model_name}/versions/"
            "{version_or_alias}/reference-profile"
        ),
    }
    assert expected <= set(paths)
    operations = paths[
        "/ai/monitoring/models/{registered_model_name}/versions/"
        "{version_or_alias}/operations"
    ]
    assert isinstance(operations, dict)
    get_operation = operations["get"]
    assert isinstance(get_operation, dict)
    assert "exact version or alias" in str(get_operation["description"])

    components = schema["components"]
    assert isinstance(components, dict)
    schemas = components["schemas"]
    assert isinstance(schemas, dict)
    event_schema = schemas["PredictionEventResponse"]
    assert isinstance(event_schema, dict)
    properties = event_schema["properties"]
    assert isinstance(properties, dict)
    assert "feature_profile" in properties
    assert "prediction_profile" in properties
    assert "requested_by_user_id" not in properties
    assert "features" not in properties
    assert "predictions" not in properties

    operational_schema = schemas["PredictionOperationalSummaryResponse"]
    assert isinstance(operational_schema, dict)
    operational_properties = operational_schema["properties"]
    assert isinstance(operational_properties, dict)
    assert {
        "matched_event_count",
        "analyzed_event_count",
        "truncated",
        "instance_capture_failures_since_start",
    } <= set(operational_properties)
    diagnostic = operational_properties["instance_capture_failures_since_start"]
    assert isinstance(diagnostic, dict)
    description = str(diagnostic["description"])
    assert "Resets on restart" in description
    assert "not window-filtered" in description
    assert "replica-aggregated" in description

    for name in ("PredictionDataQualityResponse", "ModelDriftResponse"):
        report_schema = schemas[name]
        assert isinstance(report_schema, dict)
        report_properties = report_schema["properties"]
        assert isinstance(report_properties, dict)
        assert {
            "matched_event_count",
            "analyzed_event_count",
            "truncated",
            "analysis_warning",
        } <= set(report_properties)
