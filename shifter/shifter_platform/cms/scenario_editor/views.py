"""Template-based views for Scenario Editor.

Provides the UI for managing scenario templates.
All views require staff or Threat Research group membership.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any, cast

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from cms.scenario_editor.services import (
    ScenarioEditorError,
    clone_scenario,
    create_scenario,
    delete_scenario,
    export_scenario_yaml,
    update_metadata,
    update_scenario,
    validate_yaml,
)
from cms.scenarios.registry import (
    get_scenario_detail,
    is_default_scenario,
    list_all_scenarios,
)
from shared.auth import threat_research_required
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]*[a-z0-9])?$")

FORM_TEMPLATE = "scenario_editor/form.html"
YAML_CREATE_TEMPLATE = "scenario_editor/yaml_create.html"
CLONE_TEMPLATE = "scenario_editor/clone.html"
DETAIL_ROUTE = "scenario_editor:detail"


# =============================================================================
# List View
# =============================================================================


@threat_research_required
@require_GET
def scenario_list(request: HttpRequest) -> HttpResponse:
    """List all scenarios with metadata."""
    # Staff sees all
    scenarios = list_all_scenarios(user=None)
    return render(
        request,
        "scenario_editor/list.html",
        {
            "scenarios": scenarios,
        },
    )


# =============================================================================
# Detail View
# =============================================================================


@threat_research_required
@require_GET
def scenario_detail_view(request: HttpRequest, scenario_id: str) -> HttpResponse:
    """View scenario details."""
    try:
        try:
            scenario = get_scenario_detail(scenario_id)
        except ValueError:
            logger.warning("scenario_detail_view: scenario not found scenario_id=%s", safe_log_value(scenario_id))
            return render(
                request,
                "scenario_editor/not_found.html",
                {
                    "scenario_id": scenario_id,
                },
                status=404,
            )

        yaml_content = export_scenario_yaml(scenario_id)
        return render(
            request,
            "scenario_editor/detail.html",
            {
                "scenario": scenario,
                "yaml_content": yaml_content,
                "is_default": scenario.get("is_default", False),
            },
        )
    except Exception:
        logger.exception(
            "scenario_detail_view: unexpected error for user_id=%s, scenario_id=%s",
            request.user.id,
            safe_log_value(scenario_id),
        )
        return render(
            request,
            "scenario_editor/error.html",
            {"message": "An unexpected error occurred. Please try again."},
            status=500,
        )


# =============================================================================
# Form-Based Create / Edit
# =============================================================================


def _parse_scenario_form_post(request: HttpRequest, *, require_id: bool) -> tuple[dict[str, Any], list[str]]:
    """Extract scenario fields from a form POST; return (fields, errors).

    `require_id` toggles the scenario-id field validation (creation needs it;
    edit takes the id from the URL).
    """
    scenario_id = request.POST.get("scenario_id", "").strip()
    name = request.POST.get("name", "").strip()
    description = request.POST.get("description", "").strip()
    ngfw = request.POST.get("ngfw") == "on"
    instances_json = request.POST.get("instances_json", "[]")
    subnets_json = request.POST.get("subnets_json", "[]")

    errors: list[str] = []
    if require_id:
        if not scenario_id:
            errors.append("Scenario ID is required")
        elif not SLUG_RE.match(scenario_id):
            errors.append("Scenario ID must contain only lowercase letters, numbers, hyphens, and underscores")
    if not name:
        errors.append("Name is required")
    if not description:
        errors.append("Description is required")

    try:
        instances = json.loads(instances_json)
    except json.JSONDecodeError:
        instances = []
        errors.append("Invalid instances JSON")

    try:
        subnets = json.loads(subnets_json)
    except json.JSONDecodeError:
        subnets = []
        errors.append("Invalid subnets JSON")

    if not instances:
        errors.append("At least one instance is required")

    return (
        {
            "id": scenario_id,
            "name": name,
            "description": description,
            "ngfw": ngfw,
            "instances": instances,
            "subnets": subnets,
        },
        errors,
    )


def _handle_scenario_create_post(request: HttpRequest) -> HttpResponse:
    """Validate the create form and create the scenario, re-rendering the form on error."""
    fields, errors = _parse_scenario_form_post(request, require_id=True)
    scenario_ctx = {
        "id": fields["id"],
        "name": fields["name"],
        "description": fields["description"],
        "ngfw": fields["ngfw"],
        "instances": fields["instances"],
        "subnets": fields["subnets"],
    }
    if errors:
        return render(request, FORM_TEMPLATE, {"mode": "create", "scenario": scenario_ctx, "errors": errors})

    definition = {"instances": fields["instances"], "subnets": fields["subnets"], "ngfw": fields["ngfw"]}
    try:
        create_scenario(
            cast("User", request.user),
            scenario_id=fields["id"],
            name=fields["name"],
            description=fields["description"],
            definition=definition,
        )
    except ScenarioEditorError as e:
        return render(request, FORM_TEMPLATE, {"mode": "create", "scenario": scenario_ctx, "errors": [str(e)]})

    logger.info(
        "scenario_create_form: created scenario_id=%s by user_id=%s", safe_log_value(fields["id"]), request.user.id
    )
    messages.success(request, f"Scenario '{fields['name']}' created successfully.")
    return redirect(DETAIL_ROUTE, scenario_id=fields["id"])


@threat_research_required
@require_http_methods(["GET", "POST"])
def scenario_create_form(request: HttpRequest) -> HttpResponse:
    """Form-based scenario creation."""
    try:
        if request.method == "GET":
            return render(request, FORM_TEMPLATE, {"mode": "create", "scenario": None, "errors": []})
        return _handle_scenario_create_post(request)
    except Exception:
        logger.exception("scenario_create_form: unexpected error for user_id=%s", request.user.id)
        return render(
            request,
            "scenario_editor/error.html",
            {"message": "An unexpected error occurred. Please try again."},
            status=500,
        )


def _resolve_editable_scenario(
    request: HttpRequest, scenario_id: str, *, default_message: str
) -> tuple[dict[str, Any] | None, HttpResponse | None]:
    """Return (scenario, None) for an editable custom scenario, else (None, error_response).

    Default scenarios are read-only (403, with the caller's ``default_message``) and
    missing scenarios are 404.
    """
    if is_default_scenario(scenario_id):
        return None, render(request, "scenario_editor/error.html", {"message": default_message}, status=403)
    try:
        return get_scenario_detail(scenario_id), None
    except ValueError:
        logger.warning("scenario_edit_form: scenario not found scenario_id=%s", safe_log_value(scenario_id))
        return None, render(request, "scenario_editor/not_found.html", {"scenario_id": scenario_id}, status=404)


def _handle_scenario_edit_post(request: HttpRequest, scenario_id: str, scenario: dict[str, Any]) -> HttpResponse:
    """Validate the edit form and update the scenario, re-rendering the form on error."""
    fields, errors = _parse_scenario_form_post(request, require_id=False)
    form_fields = {
        "name": fields["name"],
        "description": fields["description"],
        "ngfw": fields["ngfw"],
        "instances": fields["instances"],
        "subnets": fields["subnets"],
    }
    if errors:
        scenario.update(form_fields)
        return render(request, FORM_TEMPLATE, {"mode": "edit", "scenario": scenario, "errors": errors})

    definition = {"instances": fields["instances"], "subnets": fields["subnets"], "ngfw": fields["ngfw"]}
    try:
        update_scenario(
            cast("User", request.user),
            scenario_id,
            name=fields["name"],
            description=fields["description"],
            definition=definition,
        )
    except ScenarioEditorError as e:
        scenario.update(form_fields)
        return render(request, FORM_TEMPLATE, {"mode": "edit", "scenario": scenario, "errors": [str(e)]})

    logger.info(
        "scenario_edit_form: updated scenario_id=%s by user_id=%s", safe_log_value(scenario_id), request.user.id
    )
    messages.success(request, "Scenario updated successfully.")
    return redirect(DETAIL_ROUTE, scenario_id=scenario_id)


def _scenario_edit_form_impl(request: HttpRequest, scenario_id: str) -> HttpResponse:
    """Apply the editable-scenario guard, then dispatch GET render or POST update."""
    scenario, error = _resolve_editable_scenario(
        request, scenario_id, default_message="Default scenarios cannot be edited. Clone it to create an editable copy."
    )
    if error is not None:
        return error
    # error is None implies the scenario was resolved.
    assert scenario is not None
    if request.method == "GET":
        return render(request, FORM_TEMPLATE, {"mode": "edit", "scenario": scenario, "errors": []})
    return _handle_scenario_edit_post(request, scenario_id, scenario)


@threat_research_required
@require_http_methods(["GET", "POST"])
def scenario_edit_form(request: HttpRequest, scenario_id: str) -> HttpResponse:
    """Form-based scenario editing (custom scenarios only)."""
    try:
        return _scenario_edit_form_impl(request, scenario_id)
    except Exception:
        logger.exception(
            "scenario_edit_form: unexpected error for user_id=%s, scenario_id=%s",
            request.user.id,
            safe_log_value(scenario_id),
        )
        return render(
            request,
            "scenario_editor/error.html",
            {"message": "An unexpected error occurred. Please try again."},
            status=500,
        )


# =============================================================================
# YAML Editor
# =============================================================================


def _handle_scenario_yaml_post(request: HttpRequest, scenario_id: str, scenario: dict[str, Any]) -> HttpResponse:
    """Validate submitted YAML and update the scenario, re-rendering the editor on error."""
    submitted_yaml = request.POST.get("yaml_content", "")
    parsed, errors = validate_yaml(submitted_yaml)
    if errors:
        return render(
            request,
            "scenario_editor/yaml_editor.html",
            {"scenario": scenario, "yaml_content": submitted_yaml, "errors": errors},
        )

    # validate_yaml returns a populated mapping whenever it reports no errors.
    parsed = parsed or {}
    definition = {
        "instances": parsed.get("instances", []),
        "subnets": parsed.get("subnets", []),
        "ngfw": parsed.get("ngfw", False),
    }
    try:
        update_scenario(
            cast("User", request.user),
            scenario_id,
            name=parsed.get("name", scenario["name"]),
            description=parsed.get("description", scenario["description"]),
            definition=definition,
        )
    except ScenarioEditorError as e:
        return render(
            request,
            "scenario_editor/yaml_editor.html",
            {"scenario": scenario, "yaml_content": submitted_yaml, "errors": [str(e)]},
        )

    logger.info(
        "scenario_yaml_editor: updated scenario_id=%s by user_id=%s", safe_log_value(scenario_id), request.user.id
    )
    messages.success(request, "Scenario updated from YAML successfully.")
    return redirect(DETAIL_ROUTE, scenario_id=scenario_id)


def _scenario_yaml_editor_impl(request: HttpRequest, scenario_id: str) -> HttpResponse:
    """Apply the editable-scenario guard, then dispatch GET render or POST update."""
    scenario, error = _resolve_editable_scenario(
        request, scenario_id, default_message="Default scenarios cannot be edited via YAML. Clone it first."
    )
    if error is not None:
        return error
    # error is None implies the scenario was resolved.
    assert scenario is not None
    if request.method == "GET":
        return render(
            request,
            "scenario_editor/yaml_editor.html",
            {"scenario": scenario, "yaml_content": export_scenario_yaml(scenario_id), "errors": []},
        )
    return _handle_scenario_yaml_post(request, scenario_id, scenario)


@threat_research_required
@require_http_methods(["GET", "POST"])
def scenario_yaml_editor(request: HttpRequest, scenario_id: str) -> HttpResponse:
    """Free-form YAML editor for a scenario.

    GET: Renders the YAML editor with the scenario's current definition.
    POST: Validates and saves the YAML content.
    """
    try:
        return _scenario_yaml_editor_impl(request, scenario_id)
    except Exception:
        logger.exception(
            "scenario_yaml_editor: unexpected error for user_id=%s, scenario_id=%s",
            request.user.id,
            safe_log_value(scenario_id),
        )
        return render(
            request,
            "scenario_editor/error.html",
            {"message": "An unexpected error occurred. Please try again."},
            status=500,
        )


# =============================================================================
# YAML Create (import new scenario from YAML)
# =============================================================================


def _create_scenario_from_parsed(
    request: HttpRequest,
    *,
    scenario_id: str,
    name: str,
    description: str,
    parsed: dict[str, Any],
    submitted_yaml: str,
) -> HttpResponse:
    """Create a scenario from validated YAML fields, re-rendering the form on error."""
    definition = {
        "instances": parsed.get("instances", []),
        "subnets": parsed.get("subnets", []),
        "ngfw": parsed.get("ngfw", False),
    }
    try:
        create_scenario(
            cast("User", request.user),
            scenario_id=scenario_id,
            name=name,
            description=description,
            definition=definition,
        )
    except ScenarioEditorError as e:
        return render(request, YAML_CREATE_TEMPLATE, {"yaml_content": submitted_yaml, "errors": [str(e)]})

    logger.info(
        "scenario_yaml_create: created scenario_id=%s by user_id=%s", safe_log_value(scenario_id), request.user.id
    )
    messages.success(request, f"Scenario '{name}' created from YAML successfully.")
    return redirect(DETAIL_ROUTE, scenario_id=scenario_id)


def _handle_scenario_yaml_create_post(request: HttpRequest) -> HttpResponse:
    """Validate submitted YAML (shape then required fields) and create a new scenario."""
    submitted_yaml = request.POST.get("yaml_content", "")
    parsed, errors = validate_yaml(submitted_yaml)
    if errors:
        return render(request, YAML_CREATE_TEMPLATE, {"yaml_content": submitted_yaml, "errors": errors})

    # validate_yaml returns a populated mapping whenever it reports no errors.
    parsed = parsed or {}
    scenario_id = parsed.get("id", "")
    name = parsed.get("name", "")
    description = parsed.get("description", "")

    yaml_errors = []
    if not scenario_id:
        yaml_errors.append("YAML must include an 'id' field")
    if not name:
        yaml_errors.append("YAML must include a 'name' field")
    if not description:
        yaml_errors.append("YAML must include a 'description' field")
    if yaml_errors:
        return render(request, YAML_CREATE_TEMPLATE, {"yaml_content": submitted_yaml, "errors": yaml_errors})

    return _create_scenario_from_parsed(
        request,
        scenario_id=scenario_id,
        name=name,
        description=description,
        parsed=parsed,
        submitted_yaml=submitted_yaml,
    )


@threat_research_required
@require_http_methods(["GET", "POST"])
def scenario_yaml_create(request: HttpRequest) -> HttpResponse:
    """Create a new scenario from YAML content."""
    try:
        if request.method == "GET":
            # Provide a template YAML for new scenarios
            template_yaml = (
                "id: my-new-scenario\n"
                "name: My New Scenario\n"
                "description: Describe your scenario here.\n"
                "ngfw: false\n"
                "\n"
                "instances:\n"
                "  - name: Attacker\n"
                "    role: attacker\n"
                "    os_type: kali\n"
                "    xdr_agent: false\n"
                "\n"
                "  - name: Workstation\n"
                "    role: victim\n"
                "    os_type: from_agent\n"
                "    xdr_agent: true\n"
                "\n"
                "subnets:\n"
                "  - name: core\n"
                "    instances: [Attacker, Workstation]\n"
            )
            return render(
                request,
                YAML_CREATE_TEMPLATE,
                {
                    "yaml_content": template_yaml,
                    "errors": [],
                },
            )

        return _handle_scenario_yaml_create_post(request)
    except Exception:
        logger.exception("scenario_yaml_create: unexpected error for user_id=%s", request.user.id)
        return render(
            request,
            "scenario_editor/error.html",
            {"message": "An unexpected error occurred. Please try again."},
            status=500,
        )


# =============================================================================
# Actions
# =============================================================================


@threat_research_required
@require_POST
def scenario_delete_view(request: HttpRequest, scenario_id: str) -> HttpResponse:
    """Delete a custom scenario."""
    try:
        try:
            delete_scenario(cast("User", request.user), scenario_id)
        except ScenarioEditorError as e:
            return render(
                request,
                "scenario_editor/error.html",
                {
                    "message": str(e),
                },
            )

        logger.info(
            "scenario_delete_view: deleted scenario_id=%s by user_id=%s", safe_log_value(scenario_id), request.user.id
        )
        messages.success(request, "Scenario deleted successfully.")
        return redirect("scenario_editor:list")
    except Exception:
        logger.exception(
            "scenario_delete_view: unexpected error for user_id=%s, scenario_id=%s",
            request.user.id,
            safe_log_value(scenario_id),
        )
        return render(
            request,
            "scenario_editor/error.html",
            {"message": "An unexpected error occurred. Please try again."},
            status=500,
        )


def _toggle_scenario_metadata_flag(
    request: HttpRequest,
    scenario_id: str,
    *,
    field: str,
    default: bool,
    log_name: str,
    on_message: str,
    off_message: str,
) -> HttpResponse:
    """Flip a boolean scenario metadata flag (enabled / staff_only) and redirect to the list.

    Shared by the enabled and staff-only toggles. ``get_scenario_detail`` raises
    ``ValueError`` for a missing scenario (404); ``update_metadata`` raises
    ``ScenarioEditorError`` (rendered at 200) and anything else is a 500.
    """
    try:
        current = get_scenario_detail(scenario_id)
        new_value = not current.get(field, default)
        update_metadata(cast("User", request.user), scenario_id, **{field: new_value})
    except ValueError:
        logger.warning("%s: scenario not found scenario_id=%s", log_name, safe_log_value(scenario_id))
        return render(request, "scenario_editor/not_found.html", {"scenario_id": scenario_id}, status=404)
    except Exception as e:
        known = isinstance(e, ScenarioEditorError)
        if not known:
            logger.exception(
                "%s: unexpected error for user_id=%s, scenario_id=%s",
                log_name,
                request.user.id,
                safe_log_value(scenario_id),
            )
        return render(
            request,
            "scenario_editor/error.html",
            {"message": str(e) if known else "An unexpected error occurred. Please try again."},
            status=200 if known else 500,
        )

    logger.info(
        "%s: toggled %s=%s for scenario_id=%s by user_id=%s",
        log_name,
        field,
        new_value,
        safe_log_value(scenario_id),
        request.user.id,
    )
    messages.success(request, on_message if new_value else off_message)
    return redirect("scenario_editor:list")


@threat_research_required
@require_POST
def scenario_toggle_enabled(request: HttpRequest, scenario_id: str) -> HttpResponse:
    """Toggle enabled state for a scenario."""
    return _toggle_scenario_metadata_flag(
        request,
        scenario_id,
        field="enabled",
        default=True,
        log_name="scenario_toggle_enabled",
        on_message="Scenario enabled successfully.",
        off_message="Scenario disabled successfully.",
    )


@threat_research_required
@require_POST
def scenario_toggle_staff_only(request: HttpRequest, scenario_id: str) -> HttpResponse:
    """Toggle staff_only state for a scenario."""
    return _toggle_scenario_metadata_flag(
        request,
        scenario_id,
        field="staff_only",
        default=False,
        log_name="scenario_toggle_staff_only",
        on_message="Access set to staff only successfully.",
        off_message="Access set to all users successfully.",
    )


def _handle_scenario_clone_post(request: HttpRequest, scenario_id: str, source: dict[str, Any]) -> HttpResponse:
    """Validate the clone form and clone the scenario, re-rendering the form on error."""
    new_scenario_id = request.POST.get("new_scenario_id", "").strip()
    new_name = request.POST.get("new_name", "").strip() or None
    if not new_scenario_id:
        return render(request, CLONE_TEMPLATE, {"source": source, "errors": ["New scenario ID is required"]})
    try:
        scenario = clone_scenario(
            cast("User", request.user), scenario_id, new_scenario_id=new_scenario_id, new_name=new_name
        )
    except ScenarioEditorError as e:
        return render(request, CLONE_TEMPLATE, {"source": source, "errors": [str(e)]})

    logger.info(
        "scenario_clone_view: cloned scenario_id=%s to new_scenario_id=%s by user_id=%s",
        safe_log_value(scenario_id),
        safe_log_value(new_scenario_id),
        request.user.id,
    )
    messages.success(request, f"Scenario cloned as '{new_name or new_scenario_id}' successfully.")
    return redirect(DETAIL_ROUTE, scenario_id=scenario.scenario_id)


def _scenario_clone_view_impl(request: HttpRequest, scenario_id: str) -> HttpResponse:
    """Resolve the source scenario, then dispatch GET render or POST clone."""
    try:
        source = get_scenario_detail(scenario_id)
    except ValueError:
        logger.warning("scenario_clone_view: scenario not found scenario_id=%s", safe_log_value(scenario_id))
        return render(request, "scenario_editor/not_found.html", {"scenario_id": scenario_id}, status=404)
    if request.method == "GET":
        return render(request, CLONE_TEMPLATE, {"source": source})
    return _handle_scenario_clone_post(request, scenario_id, source)


@threat_research_required
@require_http_methods(["GET", "POST"])
def scenario_clone_view(request: HttpRequest, scenario_id: str) -> HttpResponse:
    """Clone a scenario."""
    try:
        return _scenario_clone_view_impl(request, scenario_id)
    except Exception:
        logger.exception(
            "scenario_clone_view: unexpected error for user_id=%s, scenario_id=%s",
            request.user.id,
            safe_log_value(scenario_id),
        )
        return render(
            request,
            "scenario_editor/error.html",
            {"message": "An unexpected error occurred. Please try again."},
            status=500,
        )


@threat_research_required
@require_GET
def scenario_export_view(request: HttpRequest, scenario_id: str) -> HttpResponse:
    """Download scenario as YAML file."""
    try:
        try:
            yaml_content = export_scenario_yaml(scenario_id)
        except ScenarioEditorError as e:
            logger.warning("scenario_export_view: scenario not found scenario_id=%s", safe_log_value(scenario_id))
            return render(
                request,
                "scenario_editor/error.html",
                {
                    "message": str(e),
                },
                status=404,
            )

        response = HttpResponse(yaml_content, content_type="text/yaml")
        response["Content-Disposition"] = f'attachment; filename="{scenario_id}.yaml"'
        return response
    except Exception:
        logger.exception(
            "scenario_export_view: unexpected error for user_id=%s, scenario_id=%s",
            request.user.id,
            safe_log_value(scenario_id),
        )
        return render(
            request,
            "scenario_editor/error.html",
            {"message": "An unexpected error occurred. Please try again."},
            status=500,
        )


# =============================================================================
# YAML Validation (JSON endpoint for client-side validate button)
# =============================================================================


@threat_research_required
@require_POST
def validate_yaml_view(request: HttpRequest) -> HttpResponse:
    """Validate YAML scenario content without saving.

    Called by the client-side Validate button in yaml_editor.html and yaml_create.html.
    Accepts JSON body with yaml_content, returns JSON response.
    """
    try:
        body = json.loads(request.body)
        yaml_content = body.get("yaml_content", "")
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"valid": False, "errors": ["Invalid request body"]}, status=400)

    parsed, errors = validate_yaml(yaml_content)

    if errors:
        return JsonResponse({"valid": False, "errors": errors, "definition": None})
    return JsonResponse({"valid": True, "errors": [], "definition": parsed})
