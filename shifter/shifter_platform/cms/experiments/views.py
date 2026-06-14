"""Experiment manager views.

All business logic is in experiments.services. Views handle HTTP only.
Views require staff or Threat Research group membership.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, cast

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from cms.experiments import services
from cms.experiments.exceptions import (
    ArtifactError,
    ExperimentError,
    ExperimentValidationError,
    ScriptUploadError,
)
from cms.experiments.schemas import ExperimentCreateInput
from shared.auth import threat_research_required
from shared.errors import classify_user_message
from shared.exceptions import CMSError
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


# =============================================================================
# Script views
# =============================================================================


@threat_research_required
def script_list(request: HttpRequest) -> HttpResponse:
    """List user's script assets."""
    logger.info("script_list: user_id=%s", request.user.id)
    try:
        scripts = services.list_scripts(cast("User", request.user))
        return render(
            request,
            "experiments/script_list.html",
            {
                "active_nav": "experiments",
                "scripts": scripts,
            },
        )
    except Exception:
        logger.exception(
            "script_list: unexpected error for user_id=%s",
            request.user.id,
        )
        messages.error(request, "An unexpected error occurred. Please try again.")
        return redirect("experiments:experiment_list")


def _complete_script_upload_post(request: HttpRequest, upload_token: str) -> HttpResponse:
    """Finalize a presigned script upload the client has confirmed."""
    try:
        script = services.complete_script_upload(cast("User", request.user), upload_token)
    except ScriptUploadError as e:
        messages.error(request, str(e))
        return redirect("experiments:script_upload")
    messages.success(request, f"Script '{script.name}' uploaded successfully.")
    return redirect("experiments:script_list")


