"""Form create/edit views for the scenario editor."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from cms.scenario_editor.services import (
    ScenarioFormFields,
    create_scenario_from_form_post,
    update_scenario_from_form_post,
)
from cms.scenario_editor.view_support import (
    ERRORS_CONTEXT_KEY,
    MODE_CONTEXT_KEY,
    SCENARIO_CONTEXT_KEY,
    VIEW_RECOVERABLE_EXCEPTIONS,
    render_internal_error,
    render_unexpected_error,
    resolve_editable_scenario,
)
from shared.auth import threat_research_required
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

FORM_TEMPLATE = "scenario_editor/form.html"
DETAIL_ROUTE = "scenario_editor:detail"


def _create_context(fields: ScenarioFormFields | None, errors: list[str]) -> dict[str, Any]:
    return {
        MODE_CONTEXT_KEY: "create",
        SCENARIO_CONTEXT_KEY: fields.as_context(include_id=True) if fields else None,
        ERRORS_CONTEXT_KEY: errors,
    }


def _edit_context(scenario: dict[str, Any], fields: ScenarioFormFields, errors: list[str]) -> dict[str, Any]:
    scenario.update(fields.as_context(include_id=False))
    return {MODE_CONTEXT_KEY: "edit", SCENARIO_CONTEXT_KEY: scenario, ERRORS_CONTEXT_KEY: errors}


def _handle_create_post(request: HttpRequest) -> HttpResponse:
    fields, errors = create_scenario_from_form_post(cast("User", request.user), request.POST)
    if errors:
        return render(request, FORM_TEMPLATE, _create_context(fields, errors))

    logger.info(
        "scenario_create_form: created scenario_id=%s by user_id=%s",
        safe_log_value(fields.scenario_id),
        request.user.id,
    )
    messages.success(request, f"Scenario '{fields.name}' created successfully.")
    return redirect(DETAIL_ROUTE, scenario_id=fields.scenario_id)


@threat_research_required
@require_http_methods(["GET", "POST"])
def scenario_create_form(request: HttpRequest) -> HttpResponse:
    """Form-based scenario creation."""
    try:
        if request.method == "GET":
            return render(request, FORM_TEMPLATE, _create_context(None, []))
        return _handle_create_post(request)
    except VIEW_RECOVERABLE_EXCEPTIONS:
        return render_unexpected_error(request, logger, "scenario_create_form")


def _handle_edit_post(request: HttpRequest, scenario_id: str, scenario: dict[str, Any]) -> HttpResponse:
    fields, errors = update_scenario_from_form_post(cast("User", request.user), scenario_id, request.POST)
    if errors:
        return render(request, FORM_TEMPLATE, _edit_context(scenario, fields, errors))

    logger.info(
        "scenario_edit_form: updated scenario_id=%s by user_id=%s",
        safe_log_value(scenario_id),
        request.user.id,
    )
    messages.success(request, "Scenario updated successfully.")
    return redirect(DETAIL_ROUTE, scenario_id=scenario_id)


def _scenario_edit_form_impl(request: HttpRequest, scenario_id: str) -> HttpResponse:
    scenario, error = resolve_editable_scenario(
        request,
        scenario_id,
        default_message="Default scenarios cannot be edited. Clone it to create an editable copy.",
        logger=logger,
        log_name="scenario_edit_form",
    )
    if error is not None:
        return error
    if scenario is None:
        return render_internal_error(request, logger, "scenario_edit_form", scenario_id=scenario_id)
    if request.method == "GET":
        return render(
            request,
            FORM_TEMPLATE,
            {MODE_CONTEXT_KEY: "edit", SCENARIO_CONTEXT_KEY: scenario, ERRORS_CONTEXT_KEY: []},
        )
    return _handle_edit_post(request, scenario_id, scenario)


@threat_research_required
@require_http_methods(["GET", "POST"])
def scenario_edit_form(request: HttpRequest, scenario_id: str) -> HttpResponse:
    """Form-based scenario editing for custom scenarios."""
    try:
        return _scenario_edit_form_impl(request, scenario_id)
    except VIEW_RECOVERABLE_EXCEPTIONS:
        return render_unexpected_error(request, logger, "scenario_edit_form", scenario_id=scenario_id)
