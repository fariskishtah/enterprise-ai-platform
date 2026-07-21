"""Static safety contracts for the single-VM production deployment."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any, cast

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

_ROOT = Path(__file__).resolve().parents[2]
_PRODUCTION_COMPOSE = _ROOT / "docker-compose.prod.yml"
_BASE_COMPOSE = _ROOT / "docker-compose.yml"
_NGINX_ROUTES = _ROOT / "infrastructure/nginx/routes.inc"
_NGINX_HTTP = _ROOT / "infrastructure/nginx/reverse-proxy.conf"
_RUNBOOK = _ROOT / "docs/google-cloud-production-deployment.md"
_CI = _ROOT / ".github/workflows/ci.yml"
_SCRIPTS = (
    _ROOT / "scripts/deploy-production.sh",
    _ROOT / "scripts/verify-production.sh",
    _ROOT / "scripts/rollback-production.sh",
)


class _ComposeLoader(yaml.SafeLoader):
    """Load Compose's reset/override tags for static contract assertions."""


def _compose_tag(loader: _ComposeLoader, node: yaml.Node) -> object:
    if isinstance(node, MappingNode):
        return loader.construct_mapping(node, deep=True)
    if isinstance(node, SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, ScalarNode):
        return loader.construct_scalar(node)
    raise TypeError(f"Unsupported Compose YAML node: {type(node).__name__}")


_ComposeLoader.add_constructor("!reset", _compose_tag)
_ComposeLoader.add_constructor("!override", _compose_tag)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _yaml(path: Path) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        yaml.load(_text(path), Loader=_ComposeLoader),
    )


def test_only_reverse_proxy_publishes_production_ports() -> None:
    services = _yaml(_PRODUCTION_COMPOSE)["services"]
    publishing = {name for name, service in services.items() if service.get("ports")}

    assert publishing == {"reverse-proxy"}
    assert services["reverse-proxy"]["ports"] == ["${PUBLIC_HTTP_PORT:-80}:8080"]
    for service in (
        "backend",
        "frontend",
        "postgres",
        "redis",
        "prometheus",
        "loki",
        "tempo",
        "alertmanager",
        "grafana",
    ):
        assert services[service].get("ports", []) == []


def test_data_services_are_internal_and_not_on_public_network() -> None:
    compose = _yaml(_PRODUCTION_COMPOSE)
    services = compose["services"]

    assert services["postgres"]["networks"] == ["data"]
    assert services["redis"]["networks"] == ["data"]
    assert compose["networks"]["data"]["internal"] is True
    assert compose["networks"]["application"]["internal"] is True
    assert "data" not in services["reverse-proxy"]["networks"]


def test_production_services_have_restart_logs_and_resources() -> None:
    services = _yaml(_PRODUCTION_COMPOSE)["services"]

    for name, service in services.items():
        assert service["restart"] == "unless-stopped", name
        assert service["logging"]["driver"] == "json-file", name
        assert service["logging"]["options"] == {
            "max-size": "10m",
            "max-file": "3",
        }, name
        resources = service["deploy"]["resources"]
        assert resources["limits"]["memory"], name
        assert resources["limits"]["cpus"], name
        assert resources["reservations"]["memory"], name
        assert resources["reservations"]["cpus"], name


def test_production_secrets_are_required_without_working_fallbacks() -> None:
    services = _yaml(_PRODUCTION_COMPOSE)["services"]
    backend_environment = services["backend"]["environment"]
    postgres_environment = services["postgres"]["environment"]
    grafana_environment = services["grafana"]["environment"]

    for value in (
        backend_environment["DATABASE_URL"],
        backend_environment["SECRET_KEY"],
        backend_environment["JWT_ISSUER"],
        backend_environment["JWT_AUDIENCE"],
        backend_environment["CORS_ALLOWED_ORIGINS"],
        postgres_environment["POSTGRES_DB"],
        postgres_environment["POSTGRES_USER"],
        postgres_environment["POSTGRES_PASSWORD"],
        grafana_environment["GF_SECURITY_ADMIN_USER"],
        grafana_environment["GF_SECURITY_ADMIN_PASSWORD"],
    ):
        assert "${" in value and ":?" in value
        assert ":-" not in value
    assert backend_environment["ENABLE_API_DOCS"] == "false"


def test_nginx_routes_only_to_valid_application_upstreams() -> None:
    routes = _text(_NGINX_ROUTES)
    http = _text(_NGINX_HTTP)

    assert "proxy_pass http://backend:8000/;" in routes
    assert "proxy_pass http://frontend:8080;" in routes
    assert "location /api/" in routes
    assert "X-Forwarded-For" in routes
    assert "client_max_body_size" in routes
    assert "location = /healthz" in http
    assert "listen 8080" in http


def test_deployment_scripts_are_executable_and_non_destructive() -> None:
    suite = "\n".join(_text(script) for script in _SCRIPTS)

    for script in _SCRIPTS:
        assert script.stat().st_mode & stat.S_IXUSR
        assert _text(script).startswith("#!/usr/bin/env bash\nset -Eeuo pipefail\n")
    for forbidden in (
        "down -v",
        "docker volume rm",
        "alembic downgrade",
        "git reset",
        "git checkout",
    ):
        assert forbidden not in suite
    assert _text(_SCRIPTS[0]).count("alembic upgrade head") == 1
    assert "git worktree add" in _text(_SCRIPTS[2])
    assert '--project-name "$PROJECT_NAME"' in suite


def test_frontend_keeps_local_development_and_adds_production_stage() -> None:
    base = _yaml(_BASE_COMPOSE)
    dockerfile = _text(_ROOT / "docker/frontend/Dockerfile")
    nginx = _text(_ROOT / "infrastructure/nginx/frontend.conf")

    assert base["services"]["frontend"]["build"]["target"] == "development"
    assert "FROM nginx:1.28.0-alpine AS production" in dockerfile
    assert "RUN npm run build" in dockerfile
    assert "Content-Security-Policy" in nginx
    assert "frame-ancestors 'none'" in nginx
    assert "object-src 'none'" in nginx
    assert "script-src 'self';" in nginx
    assert "script-src 'self' 'unsafe-inline'" not in nginx


def test_ci_and_runbook_cover_validation_firewall_and_billing() -> None:
    ci = _text(_CI)
    runbook = _text(_RUNBOOK).lower()

    assert "docker-compose.prod.yml" in ci
    assert "nginx:1.28.0-alpine" in ci
    assert "nginx -t" in ci
    for port in ("22", "80", "443"):
        assert f"tcp {port}" in runbook
    assert "budget" in runbook
    assert "credits" in runbook
    assert "reserved external ips" in runbook
