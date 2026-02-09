"""Experiment manager views — staff-only.

All business logic is in experiments.services. Views handle HTTP only.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, cast

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from cms.experiments import services
from cms.experiments.exceptions import (
    ArtifactError,
    ExperimentError,
    ExperimentStateError,
    ExperimentValidationError,
    ScriptUploadError,
)
from cms.experiments.schemas import ExperimentCreateInput

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


# =============================================================================
# Script views
# =============================================================================


@staff_member_required
def script_list(request: HttpRequest) -> HttpResponse:
    """List user's script assets."""
    scripts = services.list_scripts(cast("User", request.user))
    return render(
        request,
        "experiments/script_list.html",
        {
            "active_nav": "experiments",
            "scripts": scripts,
        },
    )


@staff_member_required
def script_upload(request: HttpRequest) -> HttpResponse:
    """Upload a script file — two-step presigned URL flow.

    GET:  Show upload form.
    POST: Initiate upload (returns presigned URL via JSON).
    """
    if request.method == "GET":
        return render(request, "experiments/script_upload.html", {"active_nav": "experiments"})

    if request.method == "POST":
        # Check if this is a completion request (client uploaded to S3, now confirming)
        upload_token = request.POST.get("upload_token")
        if upload_token:
            try:
                script = services.complete_script_upload(cast("User", request.user), upload_token)
                messages.success(request, f"Script '{script.name}' uploaded successfully.")
                return redirect("experiments:script_list")
            except ScriptUploadError as e:
                messages.error(request, str(e))
                return redirect("experiments:script_upload")

        # Otherwise, initiate upload
        name = request.POST.get("name", "").strip()
        filename = request.POST.get("filename", "").strip()
        file_size = request.POST.get("file_size", "0")

        try:
            file_size_int = int(file_size)
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid file_size"}, status=400)

        try:
            result = services.initiate_script_upload(cast("User", request.user), name, filename, file_size_int)
            return JsonResponse(result)
        except ScriptUploadError as e:
            return JsonResponse({"error": str(e)}, status=400)

    return HttpResponse(status=405)


@staff_member_required
@require_POST
def script_delete(request: HttpRequest, script_id: int) -> HttpResponse:
    """Soft-delete a script."""
    try:
        services.delete_script(cast("User", request.user), script_id)
        messages.success(request, "Script deleted.")
    except ScriptUploadError as e:
        messages.error(request, str(e))
    return redirect("experiments:script_list")


# =============================================================================
# Experiment views
# =============================================================================


@staff_member_required
def experiment_list(request: HttpRequest) -> HttpResponse:
    """List user's experiments."""
    experiments = services.list_experiments(cast("User", request.user))
    return render(
        request,
        "experiments/experiment_list.html",
        {
            "active_nav": "experiments",
            "experiments": experiments,
        },
    )


@staff_member_required
def experiment_create(request: HttpRequest) -> HttpResponse:
    """Create a new experiment.

    GET:  Show creation form.
    POST: Validate and create experiment.
    """
    if request.method == "GET":
        from cms.scenarios.loader import list_scenario_ids, load_scenario

        scenarios = []
        for sid in list_scenario_ids():
            try:
                s = load_scenario(sid)
                scenarios.append({"id": s.id, "name": s.name, "description": s.description})
            except ValueError:
                continue
        scripts = services.list_scripts(cast("User", request.user))
        return render(
            request,
            "experiments/experiment_create.html",
            {
                "active_nav": "experiments",
                "scenarios": scenarios,
                "scripts": scripts,
            },
        )

    if request.method == "POST":
        try:
            # Parse script assignments from form
            scripts_json = request.POST.get("scripts_json", "[]")
            scripts_data = json.loads(scripts_json) if scripts_json else []

            data = ExperimentCreateInput(
                name=request.POST.get("name", ""),
                description=request.POST.get("description", ""),
                scenario_id=request.POST.get("scenario_id", ""),
                agent_id=int(request.POST["agent_id"]) if request.POST.get("agent_id") else None,
                total_runs=int(request.POST.get("total_runs", 1)),
                max_parallel_runs=int(request.POST.get("max_parallel_runs", 1)),
                scripts=scripts_data,
            )
        except (ValueError, json.JSONDecodeError, KeyError) as e:
            messages.error(request, f"Invalid input: {e}")
            return redirect("experiments:experiment_create")

        try:
            experiment = services.create_experiment(cast("User", request.user), data)
            messages.success(request, f"Experiment '{experiment.name}' created.")
            return redirect("experiments:experiment_detail", experiment_id=experiment.pk)
        except ExperimentValidationError as e:
            messages.error(request, str(e))
            return redirect("experiments:experiment_create")

    return HttpResponse(status=405)


@staff_member_required
def experiment_detail(request: HttpRequest, experiment_id: int) -> HttpResponse:
    """View experiment details and run status."""
    try:
        experiment = services.get_experiment(cast("User", request.user), experiment_id)
    except ExperimentError:
        messages.error(request, "Experiment not found.")
        return redirect("experiments:experiment_list")

    return render(
        request,
        "experiments/experiment_detail.html",
        {
            "active_nav": "experiments",
            "experiment": experiment,
        },
    )


@staff_member_required
@require_POST
def experiment_start(request: HttpRequest, experiment_id: int) -> HttpResponse:
    """Start experiment execution."""
    try:
        services.start_experiment(cast("User", request.user), experiment_id)
        messages.success(request, "Experiment queued for execution.")
    except ExperimentError as e:
        messages.error(request, str(e))
    except ExperimentStateError as e:
        messages.error(request, str(e))
    return redirect("experiments:experiment_detail", experiment_id=experiment_id)


@staff_member_required
@require_POST
def experiment_cancel(request: HttpRequest, experiment_id: int) -> HttpResponse:
    """Cancel a running experiment."""
    try:
        services.cancel_experiment(cast("User", request.user), experiment_id)
        messages.success(request, "Experiment cancelled.")
    except (ExperimentError, ExperimentStateError) as e:
        messages.error(request, str(e))
    return redirect("experiments:experiment_detail", experiment_id=experiment_id)


# =============================================================================
# Download views
# =============================================================================


@staff_member_required
def experiment_download(request: HttpRequest, experiment_id: int) -> HttpResponse:
    """Redirect to presigned download URL for experiment bundle."""
    try:
        url = services.get_bundle_download_url(cast("User", request.user), experiment_id)
        return redirect(url)
    except ArtifactError as e:
        messages.error(request, str(e))
        return redirect("experiments:experiment_detail", experiment_id=experiment_id)


@staff_member_required
def artifact_download(
    request: HttpRequest,
    experiment_id: int,
    run_number: int,
    artifact_id: int,
) -> HttpResponse:
    """Redirect to presigned download URL for a single artifact."""
    try:
        url = services.get_artifact_download_url(cast("User", request.user), experiment_id, artifact_id)
        return redirect(url)
    except ArtifactError as e:
        messages.error(request, str(e))
        return redirect("experiments:experiment_detail", experiment_id=experiment_id)


# =============================================================================
# AJAX endpoints
# =============================================================================


@staff_member_required
def scenario_instances(request: HttpRequest, scenario_id: str) -> JsonResponse:
    """Return instance list for a scenario (AJAX)."""
    try:
        instances = services.get_scenario_instances(scenario_id)
        return JsonResponse({"instances": instances})
    except ExperimentValidationError as e:
        return JsonResponse({"error": str(e)}, status=400)
