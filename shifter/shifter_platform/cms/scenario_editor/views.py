"""Template-based views for Scenario Editor.

Provides the UI for managing scenario templates.
All views require staff or Threat Research group membership.
"""

from __future__ import annotations

import json
import logging
import re

from django.contrib import messages
from django.http import HttpResponse, JsonResponse
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
from shared.log_sanitize import safe_log

logger = logging.getLogger(__name__)

SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]*[a-z0-9])?$")


# =============================================================================
# List View
# =============================================================================


@threat_research_required
@require_GET
def scenario_list(request):
    """List all scenarios with metadata."""
    scenarios = list_all_scenarios(user=None)  # Staff sees all
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
def scenario_detail_view(request, scenario_id):
    """View scenario details."""
    try:
        try:
            scenario = get_scenario_detail(scenario_id)
        except ValueError:
            logger.warning("scenario_detail_view: scenario not found scenario_id=%s", scenario_id)
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
            scenario_id,
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


def _parse_scenario_form_post(request, *, require_id: bool) -> tuple[dict, list[str]]:
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


@threat_research_required
@require_http_methods(["GET", "POST"])
def scenario_create_form(request):
    """Form-based scenario creation."""
    try:
        if request.method == "GET":
            return render(
                request,
                "scenario_editor/form.html",
                {
                    "mode": "create",
                    "scenario": None,
                    "errors": [],
                },
            )

        fields, errors = _parse_scenario_form_post(request, require_id=True)
        scenario_id = fields["id"]
        name = fields["name"]
        description = fields["description"]
        ngfw = fields["ngfw"]
        instances = fields["instances"]
        subnets = fields["subnets"]

        if errors:
            return render(
                request,
                "scenario_editor/form.html",
                {
                    "mode": "create",
                    "scenario": {
                        "id": scenario_id,
                        "name": name,
                        "description": description,
                        "ngfw": ngfw,
                        "instances": instances,
                        "subnets": subnets,
                    },
                    "errors": errors,
                },
            )

        definition = {
            "instances": instances,
            "subnets": subnets,
            "ngfw": ngfw,
        }

        try:
            create_scenario(
                request.user,
                scenario_id=scenario_id,
                name=name,
                description=description,
                definition=definition,
            )
        except ScenarioEditorError as e:
            return render(
                request,
                "scenario_editor/form.html",
                {
                    "mode": "create",
                    "scenario": {
                        "id": scenario_id,
                        "name": name,
                        "description": description,
                        "ngfw": ngfw,
                        "instances": instances,
                        "subnets": subnets,
                    },
                    "errors": [str(e)],
                },
            )

        logger.info(
            "scenario_create_form: created scenario_id=%s by user_id=%s", safe_log(scenario_id), request.user.id
        )
        messages.success(request, f"Scenario '{name}' created successfully.")
        return redirect("scenario_editor:detail", scenario_id=scenario_id)
    except Exception:
        logger.exception("scenario_create_form: unexpected error for user_id=%s", request.user.id)
        return render(
            request,
            "scenario_editor/error.html",
            {"message": "An unexpected error occurred. Please try again."},
            status=500,
        )


