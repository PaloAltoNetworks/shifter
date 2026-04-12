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

from cms.services import (
    ScriptUploadError,
    complete_script_upload,
    delete_script,
    get_active_range,
    get_allowed_extensions,
    initiate_script_upload,
    list_scripts,
)
from cms.services import cancel_upload as cms_cancel_upload
from cms.services import complete_upload as cms_complete_upload
from cms.services import create_credential as cms_create_credential
from cms.services import create_ngfw as cms_create_ngfw
from cms.services import create_range as cms_create_range
from cms.services import delete_agent as cms_delete_agent
from cms.services import delete_credential as cms_delete_credential
from cms.services import destroy_ngfw as cms_destroy_ngfw
from cms.services import get_agent as cms_get_agent
from cms.services import get_credential as cms_get_credential
from cms.services import get_ngfw as cms_get_ngfw
from cms.services import initiate_upload as cms_initiate_upload
from cms.services import list_agents as cms_list_agents
from cms.services import list_credentials as cms_list_credentials
from cms.services import list_ngfws as cms_list_ngfws
from cms.services import list_scenarios as cms_list_scenarios
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
def dashboard(request: HttpRequest) -> HttpResponse:
    """Ranges page - launch and manage cyber ranges."""
    context = {
        "page_title": "Ranges",
        "active_nav": "ranges",
        "provisioning_timeout_ms": django_settings.PROVISIONING_TIMEOUT_MS,
    }
    return render(request, "mission_control/dashboard.html", context)


@login_required
@require_GET
def agents(request: HttpRequest) -> HttpResponse:
    """Agent management - upload and manage XDR/XSIAM agents."""
    context = {
        "page_title": "Agents",
        "active_nav": "agents",
        "agents": cms_list_agents(_get_user(request)),
        "allowed_extensions": ", ".join(get_allowed_extensions()),
    }
    return render(request, "mission_control/agents.html", context)


@login_required
@require_POST
def delete_agent(request: HttpRequest, agent_id: int) -> HttpResponse:
    """Handle agent deletion (soft delete)."""
    user = _get_user(request)
    try:
        cms_delete_agent(user, agent_id)
        messages.success(request, "Agent deleted.")
        logger.info("Agent deleted: user=%s agent_id=%s", user.email, agent_id)
    except (CMSError, AssetError) as e:
        messages.error(request, str(e))
        logger.error(
            "Agent delete error: user=%s agent_id=%s error=%s",
            user.email,
            agent_id,
            str(e),
        )

    return redirect("mission_control:agents")


@login_required
@require_GET
def terminal(request: HttpRequest) -> HttpResponse:
    """Terminal - SSH access to range instances.

    Uses active_range and has_active_range from context processor.
    Template accesses active_range.range_id for WebSocket connection.
    OS types for RDP buttons are accessed via active_range.attacker_instance/victim_instances.
    """
    context = {
        "page_title": "Terminal",
        "active_nav": "terminal",
    }
    return render(request, "mission_control/terminal.html", context)


@login_required
@require_GET
def settings(request: HttpRequest) -> HttpResponse:
    """Account settings."""
    context = {
        "page_title": "Settings",
        "active_nav": "settings",
    }
    return render(request, "mission_control/settings.html", context)


# -----------------------------------------------------------------------------
# Guacamole RDP API
# -----------------------------------------------------------------------------


