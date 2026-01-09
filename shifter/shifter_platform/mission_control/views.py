"""Mission Control views."""

import json
import logging
import os
from typing import cast

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from cms import cancel_range as cms_cancel_range
from cms import cancel_upload as cms_cancel_upload
from cms import complete_upload as cms_complete_upload
from cms import create_credential as cms_create_credential
from cms import create_range as cms_create_range
from cms import delete_agent as cms_delete_agent
from cms import delete_credential as cms_delete_credential
from cms import destroy_range as cms_destroy_range
from cms import get_active_range, get_allowed_extensions
from cms import get_credential as cms_get_credential
from cms import initiate_upload as cms_initiate_upload
from cms import list_agents as cms_list_agents
from cms import list_credentials as cms_list_credentials
from cms import list_ngfws as cms_list_ngfws
from cms import list_scenarios as cms_list_scenarios
from cms.services import create_ngfw as cms_create_ngfw
from cms.services import destroy_ngfw as cms_destroy_ngfw
from cms.services import get_ngfw as cms_get_ngfw
from mission_control.upload_session import (
    check_upload_in_progress,
    set_upload_in_progress,
)
from mission_control.utils import build_connection_urls
from shared.exceptions import AssetError, CMSError

logger = logging.getLogger(__name__)

# Error message constants
_NGFW_NOT_FOUND = "NGFW not found"


def _get_user(request: HttpRequest) -> User:
    """Get authenticated user from request. Use only in @login_required views."""
    assert request.user.is_authenticated, "View must use @login_required"
    return cast(User, request.user)


@login_required
@require_GET
def dashboard(request):
    """Main dashboard - launch and manage ranges."""
    context = {
        "page_title": "Dashboard",
        "active_nav": "dashboard",
        "provisioning_timeout_ms": django_settings.PROVISIONING_TIMEOUT_MS,
    }
    return render(request, "mission_control/dashboard.html", context)


@login_required
@require_GET
def agents(request):
    """Agent management - upload and manage XDR/XSIAM agents."""

    context = {
        "page_title": "Agents",
        "active_nav": "agents",
        "agents": cms_list_agents(request.user),
        "allowed_extensions": ", ".join(get_allowed_extensions()),
    }
    return render(request, "mission_control/agents.html", context)


@login_required
@require_POST
def delete_agent(request, agent_id):
    """Handle agent deletion (soft delete)."""
    try:
        cms_delete_agent(request.user, agent_id)
        messages.success(request, "Agent deleted.")
        logger.info("Agent deleted: user=%s agent_id=%s", request.user.email, agent_id)
    except (CMSError, AssetError) as e:
        messages.error(request, str(e))
        logger.error(
            "Agent delete error: user=%s agent_id=%s error=%s",
            request.user.email,
            agent_id,
            str(e),
        )

    return redirect("mission_control:agents")


@login_required
@require_GET
def terminal(request):
    """Terminal - SSH access to range instances.

    Uses active_range and has_active_range from context processor.
    Template accesses active_range.range_id for WebSocket connection.
    """
    context = {
        "page_title": "Terminal",
        "active_nav": "terminal",
    }
    return render(request, "mission_control/terminal.html", context)


@login_required
@require_GET
def settings(request):
    """Account settings."""
    context = {
        "page_title": "Settings",
        "active_nav": "settings",
    }
    return render(request, "mission_control/settings.html", context)


@login_required
@require_GET
def help_page(request):
    """Help and documentation."""
    context = {
        "page_title": "Help",
        "active_nav": "help",
        "support_email": django_settings.SHIFTER_SUPPORT_EMAIL,
    }
    return render(request, "mission_control/help.html", context)


# -----------------------------------------------------------------------------
# Presigned URL Upload API
# -----------------------------------------------------------------------------


