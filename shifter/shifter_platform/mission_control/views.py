"""Mission Control views."""

import json
import logging
import os

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from cms import cancel_range as cms_cancel_range
from cms import cancel_upload as cms_cancel_upload
from cms import complete_upload as cms_complete_upload
from cms import create_range as cms_create_range
from cms import delete_agent as cms_delete_agent
from cms import destroy_range as cms_destroy_range
from cms import get_active_range, get_allowed_extensions
from cms import initiate_upload as cms_initiate_upload
from cms import list_agents as cms_list_agents
from cms import list_scenarios as cms_list_scenarios
from mission_control.upload_session import check_upload_in_progress, set_upload_in_progress
from mission_control.utils import build_connection_urls
from shared.exceptions import AssetError, CMSError

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
def delete_agent(request, agent_id):
    """Handle agent deletion (soft delete)."""
    try:
        cms_delete_agent(request.user, agent_id)
        messages.success(request, "Agent deleted.")
        logger.info("Agent deleted: user=%s agent_id=%s", request.user.email, agent_id)
    except (CMSError, AssetError) as e:
        messages.error(request, str(e))
        logger.error("Agent delete error: user=%s agent_id=%s error=%s", request.user.email, agent_id, str(e))

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

    logger.info("Upload initiated: user=%s filename=%s size=%d", request.user.email, filename, file_size)

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