@login_required
@require_POST
def guacamole_rdp_url(request):
    """
    Generate a signed Guacamole URL for RDP access to a range instance.

    Request body (JSON):
        - instance_uuid: UUID of the instance to connect to

    Response (JSON):
        - url: Signed Guacamole URL that opens RDP session

    Security:
        - User must have an active range in READY status
        - URL is signed with HMAC-SHA256 and expires in 5 minutes
        - Only works for instances with GUI (kali, ubuntu, windows)
    """
    from engine.services import get_rdp_connection_info
    from mission_control.guacamole import create_guacamole_rdp_url

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    instance_uuid = data.get("instance_uuid", "").strip()
    if not instance_uuid:
        return JsonResponse({"error": "instance_uuid is required"}, status=400)

    # Get connection info from engine service
    try:
        conn_info = get_rdp_connection_info(request.user, instance_uuid)
    except ValueError as e:
        return JsonResponse({"error": str(e)}, status=400)

    # Get Guacamole secret key from settings
    secret_key = getattr(django_settings, "GUACAMOLE_JSON_AUTH_SECRET", "")
    if not secret_key:
        logger.error("GUACAMOLE_JSON_AUTH_SECRET not configured")
        return JsonResponse({"error": "RDP service not configured"}, status=503)

    # Get Guacamole URLs from settings
    guacamole_base_url = getattr(django_settings, "GUACAMOLE_BASE_URL", "/guacamole")
    guacamole_api_url = getattr(django_settings, "GUACAMOLE_API_BASE_URL", None)

    # Log whether SFTP key is available (do not log key contents)
    logger.info(
        "Guac RDP request: user=%s instance_uuid=%s os=%s sftp_key=%s",
        request.user.email,
        instance_uuid,
        conn_info.get("os_type"),
        "yes" if conn_info.get("ssh_key") else "no",
    )

    # Generate signed URL
    # Set SFTP root directory based on OS type for file transfers
    # Note: SFTP paths use forward slashes even on Windows
    os_type = conn_info.get("os_type")
    if os_type == "kali":
        sftp_root_directory = "/home/kali"
    elif os_type == "ubuntu":
        sftp_root_directory = "/home/ubuntu"
    elif os_type == "windows":
        sftp_root_directory = "/C:/Users/Administrator/Downloads"
    else:
        sftp_root_directory = None

    try:
        url = create_guacamole_rdp_url(
            base_url=guacamole_base_url,
            secret_key=secret_key,
            username=request.user.email,
            connection_name=conn_info["connection_name"],
            hostname=conn_info["private_ip"],
            expires_minutes=5,
            rdp_username=conn_info.get("rdp_username"),
            rdp_password=conn_info.get("rdp_password"),
            api_base_url=guacamole_api_url,
            sftp_root_directory=sftp_root_directory,
            sftp_private_key=conn_info.get("ssh_key"),
        )
    except ValueError as e:
        logger.error(f"Failed to generate Guacamole URL: {e}")
        return JsonResponse({"error": "Failed to generate RDP URL"}, status=500)

    logger.info(
        "Guacamole RDP URL generated: user=%s instance_uuid=%s",
        request.user.email,
        instance_uuid,
    )

    return JsonResponse({"url": url})


@login_required
@require_POST
def api_ngfw_ssh_url(request: HttpRequest, app_id: str) -> JsonResponse:
    """Generate Guacamole SSH URL for NGFW CLI access.

    POST /mc/ngfw/<app_id>/ssh-url/

    Args:
        request: HTTP request
        app_id: NGFW UUID

    Returns:
        JsonResponse with {"url": "https://..."}

    Error Responses:
        400: NGFW not found, not accessible, or permission denied
        500: Internal error

    Security:
        - User must own the NGFW (validated via Request chain)
        - NGFW must be in ready status
        - URL is signed with HMAC-SHA256 and expires in 5 minutes
    """
    from engine.services import connect_ngfw_terminal
    from mission_control.guacamole import create_guacamole_ssh_url

    user = _get_user(request)

    # Get connection details from engine service
    try:
        ssh_conn = connect_ngfw_terminal(user, app_id)
    except ValueError as e:
        logger.error(
            "NGFW SSH access denied (ValueError): user=%s ngfw_uuid=%s error=%s",
            user.email,
            app_id,
            e,
        )
        return JsonResponse({"error": str(e)}, status=400)
    except PermissionError as e:
        logger.error("NGFW SSH access denied (PermissionError): user=%s ngfw_uuid=%s", user.email, app_id)
        return JsonResponse({"error": str(e)}, status=400)
    except Exception:
        logger.exception(
            "Unexpected error getting NGFW SSH connection: user=%s ngfw_uuid=%s",
            user.email,
            app_id,
        )
        return JsonResponse({"error": "Internal server error"}, status=500)

    # Get Guacamole secret key from settings
    secret_key = getattr(django_settings, "GUACAMOLE_JSON_AUTH_SECRET", "")
    if not secret_key:
        logger.error("GUACAMOLE_JSON_AUTH_SECRET not configured")
        return JsonResponse({"error": "SSH service not configured"}, status=503)

    # Get Guacamole URLs from settings
    guacamole_base_url = getattr(django_settings, "GUACAMOLE_BASE_URL", "/guacamole")
    guacamole_api_url = getattr(django_settings, "GUACAMOLE_API_BASE_URL", None)

    # Generate Guacamole SSH URL
    try:
        url = create_guacamole_ssh_url(
            base_url=guacamole_base_url,
            secret_key=secret_key,
            username=user.email,
            connection_name=f"ngfw-{app_id}",
            hostname=ssh_conn.host,
            port=ssh_conn.port,
            ssh_username=ssh_conn.username,
            ssh_private_key=ssh_conn.private_key,
            expires_minutes=5,
            api_base_url=guacamole_api_url,
        )
    except ValueError as e:
        logger.error("Failed to generate NGFW SSH URL: user=%s ngfw_uuid=%s error=%s", user.email, app_id, e)
        return JsonResponse({"error": "Failed to generate SSH URL"}, status=500)
    except Exception:
        logger.exception("Unexpected error generating NGFW SSH URL: user=%s ngfw_uuid=%s", user.email, app_id)
        return JsonResponse({"error": "Internal server error"}, status=500)

    logger.info(
        "Guacamole SSH URL generated for NGFW: user=%s ngfw_uuid=%s",
        user.email,
        app_id,
    )

    return JsonResponse({"url": url})