@login_required
@require_POST
def initiate_upload(request):
    """
    Step 1: Request presigned URL for direct S3 upload.

    Request body (JSON):
        - name: Agent name (required)
        - filename: Original filename (required)
        - file_size: File size in bytes (required)

    Response (JSON):
        - presigned_url: URL for PUT request to S3
        - s3_key: Key that will be created
        - upload_token: Signed token for completion verification
    """
    # Check for concurrent upload (session-level lock)
    if check_upload_in_progress(request.session):
        return JsonResponse(
            {"error": "An upload is already in progress. Please wait for it to complete."},
            status=409,
        )

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    name = data.get("name", "").strip()
    filename = data.get("filename", "").strip()
    file_size = data.get("file_size", 0)

    # Basic input validation
    if not name:
        return JsonResponse({"error": "Agent name is required"}, status=400)
    if not filename:
        return JsonResponse({"error": "Filename is required"}, status=400)
    if not isinstance(file_size, int) or file_size <= 0:
        return JsonResponse({"error": "Valid file size is required"}, status=400)

    # Sanitize filename
    filename = os.path.basename(filename)

    try:
        result = cms_initiate_upload(request.user, name, filename, file_size)
    except CMSError as e:
        return JsonResponse({"error": str(e)}, status=400)

    # Mark upload in progress
    set_upload_in_progress(request.session, True)

    logger.info(
        "Upload initiated: user=%s filename=%s size=%d",
        request.user.email,
        filename,
        file_size,
    )

    return JsonResponse(result)


@login_required
@require_POST
def complete_upload(request):
    """
    Step 3: Complete upload after file is in S3.

    Request body (JSON):
        - upload_token: Token from initiate response

    Response (JSON):
        - success: true
        - agent_id: Created agent ID
        - message: Success message
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    upload_token = data.get("upload_token", "")

    try:
        agent = cms_complete_upload(request.user, upload_token)
    except CMSError as e:
        set_upload_in_progress(request.session, False)
        return JsonResponse({"error": str(e)}, status=400)

    # Clear upload in progress
    set_upload_in_progress(request.session, False)

    logger.info("Upload completed: user=%s agent_id=%s", request.user.email, agent.id)

    return JsonResponse(
        {
            "success": True,
            "agent_id": agent.id,
            "message": f"Agent '{agent.name}' uploaded successfully.",
        }
    )


@csrf_exempt  # Allow sendBeacon on page unload (no custom headers)
@login_required
@require_POST
def cancel_upload(request):
    """
    Cancel an in-progress upload.

    Request body (JSON):
        - upload_token: Token from initiate response (optional)

    Cleans up S3 object if it exists and clears upload lock.

    Note: CSRF exempt to support navigator.sendBeacon() on page unload.
    Security maintained via @login_required and HMAC-signed upload_token.
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        data = {}

    upload_token = data.get("upload_token", "")

    # Try to clean up S3 object if token provided
    if upload_token:
        try:
            cms_cancel_upload(request.user, upload_token)
            logger.info("Cancelled upload cleaned up: user=%s", request.user.email)
        except CMSError:
            pass  # Invalid token or S3 error, ignore

    # Clear upload in progress
    set_upload_in_progress(request.session, False)

    return JsonResponse({"success": True})


# -----------------------------------------------------------------------------
# Range API
# -----------------------------------------------------------------------------


@login_required
@require_GET
def get_range(request):
    """
    Get the current user's active range.

    Response (JSON):
        - has_range: true/false
        - range: RangeContext object (if exists)
    """
    active_range = get_active_range(request.user)

    if not active_range:
        return JsonResponse({"has_range": False, "range": None, "connection_urls": []})

    return JsonResponse(
        {
            "has_range": True,
            "range": active_range.model_dump(mode="json"),
            "connection_urls": build_connection_urls(active_range.instances),
        }
    )


