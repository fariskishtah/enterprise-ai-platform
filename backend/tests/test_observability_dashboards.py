"""Regression tests for the provisioned Loki dashboard query contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_DASHBOARD_PATHS = (
    _REPOSITORY_ROOT
    / "infrastructure/observability/grafana/dashboards/logs-overview.json",
    _REPOSITORY_ROOT
    / "infrastructure/observability/grafana/dashboards/request-correlation.json",
)
_LOKI_DATASOURCE = {"type": "loki", "uid": "loki"}


def _load_dashboard(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("dashboard_path", _DASHBOARD_PATHS)
def test_loki_dashboard_panels_have_bounded_all_safe_selectors(
    dashboard_path: Path,
) -> None:
    dashboard = _load_dashboard(dashboard_path)

    for panel in dashboard["panels"]:
        assert panel["datasource"] == _LOKI_DATASOURCE
        for target in panel["targets"]:
            expression = target["expr"]
            assert 'stream="docker"' in expression
            assert 'service=~"${service:regex}"' in expression
            assert 'environment=~"${environment:regex}"' in expression
            assert "service_name" not in expression


@pytest.mark.parametrize("dashboard_path", _DASHBOARD_PATHS)
def test_loki_label_variables_use_the_fixed_datasource_and_regex_all(
    dashboard_path: Path,
) -> None:
    dashboard = _load_dashboard(dashboard_path)
    variables = {
        variable["name"]: variable for variable in dashboard["templating"]["list"]
    }

    for name in ("service", "environment"):
        variable = variables[name]
        assert variable["datasource"] == _LOKI_DATASOURCE
        assert variable["query"]["type"] == 1
        assert variable["query"]["label"] == name
        assert variable["includeAll"] is True
        assert variable["allValue"] == ".*"
        assert variable["multi"] is True
        assert 'stream="docker"' in variable["query"]["stream"]

    environment_stream = variables["environment"]["query"]["stream"]
    assert 'service=~"${service:regex}"' in environment_stream


def test_logs_overview_stat_queries_render_zero_for_empty_results() -> None:
    dashboard = _load_dashboard(_DASHBOARD_PATHS[0])
    panels = {panel["title"]: panel for panel in dashboard["panels"]}

    for title in ("Errors", "Warnings"):
        assert panels[title]["targets"][0]["expr"].endswith(" or vector(0)")