@login_required
@require_POST
def guacamole_ssh_url(request: HttpRequest) -> JsonResponse:
    """Generate a signed Guacamole URL for SSH access to a range instance."""
    from engine.services import get_ssh_connection_info
    from mission_control.guacamole import create_guacamole_ssh_url

    user = _get_user(request)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    instance_uuid = data.get("instance_uuid", "").strip()
    if not instance_uuid:
        return JsonResponse({"error": "instance_uuid is required"}, status=400)

    try:
        ssh_info = get_ssh_connection_info(user, instance_uuid)
    except ValueError as e:
        logger.error(
            "Range SSH access denied (ValueError): user=%s instance_uuid=%s error=%s",
            user.email,
            instance_uuid,
            e,
        )
        return JsonResponse({"error": str(e)}, status=400)
    except PermissionError as e:
        logger.error(
            "Range SSH access denied (PermissionError): user=%s instance_uuid=%s",
            user.email,
            instance_uuid,
        )
        return JsonResponse({"error": str(e)}, status=400)
    except Exception:
        logger.exception(
            "Unexpected error getting range SSH connection: user=%s instance_uuid=%s",
            user.email,
            instance_uuid,
        )
        return JsonResponse({"error": "Internal server error"}, status=500)

    secret_key = getattr(django_settings, "GUACAMOLE_JSON_AUTH_SECRET", "")
    if not secret_key:
        logger.error("GUACAMOLE_JSON_AUTH_SECRET not configured")
        return JsonResponse({"error": "SSH service not configured"}, status=503)

    guacamole_base_url = getattr(django_settings, "GUACAMOLE_BASE_URL", "/guacamole")
    guacamole_api_url = getattr(django_settings, "GUACAMOLE_API_BASE_URL", None)

    try:
        url = create_guacamole_ssh_url(
            base_url=guacamole_base_url,
            secret_key=secret_key,
            username=user.email,
            connection_name=ssh_info["connection_name"],
            hostname=ssh_info["host"],
            port=ssh_info["port"],
            ssh_username=ssh_info["username"],
            ssh_private_key=ssh_info["private_key"],
            expires_minutes=5,
            api_base_url=guacamole_api_url,
        )
    except ValueError as e:
        logger.error(
            "Failed to generate range SSH URL: user=%s instance_uuid=%s error=%s",
            user.email,
            instance_uuid,
            e,
        )
        return JsonResponse({"error": "Failed to generate SSH URL"}, status=500)
    except Exception:
        logger.exception(
            "Unexpected error generating range SSH URL: user=%s instance_uuid=%s",
            user.email,
            instance_uuid,
        )
        return JsonResponse({"error": "Internal server error"}, status=500)

    logger.info(
        "Guacamole SSH URL generated for range instance: user=%s instance_uuid=%s host=%s provider=%s",
        user.email,
        instance_uuid,
        ssh_info["host"],
        ssh_info.get("cloud_provider") or "unknown",
    )

    return JsonResponse({"url": url})


