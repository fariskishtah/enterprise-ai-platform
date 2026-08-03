"""Static safety contracts for the isolated Paymob sandbox deployment."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from typing import Any, cast

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = _ROOT / "docker-compose.paymob-sandbox.yml"
_SCRIPT = _ROOT / "scripts/paymob-sandbox.sh"
_SEED = _ROOT / "scripts/seed_paymob_sandbox_users.py"
_NGINX = _ROOT / "infrastructure/nginx/paymob-sandbox-edge.conf.template"
_RUNBOOK = _ROOT / "docs/production/paymob-sandbox-deployment.md"
_GITIGNORE = _ROOT / ".gitignore"


class _ComposeLoader(yaml.SafeLoader):
    """Load Compose's reset/override tags for static assertions."""


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


def test_sandbox_project_and_production_label_are_exact() -> None:
    suite = "\n".join((_text(_SCRIPT), _text(_RUNBOOK)))

    assert 'PRODUCTION_PROJECT="ai-manufacturing-platform"' in suite
    assert 'SANDBOX_PROJECT="factorymind-paymob-sandbox"' in suite
    assert "com.docker.compose.project=ai-manufacturing-platform" in suite
    assert "ai-manufacturing-production" not in suite


def test_production_roles_are_discovered_without_service_name_filters() -> None:
    script = _text(_SCRIPT)
    discovery = script.split("discover_production_services()", maxsplit=1)[1].split(
        "print_production_labels()", maxsplit=1
    )[0]

    assert "com.docker.compose.project=$PRODUCTION_PROJECT" in discovery
    assert "com.docker.compose.service=" not in discovery
    assert "/etc/nginx/conf.d/default.conf" in discovery
    assert "/etc/nginx/routes.inc" in discovery
    assert "uvicorn" in discovery
    assert "/var/lib/postgresql/data" in discovery
    assert "5432/tcp" in discovery
    assert "6379/tcp" in discovery
    assert "Expected exactly one production" in script
    assert "production_provider_is_disabled" in script


def test_sandbox_compose_exposes_only_the_reverse_proxy_to_edge() -> None:
    compose = _yaml(_COMPOSE)
    services = compose["services"]

    for service in ("backend", "training-worker", "frontend", "postgres", "redis"):
        assert services[service]["ports"] == []
        assert "sandbox-edge" not in services[service].get("networks", {})
        assert services[service]["labels"]["com.factorymind.data-plane"] == (
            "sandbox-only"
        )
    assert services["reverse-proxy"]["ports"] == []
    assert services["reverse-proxy"]["networks"]["sandbox-edge"]["aliases"] == [
        "factorymind-paymob-sandbox-upstream"
    ]
    assert compose["networks"]["sandbox-edge"] == {
        "external": True,
        "name": "factorymind-paymob-sandbox-edge",
    }


def test_sandbox_storage_and_queues_are_explicitly_owned() -> None:
    compose = _yaml(_COMPOSE)
    environment = compose["x-paymob-sandbox-environment"]

    for volume in compose["volumes"].values():
        assert volume["labels"]["com.factorymind.environment"] == "paymob-sandbox"
    for variable in (
        "BILLING_WEBHOOK_QUEUE_NAME",
        "EMAIL_QUEUE_NAME",
        "TRAINING_QUEUE_NAME",
        "DATASET_QUEUE_NAME",
        "RAG_QUEUE_NAME",
        "MONITORING_QUEUE_NAME",
    ):
        assert variable in environment


def test_provider_contract_is_required_and_sandbox_only() -> None:
    environment = _yaml(_COMPOSE)["x-paymob-sandbox-environment"]

    for variable in (
        "PAYMENT_PROVIDER",
        "PAYMENT_SANDBOX_MODE",
        "PAYMOB_SECRET_KEY",
        "PAYMOB_PUBLIC_KEY",
        "PAYMOB_HMAC_SECRET",
        "PAYMOB_INTEGRATION_ID",
        "PAYMOB_MERCHANT_ID",
        "PAYMOB_WEBHOOK_URL",
        "PAYMENT_SUCCESS_URL",
        "PAYMENT_FAILURE_URL",
        "BILLING_COMMERCIAL_MODEL",
    ):
        assert ":?" in environment[variable]
    assert environment["ENVIRONMENT"] == "staging"
    assert environment["APP_ENV"] == "staging"


def test_shared_edge_preserves_production_routes_and_certificate() -> None:
    nginx = _text(_NGINX)

    assert "include /etc/nginx/routes.inc;" in nginx
    assert "/etc/letsencrypt/live/__PRODUCTION_DOMAIN__/fullchain.pem" in nginx
    assert "/etc/letsencrypt/live/__PRODUCTION_DOMAIN__/privkey.pem" in nginx
    assert "factorymind-sandbox-fullchain.pem" in nginx
    assert "factorymind-sandbox-privkey.pem" in nginx
    assert "proxy_pass http://factorymind-paymob-sandbox-upstream:8080;" in nginx
    assert nginx.count("server_name __PRODUCTION_DOMAIN__;") == 2
    assert nginx.count("server_name __SANDBOX_DOMAIN__;") == 2


def test_mutating_actions_are_separate_and_confirmation_guarded() -> None:
    script = _text(_SCRIPT)

    for token in (
        "START-SANDBOX",
        "SEED-SANDBOX-USERS",
        "ISSUE-SANDBOX-CERTIFICATE",
        "ACTIVATE-SANDBOX-INGRESS",
        "REFRESH-SANDBOX-CERTIFICATE",
        "DEACTIVATE-SANDBOX-INGRESS",
        "STOP-SANDBOX",
        "DELETE-SANDBOX-VOLUMES",
    ):
        assert f"require_confirmation {token}" in script
    assert "activate-ingress) activate_ingress" in script
    assert "issue-certificate) issue_certificate" in script
    assert "purge-volumes) purge_volumes" in script
    assert "com.factorymind.environment=paymob-sandbox" in script
    assert "volume rm --" in script