@login_required
@require_POST
def launch_range(request):
    """
    Launch a new cyber range.

    Request body (JSON):
        - agent_id: ID of agent to use for victim instances
        - scenario: Scenario type (basic, ad_attack_lab). Defaults to basic.
        - dc_agent_id: ID of Windows agent for DC (required for ad_attack_lab)

    Response (JSON):
        - success: true
        - range: Range object
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    agent_id = data.get("agent_id")
    if not agent_id:
        return JsonResponse({"error": "agent_id is required"}, status=400)

    scenario = data.get("scenario", "basic")
    valid_scenarios = {s["id"] for s in cms_list_scenarios(request.user)}
    if scenario not in valid_scenarios:
        return JsonResponse({"error": "Invalid scenario"}, status=400)

    try:
        range_ctx = cms_create_range(
            request.user,
            scenario,
            agent_id,
        )
    except CMSError as e:
        return JsonResponse({"error": str(e)}, status=400)

    logger.info(
        "Range launched: user=%s range_id=%s agent=%s scenario=%s",
        request.user.email,
        range_ctx.range_id,
        range_ctx.agent_name,
        scenario,
    )

    return JsonResponse(
        {
            "success": True,
            "range": range_ctx.model_dump(mode="json"),
        }
    )


@login_required
@require_POST
def cancel_range(request):
    """
    Cancel a provisioning range.

    Request body (JSON):
        - range_id: ID of range to cancel

    Only works for ranges in PENDING or PROVISIONING status.
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    range_id = data.get("range_id")
    if not range_id:
        return JsonResponse({"error": "range_id is required"}, status=400)

    try:
        cms_cancel_range(request.user, range_id)
    except CMSError as e:
        return JsonResponse({"error": str(e)}, status=400)

    logger.info("Range cancelled: user=%s range_id=%s", request.user.email, range_id)

    return JsonResponse({"success": True})


@login_required
@require_POST
def destroy_range(request):
    """
    Destroy an active, paused, or failed range.

    Request body (JSON):
        - range_id: ID of range to destroy

    Sets status to DESTROYING and triggers async resource cleanup.
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    range_id = data.get("range_id")
    if not range_id:
        return JsonResponse({"error": "range_id is required"}, status=400)

    try:
        cms_destroy_range(request.user, range_id)
    except CMSError as e:
        return JsonResponse({"error": str(e)}, status=400)

    logger.info("Range destroyed: user=%s range_id=%s", request.user.email, range_id)

    return JsonResponse({"success": True})


@login_required
@require_GET
def list_agents(request):
    """
    Get user's agents.

    Response (JSON):
        - agents: List of {id, name, os_name, os_slug, file_size_mb, original_filename, created_at}

    The os_slug field allows frontend to filter agents by OS type
    (e.g., 'windows' for DC agent dropdown in AD scenarios).
    """
    agents = cms_list_agents(request.user)
    return JsonResponse({"agents": agents})


# -----------------------------------------------------------------------------
# NGFW Views
# -----------------------------------------------------------------------------


@login_required
@require_GET
def ngfw_list(request: HttpRequest) -> HttpResponse:
    """List user's NGFWs."""
    ngfws = cms_list_ngfws(request.user)
    context = {
        "page_title": "NGFWs",
        "active_nav": "ngfw",
        "ngfws": ngfws,
    }
    return render(request, "mission_control/ngfw/list.html", context)


@login_required
@require_GET
def ngfw_detail(request: HttpRequest, app_id: str) -> HttpResponse:
    """View NGFW details."""
    user = _get_user(request)
    try:
        ngfw = cms_get_ngfw(user, app_id)
    except CMSError:
        raise Http404(_NGFW_NOT_FOUND) from None

    context = {
        "page_title": ngfw.name,
        "active_nav": "ngfw",
        "ngfw": ngfw,
    }
    return render(request, "mission_control/ngfw/detail.html", context)