@login_required
@require_GET
def help_page(request: HttpRequest) -> HttpResponse:
    """Help and documentation."""
    context = {
        "page_title": "Help",
        "active_nav": "help",
        "support_email": django_settings.SHIFTER_SUPPORT_EMAIL,
    }
    return render(request, "mission_control/help.html", context)


@login_required
@require_GET
def walkthrough(request: HttpRequest) -> HttpResponse:
    """Participant launch page for the standalone CTFd platform."""
    context = {
        "page_title": "CTFd",
        "active_nav": "walkthrough",
        "ctfd_url": getattr(
            django_settings,
            "CTFD_PLATFORM_URL",
            "https://ctf.shifter.keplerops.com/login",
        ),
    }
    return render(request, "mission_control/walkthrough.html", context)


# -----------------------------------------------------------------------------
# Presigned URL Upload API
# -----------------------------------------------------------------------------


@login_required
@require_POST
def initiate_upload(request: HttpRequest) -> JsonResponse:
    """
    Step 1: Request presigned URL for direct S3 upload.

    Request body (JSON):
        - name: Agent name (required)
        - filename: Original filename (required)
        - file_size: File size in bytes (required)
        - agent_type: Type of agent (optional, defaults to 'xdr')
            Valid values: 'xdr', 'xdr_collector', 'cloud_identity_engine'

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
    agent_type = data.get("agent_type", "xdr").strip()

    # Basic input validation
    if not name:
        return JsonResponse({"error": "Agent name is required"}, status=400)
    if not filename:
        return JsonResponse({"error": "Filename is required"}, status=400)
    if not isinstance(file_size, int) or file_size <= 0:
        return JsonResponse({"error": "Valid file size is required"}, status=400)

    # Validate agent_type
    valid_agent_types = {"xdr", "xdr_collector", "cloud_identity_engine"}
    if agent_type not in valid_agent_types:
        err_msg = f"Invalid agent type. Must be one of: {', '.join(valid_agent_types)}"
        return JsonResponse({"error": err_msg}, status=400)

    # Sanitize filename
    filename = os.path.basename(filename)

    user = _get_user(request)
    try:
        result = cms_initiate_upload(user, name, filename, file_size, agent_type)
    except CMSError as e:
        return JsonResponse({"error": str(e)}, status=400)

    # Mark upload in progress
    set_upload_in_progress(request.session, True)

    logger.info(
        "Upload initiated: user=%s filename=%s size=%d",
        user.email,
        filename,
        file_size,
    )

    return JsonResponse(result)


@login_required
@require_POST
def complete_upload(request: HttpRequest) -> JsonResponse:
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
    user = _get_user(request)

    try:
        agent = cms_complete_upload(user, upload_token)
    except CMSError as e:
        set_upload_in_progress(request.session, False)
        return JsonResponse({"error": str(e)}, status=400)

    # Clear upload in progress
    set_upload_in_progress(request.session, False)

    logger.info("Upload completed: user=%s agent_id=%s", user.email, agent.id)

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
def cancel_upload(request: HttpRequest) -> JsonResponse:
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
    user = _get_user(request)

    # Try to clean up S3 object if token provided
    if upload_token:
        try:
            cms_cancel_upload(user, upload_token)
            logger.info("Cancelled upload cleaned up: user=%s", user.email)
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
def get_range(request: HttpRequest) -> JsonResponse:
    """
    Get the current user's active range.

    Response (JSON):
        - has_range: true/false
        - range: RangeContext object (if exists)
    """
    active_range = get_active_range(_get_user(request))

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
def launch_range(request: HttpRequest) -> JsonResponse:
    """
    Launch a new cyber range.

    Request body (JSON):
        New format:
        - agents: Dict mapping OS type to agent ID, e.g. {"windows": 123}
        - scenario: Scenario type (basic, ad_attack_lab). Defaults to basic.

        Legacy format (backward compatible):
        - agent_id: ID of agent to use for victim instances
        - scenario: Scenario type (basic, ad_attack_lab). Defaults to basic.

    Response (JSON):
        - success: true
        - range: Range object
    """
    user = _get_user(request)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    scenario = data.get("scenario", "basic")
    valid_scenarios = {s["id"] for s in cms_list_scenarios(user)}
    if scenario not in valid_scenarios:
        return JsonResponse({"error": "Invalid scenario"}, status=400)

    # Support both new (agents) and legacy (agent_id) formats
    agents_by_os: dict[str, int] = {}
    if "agents" in data:
        # New format: {"windows": 123, "linux": 456}
        agents_by_os = data["agents"]
    elif "agent_id" in data:
        # Legacy format: single agent - determine OS from agent
        agent_id = data["agent_id"]
        if not agent_id:
            return JsonResponse({"error": "agent_id is required"}, status=400)
        try:
            agent = cms_get_agent(user, agent_id)
            os_type = "windows" if agent.os.slug == "windows" else "linux"
            agents_by_os[os_type] = agent_id
        except CMSError as e:
            return JsonResponse({"error": str(e)}, status=400)
    else:
        return JsonResponse(
            {"error": "Either 'agents' or 'agent_id' is required"},
            status=400,
        )

    try:
        range_ctx = cms_create_range(
            user,
            scenario,
            agents_by_os,
        )
    except CMSError as e:
        return JsonResponse({"error": str(e)}, status=400)

    logger.info(
        "Range launched: user=%s request_id=%s agent=%s scenario=%s",
        user.email,
        range_ctx.request_id,
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
def cancel_range(request: HttpRequest) -> JsonResponse:
    """
    Cancel a provisioning range.

    Request body (JSON):
        - request_id: UUID of the request (preferred)
        - range_id: ID of range to cancel (legacy, deprecated)

    Only works for ranges in PENDING or PROVISIONING status.
    """
    from cms.services import cancel_range as cms_cancel_range_by_id
    from cms.services import cancel_range_by_request_id as cms_cancel_range_by_request

    user = _get_user(request)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # Support both new (request_id) and legacy (range_id) formats
    request_id = data.get("request_id")
    range_id = data.get("range_id")

    if not request_id and not range_id:
        return JsonResponse({"error": "request_id or range_id is required"}, status=400)

    try:
        if request_id:
            cms_cancel_range_by_request(user, request_id)
            logger.info("Range cancelled: user=%s request_id=%s", user.email, request_id)
        else:
            cms_cancel_range_by_id(user, range_id)
            logger.info("Range cancelled: user=%s range_id=%s", user.email, range_id)
    except CMSError as e:
        return JsonResponse({"error": str(e)}, status=400)

    return JsonResponse({"success": True})


@login_required
@require_POST
def destroy_range(request: HttpRequest) -> JsonResponse:
    """
    Destroy an active, paused, or failed range.

    Request body (JSON):
        - request_id: UUID of the request (preferred)
        - range_id: ID of range to destroy (legacy, deprecated)

    Sets status to DESTROYING and triggers async resource cleanup.
    """
    from cms.services import destroy_range as cms_destroy_range_by_id
    from cms.services import destroy_range_by_request_id as cms_destroy_range_by_request

    user = _get_user(request)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # Support both new (request_id) and legacy (range_id) formats
    request_id = data.get("request_id")
    range_id = data.get("range_id")

    if not request_id and not range_id:
        return JsonResponse({"error": "request_id or range_id is required"}, status=400)

    try:
        if request_id:
            cms_destroy_range_by_request(user, request_id)
            logger.info("Range destroyed: user=%s request_id=%s", user.email, request_id)
        else:
            cms_destroy_range_by_id(user, range_id)
            logger.info("Range destroyed: user=%s range_id=%s", user.email, range_id)
    except CMSError as e:
        return JsonResponse({"error": str(e)}, status=400)

    return JsonResponse({"success": True})


@login_required
@require_POST
def pause_range(request: HttpRequest) -> JsonResponse:
    """
    Pause an active range.

    Request body (JSON):
        - request_id: UUID of the request (preferred)
        - range_id: ID of range to pause (legacy, deprecated)

    Sets status to PAUSING and triggers async instance stop.
    """
    from cms.services import pause_range as cms_pause_range_by_id
    from cms.services import pause_range_by_request_id as cms_pause_range_by_request

    user = _get_user(request)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # Support both new (request_id) and legacy (range_id) formats
    request_id = data.get("request_id")
    range_id = data.get("range_id")

    if not request_id and not range_id:
        return JsonResponse({"error": "request_id or range_id is required"}, status=400)

    try:
        if request_id:
            cms_pause_range_by_request(user, request_id)
            logger.info("Range paused: user=%s request_id=%s", user.email, request_id)
        else:
            cms_pause_range_by_id(user, range_id)
            logger.info("Range paused: user=%s range_id=%s", user.email, range_id)
    except CMSError as e:
        return JsonResponse({"error": str(e)}, status=400)

    return JsonResponse({"success": True})


@login_required
@require_POST
def resume_range(request: HttpRequest) -> JsonResponse:
    """
    Resume a paused range.

    Request body (JSON):
        - request_id: UUID of the request (preferred)
        - range_id: ID of range to resume (legacy, deprecated)

    Sets status to RESUMING and triggers async instance start.
    """
    from cms.services import resume_range as cms_resume_range_by_id
    from cms.services import resume_range_by_request_id as cms_resume_range_by_request

    user = _get_user(request)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # Support both new (request_id) and legacy (range_id) formats
    request_id = data.get("request_id")
    range_id = data.get("range_id")

    if not request_id and not range_id:
        return JsonResponse({"error": "request_id or range_id is required"}, status=400)

    try:
        if request_id:
            cms_resume_range_by_request(user, request_id)
            logger.info("Range resumed: user=%s request_id=%s", user.email, request_id)
        else:
            cms_resume_range_by_id(user, range_id)
            logger.info("Range resumed: user=%s range_id=%s", user.email, range_id)
    except CMSError as e:
        return JsonResponse({"error": str(e)}, status=400)

    return JsonResponse({"success": True})


@login_required
@require_GET
def list_agents(request: HttpRequest) -> JsonResponse:
    """
    Get user's agents.

    Response (JSON):
        - agents: List of {id, name, os_name, os_slug, file_size_mb, original_filename, created_at}

    The os_slug field allows frontend to filter agents by OS type
    (e.g., 'windows' for DC agent dropdown in AD scenarios).
    """
    agents = cms_list_agents(_get_user(request))
    return JsonResponse({"agents": agents})


@login_required
@require_GET
def list_scenarios(request: HttpRequest) -> JsonResponse:
    """
    Get available scenarios with agent requirements.

    Response (JSON):
        - scenarios: List of scenario dicts with agent_requirements field
    """
    scenarios = cms_list_scenarios(_get_user(request))
    return JsonResponse({"scenarios": scenarios})


# -----------------------------------------------------------------------------
# NGFW Views
# -----------------------------------------------------------------------------


@login_required
@require_GET
def ngfw_list(request: HttpRequest) -> HttpResponse:
    """List user's NGFWs."""
    ngfws = cms_list_ngfws(_get_user(request))
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
    from engine.services import get_ranges_for_ngfw

    user = _get_user(request)
    try:
        ngfw = cms_get_ngfw(user, app_id)
    except CMSError:
        # NGFW not found (may have failed and been cleaned up)
        # Redirect to list page instead of showing 404
        messages.warning(request, "NGFW not found. It may have failed during provisioning.")
        return redirect("mission_control:ngfw_list")

    # Get ranges linked to this NGFW (via ngfw_instance_id)
    linked_ranges = get_ranges_for_ngfw(
        user_id=cast(int, user.pk),
        ngfw_instance_id=int(ngfw.instance_id),
    )

    context = {
        "page_title": ngfw.name,
        "active_nav": "ngfw",
        "ngfw": ngfw,
        "linked_ranges": linked_ranges,
    }
    return render(request, "mission_control/ngfw/detail.html", context)