def _initiate_script_upload_post(request: HttpRequest) -> HttpResponse:
    """Start a presigned script upload and return the presigned URL as JSON."""
    name = request.POST.get("name", "").strip()
    filename = request.POST.get("filename", "").strip()
    try:
        file_size_int = int(request.POST.get("file_size", "0"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Invalid file_size"}, status=400)
    try:
        result = services.initiate_script_upload(cast("User", request.user), name, filename, file_size_int)
    except ScriptUploadError as e:
        logger.exception("script_upload: initiation failed for user_id=%s", request.user.id)
        return JsonResponse(
            {"error": classify_user_message(str(e), default="Upload could not be initiated")}, status=400
        )
    return JsonResponse(result)


def _handle_script_upload_post(request: HttpRequest) -> HttpResponse:
    """Dispatch a script-upload POST to the completion or initiation path."""
    try:
        upload_token = request.POST.get("upload_token")
        if upload_token:
            return _complete_script_upload_post(request, upload_token)
        return _initiate_script_upload_post(request)
    except Exception:
        logger.exception("script_upload: unexpected error for user_id=%s", request.user.id)
        messages.error(request, "An unexpected error occurred. Please try again.")
        return redirect("experiments:experiment_list")


@threat_research_required
def script_upload(request: HttpRequest) -> HttpResponse:
    """Upload a script file — two-step presigned URL flow.

    GET:  Show upload form.
    POST: Initiate upload (returns presigned URL via JSON).
    """
    logger.info("script_upload: user_id=%s method=%s", request.user.id, safe_log_value(request.method))
    if request.method == "GET":
        return render(request, "experiments/script_upload.html", {"active_nav": "experiments"})
    if request.method == "POST":
        return _handle_script_upload_post(request)
    return HttpResponse(status=405)


@threat_research_required
@require_POST
def script_delete(request: HttpRequest, script_id: int) -> HttpResponse:
    """Soft-delete a script."""
    logger.info("script_delete: user_id=%s script_id=%s", request.user.id, safe_log_value(script_id))
    try:
        services.delete_script(cast("User", request.user), script_id)
        messages.success(request, "Script deleted.")
    except ScriptUploadError as e:
        messages.error(request, str(e))
    except Exception:
        logger.exception(
            "script_delete: unexpected error for user_id=%s",
            request.user.id,
        )
        messages.error(request, "An unexpected error occurred. Please try again.")
    return redirect("experiments:script_list")


# =============================================================================
# Experiment views
# =============================================================================


@threat_research_required
def experiment_list(request: HttpRequest) -> HttpResponse:
    """List user's experiments."""
    logger.info("experiment_list: user_id=%s", request.user.id)
    try:
        experiments_qs = services.list_experiments(cast("User", request.user))
        paginator = Paginator(experiments_qs, 25)
        page = paginator.get_page(request.GET.get("page"))
        return render(
            request,
            "experiments/experiment_list.html",
            {
                "active_nav": "experiments",
                "experiments": page,
            },
        )
    except Exception:
        logger.exception(
            "experiment_list: unexpected error for user_id=%s",
            request.user.id,
        )
        messages.error(request, "An unexpected error occurred. Please try again.")
        return redirect("experiments:experiment_list")


def _validate_experiment_create_input(request: HttpRequest) -> ExperimentCreateInput:
    """Parse and validate the experiment-create form into an ExperimentCreateInput.

    Raises ExperimentValidationError (with a user-facing message) on malformed
    JSON, missing fields, or Pydantic validation failures.
    """
    from cms.scenarios.registry import load_scenario_template

    try:
        scripts_json = request.POST.get("scripts_json", "[]")
        scripts_data = json.loads(scripts_json) if scripts_json else []

        scenario_id = request.POST.get("scenario_id", "")
        try:
            scenario = load_scenario_template(scenario_id)
            instance_names = {inst.name for inst in scenario.instances}
        except (ValueError, CMSError):
            instance_names = set()

        input_data = {
            "name": request.POST.get("name", ""),
            "description": request.POST.get("description", ""),
            "scenario_id": scenario_id,
            "agent_id": int(request.POST["agent_id"]) if request.POST.get("agent_id") else None,
            "total_runs": int(request.POST.get("total_runs", 1)),
            "max_parallel_runs": int(request.POST.get("max_parallel_runs", 1)),
            "scripts": scripts_data,
        }
        return ExperimentCreateInput.model_validate(input_data, context={"instance_names": instance_names})
    except (json.JSONDecodeError, KeyError) as exc:
        raise ExperimentValidationError(f"Invalid input: {exc}") from exc
    except ValueError as exc:
        from pydantic import ValidationError as PydanticValidationError

        if isinstance(exc, PydanticValidationError):
            field_errors = "; ".join(f"{err['loc'][-1]}: {err['msg']}" for err in exc.errors() if err.get("loc"))
            raise ExperimentValidationError(f"Validation error: {field_errors or exc}") from exc
        raise ExperimentValidationError(f"Invalid input: {exc}") from exc


def _handle_experiment_create_post(request: HttpRequest) -> HttpResponse:
    """Validate the form, create the experiment, and redirect appropriately."""
    try:
        data = _validate_experiment_create_input(request)
        experiment = services.create_experiment(cast("User", request.user), data)
    except ExperimentValidationError as e:
        messages.error(request, str(e))
        return redirect("experiments:experiment_create")
    except Exception:
        logger.exception("experiment_create: unexpected error for user_id=%s", request.user.id)
        messages.error(request, "An unexpected error occurred. Please try again.")
        return redirect("experiments:experiment_list")
    messages.success(request, f"Experiment '{experiment.name}' created.")
    return redirect("experiments:experiment_detail", experiment_id=experiment.pk)


@threat_research_required
def experiment_create(request: HttpRequest) -> HttpResponse:
    """Create a new experiment.

    GET:  Show creation form.
    POST: Validate and create experiment.
    """
    logger.info("experiment_create: user_id=%s method=%s", request.user.id, safe_log_value(request.method))
    if request.method == "GET":
        from cms.scenarios.registry import list_all_scenarios

        scenarios = list_all_scenarios(user=cast("User", request.user))
        return render(
            request,
            "experiments/experiment_create.html",
            {
                "active_nav": "experiments",
                "scenarios": scenarios,
            },
        )

    if request.method == "POST":
        return _handle_experiment_create_post(request)

    return HttpResponse(status=405)


@threat_research_required
def experiment_detail(request: HttpRequest, experiment_id: int) -> HttpResponse:
    """View experiment details and run status."""
    logger.info("experiment_detail: user_id=%s experiment_id=%s", request.user.id, safe_log_value(experiment_id))
    try:
        experiment = services.get_experiment(cast("User", request.user), experiment_id)
    except ExperimentError:
        messages.error(request, "Experiment not found.")
        return redirect("experiments:experiment_list")
    except Exception:
        logger.exception(
            "experiment_detail: unexpected error for user_id=%s",
            request.user.id,
        )
        messages.error(request, "An unexpected error occurred. Please try again.")
        return redirect("experiments:experiment_list")

    return render(
        request,
        "experiments/experiment_detail.html",
        {
            "active_nav": "experiments",
            "experiment": experiment,
        },
    )


@threat_research_required
@require_POST
def experiment_start(request: HttpRequest, experiment_id: int) -> HttpResponse:
    """Start experiment execution."""
    logger.info("experiment_start: user_id=%s experiment_id=%s", request.user.id, safe_log_value(experiment_id))
    try:
        services.start_experiment(cast("User", request.user), experiment_id)
        messages.success(request, "Experiment queued for execution.")
    except ExperimentError as e:
        # ExperimentStateError subclasses ExperimentError, so this single
        # handler covers both; a separate ExperimentStateError clause would be
        # unreachable (SonarCloud S2190 / duplicate-except).
        messages.error(request, str(e))
    except Exception:
        logger.exception(
            "experiment_start: unexpected error for user_id=%s",
            request.user.id,
        )
        messages.error(request, "An unexpected error occurred. Please try again.")
    return redirect("experiments:experiment_detail", experiment_id=experiment_id)


@threat_research_required
@require_POST
def experiment_cancel(request: HttpRequest, experiment_id: int) -> HttpResponse:
    """Cancel a running experiment."""
    logger.info("experiment_cancel: user_id=%s experiment_id=%s", request.user.id, safe_log_value(experiment_id))
    try:
        services.cancel_experiment(cast("User", request.user), experiment_id)
        messages.success(request, "Experiment cancelled.")
    except ExperimentError as e:
        # ExperimentStateError subclasses ExperimentError, so this single handler
        # covers both; listing both would be redundant (SonarCloud S5713).
        messages.error(request, str(e))
    except Exception:
        logger.exception(
            "experiment_cancel: unexpected error for user_id=%s",
            request.user.id,
        )
        messages.error(request, "An unexpected error occurred. Please try again.")
    return redirect("experiments:experiment_detail", experiment_id=experiment_id)


# =============================================================================
# Download views
# =============================================================================


@threat_research_required
def experiment_download(request: HttpRequest, experiment_id: int) -> HttpResponse:
    """Redirect to presigned download URL for experiment bundle."""
    logger.info("experiment_download: user_id=%s experiment_id=%s", request.user.id, safe_log_value(experiment_id))
    try:
        url = services.get_bundle_download_url(cast("User", request.user), experiment_id)
        return redirect(url)
    except ArtifactError as e:
        messages.error(request, str(e))
        return redirect("experiments:experiment_detail", experiment_id=experiment_id)
    except Exception:
        logger.exception(
            "experiment_download: unexpected error for user_id=%s",
            request.user.id,
        )
        messages.error(request, "An unexpected error occurred. Please try again.")
        return redirect("experiments:experiment_list")


@threat_research_required
def artifact_download(
    request: HttpRequest,
    experiment_id: int,
    run_number: int,
    artifact_id: int,
) -> HttpResponse:
    """Redirect to presigned download URL for a single artifact."""
    logger.info(
        "artifact_download: user_id=%s experiment_id=%s artifact_id=%s",
        request.user.id,
        safe_log_value(experiment_id),
        safe_log_value(artifact_id),
    )
    try:
        url = services.get_artifact_download_url(cast("User", request.user), experiment_id, artifact_id)
        return redirect(url)
    except ArtifactError as e:
        messages.error(request, str(e))
        return redirect("experiments:experiment_detail", experiment_id=experiment_id)
    except Exception:
        logger.exception(
            "artifact_download: unexpected error for user_id=%s",
            request.user.id,
        )
        messages.error(request, "An unexpected error occurred. Please try again.")
        return redirect("experiments:experiment_list")


# =============================================================================
# AJAX endpoints
# =============================================================================


@threat_research_required
def scenario_instances(request: HttpRequest, scenario_id: str) -> JsonResponse:
    """Return instance list for a scenario (AJAX)."""
    logger.info("scenario_instances: user_id=%s scenario_id=%s", request.user.id, safe_log_value(scenario_id))
    try:
        instances = services.get_scenario_instances(scenario_id, user=cast("User", request.user))
        return JsonResponse({"instances": instances})
    except ExperimentValidationError as e:
        logger.exception("scenario_instances: validation error for scenario_id=%s", safe_log_value(scenario_id))
        return JsonResponse({"error": classify_user_message(str(e), default="Invalid scenario request")}, status=400)
    except Exception:
        logger.exception("scenario_instances: unexpected error")
        return JsonResponse({"error": "An unexpected error occurred."}, status=500)