@login_required
@require_GET
def ngfw_wizard(request: HttpRequest) -> HttpResponse:
    """NGFW setup wizard."""
    credentials = cms_list_credentials(request.user)

    # Filter by type and exclude expired (is_expired computed field)
    scm_credentials = [c for c in credentials if c.credential_type == "scm" and not c.is_expired]
    deployment_profiles = [c for c in credentials if c.credential_type == "deployment_profile" and not c.is_expired]

    context = {
        "page_title": "Setup NGFW",
        "active_nav": "ngfw",
        "scm_credentials": scm_credentials,
        "deployment_profiles": deployment_profiles,
    }
    return render(request, "mission_control/ngfw/wizard.html", context)


@login_required
@require_GET
def ngfw_deprovision(request: HttpRequest, app_id: str) -> HttpResponse:
    """NGFW deprovision confirmation page."""
    user = _get_user(request)
    try:
        ngfw = cms_get_ngfw(user, app_id)
    except CMSError:
        raise Http404(_NGFW_NOT_FOUND) from None

    context = {
        "page_title": f"Deprovision {ngfw.name}",
        "active_nav": "ngfw",
        "ngfw": ngfw,
    }
    return render(request, "mission_control/ngfw/deprovision.html", context)


# -----------------------------------------------------------------------------
# NGFW API
# -----------------------------------------------------------------------------


@login_required
@require_POST
def api_ngfw_create(request: HttpRequest) -> JsonResponse:
    """Create a new NGFW."""
    user = _get_user(request)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    name = data.get("name", "").strip()
    deployment_profile_id = data.get("deployment_profile_id")
    registration_method = data.get("registration_method")
    scm_credential_id = data.get("scm_credential_id")
    otp_value = data.get("otp_value", "").strip() if data.get("otp_value") else None
    otp_folder = data.get("otp_folder", "").strip() if data.get("otp_folder") else None

    # Convert string IDs to int (HTML forms send strings)
    if deployment_profile_id:
        deployment_profile_id = int(deployment_profile_id)
    if scm_credential_id:
        scm_credential_id = int(scm_credential_id)

    try:
        ngfw_ref = cms_create_ngfw(
            user=user,
            name=name,
            deployment_profile_id=deployment_profile_id,
            registration_method=registration_method,
            scm_credential_id=scm_credential_id,
            otp_value=otp_value,
            otp_folder=otp_folder,
        )
    except (TypeError, ValueError) as e:
        return JsonResponse({"error": str(e)}, status=400)
    except CMSError as e:
        return JsonResponse({"error": str(e)}, status=400)

    logger.info(
        "NGFW provisioning started: user=%s app_id=%s",
        user.email,
        ngfw_ref.app_id,
    )

    return JsonResponse(
        {"id": str(ngfw_ref.app_id), "name": name, "status": "provisioning"},
        status=201,
    )


@login_required
@require_GET
def api_ngfw_list(request: HttpRequest) -> JsonResponse:
    """List user's NGFWs."""
    ngfws = cms_list_ngfws(request.user)
    return JsonResponse(
        {
            "ngfws": [
                {
                    "id": str(n.app_id),
                    "name": n.name,
                    "status": n.status,
                    "created_at": n.created_at.isoformat(),
                    "serial_number": n.serial_number,
                }
                for n in ngfws
            ]
        }
    )


@login_required
@require_POST
def api_ngfw_destroy(request: HttpRequest, app_id: str) -> JsonResponse:
    """Destroy an NGFW."""
    user = _get_user(request)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    confirm_name = data.get("confirm_name", "").strip()

    try:
        cms_destroy_ngfw(user, app_id, confirm_name)
    except CMSError as e:
        if "not found" in str(e).lower():
            raise Http404(_NGFW_NOT_FOUND) from None
        return JsonResponse({"error": str(e)}, status=400)
    except ValueError as e:
        return JsonResponse({"error": str(e)}, status=400)

    logger.info("NGFW deprovisioning started: user=%s app_id=%s", user.email, app_id)
    return JsonResponse({"status": "deprovisioning"})


