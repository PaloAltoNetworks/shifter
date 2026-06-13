"""List, detail, and export views for the scenario editor."""

from __future__ import annotations

import logging

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from cms.scenario_editor.services import ScenarioEditorError, export_scenario_yaml
from cms.scenario_editor.view_support import (
    SCENARIO_CONTEXT_KEY,
    VIEW_RECOVERABLE_EXCEPTIONS,
    YAML_CONTENT_CONTEXT_KEY,
    render_error_message,
    render_not_found,
    render_unexpected_error,
)
from cms.scenarios.registry import get_scenario_detail, list_all_scenarios
from shared.auth import threat_research_required
from shared.log_sanitize import safe_log_value

logger = logging.getLogger(__name__)
IS_DEFAULT_CONTEXT_KEY = "is_default"
SCENARIOS_CONTEXT_KEY = "scenarios"


@threat_research_required
@require_GET
def scenario_list(request: HttpRequest) -> HttpResponse:
    """List all scenarios with metadata."""
    return render(request, "scenario_editor/list.html", {SCENARIOS_CONTEXT_KEY: list_all_scenarios(user=None)})


@threat_research_required
@require_GET
def scenario_detail_view(request: HttpRequest, scenario_id: str) -> HttpResponse:
    """View scenario details."""
    try:
        try:
            scenario = get_scenario_detail(scenario_id)
        except ValueError:
            return render_not_found(request, logger, "scenario_detail_view", scenario_id)

        return render(
            request,
            "scenario_editor/detail.html",
            {
                SCENARIO_CONTEXT_KEY: scenario,
                YAML_CONTENT_CONTEXT_KEY: export_scenario_yaml(scenario_id),
                IS_DEFAULT_CONTEXT_KEY: scenario.get(IS_DEFAULT_CONTEXT_KEY, False),
            },
        )
    except VIEW_RECOVERABLE_EXCEPTIONS:
        return render_unexpected_error(request, logger, "scenario_detail_view", scenario_id=scenario_id)


@threat_research_required
@require_GET
def scenario_export_view(request: HttpRequest, scenario_id: str) -> HttpResponse:
    """Download scenario as a YAML file."""
    try:
        try:
            yaml_content = export_scenario_yaml(scenario_id)
        except ScenarioEditorError as e:
            logger.warning("scenario_export_view: scenario not found scenario_id=%s", safe_log_value(scenario_id))
            return render_error_message(request, e.public_message, status=404)

        response = HttpResponse(yaml_content, content_type="text/yaml")
        response["Content-Disposition"] = f'attachment; filename="{scenario_id}.yaml"'
        return response
    except VIEW_RECOVERABLE_EXCEPTIONS:
        return render_unexpected_error(request, logger, "scenario_export_view", scenario_id=scenario_id)
