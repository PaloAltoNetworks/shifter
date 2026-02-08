"""Template-based views for Scenario Editor.

Provides the staff-facing UI for managing scenario templates.
All views require staff authentication.
"""

from __future__ import annotations

import json
import logging

from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from cms.scenarios.registry import (
    get_scenario_detail,
    is_default_scenario,
    list_all_scenarios,
)
from scenario_editor.services import (
    ScenarioEditorError,
    clone_scenario,
    create_scenario,
    delete_scenario,
    export_scenario_yaml,
    update_metadata,
    update_scenario,
    validate_yaml,
)

logger = logging.getLogger(__name__)


def staff_required(user):
    """Check if user is staff or superuser."""
    return user.is_staff or user.is_superuser


# =============================================================================
# List View
# =============================================================================


@login_required
@user_passes_test(staff_required)
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


@login_required
@user_passes_test(staff_required)
@require_GET
def scenario_detail_view(request, scenario_id):
    """View scenario details."""
    try:
        scenario = get_scenario_detail(scenario_id)
    except ValueError:
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


# =============================================================================
# Form-Based Create / Edit
# =============================================================================


@login_required
@user_passes_test(staff_required)
@require_http_methods(["GET", "POST"])
def scenario_create_form(request):
    """Form-based scenario creation."""
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

    # POST - handle form submission
    scenario_id = request.POST.get("scenario_id", "").strip()
    name = request.POST.get("name", "").strip()
    description = request.POST.get("description", "").strip()
    ngfw = request.POST.get("ngfw") == "on"
    instances_json = request.POST.get("instances_json", "[]")
    subnets_json = request.POST.get("subnets_json", "[]")

    errors = []
    if not scenario_id:
        errors.append("Scenario ID is required")
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

    return redirect("scenario_editor:detail", scenario_id=scenario_id)


@login_required
@user_passes_test(staff_required)
@require_http_methods(["GET", "POST"])
def scenario_edit_form(request, scenario_id):
    """Form-based scenario editing (custom scenarios only)."""
    if is_default_scenario(scenario_id):
        return render(
            request,
            "scenario_editor/error.html",
            {
                "message": "Default scenarios cannot be edited. Clone it to create an editable copy.",
            },
        )

    try:
        scenario = get_scenario_detail(scenario_id)
    except ValueError:
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

    # POST - handle form submission
    name = request.POST.get("name", "").strip()
    description = request.POST.get("description", "").strip()
    ngfw = request.POST.get("ngfw") == "on"
    instances_json = request.POST.get("instances_json", "[]")
    subnets_json = request.POST.get("subnets_json", "[]")

    errors = []
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

    return redirect("scenario_editor:detail", scenario_id=scenario_id)


# =============================================================================
# YAML Editor
# =============================================================================


@login_required
@user_passes_test(staff_required)
@require_http_methods(["GET", "POST"])
def scenario_yaml_editor(request, scenario_id):
    """Free-form YAML editor for a scenario.

    GET: Renders the YAML editor with the scenario's current definition.
    POST: Validates and saves the YAML content.
    """
    if is_default_scenario(scenario_id):
        return render(
            request,
            "scenario_editor/error.html",
            {
                "message": "Default scenarios cannot be edited via YAML. Clone it first.",
            },
        )

    try:
        scenario = get_scenario_detail(scenario_id)
    except ValueError:
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

    return redirect("scenario_editor:detail", scenario_id=scenario_id)


# =============================================================================
# YAML Create (import new scenario from YAML)
# =============================================================================


@login_required
@user_passes_test(staff_required)
@require_http_methods(["GET", "POST"])
def scenario_yaml_create(request):
    """Create a new scenario from YAML content."""
    if request.method == "GET":
        # Provide a template YAML for new scenarios
        template_yaml = (
            "id: my-new-scenario\n"
            "name: My New Scenario\n"
            "description: Describe your scenario here.\n"
            "enabled: true\n"
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

    return redirect("scenario_editor:detail", scenario_id=scenario_id)


# =============================================================================
# Actions
# =============================================================================


@login_required
@user_passes_test(staff_required)
@require_POST
def scenario_delete_view(request, scenario_id):
    """Delete a custom scenario."""
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

    return redirect("scenario_editor:list")


@login_required
@user_passes_test(staff_required)
@require_POST
def scenario_toggle_enabled(request, scenario_id):
    """Toggle enabled state for a scenario."""
    try:
        current = get_scenario_detail(scenario_id)
    except ValueError:
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

    return redirect("scenario_editor:list")


@login_required
@user_passes_test(staff_required)
@require_POST
def scenario_toggle_staff_only(request, scenario_id):
    """Toggle staff_only state for a scenario."""
    try:
        current = get_scenario_detail(scenario_id)
    except ValueError:
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

    return redirect("scenario_editor:list")


@login_required
@user_passes_test(staff_required)
@require_http_methods(["GET", "POST"])
def scenario_clone_view(request, scenario_id):
    """Clone a scenario."""
    try:
        source = get_scenario_detail(scenario_id)
    except ValueError:
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

    return redirect("scenario_editor:detail", scenario_id=scenario.scenario_id)


@login_required
@user_passes_test(staff_required)
@require_GET
def scenario_export_view(request, scenario_id):
    """Download scenario as YAML file."""
    try:
        yaml_content = export_scenario_yaml(scenario_id)
    except ScenarioEditorError as e:
        return render(
            request,
            "scenario_editor/error.html",
            {
                "message": str(e),
            },
        )

    response = HttpResponse(yaml_content, content_type="text/yaml")
    response["Content-Disposition"] = f'attachment; filename="{scenario_id}.yaml"'
    return response
