"""Mission Control views."""

import json
import logging
import os

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from cms.assets.services import AssetError, get_storage_used
from cms.assets.services import create_agent as cms_create_agent
from cms.assets.services import delete_agent as cms_delete_agent
from cms.assets.upload_session import check_upload_in_progress, set_upload_in_progress
from cms.models import Credential
from cms.services import list_scenarios as cms_list_scenarios
from engine.services.allocation import AllocationError
from engine.services.orchestration import OrchestrationError, cancel, destroy, launch
from engine.services.scenarios import ScenarioValidationError
from engine.services.serialization import range_to_dict

from .models import AgentConfig, Range, UserNGFW
from .services.s3 import (
    S3Error,
    generate_presigned_upload_url,
    tag_s3_object,
    verify_s3_object_exists,
)
from .services.s3 import (
    delete_agent as s3_delete,
)
from .services.s3 import (
    upload_agent as s3_upload,
)
from .services.upload_token import generate_upload_token, verify_upload_token
from .services.validation import (
    ValidationError,
    get_allowed_extensions,
    validate_agent_file,
    validate_file_extension,
)

logger = logging.getLogger(__name__)


@login_required
@require_GET
def dashboard(request):
    """Main dashboard - launch and manage ranges."""
    context = {
        "page_title": "Dashboard",
        "active_nav": "dashboard",
    }
    return render(request, "mission_control/dashboard.html", context)


@login_required
@require_GET
def agents(request):
    """Agent management - upload and manage XDR/XSIAM agents."""
    user_agents = AgentConfig.active_for_user(request.user).select_related("os")

    context = {
        "page_title": "Agents",
        "active_nav": "agents",
        "agents": user_agents,
        "allowed_extensions": ", ".join(get_allowed_extensions()),
    }
    return render(request, "mission_control/agents.html", context)


@login_required
@require_POST
def upload_agent(request):
    """Handle agent file upload."""
    name = request.POST.get("name", "").strip()
    uploaded_file = request.FILES.get("file")

    # Validate form inputs
    if not name:
        messages.error(request, "Agent name is required.")
        return redirect("mission_control:agents")

    if not uploaded_file:
        messages.error(request, "No file was uploaded.")
        return redirect("mission_control:agents")

    # Sanitize filename - strip path components
    original_filename = os.path.basename(uploaded_file.name)

    try:
        # Validate file (size, extension, magic bytes)
        file_format = validate_agent_file(uploaded_file, original_filename)

        # Upload to S3
        s3_key, sha256_hash, file_size = s3_upload(uploaded_file, request.user.id, original_filename)

        # Create agent record via CMS service
        agent = cms_create_agent(
            user=request.user,
            name=name,
            s3_key=s3_key,
            filename=original_filename,
            os_slug=file_format.os_slug,
            file_size=file_size,
            sha256=sha256_hash,
        )

        messages.success(request, f"Agent '{name}' uploaded successfully.")
        logger.info(
            "Agent uploaded: user=%s agent_id=%s filename=%s",
            request.user.email,
            agent.id,
            original_filename,
        )

    except ValidationError as e:
        messages.error(request, str(e))
        logger.warning(
            "Agent upload validation failed: user=%s error=%s",
            request.user.email,
            str(e),
        )
    except AssetError as e:
        messages.error(request, str(e))
        logger.error(
            "Agent creation failed: user=%s error=%s",
            request.user.email,
            str(e),
        )
    except S3Error as e:
        messages.error(request, "Failed to upload file. Please try again.")
        logger.error(
            "Agent upload S3 error: user=%s error=%s",
            request.user.email,
            str(e),
        )

    return redirect("mission_control:agents")


@login_required
@require_POST
def delete_agent(request, agent_id):
    """Handle agent deletion (soft delete)."""
    agent = get_object_or_404(AgentConfig, id=agent_id, user=request.user, deleted_at__isnull=True)

    try:
        cms_delete_agent(agent)

        messages.success(request, f"Agent '{agent.name}' deleted.")
        logger.info(
            "Agent deleted: user=%s agent_id=%s agent_name=%s",
            request.user.email,
            agent.id,
            agent.name,
        )

    except AssetError as e:
        messages.error(request, "Failed to delete agent. Please try again.")
        logger.error(
            "Agent delete error: user=%s agent_id=%s error=%s",
            request.user.email,
            agent.id,
            str(e),
        )

    return redirect("mission_control:agents")


