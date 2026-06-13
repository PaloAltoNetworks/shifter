"""YAML create/edit and validation views for the scenario editor."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, cast

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from cms.scenario_editor.services import (
    create_scenario_from_yaml_post,
    export_scenario_yaml,
    new_scenario_template_yaml,
    update_scenario_from_yaml_post,
    validate_yaml,
)
from cms.scenario_editor.view_support import render_unexpected_error, resolve_editable_scenario
from shared.auth import threat_research_required
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

YAML_CREATE_TEMPLATE = "scenario_editor/yaml_create.html"
YAML_EDITOR_TEMPLATE = "scenario_editor/yaml_editor.html"
DETAIL_ROUTE = "scenario_editor:detail"


def _yaml_editor_context(scenario: dict[str, Any], yaml_content: str, errors: list[str]) -> dict[str, Any]:
    return {"scenario": scenario, "yaml_content": yaml_content, "errors": errors}


def _handle_yaml_editor_post(request: HttpRequest, scenario_id: str, scenario: dict[str, Any]) -> HttpResponse:
    submitted_yaml = request.POST.get("yaml_content", "")
    errors = update_scenario_from_yaml_post(
        cast("User", request.user),
        scenario_id,
        submitted_yaml,
        fallback_name=scenario["name"],
        fallback_description=scenario["description"],
    )
    if errors:
        return render(request, YAML_EDITOR_TEMPLATE, _yaml_editor_context(scenario, submitted_yaml, errors))

    logger.info(
        "scenario_yaml_editor: updated scenario_id=%s by user_id=%s",
        safe_log_value(scenario_id),
        request.user.id,
    )
    messages.success(request, "Scenario updated from YAML successfully.")
    return redirect(DETAIL_ROUTE, scenario_id=scenario_id)


def _scenario_yaml_editor_impl(request: HttpRequest, scenario_id: str) -> HttpResponse:
    scenario, error = resolve_editable_scenario(
        request,
        scenario_id,
        default_message="Default scenarios cannot be edited via YAML. Clone it first.",
        logger=logger,
        log_name="scenario_yaml_editor",
    )
    if error is not None:
        return error
    assert scenario is not None
    if request.method == "GET":
        return render(
            request,
            YAML_EDITOR_TEMPLATE,
            _yaml_editor_context(scenario, export_scenario_yaml(scenario_id), []),
        )
    return _handle_yaml_editor_post(request, scenario_id, scenario)


@threat_research_required
@require_http_methods(["GET", "POST"])
def scenario_yaml_editor(request: HttpRequest, scenario_id: str) -> HttpResponse:
    """Free-form YAML editor for a scenario."""
    try:
        return _scenario_yaml_editor_impl(request, scenario_id)
    except Exception:
        return render_unexpected_error(request, logger, "scenario_yaml_editor", scenario_id=scenario_id)


def _handle_yaml_create_post(request: HttpRequest) -> HttpResponse:
    submitted_yaml = request.POST.get("yaml_content", "")
    fields, errors = create_scenario_from_yaml_post(cast("User", request.user), submitted_yaml)
    if errors:
        return render(request, YAML_CREATE_TEMPLATE, {"yaml_content": submitted_yaml, "errors": errors})

    assert fields is not None
    logger.info(
        "scenario_yaml_create: created scenario_id=%s by user_id=%s",
        safe_log_value(fields.scenario_id),
        request.user.id,
    )
    messages.success(request, f"Scenario '{fields.name}' created from YAML successfully.")
    return redirect(DETAIL_ROUTE, scenario_id=fields.scenario_id)


@threat_research_required
@require_http_methods(["GET", "POST"])
def scenario_yaml_create(request: HttpRequest) -> HttpResponse:
    """Create a new scenario from YAML content."""
    try:
        if request.method == "GET":
            return render(
                request,
                YAML_CREATE_TEMPLATE,
                {"yaml_content": new_scenario_template_yaml(), "errors": []},
            )
        return _handle_yaml_create_post(request)
    except Exception:
        return render_unexpected_error(request, logger, "scenario_yaml_create")


@threat_research_required
@require_POST
def validate_yaml_view(request: HttpRequest) -> HttpResponse:
    """Validate YAML scenario content without saving."""
    try:
        body = json.loads(request.body)
        yaml_content = body.get("yaml_content", "")
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"valid": False, "errors": ["Invalid request body"]}, status=400)

    parsed, errors = validate_yaml(yaml_content)
    if errors:
        return JsonResponse({"valid": False, "errors": errors, "definition": None})
    return JsonResponse({"valid": True, "errors": [], "definition": parsed})
