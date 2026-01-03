"""Mission Control views.
"""

import json
import logging
import os

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from cms import create_range as cms_create_range
from cms import get_active_range, get_allowed_extensions
from cms import list_agents as cms_list_agents
from cms import list_scenarios as cms_list_scenarios
from cms.exceptions import CMSError

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

    context = {
        "page_title": "Agents",
        "active_nav": "agents",
        "agents": cms_list_agents(request.user),
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
def get_range(request):
    """
    Get the current user's active range.

    Response (JSON):
        - has_range: true/false
        - range: RangeContext object (if exists)
    """
    active_range = get_active_range(request.user)

    if not active_range:
        return JsonResponse({"has_range": False, "range": None})

    return JsonResponse(
        {
            "has_range": True,
            "range": active_range.model_dump(mode="json"),
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
