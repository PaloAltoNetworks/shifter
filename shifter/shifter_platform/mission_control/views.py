"""Mission Control views."""

import json
import logging
import os

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
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


# -----------------------------------------------------------------------------
# NGFW Views
# -----------------------------------------------------------------------------


@login_required
@require_GET
def ngfw_list(request):
    """List user's NGFWs."""
    from cms.models import UserNGFW

    ngfws = UserNGFW.active_for_user(request.user).order_by("-created_at")

    context = {
        "page_title": "NGFWs",
        "active_nav": "ngfw",
        "ngfws": ngfws,
    }
    return render(request, "mission_control/ngfw/list.html", context)


@login_required
@require_GET
def ngfw_detail(request, ngfw_id):
    """View NGFW details."""
    from cms.models import UserNGFW
    from engine.models import Range

    try:
        ngfw = UserNGFW.active_for_user(request.user).get(id=ngfw_id)
    except UserNGFW.DoesNotExist:
        raise Http404("NGFW not found")

    # Get ranges linked to this NGFW (exclude destroyed/failed)
    linked_ranges = Range.objects.filter(ngfw=ngfw).exclude(
        status__in=[Range.Status.DESTROYED, Range.Status.FAILED]
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
def ngfw_wizard(request):
    """NGFW setup wizard."""
    from cms.models import Credential

    # Get user's credentials
    scm_credentials = Credential.objects.filter(
        user=request.user,
        credential_type=Credential.Type.SCM,
        deleted_at__isnull=True,
    ).exclude(
        expires_at__lt=timezone.now()  # Exclude expired
    )

    deployment_profiles = Credential.objects.filter(
        user=request.user,
        credential_type=Credential.Type.DEPLOYMENT_PROFILE,
        deleted_at__isnull=True,
    ).exclude(
        expires_at__lt=timezone.now()  # Exclude expired
    )

    context = {
        "page_title": "Setup NGFW",
        "active_nav": "ngfw",
        "scm_credentials": scm_credentials,
        "deployment_profiles": deployment_profiles,
    }
    return render(request, "mission_control/ngfw/wizard.html", context)


@login_required
@require_GET
def ngfw_deprovision(request, ngfw_id):
    """NGFW deprovision confirmation page."""
    from cms.models import UserNGFW
    from engine.models import Range

    try:
        ngfw = UserNGFW.active_for_user(request.user).get(id=ngfw_id)
    except UserNGFW.DoesNotExist:
        raise Http404("NGFW not found")

    # Get ranges linked to this NGFW (exclude destroyed/failed)
    linked_ranges = Range.objects.filter(ngfw=ngfw).exclude(
        status__in=[Range.Status.DESTROYED, Range.Status.FAILED]
    )

    context = {
        "page_title": f"Deprovision {ngfw.name}",
        "active_nav": "ngfw",
        "ngfw": ngfw,
        "linked_ranges": linked_ranges,
    }
    return render(request, "mission_control/ngfw/deprovision.html", context)


# -----------------------------------------------------------------------------
# NGFW API
# -----------------------------------------------------------------------------


@login_required
@require_POST
def api_ngfw_provision(request):
    """Provision a new NGFW."""
    from cms.models import Credential, UserNGFW

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    name = data.get("name", "").strip()
    deployment_profile_id = data.get("deployment_profile_id")
    registration_method = data.get("registration_method")

    # Validate required fields
    if not name:
        return JsonResponse({"error": "Name is required"}, status=400)
    if not deployment_profile_id:
        return JsonResponse({"error": "Deployment profile is required"}, status=400)

    # Validate deployment profile exists and belongs to user
    if not Credential.objects.filter(
        id=deployment_profile_id,
        user=request.user,
        credential_type=Credential.Type.DEPLOYMENT_PROFILE,
        deleted_at__isnull=True,
    ).exists():
        return JsonResponse({"error": "Invalid deployment profile"}, status=400)

    # Validate registration method
    if registration_method == "pin":
        scm_credential_id = data.get("scm_credential_id")
        if not scm_credential_id:
            return JsonResponse({"error": "SCM credential is required for PIN method"}, status=400)
        try:
            Credential.objects.get(
                id=scm_credential_id,
                user=request.user,
                credential_type=Credential.Type.SCM,
                deleted_at__isnull=True,
            )
        except Credential.DoesNotExist:
            return JsonResponse({"error": "Invalid SCM credential"}, status=400)
    elif registration_method == "otp":
        otp_value = data.get("otp_value", "").strip()
        otp_folder = data.get("otp_folder", "").strip()
        if not otp_value or not otp_folder:
            return JsonResponse({"error": "OTP value and folder are required"}, status=400)
    else:
        return JsonResponse({"error": "Invalid registration method"}, status=400)

    # Create NGFW record
    ngfw = UserNGFW.objects.create(
        user=request.user,
        name=name,
        status=UserNGFW.Status.PROVISIONING,
    )

    logger.info("NGFW provisioning started: user=%s ngfw_id=%s", request.user.email, ngfw.id)

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
def api_ngfw_list(request):
    """List user's NGFWs."""
    from cms.models import UserNGFW

    ngfws = UserNGFW.active_for_user(request.user).order_by("-created_at")

    return JsonResponse({
        "ngfws": [
            {
                "id": n.id,
                "name": n.name,
                "status": n.status,
                "serial_number": n.serial_number,
                "management_ip": str(n.management_ip) if n.management_ip else None,
                "xdr_configured": n.xdr_configured,
                "created_at": n.created_at.isoformat(),
            }
            for n in ngfws
        ]
    })


@login_required
@require_GET
def api_ngfw_status(request, ngfw_id):
    """Get NGFW status."""
    from cms.models import UserNGFW

    try:
        ngfw = UserNGFW.active_for_user(request.user).get(id=ngfw_id)
    except UserNGFW.DoesNotExist:
        raise Http404("NGFW not found")

    return JsonResponse({
        "status": ngfw.status,
        "serial_number": ngfw.serial_number,
    })


@login_required
@require_POST
def api_ngfw_start(request, ngfw_id):
    """Start a stopped NGFW."""
    from cms.models import UserNGFW

    try:
        ngfw = UserNGFW.active_for_user(request.user).get(id=ngfw_id)
    except UserNGFW.DoesNotExist:
        raise Http404("NGFW not found")

    if ngfw.status not in [UserNGFW.Status.READY, UserNGFW.Status.STOPPED]:
        return JsonResponse(
            {"error": f"Cannot start NGFW in '{ngfw.get_status_display()}' status"},
            status=400,
        )

    # Update status
    ngfw.status = UserNGFW.Status.ACTIVE
    ngfw.last_started_at = timezone.now()
    ngfw.save(update_fields=["status", "last_started_at"])

    logger.info("NGFW started: user=%s ngfw_id=%s", request.user.email, ngfw_id)

    return JsonResponse({"status": ngfw.status})


@login_required
@require_POST
def api_ngfw_stop(request, ngfw_id):
    """Stop an active NGFW."""
    from cms.models import UserNGFW

    try:
        ngfw = UserNGFW.active_for_user(request.user).get(id=ngfw_id)
    except UserNGFW.DoesNotExist:
        raise Http404("NGFW not found")

    if ngfw.status != UserNGFW.Status.ACTIVE:
        return JsonResponse(
            {"error": f"Cannot stop NGFW in '{ngfw.get_status_display()}' status"},
            status=400,
        )

    # Update status
    ngfw.status = UserNGFW.Status.STOPPED
    ngfw.last_stopped_at = timezone.now()
    ngfw.save(update_fields=["status", "last_stopped_at"])

    logger.info("NGFW stopped: user=%s ngfw_id=%s", request.user.email, ngfw_id)

    return JsonResponse({"status": ngfw.status})


@login_required
@require_POST
def api_ngfw_deprovision(request, ngfw_id):
    """Deprovision an NGFW."""
    from cms.models import UserNGFW

    try:
        ngfw = UserNGFW.active_for_user(request.user).get(id=ngfw_id)
    except UserNGFW.DoesNotExist:
        raise Http404("NGFW not found")

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    confirm_name = data.get("confirm_name", "").strip()
    if confirm_name != ngfw.name:
        return JsonResponse({"error": "Name confirmation does not match"}, status=400)

    # Update status
    ngfw.status = UserNGFW.Status.DEPROVISIONING
    ngfw.save(update_fields=["status"])

    logger.info("NGFW deprovisioning started: user=%s ngfw_id=%s", request.user.email, ngfw_id)

    return JsonResponse({"status": ngfw.status})


# -----------------------------------------------------------------------------
# Credential Views
# -----------------------------------------------------------------------------


@login_required
@require_GET
def credentials_list(request):
    """List user's credentials."""
    from cms.models import Credential

    credentials = Credential.objects.filter(
        user=request.user,
        deleted_at__isnull=True,
    ).order_by("-created_at")

    scm_count = credentials.filter(credential_type=Credential.Type.SCM).count()
    profile_count = credentials.filter(credential_type=Credential.Type.DEPLOYMENT_PROFILE).count()

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
    from cms.models import Credential

    try:
        credential = Credential.objects.get(
            id=credential_id,
            user=request.user,
            deleted_at__isnull=True,
        )
    except Credential.DoesNotExist:
        raise Http404("Credential not found")

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
    """Create a new credential."""
    from cms.models import Credential

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    name = data.get("name", "").strip()
    credential_type = data.get("credential_type")
    expires_at = data.get("expires_at")

    # Validate required fields
    if not name:
        return JsonResponse({"error": "Name is required"}, status=400)
    if credential_type not in [Credential.Type.SCM, Credential.Type.DEPLOYMENT_PROFILE]:
        return JsonResponse({"error": "Invalid credential type"}, status=400)

    # Build credential based on type
    credential = Credential(
        user=request.user,
        name=name,
        credential_type=credential_type,
    )

    if expires_at:
        from django.utils.dateparse import parse_date
        credential.expires_at = parse_date(expires_at)

    if credential_type == Credential.Type.SCM:
        credential.scm_folder_name = data.get("scm_folder_name", "").strip()
        credential.scm_pin_id = data.get("scm_pin_id", "").strip()
        credential.scm_pin_value = data.get("scm_pin_value", "")
        credential.sls_region = data.get("sls_region", "")
    else:
        credential.authcode = data.get("authcode", "")

    try:
        credential.full_clean()
        credential.save()
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)

    logger.info("Credential created: user=%s credential_id=%s type=%s", request.user.email, credential.id, credential_type)

    return JsonResponse(
        {
            "id": credential.id,
            "name": credential.name,
            "credential_type": credential.credential_type,
        },
        status=201,
    )


@login_required
@require_POST
def api_credential_delete(request, credential_id):
    """Soft-delete a credential."""
    from cms.models import Credential

    try:
        credential = Credential.objects.get(
            id=credential_id,
            user=request.user,
            deleted_at__isnull=True,
        )
    except Credential.DoesNotExist:
        raise Http404("Credential not found")

    # Soft delete
    credential.deleted_at = timezone.now()
    credential.save(update_fields=["deleted_at"])

    logger.info("Credential deleted: user=%s credential_id=%s", request.user.email, credential_id)

    return JsonResponse({"success": True})