def test_scripts_never_use_broad_compose_teardown_or_production_env() -> None:
    suite = "\n".join((_text(_SCRIPT), _text(_RUNBOOK)))

    assert "docker compose down" not in suite
    assert "compose down" not in suite
    assert "source .env.production" not in suite
    assert "--env-file .env.production" not in suite
    assert "cat .env.production" not in suite
    assert "rm -rf" not in suite


def test_secret_files_are_ignored_and_seed_is_fail_closed() -> None:
    ignored = _text(_GITIGNORE)
    seed = _text(_SEED)

    assert "\n.env.paymob-sandbox\n" in ignored
    assert "/.deployment/paymob-sandbox/" in ignored
    assert 'required("ENABLE_DEVELOPMENT_SEED").lower() != "true"' in seed
    assert 'settings.environment != "staging"' in seed
    assert "not settings.payment_sandbox_mode" in seed
    assert 'settings.payment_provider != "paymob"' in seed
    assert '"is_platform_operator": False' in seed
    assert "email addresses" not in seed.split("print(", maxsplit=1)[1]


def test_secret_configuration_is_hidden_atomic_and_mode_0600() -> None:
    script = _text(_SCRIPT)

    assert "read -r -s HIDDEN_VALUE" in script
    assert 'next_file="$ENV_FILE.next"' in script
    assert 'chmod 600 "$next_file"' in script
    assert 'mv -f -- "$next_file" "$ENV_FILE"' in script
    assert "set -x" not in script
    assert "Live Paymob key prefixes are forbidden" in script
    assert "Sandbox environment created without displaying secret values" in script


def test_sandbox_shell_script_syntax_and_dry_run() -> None:
    assert _SCRIPT.stat().st_mode & stat.S_IXUSR
    subprocess.run(["bash", "-n", str(_SCRIPT)], check=True)
    result = subprocess.run(
        [str(_SCRIPT), "dry-run"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "no Docker, certificate, environment, or ingress mutation" in result.stdout
    assert "com.docker.compose.project=ai-manufacturing-platform" in result.stdout
    assert "activate-ingress --confirm ACTIVATE-SANDBOX-INGRESS" in result.stdout


def test_read_only_preflight_discovers_nonstandard_service_labels(
    tmp_path: Path,
) -> None:
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -eu
command_name="$1"
shift
case "$command_name" in
  version)
    printf '26.1.0\\n'
    ;;
  ps)
    if [[ " $* " == *" --format "* ]]; then
      printf 'NAMES PROJECT SERVICE\\n'
      printf 'edge ai-manufacturing-platform gateway-edge\\n'
      printf 'api ai-manufacturing-platform application-api\\n'
      printf 'db ai-manufacturing-platform database-main\\n'
      printf 'cache ai-manufacturing-platform cache-primary\\n'
    else
      printf 'proxy-id\\nbackend-id\\npostgres-id\\nredis-id\\n'
    fi
    ;;
  inspect)
    format=''
    identifier="${!#}"
    while (($#)); do
      if [[ "$1" == --format ]]; then
        format="$2"
        break
      fi
      shift
    done
    if [[ "$format" == *com.docker.compose.project* ]]; then
      printf 'ai-manufacturing-platform\\n'
    elif [[ "$format" == *com.docker.compose.service* ]]; then
      case "$identifier" in
        proxy-id) printf 'gateway-edge\\n' ;;
        backend-id) printf 'application-api\\n' ;;
        postgres-id) printf 'database-main\\n' ;;
        redis-id) printf 'cache-primary\\n' ;;
      esac
    elif [[ "$format" == *'.Mounts'* ]]; then
      case "$identifier" in
        proxy-id) printf '/etc/nginx/conf.d/default.conf\\n/etc/nginx/routes.inc\\n' ;;
        postgres-id) printf '/var/lib/postgresql/data\\n' ;;
        redis-id) printf '/data\\n' ;;
      esac
    elif [[ "$format" == *ExposedPorts* ]]; then
      case "$identifier" in
        proxy-id) printf '8080/tcp\\n8443/tcp\\n' ;;
        backend-id) printf '8000/tcp\\n' ;;
        postgres-id) printf '5432/tcp\\n' ;;
        redis-id) printf '6379/tcp\\n' ;;
      esac
    elif [[ "$format" == *'.Config.Cmd'* ]]; then
      case "$identifier" in
        proxy-id) printf '["nginx"]\\n' ;;
        backend-id) printf '["uvicorn","app.main:app"]\\n' ;;
        postgres-id) printf '["postgres"]\\n' ;;
        redis-id) printf '["redis-server"]\\n' ;;
      esac
    fi
    ;;
  exec)
    exit 0
    ;;
  *)
    printf 'unexpected fake Docker command: %s\\n' "$command_name" >&2
    exit 2
    ;;
esac
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    environment = os.environ.copy()
    environment["DOCKER_BIN"] = str(fake_docker)

    result = subprocess.run(
        [str(_SCRIPT), "preflight"],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert "reverse-proxy: gateway-edge" in result.stdout
    assert "backend: application-api" in result.stdout
    assert "postgres: database-main" in result.stdout
    assert "redis: cache-primary" in result.stdout
    assert "production payment collection is disabled" in result.stdout
