"""Static safety contracts for the isolated Paymob sandbox deployment."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = _ROOT / "docker-compose.paymob-sandbox.yml"
_PRODUCTION_COMPOSE = _ROOT / "docker-compose.prod.yml"
_HTTPS_COMPOSE = _ROOT / "docker-compose.https.yml"
_SCRIPT = _ROOT / "scripts/paymob-sandbox.sh"
_PREPARE_HTTPS = _ROOT / "scripts/prepare-production-https.sh"
_REVERSE_PROXY_DOCKERFILE = _ROOT / "docker/reverse-proxy/Dockerfile"
_SEED = _ROOT / "scripts/seed_paymob_sandbox_users.py"
_OWNER_BOOTSTRAP = _ROOT / "scripts/bootstrap_paymob_sandbox_callback_owner.py"
_NGINX = _ROOT / "infrastructure/nginx/paymob-sandbox-edge.conf.template"
_PRODUCTION_NGINX = _ROOT / "infrastructure/nginx/https.conf.template"
_RUNBOOK = _ROOT / "docs/production/paymob-sandbox-deployment.md"
_PRODUCTION_ENV_TEMPLATE = _ROOT / "docs/production/environment-template.md"
_ENV_EXAMPLE = _ROOT / ".env.example"
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


def _owner_bootstrap_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "factorymind_paymob_owner_bootstrap", _OWNER_BOOTSTRAP
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _valid_owner_evidence(module: Any, key: str, owner: str = "700001") -> Any:
    return module.CallbackOwnerEvidence(
        evidence_key=key,
        event_status="quarantined",
        event_type="transaction.captured",
        validation_outcome="quarantined_wrong_merchant",
        safe_validation_outcome="quarantined_wrong_merchant",
        last_error_category="quarantined_wrong_merchant",
        attempts=0,
        queued=False,
        terminal=True,
        owner=owner,
        integration_id=123456,
        environment="sandbox",
        decision="succeeded_eligible",
        state="succeeded",
        source_type="card",
        amount_minor=100_000,
        currency="EGP",
        payment_present=True,
        payment_company_matches=True,
        payment_provider="paymob",
        payment_integration_id=123456,
        payment_environment="sandbox",
        payment_amount_minor=100_000,
        payment_currency="EGP",
    )


def _yaml(path: Path) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        yaml.load(_text(path), Loader=_ComposeLoader),
    )


def _permission_functions() -> str:
    script = _text(_SCRIPT)
    return (
        "file_mode()"
        + script.split("file_mode()", maxsplit=1)[1].split(
            "read_env_value()", maxsplit=1
        )[0]
    )


def _fake_stat(tmp_path: Path, implementation: str, mode: str) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    stat_command = fake_bin / "stat"
    supports_gnu_format = "true" if implementation == "gnu" else "false"
    supports_bsd_format = "true" if implementation == "bsd" else "false"
    stat_command.write_text(
        f"""#!/usr/bin/env bash
set -eu
if [[ "$1" == "-c" ]]; then
  {supports_gnu_format} || exit 1
  printf '%s\\n' {mode!r}
elif [[ "$1" == "-f" ]]; then
  {supports_bsd_format} || {{
    printf 'GNU filesystem metadata that must not be returned\\n'
    exit 0
  }}
  printf '%s\\n' {mode!r}
else
  exit 2
fi
""",
        encoding="utf-8",
    )
    stat_command.chmod(0o755)
    return fake_bin


def _run_permission_probe(
    tmp_path: Path,
    *,
    implementation: str,
    mode: str,
    require_environment: bool = False,
    file_permissions: int = 0o600,
) -> subprocess.CompletedProcess[str]:
    env_file = tmp_path / ".env.paymob-sandbox"
    env_file.write_text(
        "PAYMOB_SECRET_KEY=never-display-this-secret\n", encoding="utf-8"
    )
    env_file.chmod(file_permissions)
    probe = tmp_path / "permission-probe.sh"
    operation = (
        "require_environment" if require_environment else 'file_mode "$ENV_FILE"'
    )
    probe.write_text(
        f"""#!/usr/bin/env bash
set -Eeuo pipefail
ENV_FILE={str(env_file)!r}
{_permission_functions()}
{operation}
""",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PATH"] = os.pathsep.join(
        (str(_fake_stat(tmp_path, implementation, mode)), "/usr/bin", "/bin")
    )
    return subprocess.run(
        ["bash", str(probe)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def _redis_functions() -> str:
    script = _text(_SCRIPT)
    return (
        "redis_resolved_ip()"
        + script.split("redis_resolved_ip()", maxsplit=1)[1].split(
            "assert_host_port_owner()", maxsplit=1
        )[0]
    )


def _redis_isolation_state() -> dict[str, Any]:
    production_data = "ai-manufacturing-platform_data"
    sandbox_data = "factorymind-paymob-sandbox_data"
    return {
        "urls": {
            "production-backend": "redis://redis:6379/0",
            "sandbox-backend": "redis://redis:6379/0",
        },
        "resolved_ips": {
            "production-backend": "172.22.0.2",
            "sandbox-backend": "172.28.0.3",
        },
        "networks": {
            production_data: "production-data-network-id",
            sandbox_data: "sandbox-data-network-id",
        },
        "containers": {
            "production-redis": {
                "networks": {
                    production_data: {
                        "id": "production-data-network-id",
                        "ip": "172.22.0.2",
                    }
                },
                "volume": "ai-manufacturing-platform_redis-data",
            },
            "sandbox-redis": {
                "networks": {
                    sandbox_data: {
                        "id": "sandbox-data-network-id",
                        "ip": "172.28.0.3",
                    }
                },
                "volume": "factorymind-paymob-sandbox_redis-data",
            },
        },
    }


def _fake_docker_for_redis(tmp_path: Path) -> Path:
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys

state = json.loads(os.environ["FAKE_DOCKER_STATE"])
args = sys.argv[1:]

if args[0] == "exec":
    container = args[1]
    environment = os.environ.copy()
    environment.pop("REDIS_URL", None)
    url = state["urls"].get(container)
    if url is not None:
        environment["REDIS_URL"] = url
    resolved_ip = state["resolved_ips"].get(container)
    if resolved_ip is not None:
        environment["FAKE_RESOLVED_IP"] = resolved_ip
    else:
        environment.pop("FAKE_RESOLVED_IP", None)
    environment["PYTHONPATH"] = os.environ["FAKE_SOCKET_MODULE_DIR"]
    command = args[2:]
    if command[0] == "python":
        command[0] = sys.executable
    raise SystemExit(subprocess.run(command, env=environment).returncode)

if args[:2] == ["network", "inspect"]:
    network = args[-1]
    network_id = state["networks"].get(network)
    if network_id is None:
        raise SystemExit(1)
    print(network_id)
    raise SystemExit(0)

if args[0] == "inspect":
    output_format = args[2]
    container = state["containers"].get(args[-1])
    if container is None:
        raise SystemExit(1)
    if ".Mounts" in output_format:
        print(container.get("volume", ""))
    elif "NetworkID" in output_format:
        for network in container["networks"].values():
            print(network["id"])
    elif "println $name" in output_format:
        for name in container["networks"]:
            print(name)
    elif "with index" in output_format:
        match = re.search(r'Networks "([^"]+)"', output_format)
        network = container["networks"].get(match.group(1)) if match else None
        print(network["ip"] if network else "")
    else:
        raise SystemExit(2)
    raise SystemExit(0)

raise SystemExit(2)
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    socket_module_dir = tmp_path / "fake-python"
    socket_module_dir.mkdir()
    (socket_module_dir / "socket.py").write_text(
        """import os

