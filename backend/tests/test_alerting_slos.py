"""Static contracts for SLO rules, alert routing, dashboards, and runbooks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = _ROOT / "docker-compose.yml"
_PROMETHEUS = _ROOT / "infrastructure/observability/prometheus/prometheus.yml"
_RULES = _ROOT / "infrastructure/observability/prometheus/rules"
_ALERTMANAGER = _ROOT / "infrastructure/observability/alertmanager/alertmanager.yml"
_DASHBOARDS = _ROOT / "infrastructure/observability/grafana/dashboards"
_RUNBOOKS = _ROOT / "docs/runbooks"

_PRIMARY_SLOS = {
    "http_availability": "0.001",
    "http_latency": "0.01",
    "background_job_success": "0.01",
    "training_success": "0.05",
    "monitoring_success": "0.01",
}
_WINDOWS = ("5m", "30m", "1h", "2h", "6h", "1d", "3d", "30d")
_REQUIRED_RUNBOOKS = {
    "api-high-error-rate.md",
    "api-latency-degradation.md",
    "backend-down.md",
    "worker-down.md",
    "background-job-failures.md",
    "training-failures.md",
    "monitoring-retraining-failures.md",
    "postgres-issues.md",
    "redis-issues.md",
    "loki-down.md",
    "tempo-down.md",
    "grafana-down.md",
    "alertmanager-down.md",
    "slo-burn-rate.md",
}
_REQUIRED_RUNBOOK_SECTIONS = (
    "## Impact",
    "## Symptoms",
    "## Dashboard and queries",
    "## Immediate checks",
    "## Diagnosis",
    "## Mitigation",
    "## Escalation",
    "## Verification",
)
_SENSITIVE_LABEL_TERMS = (
    "tenant",
    "user_id",
    "email",
    "token",
    "password",
    "secret",
    "job_id",
    "model_id",
    "request_body",
    "query_string",
    "exception",
)


def _yaml(path: Path) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        yaml.safe_load(path.read_text(encoding="utf-8")),
    )


def _rule_files() -> list[Path]:
    return sorted(_RULES.glob("*.yml"))


def _alert_rules() -> list[dict[str, Any]]:
    return [
        rule
        for path in _rule_files()
        for group in _yaml(path)["groups"]
        for rule in group["rules"]
        if "alert" in rule
    ]


def _all_rules() -> list[dict[str, Any]]:
    return [
        rule
        for path in _rule_files()
        for group in _yaml(path)["groups"]
        for rule in group["rules"]
    ]


def test_compose_pins_local_persistent_alertmanager_and_mounts_rules() -> None:
    compose = _yaml(_COMPOSE)
    services = compose["services"]
    alertmanager = services["alertmanager"]

    assert alertmanager["image"] == "prom/alertmanager:v0.32.1"
    assert alertmanager["ports"] == ["127.0.0.1:${ALERTMANAGER_PORT:-9093}:9093"]
    assert "alertmanager-data:/alertmanager" in alertmanager["volumes"]
    assert "alertmanager-data" in compose["volumes"]
    assert "--enable-feature=utf8-strict-mode" in alertmanager["command"]

    prometheus = services["prometheus"]
    assert "--storage.tsdb.retention.time=30d" in prometheus["command"]
    assert (
        "./infrastructure/observability/prometheus/rules:/etc/prometheus/rules:ro"
        in prometheus["volumes"]
    )
    assert prometheus["depends_on"]["alertmanager"]["condition"] == "service_healthy"


def test_prometheus_loads_rules_discovers_alertmanager_and_preserves_jobs() -> None:
    config = _yaml(_PROMETHEUS)

    assert config["rule_files"] == ["/etc/prometheus/rules/*.yml"]
    targets = config["alerting"]["alertmanagers"][0]["static_configs"][0]["targets"]
    assert targets == ["alertmanager:9093"]
    jobs = {item["job_name"] for item in config["scrape_configs"]}
    assert {
        "backend",
        "training-worker",
        "postgres-exporter",
        "redis-exporter",
        "cadvisor",
        "prometheus",
        "alertmanager",
        "loki",
        "tempo",
        "grafana",
    } <= jobs


def test_alertmanager_has_only_local_null_receivers_and_inhibition() -> None:
    config = _yaml(_ALERTMANAGER)
    route = config["route"]

    assert route["group_by"] == ["alertname", "service", "severity"]
    assert route["receiver"] == "local-null"
    assert {child["receiver"] for child in route["routes"]} == {
        "local-critical",
        "local-warning",
        "local-info",
    }
    receivers = config["receivers"]
    assert {receiver["name"] for receiver in receivers} == {
        "local-null",
        "local-critical",
        "local-warning",
        "local-info",
    }
    assert all(set(receiver) == {"name"} for receiver in receivers)
    assert any(
        rule["equal"] == ["service", "slo"]
        and 'severity="critical"' in rule["source_matchers"]
        for rule in config["inhibit_rules"]
    )

    serialized = json.dumps(config).lower()
    for external_config in (
        "email_configs",
        "slack_configs",
        "webhook_configs",
        "pagerduty_configs",
        "opsgenie_configs",
        "victorops_configs",
    ):
        assert external_config not in serialized


def test_primary_slos_have_all_recording_windows_and_budget_series() -> None:
    recording = _yaml(_RULES / "sli-recording-rules.yml")
    rules = recording["groups"][0]["rules"]
    names = {rule["record"] for rule in rules}
    text = (_RULES / "sli-recording-rules.yml").read_text(encoding="utf-8")

    for slo, budget in _PRIMARY_SLOS.items():
        for window in _WINDOWS:
            assert f"slo:{slo}:error_ratio_rate{window}" in names
            assert f"slo:{slo}:burn_rate{window}" in names
        assert f"slo:{slo}:good_ratio30d" in names
        assert f"slo:{slo}:error_budget_remaining_ratio30d" in names
        assert f"slo:{slo}:error_ratio_rate30d / {budget}" in text

    assert 'status_code=~"5.."' in text
    assert 'le="0.5"' in text
    assert 'final_status=~"completed|failed"' in text
    assert 'monitoring_evaluations_total{final_status="failed"}' in text


def test_alert_and_recording_rule_names_are_unique() -> None:
    rules = _all_rules()
    alert_names = [rule["alert"] for rule in rules if "alert" in rule]
    recording_names = [rule["record"] for rule in rules if "record" in rule]

    assert len(alert_names) == len(set(alert_names))
    assert len(recording_names) == len(set(recording_names))


def test_each_primary_slo_has_four_paired_burn_alerts() -> None:
    config = _yaml(_RULES / "slo-burn-rate-alerts.yml")
    rules = config["groups"][0]["rules"]

    assert len(rules) == len(_PRIMARY_SLOS) * 4
    for slo in _PRIMARY_SLOS:
        matching = [
            rule for rule in rules if rule["labels"]["slo"] == slo.replace("_", "-")
        ]
        assert len(matching) == 4
        expressions = "\n".join(str(rule["expr"]) for rule in matching)
        for pair in (("5m", "1h"), ("30m", "6h"), ("2h", "1d"), ("6h", "3d")):
            assert all(f"burn_rate{window}" in expressions for window in pair)
        assert {rule["labels"]["severity"] for rule in matching} == {
            "critical",
            "warning",
            "info",
        }


def test_every_alert_has_bounded_labels_annotations_and_live_links() -> None:
    dashboard_uids = {
        json.loads(path.read_text(encoding="utf-8"))["uid"]
        for path in _DASHBOARDS.glob("*.json")
    }
    alerts = _alert_rules()

    assert alerts
    for alert in alerts:
        labels = alert["labels"]
        annotations = alert["annotations"]
        assert {"severity", "service", "component", "team", "slo"} <= set(labels)
        assert {"summary", "description", "runbook_url", "dashboard_url"} <= set(
            annotations
        )
        runbook = _ROOT / annotations["runbook_url"]
        assert runbook.is_file(), (alert["alert"], runbook)
        dashboard_uid = str(annotations["dashboard_url"]).rstrip("/").split("/")[-1]
        assert dashboard_uid in dashboard_uids, (alert["alert"], dashboard_uid)
        for label_name in labels:
            assert not any(
                term in label_name.lower() for term in _SENSITIVE_LABEL_TERMS
            )


def test_required_runbooks_have_operator_response_sections() -> None:
    available = {path.name for path in _RUNBOOKS.glob("*.md")}
    assert available >= _REQUIRED_RUNBOOKS

    for name in _REQUIRED_RUNBOOKS:
        text = (_RUNBOOKS / name).read_text(encoding="utf-8")
        for section in _REQUIRED_RUNBOOK_SECTIONS:
            assert section in text, (name, section)
        assert "```promql" in text


def test_slo_and_alerting_dashboards_use_fixed_prometheus_uid() -> None:
    expected = {
        "slo-overview.json": "slo-overview",
        "alerting-overview.json": "alerting-overview",
    }
    for filename, uid in expected.items():
        dashboard = json.loads((_DASHBOARDS / filename).read_text(encoding="utf-8"))
        assert dashboard["uid"] == uid
        assert dashboard["panels"]
        for panel in dashboard["panels"]:
            assert panel["datasource"] == {
                "type": "prometheus",
                "uid": "prometheus",
            }
            assert panel["targets"]
            for target in panel["targets"]:
                assert target["datasource"] == {
                    "type": "prometheus",
                    "uid": "prometheus",
                }


def test_every_prometheus_dashboard_panel_uses_fixed_uid() -> None:
    for path in _DASHBOARDS.glob("*.json"):
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        for panel in dashboard["panels"]:
            datasource = panel.get("datasource")
            if datasource not in (
                "prometheus",
                {"type": "prometheus", "uid": "prometheus"},
            ):
                continue
            assert datasource in (
                "prometheus",
                {"type": "prometheus", "uid": "prometheus"},
            )
            for target in panel["targets"]:
                assert target.get("datasource", "prometheus") in (
                    "prometheus",
                    {"type": "prometheus", "uid": "prometheus"},
                )


def test_no_grafana_managed_alerting_duplicates_are_provisioned() -> None:
    provisioning = _ROOT / "infrastructure/observability/grafana/provisioning"

    assert not (provisioning / "alerting").exists()
    assert all(
        "apiVersion: 1\ngroups:" not in path.read_text(encoding="utf-8")
        for path in provisioning.rglob("*.yml")
    )