@login_required
@require_GET
def ngfw_wizard(request: HttpRequest) -> HttpResponse:
    """NGFW setup wizard."""
    credentials = cms_list_credentials(_get_user(request))

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
        # NGFW not found - redirect to list page
        messages.warning(request, "NGFW not found.")
        return redirect("mission_control:ngfw_list")

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
    ngfws = cms_list_ngfws(_get_user(request))
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
def credentials_list(request: HttpRequest) -> HttpResponse:
    """List user's credentials."""
    credentials = cms_list_credentials(_get_user(request))

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
def credential_detail(request: HttpRequest, credential_id: int) -> HttpResponse:
    """View credential details."""
    try:
        credential = cms_get_credential(_get_user(request), credential_id)
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
def credential_add(request: HttpRequest) -> HttpResponse:
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
def api_credential_create(request: HttpRequest) -> JsonResponse:
    """Create a new credential.

    Accepts JSON with credential_type ('scm' or 'deployment_profile') and
    type-specific fields. Validates via Pydantic specs, creates via service.
    """
    from pydantic import ValidationError as PydanticValidationError

    from shared.schemas import DeploymentProfileSpec, SCMCredentialSpec

    user = _get_user(request)
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
    data["user_id"] = user.id

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
            user,
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
        user.email,
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
def api_credential_delete(request: HttpRequest, credential_id: int) -> JsonResponse:
    """Soft-delete a credential."""
    user = _get_user(request)
    try:
        cms_delete_credential(user, credential_id)
    except CMSError:
        raise Http404("Credential not found") from None

    logger.info(
        "Credential deleted: user=%s credential_id=%s",
        user.email,
        credential_id,
    )

    return JsonResponse({"success": True})