SOCK_STREAM = 1


def getaddrinfo(host, port, type=None):
    resolved_ip = os.environ.get("FAKE_RESOLVED_IP")
    if not resolved_ip:
        raise OSError("DNS resolution unavailable")
    return [(None, None, None, None, (resolved_ip, port))]
""",
        encoding="utf-8",
    )
    return fake_docker


def _run_redis_isolation_probe(
    tmp_path: Path,
    state: dict[str, Any],
    *,
    production_redis: str = "production-redis",
    sandbox_redis: str = "sandbox-redis",
) -> subprocess.CompletedProcess[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    fake_docker = _fake_docker_for_redis(tmp_path)
    probe = tmp_path / "redis-isolation-probe.sh"
    probe.write_text(
        f"""#!/usr/bin/env bash
set -Eeuo pipefail
DOCKER_BIN={str(fake_docker)!r}
PRODUCTION_APPLICATION_NETWORK=ai-manufacturing-platform_application
PRODUCTION_DATA_NETWORK=ai-manufacturing-platform_data
SANDBOX_APPLICATION_NETWORK=factorymind-paymob-sandbox_application
SANDBOX_DATA_NETWORK=factorymind-paymob-sandbox_data
{_redis_functions()}
assert_redis_runtime_isolation \\
  production-backend sandbox-backend {production_redis} {sandbox_redis}
""",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["FAKE_DOCKER_STATE"] = json.dumps(state)
    environment["FAKE_SOCKET_MODULE_DIR"] = str(tmp_path / "fake-python")
    return subprocess.run(
        ["bash", str(probe)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def _certificate_stage_function() -> str:
    script = _text(_SCRIPT)
    return (
        "stage_sandbox_certificate()"
        + script.split("stage_sandbox_certificate()", maxsplit=1)[1].split(
            "issue_certificate()", maxsplit=1
        )[0]
    )


def _shell_function(function_name: str, next_function_name: str) -> str:
    script = _text(_SCRIPT)
    marker = f"{function_name}()"
    return (
        marker
        + script.split(marker, maxsplit=1)[1].split(
            f"{next_function_name}()", maxsplit=1
        )[0]
    )


def _run_certificate_stage_probe(
    tmp_path: Path,
    *,
    repetitions: int = 1,
    fail_destination: str = "",
) -> tuple[subprocess.CompletedProcess[str], dict[str, Path]]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    command_log = tmp_path / "commands.log"
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text(
        """#!/usr/bin/env bash
set -eu
printf 'sudo' >>"$FAKE_COMMAND_LOG"
printf ' %q' "$@" >>"$FAKE_COMMAND_LOG"
printf '\n' >>"$FAKE_COMMAND_LOG"
FAKE_PRIVILEGED=true "$@"
""",
        encoding="utf-8",
    )
    fake_sudo.chmod(0o755)
    fake_install = fake_bin / "install"
    fake_install.write_text(
        """#!/usr/bin/env bash
set -eu
printf 'install' >>"$FAKE_COMMAND_LOG"
printf ' %q' "$@" >>"$FAKE_COMMAND_LOG"
printf '\n' >>"$FAKE_COMMAND_LOG"
[[ "${FAKE_PRIVILEGED:-}" == true ]] || {
  printf 'simulated root-owned parent rejected unprivileged install\n' >&2
  exit 77
}
destination="${!#}"
directory_install=false
for argument in "$@"; do
  [[ "$argument" == -d ]] && directory_install=true
done
if [[ "$directory_install" == true ]]; then
  mkdir -p -- "$destination"
  chmod 0750 "$destination"
  exit 0