# -----------------------------------------------------------------------------
# Credential Views
# -----------------------------------------------------------------------------


@login_required
@require_GET
def credentials_list(request):
    """List user's credentials."""
    credentials = cms_list_credentials(request.user)

    scm_count = sum(1 for c in credentials if c.credential_type == "scm")
    profile_count = sum(1 for c in credentials if c.credential_type == "deployment_profile")

    context = {
        "page_title": "Credentials",
        "active_nav": "credentials",
        "credentials": credentials,
        "scm_count": scm_count,
        "profile_count": profile_count,
    }
    return render(request, "mission_control/credentials/list.html", context)


@login_required
@require_GET
def credential_detail(request, credential_id):
    """View credential details."""
    try:
        credential = cms_get_credential(request.user, credential_id)
    except CMSError:
        raise Http404("Credential not found") from None

    context = {
        "page_title": credential.name,
        "active_nav": "credentials",
        "credential": credential,
    }
    return render(request, "mission_control/credentials/detail.html", context)


@login_required
@require_GET
def credential_add(request):
    """Add credential form (unified page with type selector)."""
    context = {
        "page_title": "Add Credential",
        "active_nav": "credentials",
    }
    return render(request, "mission_control/credentials/add.html", context)


# -----------------------------------------------------------------------------
# Credential API
# -----------------------------------------------------------------------------


@login_required
@require_POST
def api_credential_create(request):
    """Create a new credential.

    Accepts JSON with credential_type ('scm' or 'deployment_profile') and
    type-specific fields. Validates via Pydantic specs, creates via service.
    """
    from pydantic import ValidationError as PydanticValidationError

    from shared.schemas import DeploymentProfileSpec, SCMCredentialSpec

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    credential_type_slug = data.get("credential_type")
    if credential_type_slug not in ("scm", "deployment_profile"):
        return JsonResponse(
            {"error": f"Invalid credential type: {credential_type_slug}"},
            status=400,
        )

    # Add user_id for spec validation
    data["user_id"] = request.user.id

    # Select spec class based on type
    spec_class = SCMCredentialSpec if credential_type_slug == "scm" else DeploymentProfileSpec

    # Validate with Pydantic spec
    try:
        spec = spec_class.model_validate(data)
    except PydanticValidationError as e:
        errors = e.errors()
        return JsonResponse(
            {"error": errors[0]["msg"] if errors else "Validation failed"},
            status=400,
        )

    # Build kwargs for service (exclude user_id, service adds that)
    kwargs = spec.model_dump(exclude={"user_id"})

    try:
        cred_ref = cms_create_credential(
            request.user,
            credential_type_slug,
            **kwargs,
        )
    except (CMSError, ValueError) as e:
        return JsonResponse({"error": str(e)}, status=400)
    except ValidationError as e:
        # Django constraint violations (e.g., duplicate name)
        msg = e.message_dict.get("__all__", [str(e)])[0] if hasattr(e, "message_dict") else str(e)
        if "unique_active_credential_name_per_user" in msg:
            msg = "A credential with this name already exists"
        return JsonResponse({"error": msg}, status=400)

    logger.info(
        "Credential created: user=%s credential_id=%s type=%s",
        request.user.email,
        cred_ref.credential_id,
        credential_type_slug,
    )

    return JsonResponse(
        {
            "id": cred_ref.credential_id,
            "name": spec.name,
            "credential_type": credential_type_slug,
        },
        status=201,
    )


@login_required
@require_POST
def api_credential_delete(request, credential_id):
    """Soft-delete a credential."""
    try:
        cms_delete_credential(request.user, credential_id)
    except CMSError:
        raise Http404("Credential not found") from None

    logger.info(
        "Credential deleted: user=%s credential_id=%s",
        request.user.email,
        credential_id,
    )

    return JsonResponse({"success": True})