# -----------------------------------------------------------------------------
# Files (Scripts) Views
# -----------------------------------------------------------------------------


@login_required
@require_GET
def files(request: HttpRequest) -> HttpResponse:
    """File management - upload and manage script files."""
    scripts = list_scripts(_get_user(request))
    context = {
        "page_title": "Files",
        "active_nav": "files",
        "scripts": scripts,
    }
    return render(request, "mission_control/files.html", context)


@login_required
@require_POST
def file_upload(request: HttpRequest) -> JsonResponse:
    """Script file upload — two-step presigned URL flow (JSON API).

    Step 1: POST with {name, filename, file_size} → returns {presigned_url, upload_token}
    Step 2: POST with {upload_token} → returns {success, script_id}
    """
    user = _get_user(request)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    upload_token = data.get("upload_token")

    if upload_token:
        # Step 2: Complete upload
        try:
            script = complete_script_upload(user, upload_token)
        except ScriptUploadError as e:
            return JsonResponse({"error": str(e)}, status=400)

        logger.info("Script upload completed: user=%s script_id=%s", user.email, script.pk)
        return JsonResponse(
            {
                "success": True,
                "script_id": script.pk,
                "message": f"Script '{script.name}' uploaded successfully.",
            }
        )

    # Step 1: Initiate upload
    name = data.get("name", "").strip()
    filename = data.get("filename", "").strip()
    file_size = data.get("file_size", 0)

    if not name:
        return JsonResponse({"error": "Script name is required"}, status=400)
    if not filename:
        return JsonResponse({"error": "Filename is required"}, status=400)
    if not isinstance(file_size, int) or file_size <= 0:
        return JsonResponse({"error": "Valid file size is required"}, status=400)

    filename = os.path.basename(filename)

    try:
        result = initiate_script_upload(user, name, filename, file_size)
    except ScriptUploadError as e:
        return JsonResponse({"error": str(e)}, status=400)

    logger.info(
        "Script upload initiated: user=%s filename=%s size=%d",
        user.email,
        filename,
        file_size,
    )
    return JsonResponse(result)


@login_required
@require_POST
def file_delete(request: HttpRequest, script_id: int) -> HttpResponse:
    """Delete a script file (soft delete)."""
    user = _get_user(request)
    try:
        delete_script(user, script_id)
        messages.success(request, "Script deleted.")
        logger.info("Script deleted: user=%s script_id=%s", user.email, script_id)
    except ScriptUploadError as e:
        messages.error(request, str(e))
        logger.error(
            "Script delete error: user=%s script_id=%s error=%s",
            user.email,
            script_id,
            str(e),
        )

    return redirect("mission_control:files")


@login_required
@require_GET
def api_list_scripts(request: HttpRequest) -> JsonResponse:
    """JSON endpoint for listing scripts (used by experiment create form)."""
    scripts = list_scripts(_get_user(request))
    return JsonResponse(
        {
            "scripts": [
                {
                    "id": s.pk,
                    "name": s.name,
                    "filename": s.original_filename,
                }
                for s in scripts
            ]
        }
    )