fi
source_index=$(($# - 1))
source_path="${!source_index}"
if [[ "${destination##*/}" == "${FAKE_FAIL_DESTINATION:-}" ]]; then
  exit 78
fi
cp -- "$source_path" "$destination"
chmod 0640 "$destination"
""",
        encoding="utf-8",
    )
    fake_install.chmod(0o755)

    state_dir = tmp_path / "root-owned-sandbox-state"
    target_dir = state_dir / "https/certs"
    target_dir.mkdir(parents=True)
    target_dir.chmod(0o700)
    live_dir = tmp_path / "letsencrypt/live/factorymind-sandbox.ddnsgeek.com"
    live_dir.mkdir(parents=True)
    fullchain = live_dir / "fullchain.pem"
    private_key = live_dir / "privkey.pem"
    fullchain.write_text("sandbox-fullchain-material\n", encoding="utf-8")
    private_key.write_text("never-print-private-key-material\n", encoding="utf-8")
    probe = tmp_path / "certificate-stage-probe.sh"
    probe.write_text(
        f"""#!/usr/bin/env bash
set -Eeuo pipefail
DRY_RUN=false
STATE_DIR={str(state_dir)!r}
run() {{ "$@"; }}
quote_command() {{ printf 'dry-run only\n'; }}
{_certificate_stage_function()}
for ((attempt = 0; attempt < {repetitions}; attempt++)); do
  stage_sandbox_certificate {str(live_dir)!r}
done
""",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PATH"] = os.pathsep.join((str(fake_bin), "/usr/bin", "/bin"))
    environment["FAKE_COMMAND_LOG"] = str(command_log)
    environment["FAKE_FAIL_DESTINATION"] = fail_destination
    result = subprocess.run(
        ["bash", str(probe)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    return result, {
        "command_log": command_log,
        "fullchain": target_dir / "fullchain.pem",
        "private_key": target_dir / "privkey.pem",
        "target_dir": target_dir,
    }


def _run_ingress_probe(
    tmp_path: Path,
    *,
    action: str = "activate",
    repetitions: int = 1,
    fail_step: str = "",
    missing_certificate: bool = False,
    previous_config: str = "",
) -> tuple[subprocess.CompletedProcess[str], dict[str, Path]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    command_log = tmp_path / "commands.log"
    edge_state = tmp_path / "production-edge-connected"
    nginx_test_count = tmp_path / "nginx-test-count"
    reload_count = tmp_path / "reload-count"
    state_dir = tmp_path / ".deployment/paymob-sandbox"
    include_dir = tmp_path / ".deployment/https/sandbox-conf.d"
    certificate_dir = state_dir / "https/certs"
    production_certificate_dir = tmp_path / ".deployment/https/certs"
    include_dir.mkdir(parents=True)
    certificate_dir.mkdir(parents=True)
    production_certificate_dir.mkdir(parents=True)
    (certificate_dir / "fullchain.pem").write_text(
        "sandbox-fullchain-never-print\n", encoding="utf-8"
    )
    (certificate_dir / "privkey.pem").write_text(
        "sandbox-private-key-never-print\n", encoding="utf-8"
    )
    if missing_certificate:
        (certificate_dir / "privkey.pem").unlink()
    production_default = tmp_path / "production-default.conf"
    production_default.write_text("production-default-unchanged\n", encoding="utf-8")
    production_fullchain = production_certificate_dir / "fullchain.pem"
    production_private_key = production_certificate_dir / "privkey.pem"
    production_fullchain.write_text(
        "production-fullchain-unchanged\n", encoding="utf-8"
    )
    production_private_key.write_text(
        "production-private-key-never-print\n", encoding="utf-8"
    )
    managed_config = include_dir / "paymob-sandbox.conf"
    ingress_marker = state_dir / "ingress-active"
    if previous_config:
        managed_config.write_text(previous_config, encoding="utf-8")
    if action == "deactivate":
        managed_config.write_text(
            _text(_NGINX).replace(
                "__SANDBOX_DOMAIN__", "factorymind-sandbox.ddnsgeek.com"
            ),
            encoding="utf-8",
        )
        ingress_marker.parent.mkdir(parents=True, exist_ok=True)
        ingress_marker.touch()
        edge_state.touch()
        (include_dir / "unrelated.conf").write_text(
            "# unrelated managed include\n", encoding="utf-8"
        )

    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text(
        """#!/usr/bin/env bash
set -eu
printf 'sudo' >>"$FAKE_COMMAND_LOG"
printf ' %q' "$@" >>"$FAKE_COMMAND_LOG"
printf '\n' >>"$FAKE_COMMAND_LOG"
"$@"
""",
        encoding="utf-8",
    )
    fake_sudo.chmod(0o755)
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -eu
printf 'docker' >>"$FAKE_COMMAND_LOG"
printf ' %q' "$@" >>"$FAKE_COMMAND_LOG"
printf '\n' >>"$FAKE_COMMAND_LOG"
command_name="$1"
shift
case "$command_name" in
  network)
    operation="$1"
    shift
    case "$operation" in
      connect) touch "$FAKE_EDGE_STATE" ;;
      disconnect) rm -f -- "$FAKE_EDGE_STATE" ;;
      *) exit 2 ;;
    esac
    ;;
  exec)
    container="$1"
    shift
    [[ "$container" == production-proxy ]] || exit 2
    if [[ "$1" == /bin/sh ]]; then
      [[ "${FAIL_STEP:-}" != upstream ]]
      exit
    fi
    [[ "$1" == nginx ]] || exit 2
    shift
    case "$1" in
      -t)
        if [[ " $* " == *" -c "* ]]; then
          grep -Fq 'access_log /dev/null;' "$FAKE_VALIDATION_CONFIG"
          for temporary_path in client_body proxy fastcgi uwsgi scgi; do
            grep -Eq "${temporary_path}_temp_path /tmp/paymob-sandbox-.+-temp;" \
              "$FAKE_VALIDATION_CONFIG"
          done
          ! grep -Fq '/var/cache/nginx' "$FAKE_VALIDATION_CONFIG"
          [[ "${FAIL_STEP:-}" != candidate_validation ]]
          exit
        fi
        count=0
        [[ ! -f "$FAKE_NGINX_TEST_COUNT" ]] || count="$(cat "$FAKE_NGINX_TEST_COUNT")"
        count=$((count + 1))
        printf '%s\n' "$count" >"$FAKE_NGINX_TEST_COUNT"
        if [[ "${FAIL_STEP:-}" == active_validation && "$count" -eq 1 ]]; then
          exit 1
        fi
        ;;
      -s)
        count=0
        [[ ! -f "$FAKE_RELOAD_COUNT" ]] || count="$(cat "$FAKE_RELOAD_COUNT")"
        count=$((count + 1))
        printf '%s\n' "$count" >"$FAKE_RELOAD_COUNT"
        if [[ "${FAIL_STEP:-}" == reload && "$count" -eq 1 ]]; then
          exit 1
        fi
        ;;
      -T)
        printf '# configuration file /etc/nginx/conf.d/default.conf:\n'
        cat "$FAKE_PRODUCTION_DEFAULT"
        if [[ "${FAIL_STEP:-}" != active_config_missing ]] \
          && [[ -f "$FAKE_MANAGED_CONFIG" ]]; then
          printf '# configuration file /etc/nginx/sandbox-conf.d/paymob-sandbox.conf:\n'
          cat "$FAKE_MANAGED_CONFIG"
        fi
        ;;
      *) exit 2 ;;
    esac
    ;;
  *) exit 2 ;;
esac
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    probe = tmp_path / "ingress-probe.sh"
    confirmation = (
        "ACTIVATE-SANDBOX-INGRESS"
        if action == "activate"
        else "DEACTIVATE-SANDBOX-INGRESS"
    )
    probe.write_text(
        f"""#!/usr/bin/env bash
set -Eeuo pipefail
DRY_RUN=false
CONFIRMATION={confirmation!r}
DOCKER_BIN={str(fake_docker)!r}
PRODUCTION_PROXY_ID=production-proxy
SANDBOX_DOMAIN=factorymind-sandbox.ddnsgeek.com
EDGE_NETWORK=factorymind-paymob-sandbox-edge
EDGE_ALIAS=factorymind-paymob-sandbox-upstream
STATE_DIR={str(state_dir)!r}
GENERATED_NGINX={str(state_dir / "nginx/sandbox-vhost.conf")!r}
NGINX_INCLUDE_SOURCE={str(include_dir)!r}
NGINX_INCLUDE_DESTINATION=/etc/nginx/sandbox-conf.d
NGINX_MANAGED_FILENAME=paymob-sandbox.conf
NGINX_CERT_DESTINATION=/etc/nginx/paymob-sandbox-certs
INGRESS_MARKER={str(ingress_marker)!r}
TEMPLATE={str(_NGINX)!r}
require_confirmation() {{ [[ "$CONFIRMATION" == "$1" ]]; }}
require_environment() {{ :; }}
verify_isolation() {{
  printf 'verify-isolation %s\n' "$*" >>"$FAKE_COMMAND_LOG"
  [[ "${{FAIL_STEP:-}}" != isolation ]]
}}
require_sandbox_services_ready() {{
  printf 'sandbox-services-ready\n' >>"$FAKE_COMMAND_LOG"
  [[ "${{FAIL_STEP:-}}" != health ]]
}}
sandbox_proxy_id() {{ printf 'sandbox-proxy'; }}
ensure_edge_network() {{ :; }}
require_managed_ingress_layout() {{
  printf '%s\n%s\n' {str(include_dir)!r} {str(certificate_dir)!r}
}}
network_contains_container() {{
  if [[ "$2" == sandbox-proxy ]]; then
    return 0
  fi
  [[ -f "$FAKE_EDGE_STATE" ]]
}}
preflight() {{ :; }}
quote_command() {{ :; }}
{_shell_function("render_nginx", "require_managed_ingress_layout")}
{_shell_function("verify_active_sandbox_nginx", "verify_sandbox_nginx_absent")}
{_shell_function("verify_sandbox_nginx_absent", "verify_local_sandbox_tls")}
verify_local_sandbox_tls() {{
  printf 'local-sni-validation\n' >>"$FAKE_COMMAND_LOG"
  [[ "${{FAIL_STEP:-}}" != sni ]]
}}
{_shell_function("activate_ingress", "refresh_certificate")}
{_shell_function("deactivate_ingress", "status")}
for ((attempt = 0; attempt < {repetitions}; attempt++)); do
  {("activate_ingress" if action == "activate" else "deactivate_ingress")}
done
""",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PATH"] = os.pathsep.join((str(fake_bin), "/usr/bin", "/bin"))
    environment["FAIL_STEP"] = fail_step
    environment["FAKE_COMMAND_LOG"] = str(command_log)
    environment["FAKE_EDGE_STATE"] = str(edge_state)
    environment["FAKE_MANAGED_CONFIG"] = str(managed_config)
    environment["FAKE_VALIDATION_CONFIG"] = str(
        include_dir / "paymob-sandbox.conf.validation"
    )
    environment["FAKE_NGINX_TEST_COUNT"] = str(nginx_test_count)
    environment["FAKE_RELOAD_COUNT"] = str(reload_count)
    environment["FAKE_PRODUCTION_DEFAULT"] = str(production_default)
    result = subprocess.run(
        ["bash", str(probe)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    return result, {
        "command_log": command_log,
        "edge_state": edge_state,
        "include_dir": include_dir,
        "ingress_marker": ingress_marker,
        "managed_config": managed_config,
        "production_default": production_default,
        "production_fullchain": production_fullchain,
        "production_private_key": production_private_key,
        "reload_count": reload_count,
    }


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
        "PAYMOB_WEBHOOK_URL",
        "PAYMENT_SUCCESS_URL",
        "PAYMENT_FAILURE_URL",
        "BILLING_COMMERCIAL_MODEL",
    ):
        assert ":?" in environment[variable]
    assert environment["PAYMOB_EXPECTED_CALLBACK_OWNER"] == (
        "${PAYMOB_EXPECTED_CALLBACK_OWNER:-}"
    )
    assert environment["PAYMOB_MERCHANT_ID"] == "${PAYMOB_MERCHANT_ID:-}"
    assert environment["ENVIRONMENT"] == "staging"
    assert environment["APP_ENV"] == "staging"


def test_production_payment_provider_is_hard_disabled_without_credentials() -> None:
    compose = _yaml(_PRODUCTION_COMPOSE)
    for service_name in ("backend", "training-worker"):
        environment = compose["services"][service_name]["environment"]
        assert environment["PAYMENT_PROVIDER"] == "disabled"
        assert environment["PAYMENT_SANDBOX_MODE"] == "true"
        for secret_name in (
            "PAYMOB_API_KEY",
            "PAYMOB_SECRET_KEY",
            "PAYMOB_PUBLIC_KEY",
            "PAYMOB_HMAC_SECRET",
            "PAYMOB_INTEGRATION_ID",
            "PAYMOB_EXPECTED_CALLBACK_OWNER",
            "PAYMOB_MERCHANT_ID",
        ):
            assert environment[secret_name] == ""

    production_template = _text(_PRODUCTION_ENV_TEMPLATE)
    example = _text(_ENV_EXAMPLE)
    assert "PAYMENT_PROVIDER=disabled" in production_template
    assert "PAYMENT_SANDBOX_MODE=true" in production_template
    assert "PAYMENT_PROVIDER=paymob" not in production_template
    assert "Production remains PAYMENT_PROVIDER=disabled" in example


def test_callback_owner_bootstrap_requires_consistent_authenticated_evidence() -> None:
    module = _owner_bootstrap_module()
    evidence = [
        _valid_owner_evidence(module, "first"),
        _valid_owner_evidence(module, "second"),
    ]

    assert (
        module.validated_callback_owner(evidence, expected_integration_id=123456)
        == "700001"
    )

    with pytest.raises(module.CallbackOwnerEvidenceError, match="owners disagree"):
        module.validated_callback_owner(
            [evidence[0], _valid_owner_evidence(module, "other", "700002")],
            expected_integration_id=123456,
        )
    with pytest.raises(module.CallbackOwnerEvidenceError, match="At least two"):
        module.validated_callback_owner(evidence[:1], expected_integration_id=123456)


def test_callback_owner_bootstrap_rejects_unauthenticated_or_mismatched_evidence() -> (
    None
):
    module = _owner_bootstrap_module()
    valid = _valid_owner_evidence(module, "valid")
    invalid = _valid_owner_evidence(module, "invalid")
    invalid = replace(
        invalid,
        validation_outcome="quarantined_invalid_hmac",
        safe_validation_outcome="quarantined_invalid_hmac",
    )
    with pytest.raises(
        module.CallbackOwnerEvidenceError, match="authenticated wrong-owner"
    ):
        module.validated_callback_owner(
            [valid, invalid], expected_integration_id=123456
        )

    wrong_quote = _valid_owner_evidence(module, "wrong-quote")
    wrong_quote = replace(wrong_quote, payment_amount_minor=1)
    with pytest.raises(
        module.CallbackOwnerEvidenceError, match="payment binding is inconsistent"
    ):
        module.validated_callback_owner(
            [valid, wrong_quote], expected_integration_id=123456
        )


def test_callback_owner_bootstrap_refuses_production_runtime() -> None:
    module = _owner_bootstrap_module()
    with pytest.raises(module.CallbackOwnerEvidenceError, match="Production"):
        module.validate_sandbox_runtime(
            environment="production",
            app_environment="production",
            payment_provider="disabled",
            sandbox_mode=False,
            database_name="production",
        )


def test_callback_owner_bootstrap_updates_only_canonical_sandbox_key() -> None:
    script = _text(_SCRIPT)
    helper = _text(_OWNER_BOOTSTRAP)
    function = script.split("bootstrap_callback_owner()", maxsplit=1)[1].split(
        "mount_source_for_destination()", maxsplit=1
    )[0]

    assert "require_confirmation BOOTSTRAP-SANDBOX-CALLBACK-OWNER" in function
    assert "sandbox_service_id backend" in function
    assert "com.factorymind.environment" in function
    assert "PAYMOB_EXPECTED_CALLBACK_OWNER=" in function
    assert "PAYMOB_MERCHANT_ID=" not in function
    assert "configure" not in function
    assert "replay" not in function.lower()
    assert ".env.production" not in function
    assert 'chmod 600 "$owner_next_file"' in function
    assert 'mv -f -- "$owner_next_file" "$ENV_FILE"' in function
    assert '"$CALLBACK_OWNER_CONTAINER_FILE" >"$evidence_copy"' in function
    assert '"$DOCKER_BIN" cp' not in function
    assert "CALLBACK_OWNER_BACKEND_ID" in script
    assert "print(owner" not in helper
    assert "factorymind_paymob_sandbox" in helper


def test_shared_edge_uses_an_isolated_include_and_certificate_mount() -> None:
    nginx = _text(_NGINX)
    production_nginx = _text(_PRODUCTION_NGINX)
    https_compose = _yaml(_HTTPS_COMPOSE)
    mounts = https_compose["services"]["reverse-proxy"]["volumes"]

    assert "__PRODUCTION_DOMAIN__" not in nginx
    assert "include /etc/nginx/routes.inc;" not in nginx
    assert "include /etc/nginx/sandbox-conf.d/*.conf;" in production_nginx
    assert "/etc/nginx/paymob-sandbox-certs/fullchain.pem" in nginx
    assert "/etc/nginx/paymob-sandbox-certs/privkey.pem" in nginx
    assert "proxy_pass http://factorymind-paymob-sandbox-upstream:8080;" in nginx
    assert nginx.count("server_name __SANDBOX_DOMAIN__;") == 2
    assert any("/etc/nginx/sandbox-conf.d:ro" in mount for mount in mounts)
    assert any("/etc/nginx/paymob-sandbox-certs:ro" in mount for mount in mounts)
    for header in (
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
        "Permissions-Policy",
    ):
        assert nginx.count(f"add_header {header} ") == 1
        assert nginx.count(f"proxy_hide_header {header};") == 1


def test_sandbox_certificate_owner_matches_unprivileged_nginx_runtime() -> None:
    dockerfile = _text(_REVERSE_PROXY_DOCKERFILE)
    prepare_https = _text(_PREPARE_HTTPS)

    assert "FROM nginxinc/nginx-unprivileged:1.28.0-alpine" in dockerfile
    assert "USER 101:101" in dockerfile
    assert "--user 101:101" in prepare_https
    assert "chown 101:101 /target/fullchain.pem.new /target/privkey.pem.new" in (
        prepare_https
    )
    assert "chown 101:101 /target" in prepare_https


def test_root_owned_sandbox_certificate_path_is_staged_privileged_and_idempotent(
    tmp_path: Path,
) -> None:
    result, paths = _run_certificate_stage_probe(tmp_path, repetitions=2)
    command_log = _text(paths["command_log"])
    directory_commands = [
        line for line in command_log.splitlines() if line.startswith("sudo install -d ")
    ]
    certificate_commands = [
        line
        for line in command_log.splitlines()
        if line.startswith("sudo install -o 101 -g 101 -m 0640 ")
    ]

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert len(directory_commands) == 2
    assert all("-o 101 -g 101 -m 0750" in line for line in directory_commands)
    assert len(certificate_commands) == 4
    assert sum("fullchain.pem" in line for line in certificate_commands) == 2
    assert sum("privkey.pem" in line for line in certificate_commands) == 2
    assert stat.S_IMODE(paths["target_dir"].stat().st_mode) == 0o750
    assert stat.S_IMODE(paths["fullchain"].stat().st_mode) == 0o640
    assert stat.S_IMODE(paths["private_key"].stat().st_mode) == 0o640
    assert _text(paths["fullchain"]) == "sandbox-fullchain-material\n"
    assert _text(paths["private_key"]) == "never-print-private-key-material\n"
    assert "never-print-private-key-material" not in result.stdout + result.stderr


def test_failed_sandbox_certificate_stage_is_closed_and_production_is_untouched(
    tmp_path: Path,
) -> None:
    production_dir = tmp_path / "production-certs"
    production_dir.mkdir()
    production_fullchain = production_dir / "fullchain.pem"
    production_private_key = production_dir / "privkey.pem"
    production_fullchain.write_text("production-fullchain\n", encoding="utf-8")
    production_private_key.write_text(
        "production-private-key-never-print\n", encoding="utf-8"
    )
    production_fullchain.chmod(0o640)
    production_private_key.chmod(0o640)

    result, paths = _run_certificate_stage_probe(
        tmp_path / "sandbox-stage",
        fail_destination="privkey.pem",
    )
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert not paths["private_key"].exists()
    assert _text(production_fullchain) == "production-fullchain\n"
    assert _text(production_private_key) == "production-private-key-never-print\n"
    assert stat.S_IMODE(production_fullchain.stat().st_mode) == 0o640
    assert stat.S_IMODE(production_private_key.stat().st_mode) == 0o640
    assert "never-print-private-key-material" not in output
    assert "production-private-key-never-print" not in output


def test_sandbox_certificate_staging_is_narrow_and_refresh_remains_rollback_safe() -> (
    None
):
    script = _text(_SCRIPT)
    stage = _certificate_stage_function()
    refresh = script.split("refresh_certificate()", maxsplit=1)[1].split(
        "deactivate_ingress()", maxsplit=1
    )[0]

    assert "chown" not in stage
    assert "chown -R" not in script
    assert "rm " not in stage
    assert ".deployment/https/certs" not in stage
    assert (
        script.count(
            'stage_sandbox_certificate "/etc/letsencrypt/live/$SANDBOX_DOMAIN"'
        )
        == 2
    )
    assert refresh.index("trap rollback_certificate_refresh ERR") < refresh.index(
        'stage_sandbox_certificate "/etc/letsencrypt/live/$SANDBOX_DOMAIN"'
    )
    assert refresh.count('"$certificate_backup/fullchain.pem"') >= 2
    assert refresh.count('"$certificate_backup/privkey.pem"') >= 2


def test_ingress_activation_never_replaces_production_configuration() -> None:
    script = _text(_SCRIPT)
    activation = script.split("activate_ingress()", maxsplit=1)[1].split(
        "refresh_certificate()", maxsplit=1
    )[0]
    deactivation = script.split("deactivate_ingress()", maxsplit=1)[1].split(
        "status()", maxsplit=1
    )[0]
    refresh = script.split("refresh_certificate()", maxsplit=1)[1].split(
        "deactivate_ingress()", maxsplit=1
    )[0]

    assert 'NGINX_INCLUDE_DESTINATION="/etc/nginx/sandbox-conf.d"' in script
    assert 'NGINX_MANAGED_FILENAME="paymob-sandbox.conf"' in script
    assert "require_managed_ingress_layout" in activation
    assert 'candidate_config="$managed_config.next"' in activation
    assert 'sudo mv -- "$candidate_config" "$managed_config"' in activation
    assert 'sudo rm -f -- "$managed_config"' in activation
    assert "nginx -t" in activation
    assert "nginx -s reload" in activation
    assert activation.index("nginx -t") < activation.index("nginx -s reload")
    assert "/etc/nginx/conf.d/default.conf" not in activation
    assert "NGINX_BACKUP" not in script
    assert "verify_active_sandbox_nginx" in activation
    assert "verify_local_sandbox_tls" in activation
    assert "rollback_activation" in activation
    assert 'sudo mv -f -- "$backup_config" "$managed_config"' in activation
    assert 'sudo rm -- "$managed_config"' in deactivation
    assert "/etc/nginx/conf.d/default.conf" not in deactivation
    assert "certificate-backup" in refresh
    assert "rollback_certificate_refresh" in refresh
    assert "trap rollback_certificate_refresh ERR" in refresh


def test_ingress_activation_installs_exact_managed_sandbox_vhost(
    tmp_path: Path,
) -> None:
    result, paths = _run_ingress_probe(tmp_path)
    managed_config = _text(paths["managed_config"])
    output = result.stdout + result.stderr

    assert result.returncode == 0
    assert sorted(path.name for path in paths["include_dir"].iterdir()) == [
        "paymob-sandbox.conf"
    ]
    assert "server_name factorymind-sandbox.ddnsgeek.com;" in managed_config
    assert (
        "ssl_certificate /etc/nginx/paymob-sandbox-certs/fullchain.pem;"
        in managed_config
    )
    assert (
        "ssl_certificate_key /etc/nginx/paymob-sandbox-certs/privkey.pem;"
        in managed_config
    )
    assert (
        "proxy_pass http://factorymind-paymob-sandbox-upstream:8080;" in managed_config
    )
    assert "/etc/letsencrypt/" not in managed_config
    assert "proxy_pass http://backend" not in managed_config
    assert "proxy_pass http://frontend" not in managed_config
    assert paths["ingress_marker"].is_file()
    assert "sandbox-private-key-never-print" not in output
    assert "production-private-key-never-print" not in output


def test_ingress_activation_checks_isolation_health_dns_nginx_and_sni(
    tmp_path: Path,
) -> None:
    result, paths = _run_ingress_probe(tmp_path)
    command_log = _text(paths["command_log"])

    assert result.returncode == 0
    assert "verify-isolation false" in command_log
    assert "sandbox-services-ready" in command_log
    assert "getent\\ hosts" in command_log
    assert "factorymind-paymob-sandbox-upstream" in command_log
    assert "paymob-sandbox.conf.validation" in command_log
    assert "nginx -t" in command_log
    assert "nginx -s reload" in command_log
    assert "nginx -T" in command_log
    assert "local-sni-validation" in command_log


def test_candidate_nginx_validation_uses_only_writable_tmpfs_paths() -> None:
    script = _text(_SCRIPT)
    activation = script.split("activate_ingress()", maxsplit=1)[1].split(
        "refresh_certificate()", maxsplit=1
    )[0]
    reverse_proxy = _yaml(_PRODUCTION_COMPOSE)["services"]["reverse-proxy"]

    assert reverse_proxy["read_only"] is True
    assert any(mount.startswith("/tmp:rw,") for mount in reverse_proxy["tmpfs"])
    assert "pid /tmp/paymob-sandbox-validation.pid;" in activation
    assert "access_log /dev/null;" in activation
    for directive in (
        "client_body_temp_path /tmp/paymob-sandbox-client-temp;",
        "proxy_temp_path /tmp/paymob-sandbox-proxy-temp;",
        "fastcgi_temp_path /tmp/paymob-sandbox-fastcgi-temp;",
        "uwsgi_temp_path /tmp/paymob-sandbox-uwsgi-temp;",
        "scgi_temp_path /tmp/paymob-sandbox-scgi-temp;",
    ):
        assert directive in activation
    assert "/var/cache/nginx" not in activation
    assert "chmod -R" not in script
    assert "chown -R" not in script


def test_ingress_activation_fails_before_install_for_missing_cert_or_isolation(
    tmp_path: Path,
) -> None:
    missing_certificate, missing_paths = _run_ingress_probe(
        tmp_path / "missing-certificate",
        missing_certificate=True,
    )
    failed_isolation, isolation_paths = _run_ingress_probe(
        tmp_path / "failed-isolation",
        fail_step="isolation",
    )

    assert missing_certificate.returncode != 0
    assert failed_isolation.returncode != 0
    assert not missing_paths["managed_config"].exists()
    assert not isolation_paths["managed_config"].exists()
    assert "Issue and stage the sandbox certificate" in missing_certificate.stderr
    assert "nginx -s reload" not in _text(isolation_paths["command_log"])


def test_ingress_activation_rolls_back_new_config_for_any_validation_failure(
    tmp_path: Path,
) -> None:
    for fail_step in (
        "candidate_validation",
        "active_validation",
        "reload",
        "active_config_missing",
        "sni",
    ):
        result, paths = _run_ingress_probe(
            tmp_path / fail_step,
            fail_step=fail_step,
        )

        assert result.returncode != 0
        assert not paths["managed_config"].exists()
        assert not paths["ingress_marker"].exists()
        assert "rollback validation passed" in result.stderr


def test_ingress_activation_restores_previous_config_after_failed_update(
    tmp_path: Path,
) -> None:
    previous_config = "# previous Sandbox managed config\n"
    result, paths = _run_ingress_probe(
        tmp_path,
        fail_step="active_validation",
        previous_config=previous_config,
    )

    assert result.returncode != 0
    assert _text(paths["managed_config"]) == previous_config
    assert "rollback validation passed" in result.stderr


def test_ingress_activation_is_idempotent_and_never_changes_production_files(
    tmp_path: Path,
) -> None:
    result, paths = _run_ingress_probe(tmp_path, repetitions=2)
    output = result.stdout + result.stderr

    assert result.returncode == 0
    assert _text(paths["reload_count"]) == "2\n"
    assert _text(paths["production_default"]) == "production-default-unchanged\n"
    assert _text(paths["production_fullchain"]) == ("production-fullchain-unchanged\n")
    assert _text(paths["production_private_key"]) == (
        "production-private-key-never-print\n"
    )
    assert "sandbox-private-key-never-print" not in output
    assert "production-private-key-never-print" not in output


def test_ingress_deactivation_removes_only_managed_config(tmp_path: Path) -> None:
    result, paths = _run_ingress_probe(tmp_path, action="deactivate")

    assert result.returncode == 0
    assert not paths["managed_config"].exists()
    assert not paths["ingress_marker"].exists()
    assert (paths["include_dir"] / "unrelated.conf").is_file()
    assert not paths["edge_state"].exists()
    assert _text(paths["production_default"]) == "production-default-unchanged\n"
    assert _text(paths["production_private_key"]) == (
        "production-private-key-never-print\n"
    )


def test_ingress_deactivation_restores_only_managed_config_on_failure(
    tmp_path: Path,
) -> None:
    result, paths = _run_ingress_probe(
        tmp_path,
        action="deactivate",
        fail_step="active_validation",
    )

    assert result.returncode != 0
    assert paths["managed_config"].is_file()
    assert paths["ingress_marker"].is_file()
    assert paths["edge_state"].is_file()
    assert (paths["include_dir"] / "unrelated.conf").is_file()
    assert "rollback validation passed" in result.stderr


def test_https_preparation_precreates_and_validates_managed_mounts() -> None:
    prepare = _text(_PREPARE_HTTPS)

    assert 'generated_sandbox_config_dir="$generated_dir/sandbox-conf.d"' in prepare
    assert ".deployment/paymob-sandbox/https/certs" in prepare
    assert "/etc/nginx/sandbox-conf.d:ro" in prepare
    assert "/etc/nginx/paymob-sandbox-certs:ro" in prepare


def test_runtime_verifier_covers_data_plane_and_namespace_isolation() -> None:
    script = _text(_SCRIPT)
    verifier = script.split("verify_isolation()", maxsplit=1)[1].split(
        "stop_sandbox()", maxsplit=1
    )[0]

    for contract in (
        "assert_redis_runtime_isolation",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "DATABASE_URL",
        "SECRET_KEY",
        "BILLING_WEBHOOK_QUEUE_NAME",
        "EMAIL_QUEUE_NAME",
        "TRAINING_QUEUE_NAME",
        "DATASET_QUEUE_NAME",
        "RAG_QUEUE_NAME",
        "MONITORING_QUEUE_NAME",
        "assert_no_shared_networks",
        "assert_proxy_network_boundary",
        'assert_no_shared_networks "$PRODUCTION_PROXY_ID" "$sandbox_container"',
        'assert_no_shared_networks "$production_container" "$sandbox_proxy"',
        "assert_host_port_owner 80",
        "assert_host_port_owner 443",
    ):
        assert contract in verifier
    assert 'network_contains_container "$EDGE_NETWORK" "$sandbox_container"' in verifier
    assert (
        'assert_distinct_environment_value "$PRODUCTION_BACKEND_ID" '
        '"$sandbox_backend" REDIS_URL'
    ) not in verifier
    assert 'os.environ.get("REDIS_URL", "")' in _redis_functions()


def test_identical_redis_urls_are_accepted_for_distinct_runtime_identities(
    tmp_path: Path,
) -> None:
    state = _redis_isolation_state()

    result = _run_redis_isolation_probe(tmp_path, state)

    assert state["urls"]["production-backend"] == state["urls"]["sandbox-backend"]
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_shared_redis_container_or_ip_is_rejected(tmp_path: Path) -> None:
    shared_container = _run_redis_isolation_probe(
        tmp_path / "container",
        _redis_isolation_state(),
        sandbox_redis="production-redis",
    )
    shared_ip_state = _redis_isolation_state()
    shared_ip_state["resolved_ips"]["sandbox-backend"] = "172.22.0.2"
    shared_ip_state["containers"]["sandbox-redis"]["networks"][
        "factorymind-paymob-sandbox_data"
    ]["ip"] = "172.22.0.2"
    shared_ip = _run_redis_isolation_probe(tmp_path / "ip", shared_ip_state)

    assert shared_container.returncode == 1
    assert shared_ip.returncode == 1


def test_shared_redis_network_is_rejected(tmp_path: Path) -> None:
    state = _redis_isolation_state()
    for container in ("production-redis", "sandbox-redis"):
        state["containers"][container]["networks"]["shared-data"] = {
            "id": "shared-data-network-id",
            "ip": "172.30.0.2",
        }

    result = _run_redis_isolation_probe(tmp_path, state)

    assert result.returncode == 1
    assert "share a Docker network" in result.stderr


def test_shared_redis_volume_is_rejected(tmp_path: Path) -> None:
    state = _redis_isolation_state()
    state["containers"]["sandbox-redis"]["volume"] = (
        "ai-manufacturing-platform_redis-data"
    )

    result = _run_redis_isolation_probe(tmp_path, state)

    assert result.returncode == 1
    assert "Redis storage is not isolated" in result.stderr


def test_sandbox_redis_on_production_data_network_is_rejected(
    tmp_path: Path,
) -> None:
    state = _redis_isolation_state()
    state["containers"]["sandbox-redis"]["networks"][
        "ai-manufacturing-platform_data"
    ] = {"id": "production-data-network-id", "ip": "172.22.0.9"}

    result = _run_redis_isolation_probe(tmp_path, state)

    assert result.returncode == 1
    assert "Sandbox Redis is attached to a production" in result.stderr


def test_production_redis_on_sandbox_data_network_is_rejected(
    tmp_path: Path,
) -> None:
    state = _redis_isolation_state()
    state["containers"]["production-redis"]["networks"][
        "factorymind-paymob-sandbox_data"
    ] = {"id": "sandbox-data-network-id", "ip": "172.28.0.9"}

    result = _run_redis_isolation_probe(tmp_path, state)

    assert result.returncode == 1
    assert "Production Redis is attached to a Sandbox" in result.stderr


def test_missing_or_malformed_redis_url_is_rejected(tmp_path: Path) -> None:
    invalid_urls = (
        None,
        "not-a-redis-url",
        "redis://redis/db",
        "redis://:6379/0",
        "redis://redis:6379/not-a-database-number",
    )
    for index, invalid_url in enumerate(invalid_urls):
        state = _redis_isolation_state()
        state["urls"]["sandbox-backend"] = invalid_url

        result = _run_redis_isolation_probe(tmp_path / str(index), state)

        assert result.returncode == 1
        assert "Sandbox REDIS_URL is missing, malformed" in result.stderr


def test_unverifiable_redis_dns_or_container_identity_is_rejected(
    tmp_path: Path,
) -> None:
    unresolved_state = _redis_isolation_state()
    unresolved_state["resolved_ips"]["sandbox-backend"] = None
    wrong_target_state = _redis_isolation_state()
    wrong_target_state["resolved_ips"]["sandbox-backend"] = "172.28.0.99"
    wrong_network_state = _redis_isolation_state()
    wrong_network_state["containers"]["sandbox-redis"]["networks"][
        "factorymind-paymob-sandbox_data"
    ]["id"] = "ambiguous-network-id"

    unresolved = _run_redis_isolation_probe(tmp_path / "dns", unresolved_state)
    wrong_target = _run_redis_isolation_probe(tmp_path / "identity", wrong_target_state)
    wrong_network = _run_redis_isolation_probe(
        tmp_path / "network", wrong_network_state
    )

    assert unresolved.returncode == 1
    assert wrong_target.returncode == 1
    assert wrong_network.returncode == 1
    assert "does not resolve to the expected Redis container" in wrong_target.stderr
    assert "expected data network ID" in wrong_network.stderr


def test_redis_identity_verifier_never_prints_url_credentials(
    tmp_path: Path,
) -> None:
    state = _redis_isolation_state()
    state["urls"]["production-backend"] = (
        "redis://production:production-password@redis:6379/0"
    )
    state["urls"]["sandbox-backend"] = "redis://sandbox:sandbox-password@redis:6379/0"
    state["resolved_ips"]["sandbox-backend"] = "172.28.0.99"

    result = _run_redis_isolation_probe(tmp_path, state)
    output = result.stdout + result.stderr

    assert result.returncode == 1
    assert "production-password" not in output
    assert "sandbox-password" not in output
    assert "redis://" not in output


def test_mutating_actions_are_separate_and_confirmation_guarded() -> None:
    script = _text(_SCRIPT)

    for token in (
        "BOOTSTRAP-SANDBOX-CALLBACK-OWNER",
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
    assert "bootstrap-owner) bootstrap_callback_owner" in script
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
    configure = script.split("configure()", maxsplit=1)[1].split(
        "ensure_edge_network()", maxsplit=1
    )[0]
    assert 'write_env "$next_file" PAYMOB_EXPECTED_CALLBACK_OWNER' in configure
    assert 'write_env "$next_file" PAYMOB_MERCHANT_ID' not in configure
    assert "set -x" not in script
    assert "Live Paymob key prefixes are forbidden" in script
    assert "Sandbox environment created without displaying secret values" in script


def test_file_mode_prefers_gnu_stat_and_returns_only_the_mode(tmp_path: Path) -> None:
    result = _run_permission_probe(tmp_path, implementation="gnu", mode="600")

    assert result.returncode == 0
    assert result.stdout == "600\n"
    assert result.stderr == ""
    assert "filesystem metadata" not in result.stdout


def test_file_mode_falls_back_to_bsd_stat_and_returns_only_the_mode(
    tmp_path: Path,
) -> None:
    result = _run_permission_probe(tmp_path, implementation="bsd", mode="600")

    assert result.returncode == 0
    assert result.stdout == "600\n"
    assert result.stderr == ""


def test_valid_mode_0600_sandbox_environment_is_accepted(tmp_path: Path) -> None:
    result = _run_permission_probe(
        tmp_path,
        implementation="gnu",
        mode="600",
        require_environment=True,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_non_0600_sandbox_environment_is_rejected(tmp_path: Path) -> None:
    result = _run_permission_probe(
        tmp_path,
        implementation="gnu",
        mode="640",
        require_environment=True,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Sandbox environment must have mode 0600.\n"


def test_permission_check_never_reads_or_displays_secret_content(
    tmp_path: Path,
) -> None:
    result = _run_permission_probe(
        tmp_path,
        implementation="gnu",
        mode="600",
        require_environment=True,
        file_permissions=0o000,
    )

    assert result.returncode == 0
    assert "never-display-this-secret" not in result.stdout
    assert "never-display-this-secret" not in result.stderr
    permission_functions = _permission_functions()
    assert "read_env_value" not in permission_functions
    assert "sed " not in permission_functions
    assert "cat " not in permission_functions


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
    sandbox_config_mount = tmp_path / "sandbox-conf.d"
    sandbox_certificate_mount = tmp_path / "sandbox-certs"
    sandbox_config_mount.mkdir()
    sandbox_certificate_mount.mkdir()
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
    elif [[ "$format" == *'if eq .Destination'* ]]; then
      if [[ "$format" == *'/etc/nginx/sandbox-conf.d'* ]]; then
        printf '%s\\n' "$FAKE_SANDBOX_CONFIG_MOUNT"
      elif [[ "$format" == *'/etc/nginx/paymob-sandbox-certs'* ]]; then
        printf '%s\\n' "$FAKE_SANDBOX_CERTIFICATE_MOUNT"
      fi
    elif [[ "$format" == *'.Mounts'* ]]; then
      case "$identifier" in
        proxy-id)
          printf '/etc/nginx/conf.d/default.conf\\n'
          printf '/etc/nginx/routes.inc\\n'
          printf '/etc/nginx/sandbox-conf.d\\n'
          printf '/etc/nginx/paymob-sandbox-certs\\n'
          ;;
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
    environment["FAKE_SANDBOX_CONFIG_MOUNT"] = str(sandbox_config_mount)
    environment["FAKE_SANDBOX_CERTIFICATE_MOUNT"] = str(sandbox_certificate_mount)

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
    assert "isolated ingress layout is present" in result.stdout