@login_required
@require_GET
def terminal(request):
    """Terminal - SSH access to range instances."""
    # Get user's active range (may be None or not ready)
    active_range = Range.get_active_for_user(request.user)

    # Check if range is ready for terminal access
    range_ready = active_range and active_range.status == Range.Status.READY

    context = {
        "page_title": "Terminal",
        "active_nav": "terminal",
        "range": active_range if range_ready else None,
        "range_id": active_range.id if range_ready else None,
        "range_ready": range_ready,
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
    # Check for concurrent upload
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

    # Validate inputs
    if not name:
        return JsonResponse({"error": "Agent name is required"}, status=400)
    if not filename:
        return JsonResponse({"error": "Filename is required"}, status=400)
    if not isinstance(file_size, int) or file_size <= 0:
        return JsonResponse({"error": "Valid file size is required"}, status=400)

    # Sanitize filename
    filename = os.path.basename(filename)

    # Check file size limit (per file)
    max_bytes = django_settings.AGENT_MAX_FILE_SIZE_MB * 1024 * 1024
    if file_size > max_bytes:
        return JsonResponse(
            {
                "error": f"File size ({file_size / 1024 / 1024:.1f} MB) exceeds "
                f"maximum allowed ({django_settings.AGENT_MAX_FILE_SIZE_MB} MB)"
            },
            status=400,
        )

    # Check user storage quota
    current_usage = get_storage_used(request.user)
    quota_bytes = django_settings.AGENT_USER_STORAGE_QUOTA_MB * 1024 * 1024
    if current_usage + file_size > quota_bytes:
        available_mb = (quota_bytes - current_usage) / 1024 / 1024
        return JsonResponse(
            {
                "error": f"Storage quota exceeded. You have {available_mb:.1f} MB available "
                f"of {django_settings.AGENT_USER_STORAGE_QUOTA_MB} MB total."
            },
            status=400,
        )

    # Validate extension
    try:
        file_format = validate_file_extension(filename)
    except ValidationError as e:
        return JsonResponse({"error": str(e)}, status=400)

    # Generate presigned URL
    try:
        presigned_url, s3_key = generate_presigned_upload_url(
            user_id=request.user.id,
            filename=filename,
        )
    except S3Error as e:
        logger.error(f"Failed to generate presigned URL: {e}")
        return JsonResponse({"error": "Failed to initiate upload"}, status=500)

    # Generate upload token
    upload_token = generate_upload_token(
        user_id=request.user.id,
        s3_key=s3_key,
        name=name,
        filename=filename,
        os_slug=file_format.os_slug,
        file_size=file_size,
    )

    # Mark upload in progress
    set_upload_in_progress(request.session, True)

    logger.info(
        "Upload initiated: user=%s filename=%s size=%d",
        request.user.email,
        filename,
        file_size,
    )

    return JsonResponse(
        {
            "presigned_url": presigned_url,
            "s3_key": s3_key,
            "upload_token": upload_token,
            "expected_os": file_format.os_slug,
        }
    )


@login_required
@require_POST
def complete_upload(request):
    """
    Step 3: Complete upload after file is in S3.

    Request body (JSON):
        - upload_token: Token from initiate response
        - sha256_hash: Client-computed SHA256 of uploaded file (optional)

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
    client_sha256 = data.get("sha256_hash", "")

    # Verify and decode token
    try:
        token_data = verify_upload_token(upload_token, request.user.id)
    except ValueError as e:
        set_upload_in_progress(request.session, False)
        return JsonResponse({"error": str(e)}, status=400)

    s3_key = token_data["s3_key"]
    name = token_data["name"]
    filename = token_data["filename"]
    os_slug = token_data["os_slug"]

    # Validate S3 key belongs to this user (defense in depth)
    expected_prefix = f"agents/{request.user.id}/"
    if not s3_key.startswith(expected_prefix):
        set_upload_in_progress(request.session, False)
        logger.warning(
            "S3 key prefix mismatch: user=%s expected=%s got=%s",
            request.user.id,
            expected_prefix,
            s3_key[:50],
        )
        return JsonResponse({"error": "Invalid upload token"}, status=403)

    # Verify file exists in S3
    try:
        file_size, etag = verify_s3_object_exists(s3_key)
    except S3Error:
        set_upload_in_progress(request.session, False)
        logger.warning(f"Upload completion failed - file not found: {s3_key}")
        return JsonResponse({"error": "File not found in storage. Upload may have failed."}, status=400)

    # Tag object as completed (for lifecycle rule)
    try:
        tag_s3_object(s3_key, {"status": "completed", "user_id": str(request.user.id)})
    except S3Error as e:
        logger.warning(f"Failed to tag S3 object: {e}")
        # Non-fatal, continue

    # Create agent record via CMS service
    try:
        agent = cms_create_agent(
            user=request.user,
            name=name,
            s3_key=s3_key,
            filename=filename,
            os_slug=os_slug,
            file_size=file_size,
            sha256=client_sha256 or etag,  # Use client hash or ETag as fallback
            upload_method="presigned",
        )
    except AssetError as e:
        set_upload_in_progress(request.session, False)
        return JsonResponse({"error": str(e)}, status=400)

    # Clear upload in progress
    set_upload_in_progress(request.session, False)

    logger.info(
        "Upload completed: user=%s agent_id=%s filename=%s size=%d",
        request.user.email,
        agent.id,
        filename,
        file_size,
    )

    return JsonResponse(
        {
            "success": True,
            "agent_id": agent.id,
            "message": f"Agent '{name}' uploaded successfully.",
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
            token_data = verify_upload_token(upload_token, request.user.id)
            s3_key = token_data["s3_key"]
            try:
                s3_delete(s3_key)
                logger.info(f"Cancelled upload cleaned up: {s3_key}")
            except S3Error:
                pass  # Object may not exist yet
        except ValueError:
            pass  # Invalid token, ignore

    # Clear upload in progress
    set_upload_in_progress(request.session, False)

    return JsonResponse({"success": True})


# -----------------------------------------------------------------------------
# Range API
# -----------------------------------------------------------------------------


@login_required
@require_GET
def get_range_status(request):
    """
    Get the current user's active range status.

    Response (JSON):
        - has_range: true/false
        - range: Range object (if exists)
    """
    active_range = Range.get_active_for_user(request.user)

    if not active_range:
        return JsonResponse({"has_range": False, "range": None})

    return JsonResponse(
        {
            "has_range": True,
            "range": range_to_dict(active_range),
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

    # NGFW support is planned but not yet implemented with new models
    # For now, ngfw_enabled is always False
    ngfw_enabled = False

    try:
        range_obj = launch(
            request.user,
            agent_id,
            scenario,
            ngfw_enabled=ngfw_enabled,
        )
    except OrchestrationError as e:
        return JsonResponse({"error": str(e)}, status=e.status_code)
    except ScenarioValidationError as e:
        return JsonResponse({"error": str(e)}, status=e.status_code)
    except AllocationError as e:
        logger.error("Failed to allocate subnet index: %s", e)
        return JsonResponse(
            {"error": "No capacity available. Please try again later or destroy existing ranges."},
            status=503,
        )

    logger.info(
        "Range launched: user=%s range_id=%s agent=%s scenario=%s",
        request.user.email,
        range_obj.id,
        range_obj.agent.name,
        scenario,
    )

    return JsonResponse(
        {
            "success": True,
            "range": range_to_dict(range_obj),
        }
    )


@login_required
@require_POST
def cancel_range(request):
    """
    Cancel a provisioning range.

    Only works for ranges in PENDING or PROVISIONING status.
    """
    try:
        cancel(request.user)
    except OrchestrationError as e:
        return JsonResponse({"error": str(e)}, status=e.status_code)

    logger.info("Range cancelled: user=%s", request.user.email)

    return JsonResponse({"success": True})


@login_required
@require_POST
def destroy_range(request):
    """
    Destroy an active, paused, or failed range.

    Sets status to DESTROYING and triggers async resource cleanup.
    """
    try:
        destroy(request.user)
    except OrchestrationError as e:
        return JsonResponse({"error": str(e)}, status=e.status_code)

    logger.info("Range destroyed: user=%s", request.user.email)

    return JsonResponse({"success": True})


@login_required
@require_GET
def list_agents_for_launch(request):
    """
    Get user's agents for the launch dropdown.

    Response (JSON):
        - agents: List of {id, name, os_name, os_slug, file_size_mb}

    The os_slug field allows frontend to filter agents by OS type
    (e.g., 'windows' for DC agent dropdown in AD scenarios).
    """
    agents = AgentConfig.active_for_user(request.user).select_related("os")
    agent_list = [
        {
            "id": agent.id,
            "name": agent.name,
            "os_name": agent.os.name,
            "os_slug": agent.os.slug,
            "file_size_mb": agent.file_size_mb,
        }
        for agent in agents
    ]
    return JsonResponse({"agents": agent_list})


# -----------------------------------------------------------------------------
# NGFW Management Views
# -----------------------------------------------------------------------------


@login_required
@require_GET
def ngfw_list(request):
    """List user's NGFWs with status badges."""
    ngfws = UserNGFW.active_for_user(request.user)

    context = {
        "page_title": "NGFWs",
        "active_nav": "ngfw",
        "ngfws": ngfws,
    }
    return render(request, "mission_control/assets/ngfw/list.html", context)


@login_required
@require_GET
def ngfw_detail(request, ngfw_id):
    """Display NGFW details including AWS resources and linked ranges."""
    ngfw = get_object_or_404(
        UserNGFW,
        id=ngfw_id,
        user=request.user,
        deleted_at__isnull=True,
    )

    # Get ranges linked to this NGFW
    linked_ranges = Range.objects.filter(
        ngfw=ngfw,
        status__in=[
            Range.Status.PENDING,
            Range.Status.PROVISIONING,
            Range.Status.READY,
            Range.Status.PAUSED,
            Range.Status.RESUMING,
        ],
    )

    context = {
        "page_title": ngfw.name,
        "active_nav": "ngfw",
        "ngfw": ngfw,
        "linked_ranges": linked_ranges,
    }
    return render(request, "mission_control/assets/ngfw/detail.html", context)


@login_required
@require_GET
def ngfw_wizard(request):
    """Setup wizard for provisioning a new NGFW."""
    # TODO: migrate to CMS - move credential queries to cms.services
    # Get user's non-expired SCM credentials
    scm_credentials = Credential.active_for_user(request.user).filter(
        credential_type=Credential.Type.SCM, expires_at__isnull=True
    ) | Credential.active_for_user(request.user).filter(
        credential_type=Credential.Type.SCM, expires_at__gt=timezone.now()
    )

    # Get user's deployment profiles (non-expired)
    deployment_profiles = Credential.active_for_user(request.user).filter(
        credential_type=Credential.Type.DEPLOYMENT_PROFILE, expires_at__isnull=True
    ) | Credential.active_for_user(request.user).filter(
        credential_type=Credential.Type.DEPLOYMENT_PROFILE, expires_at__gt=timezone.now()
    )

    context = {
        "page_title": "Setup NGFW",
        "active_nav": "ngfw",
        "scm_credentials": scm_credentials,
        "deployment_profiles": deployment_profiles,
    }
    return render(request, "mission_control/assets/ngfw/wizard.html", context)


@login_required
@require_GET
def ngfw_deprovision(request, ngfw_id):
    """Deprovision confirmation page with warnings."""
    ngfw = get_object_or_404(
        UserNGFW,
        id=ngfw_id,
        user=request.user,
        deleted_at__isnull=True,
    )

    # Get ranges linked to this NGFW
    linked_ranges = Range.objects.filter(
        ngfw=ngfw,
        status__in=[
            Range.Status.PENDING,
            Range.Status.PROVISIONING,
            Range.Status.READY,
            Range.Status.PAUSED,
            Range.Status.RESUMING,
        ],
    )

    context = {
        "page_title": f"Deprovision {ngfw.name}",
        "active_nav": "ngfw",
        "ngfw": ngfw,
        "linked_ranges": linked_ranges,
    }
    return render(request, "mission_control/assets/ngfw/deprovision.html", context)


# -----------------------------------------------------------------------------
# NGFW API Endpoints
# -----------------------------------------------------------------------------


@login_required
@require_GET
def api_ngfw_list(request):
    """
    List user's NGFWs as JSON.

    Response (JSON):
        - ngfws: List of NGFW objects with id, name, status
    """
    ngfws = UserNGFW.active_for_user(request.user)
    return JsonResponse({"ngfws": [{"id": n.id, "name": n.name, "status": n.status} for n in ngfws]})


@login_required
@require_POST
def api_ngfw_provision(request):
    """
    Start NGFW provisioning.

    Request body (JSON):
        - name: NGFW name (required)
        - deployment_profile_id: ID of deployment profile (required)
        - registration_method: 'pin' or 'otp' (required)
        - scm_credential_id: ID of SCM credential (required for 'pin' method)
        - otp_value: OTP value (required for 'otp' method)
        - otp_folder: SCM folder name (required for 'otp' method)
        - sls_region: SLS region (required for 'otp' method)

    Response (JSON):
        - id: Created NGFW ID
        - name: NGFW name
        - status: NGFW status
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # Required fields
    name = data.get("name", "").strip()
    deployment_profile_id = data.get("deployment_profile_id")
    registration_method = data.get("registration_method")

    # Validate required fields
    errors = []
    if not name:
        errors.append("name is required")
    if not deployment_profile_id:
        errors.append("deployment_profile_id is required")
    if registration_method not in ("pin", "otp"):
        errors.append("registration_method must be 'pin' or 'otp'")

    if errors:
        return JsonResponse({"error": ", ".join(errors)}, status=400)

    # TODO: migrate to CMS - move credential validation to cms.services
    # Validate deployment profile belongs to user
    deployment_profile = (
        Credential.active_for_user(request.user)
        .filter(
            id=deployment_profile_id,
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
        )
        .first()
    )
    if not deployment_profile:
        return JsonResponse({"error": "Deployment profile not found"}, status=400)

    # Handle registration method-specific validation
    scm_credential = None
    if registration_method == "pin":
        scm_credential_id = data.get("scm_credential_id")
        if not scm_credential_id:
            return JsonResponse({"error": "scm_credential_id required for PIN method"}, status=400)
        scm_credential = (
            Credential.active_for_user(request.user)
            .filter(
                id=scm_credential_id,
                credential_type=Credential.Type.SCM,
            )
            .first()
        )
        if not scm_credential:
            return JsonResponse({"error": "SCM credential not found"}, status=400)
    else:  # otp
        otp_value = data.get("otp_value", "").strip()
        otp_folder = data.get("otp_folder", "").strip()
        _sls_region = data.get("sls_region", "americas")
        if not otp_value:
            return JsonResponse({"error": "otp_value required for OTP method"}, status=400)
        if not otp_folder:
            return JsonResponse({"error": "otp_folder required for OTP method"}, status=400)

    # Create NGFW record
    # Note: Credentials are managed by CMS, not stored on UserNGFW.
    # The credential IDs are validated above but will be passed to
    # the provisioning backend through the CMS service interface.
    ngfw = UserNGFW.objects.create(
        user=request.user,
        name=name,
        status=UserNGFW.Status.PROVISIONING,
    )

    # Store OTP data if using OTP method (for provisioning task to use)
    if registration_method == "otp":
        # In a real implementation, this would be passed to the provisioning task
        # For now, store in a way that can be retrieved by the provisioning backend
        pass

    logger.info(
        "NGFW provisioning started: user=%s ngfw_id=%s name=%s method=%s",
        request.user.email,
        ngfw.id,
        name,
        registration_method,
    )

    # TODO: Trigger actual provisioning via engine service (Issue #414)
    # For now, the NGFW is created with PROVISIONING status

    return JsonResponse(
        {
            "id": ngfw.id,
            "name": ngfw.name,
            "status": ngfw.status,
        },
        status=201,
    )


@login_required
@require_GET
def api_ngfw_status(request, ngfw_id):
    """
    Get NGFW status.

    Response (JSON):
        - id: NGFW ID
        - name: NGFW name
        - status: Current status
        - serial_number: Serial number (if provisioned)
    """
    ngfw = UserNGFW.active_for_user(request.user).filter(id=ngfw_id).first()
    if not ngfw:
        return JsonResponse({"error": "NGFW not found"}, status=404)

    return JsonResponse(
        {
            "id": ngfw.id,
            "name": ngfw.name,
            "status": ngfw.status,
            "serial_number": ngfw.serial_number,
            "instance_id": ngfw.instance_id,
        }
    )


@login_required
@require_POST
def api_ngfw_start(request, ngfw_id):
    """
    Start an NGFW (EC2 instance).

    Only valid for NGFWs in 'ready' or 'stopped' status.

    Response (JSON):
        - id: NGFW ID
        - status: New status (starting)
    """
    ngfw = UserNGFW.active_for_user(request.user).filter(id=ngfw_id).first()
    if not ngfw:
        return JsonResponse({"error": "NGFW not found"}, status=404)

    # Validate current status
    if ngfw.status not in (UserNGFW.Status.READY, UserNGFW.Status.STOPPED):
        return JsonResponse(
            {"error": f"Cannot start NGFW in '{ngfw.status}' status"},
            status=400,
        )

    # Update status to starting
    ngfw.status = UserNGFW.Status.STARTING
    ngfw.save(update_fields=["status"])

    # TODO: Trigger actual EC2 start via engine service (Issue #414)
    # For now, simulate by setting to ACTIVE immediately
    ngfw.status = UserNGFW.Status.ACTIVE
    ngfw.last_started_at = timezone.now()
    ngfw.save(update_fields=["status", "last_started_at"])

    logger.info(
        "NGFW started: user=%s ngfw_id=%s",
        request.user.email,
        ngfw.id,
    )

    return JsonResponse(
        {
            "id": ngfw.id,
            "status": ngfw.status,
        }
    )


@login_required
@require_POST
def api_ngfw_stop(request, ngfw_id):
    """
    Stop an NGFW (EC2 instance).

    Only valid for NGFWs in 'active' status.

    Response (JSON):
        - id: NGFW ID
        - status: New status (stopping/stopped)
    """
    ngfw = UserNGFW.active_for_user(request.user).filter(id=ngfw_id).first()
    if not ngfw:
        return JsonResponse({"error": "NGFW not found"}, status=404)

    # Validate current status
    if ngfw.status != UserNGFW.Status.ACTIVE:
        return JsonResponse(
            {"error": f"Cannot stop NGFW in '{ngfw.status}' status"},
            status=400,
        )

    # Update status to stopping
    ngfw.status = UserNGFW.Status.STOPPING
    ngfw.save(update_fields=["status"])

    # TODO: Trigger actual EC2 stop via engine service (Issue #414)
    # For now, simulate by setting to STOPPED immediately
    ngfw.status = UserNGFW.Status.STOPPED
    ngfw.last_stopped_at = timezone.now()
    ngfw.save(update_fields=["status", "last_stopped_at"])

    logger.info(
        "NGFW stopped: user=%s ngfw_id=%s",
        request.user.email,
        ngfw.id,
    )

    return JsonResponse(
        {
            "id": ngfw.id,
            "status": ngfw.status,
        }
    )


@login_required
@require_POST
def api_ngfw_deprovision(request, ngfw_id):
    """
    Deprovision an NGFW.

    Request body (JSON):
        - confirm_name: Must match NGFW name exactly

    Response (JSON):
        - id: NGFW ID
        - status: New status (deprovisioning)
    """
    ngfw = UserNGFW.active_for_user(request.user).filter(id=ngfw_id).first()
    if not ngfw:
        return JsonResponse({"error": "NGFW not found"}, status=404)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    confirm_name = data.get("confirm_name", "")
    if not confirm_name:
        return JsonResponse({"error": "confirm_name is required"}, status=400)

    if confirm_name != ngfw.name:
        return JsonResponse(
            {"error": "Name confirmation does not match"},
            status=400,
        )

    # Update status to deprovisioning
    ngfw.status = UserNGFW.Status.DEPROVISIONING
    ngfw.save(update_fields=["status"])

    # TODO: Trigger actual deprovisioning via engine service (Issue #414)

    logger.info(
        "NGFW deprovisioning started: user=%s ngfw_id=%s",
        request.user.email,
        ngfw.id,
    )

    return JsonResponse(
        {
            "id": ngfw.id,
            "status": ngfw.status,
        }
    )
