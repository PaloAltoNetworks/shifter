"""DRF API views for Scenario Editor.

Provides REST API endpoints for scenario CRUD, validation,
metadata management, cloning, and YAML import/export.

All endpoints require staff authentication.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from cms.scenario_editor.permissions import IsStaffUser
from cms.scenario_editor.serializers import (
    ScenarioCloneSerializer,
    ScenarioCreateSerializer,
    ScenarioDetailSerializer,
    ScenarioListSerializer,
    ScenarioMetadataResponseSerializer,
    ScenarioMetadataSerializer,
    ScenarioUpdateSerializer,
    ScenarioValidateSerializer,
    ScenarioYAMLSerializer,
)
from cms.scenario_editor.services import (
    ScenarioEditorError,
    clone_scenario,
    create_scenario,
    delete_scenario,
    export_scenario_yaml,
    update_metadata,
    update_scenario,
    validate_definition,
    validate_yaml,
)

logger = logging.getLogger(__name__)


def _error_status_for_scenario_error(e):
    """Return 404 for not-found errors, 400 for everything else."""
    if "not found" in str(e).lower():
        return status.HTTP_404_NOT_FOUND
    return status.HTTP_400_BAD_REQUEST


@api_view(["GET"])
@permission_classes([IsStaffUser])
def scenario_list(request):
    """List all scenarios (defaults + customs) with metadata.

    Staff users see all scenarios including disabled and staff-only.

    Query params:
        include_disabled: If 'true', include disabled scenarios (default: true for staff).
    """
    from cms.scenarios.registry import list_all_scenarios

    # Staff sees everything (no user filtering)
    scenarios = list_all_scenarios(user=None)

    serializer = ScenarioListSerializer(scenarios, many=True)
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([IsStaffUser])
def scenario_create(request):
    """Create a new custom scenario.

    Request body:
        scenario_id: URL-safe unique identifier
        name: Display name
        description: User-facing description
        definition: {instances: [...], subnets: [...], ngfw: bool}
    """
    serializer = ScenarioCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
        scenario = create_scenario(
            request.user,
            scenario_id=serializer.validated_data["scenario_id"],
            name=serializer.validated_data["name"],
            description=serializer.validated_data["description"],
            definition=serializer.validated_data["definition"],
        )
    except ScenarioEditorError as e:
        return Response(
            {"error": "scenario_error", "message": str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        logger.exception("scenario_create: unexpected error for user_id=%s", request.user.id)
        return Response(
            {"error": "internal_error", "message": "An unexpected error occurred"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Return the full scenario detail
    from cms.scenarios.registry import get_scenario_detail

    detail = get_scenario_detail(scenario.scenario_id)
    output = ScenarioDetailSerializer(detail)
    logger.info("scenario_create: created scenario_id=%s by user_id=%s", scenario.scenario_id, request.user.id)
    return Response(output.data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsStaffUser])
def scenario_detail(request, scenario_id):
    """Get a single scenario by ID."""
    from cms.scenarios.registry import get_scenario_detail

    try:
        detail = get_scenario_detail(scenario_id)
    except ValueError:
        logger.warning("scenario_detail: scenario not found scenario_id=%s", scenario_id)
        return Response(
            {"error": "not_found", "message": f"Scenario '{scenario_id}' not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    serializer = ScenarioDetailSerializer(detail)
    return Response(serializer.data)


@api_view(["PUT", "PATCH"])
@permission_classes([IsStaffUser])
def scenario_update(request, scenario_id):
    """Update a custom scenario.

    PUT requires all fields, PATCH allows partial updates.
    Default scenarios cannot be updated.
    """
    partial = request.method == "PATCH"
    serializer = ScenarioUpdateSerializer(data=request.data, partial=partial)
    serializer.is_valid(raise_exception=True)

    try:
        scenario = update_scenario(
            request.user,
            scenario_id,
            name=serializer.validated_data.get("name"),
            description=serializer.validated_data.get("description"),
            definition=serializer.validated_data.get("definition"),
        )
    except ScenarioEditorError as e:
        error_status = _error_status_for_scenario_error(e)
        if error_status == status.HTTP_404_NOT_FOUND:
            logger.warning("scenario_update: scenario not found scenario_id=%s", scenario_id)
        return Response(
            {"error": "scenario_error", "message": str(e)},
            status=error_status,
        )
    except Exception:
        logger.exception(
            "scenario_update: unexpected error for user_id=%s, scenario_id=%s",
            request.user.id,
            scenario_id,
        )
        return Response(
            {"error": "internal_error", "message": "An unexpected error occurred"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    from cms.scenarios.registry import get_scenario_detail

    detail = get_scenario_detail(scenario.scenario_id)
    output = ScenarioDetailSerializer(detail)
    logger.info("scenario_update: updated scenario_id=%s by user_id=%s", scenario_id, request.user.id)
    return Response(output.data)


@api_view(["DELETE"])
@permission_classes([IsStaffUser])
def scenario_delete(request, scenario_id):
    """Soft-delete a custom scenario.

    Default scenarios cannot be deleted.
    """
    try:
        delete_scenario(request.user, scenario_id)
    except ScenarioEditorError as e:
        error_status = _error_status_for_scenario_error(e)
        if error_status == status.HTTP_404_NOT_FOUND:
            logger.warning("scenario_delete: scenario not found scenario_id=%s", scenario_id)
        return Response(
            {"error": "scenario_error", "message": str(e)},
            status=error_status,
        )
    except Exception:
        logger.exception(
            "scenario_delete: unexpected error for user_id=%s, scenario_id=%s",
            request.user.id,
            scenario_id,
        )
        return Response(
            {"error": "internal_error", "message": "An unexpected error occurred"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    logger.info("scenario_delete: deleted scenario_id=%s by user_id=%s", scenario_id, request.user.id)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
@permission_classes([IsStaffUser])
def scenario_validate(request):
    """Validate a scenario definition without saving.

    Request body:
        definition: Full scenario definition dict
            (must include id, name, description, instances, etc.)

    Returns:
        {valid: true} or {valid: false, errors: [...]}
    """
    serializer = ScenarioValidateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    errors = validate_definition(serializer.validated_data["definition"])

    if errors:
        return Response({"valid": False, "errors": errors})
    return Response({"valid": True, "errors": []})


@api_view(["POST"])
@permission_classes([IsStaffUser])
def scenario_validate_yaml(request):
    """Validate YAML scenario content without saving.

    Request body:
        yaml_content: Raw YAML string

    Returns:
        {valid: true, definition: {...}} or {valid: false, errors: [...]}
    """
    serializer = ScenarioYAMLSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    parsed, errors = validate_yaml(serializer.validated_data["yaml_content"])

    if errors:
        return Response({"valid": False, "errors": errors, "definition": None})
    return Response({"valid": True, "errors": [], "definition": parsed})


@api_view(["PATCH"])
@permission_classes([IsStaffUser])
def scenario_metadata(request, scenario_id):
    """Update metadata (enabled, staff_only) for any scenario.

    Works for both default and custom scenarios.

    Request body:
        enabled: bool (optional)
        staff_only: bool (optional)
    """
    serializer = ScenarioMetadataSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
        metadata = update_metadata(
            request.user,
            scenario_id,
            enabled=serializer.validated_data.get("enabled"),
            staff_only=serializer.validated_data.get("staff_only"),
        )
    except ScenarioEditorError as e:
        error_status = _error_status_for_scenario_error(e)
        if error_status == status.HTTP_404_NOT_FOUND:
            logger.warning("scenario_metadata: scenario not found scenario_id=%s", scenario_id)
        return Response(
            {"error": "scenario_error", "message": str(e)},
            status=error_status,
        )
    except Exception:
        logger.exception(
            "scenario_metadata: unexpected error for user_id=%s, scenario_id=%s",
            request.user.id,
            scenario_id,
        )
        return Response(
            {"error": "internal_error", "message": "An unexpected error occurred"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    output = ScenarioMetadataResponseSerializer(
        {
            "scenario_id": metadata.scenario_id,
            "enabled": metadata.enabled,
            "staff_only": metadata.staff_only,
            "updated_at": metadata.updated_at,
        }
    )
    logger.info("scenario_metadata: updated metadata for scenario_id=%s by user_id=%s", scenario_id, request.user.id)
    return Response(output.data)


@api_view(["POST"])
@permission_classes([IsStaffUser])
def scenario_clone(request, scenario_id):
    """Clone an existing scenario into a new custom scenario.

    Request body:
        new_scenario_id: URL-safe identifier for the clone
        new_name: Display name (optional, defaults to "Copy of <original>")
    """
    serializer = ScenarioCloneSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
        scenario = clone_scenario(
            request.user,
            scenario_id,
            new_scenario_id=serializer.validated_data["new_scenario_id"],
            new_name=serializer.validated_data.get("new_name"),
        )
    except ScenarioEditorError as e:
        return Response(
            {"error": "scenario_error", "message": str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        logger.exception(
            "scenario_clone: unexpected error for user_id=%s, scenario_id=%s",
            request.user.id,
            scenario_id,
        )
        return Response(
            {"error": "internal_error", "message": "An unexpected error occurred"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    from cms.scenarios.registry import get_scenario_detail

    detail = get_scenario_detail(scenario.scenario_id)
    output = ScenarioDetailSerializer(detail)
    logger.info(
        "scenario_clone: cloned scenario_id=%s to new_scenario_id=%s by user_id=%s",
        scenario_id,
        scenario.scenario_id,
        request.user.id,
    )
    return Response(output.data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsStaffUser])
def scenario_export_yaml(request, scenario_id):
    """Export a scenario as YAML.

    Returns the scenario definition formatted as YAML text.
    """
    try:
        yaml_content = export_scenario_yaml(scenario_id)
    except ScenarioEditorError as e:
        logger.warning("scenario_export_yaml: scenario not found scenario_id=%s", scenario_id)
        return Response(
            {"error": "scenario_error", "message": str(e)},
            status=status.HTTP_404_NOT_FOUND,
        )
    except Exception:
        logger.exception(
            "scenario_export_yaml: unexpected error for user_id=%s, scenario_id=%s",
            request.user.id,
            scenario_id,
        )
        return Response(
            {"error": "internal_error", "message": "An unexpected error occurred"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return Response(
        {"scenario_id": scenario_id, "yaml": yaml_content},
        content_type="application/json",
    )


@api_view(["POST"])
@permission_classes([IsStaffUser])
def scenario_import_yaml(request):
    """Import a scenario from YAML content.

    Parses the YAML, validates it, and creates a new custom scenario.

    Request body:
        yaml_content: Raw YAML string (must include id, name, description, instances)
    """
    serializer = ScenarioYAMLSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    parsed, errors = validate_yaml(serializer.validated_data["yaml_content"])
    if errors:
        return Response(
            {"error": "validation_error", "errors": errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Extract fields from parsed YAML
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
        return Response(
            {"error": "validation_error", "errors": yaml_errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    definition = {
        "instances": parsed.get("instances", []),
        "subnets": parsed.get("subnets", []),
        "ngfw": parsed.get("ngfw", False),
    }

    try:
        scenario = create_scenario(
            request.user,
            scenario_id=scenario_id,
            name=name,
            description=description,
            definition=definition,
        )
    except ScenarioEditorError as e:
        return Response(
            {"error": "scenario_error", "message": str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        logger.exception("scenario_import_yaml: unexpected error for user_id=%s", request.user.id)
        return Response(
            {"error": "internal_error", "message": "An unexpected error occurred"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    from cms.scenarios.registry import get_scenario_detail

    detail = get_scenario_detail(scenario.scenario_id)
    output = ScenarioDetailSerializer(detail)
    logger.info("scenario_import_yaml: created scenario_id=%s by user_id=%s", scenario_id, request.user.id)
    return Response(output.data, status=status.HTTP_201_CREATED)