@threat_research_required
@require_http_methods(["GET", "POST"])
def scenario_edit_form(request, scenario_id):
    """Form-based scenario editing (custom scenarios only)."""
    try:
        if is_default_scenario(scenario_id):
            return render(
                request,
                "scenario_editor/error.html",
                {
                    "message": "Default scenarios cannot be edited. Clone it to create an editable copy.",
                },
                status=403,
            )

        try:
            scenario = get_scenario_detail(scenario_id)
        except ValueError:
            logger.warning("scenario_edit_form: scenario not found scenario_id=%s", scenario_id)
            return render(
                request,
                "scenario_editor/not_found.html",
                {
                    "scenario_id": scenario_id,
                },
                status=404,
            )

        if request.method == "GET":
            return render(
                request,
                "scenario_editor/form.html",
                {
                    "mode": "edit",
                    "scenario": scenario,
                    "errors": [],
                },
            )

        fields, errors = _parse_scenario_form_post(request, require_id=False)
        name = fields["name"]
        description = fields["description"]
        ngfw = fields["ngfw"]
        instances = fields["instances"]
        subnets = fields["subnets"]

        if errors:
            scenario.update(
                {
                    "name": name,
                    "description": description,
                    "ngfw": ngfw,
                    "instances": instances,
                    "subnets": subnets,
                }
            )
            return render(
                request,
                "scenario_editor/form.html",
                {
                    "mode": "edit",
                    "scenario": scenario,
                    "errors": errors,
                },
            )

        definition = {
            "instances": instances,
            "subnets": subnets,
            "ngfw": ngfw,
        }

        try:
            update_scenario(
                request.user,
                scenario_id,
                name=name,
                description=description,
                definition=definition,
            )
        except ScenarioEditorError as e:
            scenario.update(
                {
                    "name": name,
                    "description": description,
                    "ngfw": ngfw,
                    "instances": instances,
                    "subnets": subnets,
                }
            )
            return render(
                request,
                "scenario_editor/form.html",
                {
                    "mode": "edit",
                    "scenario": scenario,
                    "errors": [str(e)],
                },
            )

        logger.info("scenario_edit_form: updated scenario_id=%s by user_id=%s", scenario_id, request.user.id)
        messages.success(request, "Scenario updated successfully.")
        return redirect("scenario_editor:detail", scenario_id=scenario_id)
    except Exception:
        logger.exception(
            "scenario_edit_form: unexpected error for user_id=%s, scenario_id=%s",
            request.user.id,
            scenario_id,
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


@threat_research_required
@require_http_methods(["GET", "POST"])
def scenario_yaml_editor(request, scenario_id):
    """Free-form YAML editor for a scenario.

    GET: Renders the YAML editor with the scenario's current definition.
    POST: Validates and saves the YAML content.
    """
    try:
        if is_default_scenario(scenario_id):
            return render(
                request,
                "scenario_editor/error.html",
                {
                    "message": "Default scenarios cannot be edited via YAML. Clone it first.",
                },
                status=403,
            )

        try:
            scenario = get_scenario_detail(scenario_id)
        except ValueError:
            logger.warning("scenario_yaml_editor: scenario not found scenario_id=%s", scenario_id)
            return render(
                request,
                "scenario_editor/not_found.html",
                {
                    "scenario_id": scenario_id,
                },
                status=404,
            )

        yaml_content = export_scenario_yaml(scenario_id)

        if request.method == "GET":
            return render(
                request,
                "scenario_editor/yaml_editor.html",
                {
                    "scenario": scenario,
                    "yaml_content": yaml_content,
                    "errors": [],
                },
            )

        # POST - validate and save
        submitted_yaml = request.POST.get("yaml_content", "")
        parsed, errors = validate_yaml(submitted_yaml)

        if errors:
            return render(
                request,
                "scenario_editor/yaml_editor.html",
                {
                    "scenario": scenario,
                    "yaml_content": submitted_yaml,
                    "errors": errors,
                },
            )

        # Extract fields from parsed YAML
        name = parsed.get("name", scenario["name"])
        description = parsed.get("description", scenario["description"])
        definition = {
            "instances": parsed.get("instances", []),
            "subnets": parsed.get("subnets", []),
            "ngfw": parsed.get("ngfw", False),
        }

        try:
            update_scenario(
                request.user,
                scenario_id,
                name=name,
                description=description,
                definition=definition,
            )
        except ScenarioEditorError as e:
            return render(
                request,
                "scenario_editor/yaml_editor.html",
                {
                    "scenario": scenario,
                    "yaml_content": submitted_yaml,
                    "errors": [str(e)],
                },
            )

        logger.info("scenario_yaml_editor: updated scenario_id=%s by user_id=%s", scenario_id, request.user.id)
        messages.success(request, "Scenario updated from YAML successfully.")
        return redirect("scenario_editor:detail", scenario_id=scenario_id)
    except Exception:
        logger.exception(
            "scenario_yaml_editor: unexpected error for user_id=%s, scenario_id=%s",
            request.user.id,
            scenario_id,
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


@threat_research_required
@require_http_methods(["GET", "POST"])
def scenario_yaml_create(request):
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
                "scenario_editor/yaml_create.html",
                {
                    "yaml_content": template_yaml,
                    "errors": [],
                },
            )

        # POST
        submitted_yaml = request.POST.get("yaml_content", "")
        parsed, errors = validate_yaml(submitted_yaml)

        if errors:
            return render(
                request,
                "scenario_editor/yaml_create.html",
                {
                    "yaml_content": submitted_yaml,
                    "errors": errors,
                },
            )

        scenario_id = parsed.get("id", "")
        name = parsed.get("name", "")
        description = parsed.get("description", "")

        # Validate required fields from YAML
        yaml_errors = []
        if not scenario_id:
            yaml_errors.append("YAML must include an 'id' field")
        if not name:
            yaml_errors.append("YAML must include a 'name' field")
        if not description:
            yaml_errors.append("YAML must include a 'description' field")
        if yaml_errors:
            return render(
                request,
                "scenario_editor/yaml_create.html",
                {
                    "yaml_content": submitted_yaml,
                    "errors": yaml_errors,
                },
            )

        definition = {
            "instances": parsed.get("instances", []),
            "subnets": parsed.get("subnets", []),
            "ngfw": parsed.get("ngfw", False),
        }

        try:
            create_scenario(
                request.user,
                scenario_id=scenario_id,
                name=name,
                description=description,
                definition=definition,
            )
        except ScenarioEditorError as e:
            return render(
                request,
                "scenario_editor/yaml_create.html",
                {
                    "yaml_content": submitted_yaml,
                    "errors": [str(e)],
                },
            )

        logger.info("scenario_yaml_create: created scenario_id=%s by user_id=%s", scenario_id, request.user.id)
        messages.success(request, f"Scenario '{name}' created from YAML successfully.")
        return redirect("scenario_editor:detail", scenario_id=scenario_id)
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
def scenario_delete_view(request, scenario_id):
    """Delete a custom scenario."""
    try:
        try:
            delete_scenario(request.user, scenario_id)
        except ScenarioEditorError as e:
            return render(
                request,
                "scenario_editor/error.html",
                {
                    "message": str(e),
                },
            )

        logger.info("scenario_delete_view: deleted scenario_id=%s by user_id=%s", scenario_id, request.user.id)
        messages.success(request, "Scenario deleted successfully.")
        return redirect("scenario_editor:list")
    except Exception:
        logger.exception(
            "scenario_delete_view: unexpected error for user_id=%s, scenario_id=%s",
            request.user.id,
            scenario_id,
        )
        return render(
            request,
            "scenario_editor/error.html",
            {"message": "An unexpected error occurred. Please try again."},
            status=500,
        )


@threat_research_required
@require_POST
def scenario_toggle_enabled(request, scenario_id):
    """Toggle enabled state for a scenario."""
    try:
        try:
            current = get_scenario_detail(scenario_id)
        except ValueError:
            logger.warning("scenario_toggle_enabled: scenario not found scenario_id=%s", scenario_id)
            return render(
                request,
                "scenario_editor/not_found.html",
                {
                    "scenario_id": scenario_id,
                },
                status=404,
            )

        new_enabled = not current.get("enabled", True)

        try:
            update_metadata(request.user, scenario_id, enabled=new_enabled)
        except ScenarioEditorError as e:
            return render(
                request,
                "scenario_editor/error.html",
                {
                    "message": str(e),
                },
            )

        logger.info(
            "scenario_toggle_enabled: toggled enabled=%s for scenario_id=%s by user_id=%s",
            new_enabled,
            scenario_id,
            request.user.id,
        )
        messages.success(request, f"Scenario {'enabled' if new_enabled else 'disabled'} successfully.")
        return redirect("scenario_editor:list")
    except Exception:
        logger.exception(
            "scenario_toggle_enabled: unexpected error for user_id=%s, scenario_id=%s",
            request.user.id,
            scenario_id,
        )
        return render(
            request,
            "scenario_editor/error.html",
            {"message": "An unexpected error occurred. Please try again."},
            status=500,
        )


@threat_research_required
@require_POST
def scenario_toggle_staff_only(request, scenario_id):
    """Toggle staff_only state for a scenario."""
    try:
        try:
            current = get_scenario_detail(scenario_id)
        except ValueError:
            logger.warning("scenario_toggle_staff_only: scenario not found scenario_id=%s", scenario_id)
            return render(
                request,
                "scenario_editor/not_found.html",
                {
                    "scenario_id": scenario_id,
                },
                status=404,
            )

        new_staff_only = not current.get("staff_only", False)

        try:
            update_metadata(request.user, scenario_id, staff_only=new_staff_only)
        except ScenarioEditorError as e:
            return render(
                request,
                "scenario_editor/error.html",
                {
                    "message": str(e),
                },
            )

        logger.info(
            "scenario_toggle_staff_only: toggled staff_only=%s for scenario_id=%s by user_id=%s",
            new_staff_only,
            scenario_id,
            request.user.id,
        )
        messages.success(request, f"Access set to {'staff only' if new_staff_only else 'all users'} successfully.")
        return redirect("scenario_editor:list")
    except Exception:
        logger.exception(
            "scenario_toggle_staff_only: unexpected error for user_id=%s, scenario_id=%s",
            request.user.id,
            scenario_id,
        )
        return render(
            request,
            "scenario_editor/error.html",
            {"message": "An unexpected error occurred. Please try again."},
            status=500,
        )


@threat_research_required
@require_http_methods(["GET", "POST"])
def scenario_clone_view(request, scenario_id):
    """Clone a scenario."""
    try:
        try:
            source = get_scenario_detail(scenario_id)
        except ValueError:
            logger.warning("scenario_clone_view: scenario not found scenario_id=%s", scenario_id)
            return render(
                request,
                "scenario_editor/not_found.html",
                {
                    "scenario_id": scenario_id,
                },
                status=404,
            )

        if request.method == "GET":
            return render(
                request,
                "scenario_editor/clone.html",
                {
                    "source": source,
                },
            )

        new_scenario_id = request.POST.get("new_scenario_id", "").strip()
        new_name = request.POST.get("new_name", "").strip() or None

        if not new_scenario_id:
            return render(
                request,
                "scenario_editor/clone.html",
                {
                    "source": source,
                    "errors": ["New scenario ID is required"],
                },
            )

        try:
            scenario = clone_scenario(
                request.user,
                scenario_id,
                new_scenario_id=new_scenario_id,
                new_name=new_name,
            )
        except ScenarioEditorError as e:
            return render(
                request,
                "scenario_editor/clone.html",
                {
                    "source": source,
                    "errors": [str(e)],
                },
            )

        logger.info(
            "scenario_clone_view: cloned scenario_id=%s to new_scenario_id=%s by user_id=%s",
            safe_log(scenario_id),
            safe_log(new_scenario_id),
            request.user.id,
        )
        messages.success(request, f"Scenario cloned as '{new_name or new_scenario_id}' successfully.")
        return redirect("scenario_editor:detail", scenario_id=scenario.scenario_id)
    except Exception:
        logger.exception(
            "scenario_clone_view: unexpected error for user_id=%s, scenario_id=%s",
            request.user.id,
            scenario_id,
        )
        return render(
            request,
            "scenario_editor/error.html",
            {"message": "An unexpected error occurred. Please try again."},
            status=500,
        )


@threat_research_required
@require_GET
def scenario_export_view(request, scenario_id):
    """Download scenario as YAML file."""
    try:
        try:
            yaml_content = export_scenario_yaml(scenario_id)
        except ScenarioEditorError as e:
            logger.warning("scenario_export_view: scenario not found scenario_id=%s", scenario_id)
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
            scenario_id,
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
def validate_yaml_view(request):
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
