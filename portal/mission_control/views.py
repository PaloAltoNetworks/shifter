"""Mission Control views."""

import json
import logging
import os

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import ActivityLog, AgentConfig, OperatingSystem
from .services.s3 import (
    S3Error,
    delete_agent as s3_delete,
    generate_presigned_upload_url,
    tag_s3_object,
    upload_agent as s3_upload,
    verify_s3_object_exists,
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

        # Look up OS
        os_obj = OperatingSystem.objects.filter(slug=file_format.os_slug).first()
        if not os_obj:
            messages.error(request, f"Operating system '{file_format.os_slug}' not found.")
            return redirect("mission_control:agents")

        # Upload to S3
        s3_key, sha256_hash, file_size = s3_upload(
            uploaded_file, request.user.id, original_filename
        )

        # Create database record
        agent = AgentConfig.objects.create(
            user=request.user,
            os=os_obj,
            name=name,
            s3_key=s3_key,
            original_filename=original_filename,
            file_size_bytes=file_size,
            sha256_hash=sha256_hash,
        )

        # Log activity
        ActivityLog.log(
            "agent_uploaded",
            user=request.user,
            agent_id=agent.id,
            agent_name=name,
            filename=original_filename,
            os=file_format.os_slug,
            file_size=file_size,
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
        # Delete from S3 first
        s3_delete(agent.s3_key)

        # Soft delete the database record
        agent.deleted_at = timezone.now()
        agent.save(update_fields=["deleted_at"])

        # Log activity
        ActivityLog.log(
            "agent_deleted",
            user=request.user,
            agent_id=agent.id,
            agent_name=agent.name,
        )

        messages.success(request, f"Agent '{agent.name}' deleted.")
        logger.info(
            "Agent deleted: user=%s agent_id=%s agent_name=%s",
            request.user.email,
            agent.id,
            agent.name,
        )

    except S3Error as e:
        messages.error(request, "Failed to delete agent. Please try again.")
        logger.error(
            "Agent delete S3 error: user=%s agent_id=%s error=%s",
            request.user.email,
            agent.id,
            str(e),
        )

    return redirect("mission_control:agents")


@login_required
@require_GET
def history(request):
    """Range history - view past sessions."""
    context = {
        "page_title": "History",
        "active_nav": "history",
    }
    return render(request, "mission_control/history.html", context)


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


def _get_user_storage_used(user) -> int:
    """Get total bytes used by a user's active agents."""
    result = AgentConfig.active_for_user(user).aggregate(total=Sum("file_size_bytes"))
    return result["total"] or 0


def _check_upload_in_progress(request) -> bool:
    """Check if user has an upload in progress (stored in session)."""
    return request.session.get("upload_in_progress", False)


def _set_upload_in_progress(request, in_progress: bool):
    """Set upload in progress flag in session."""
    request.session["upload_in_progress"] = in_progress


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
    if _check_upload_in_progress(request):
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
    current_usage = _get_user_storage_used(request.user)
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
    _set_upload_in_progress(request, True)

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
        _set_upload_in_progress(request, False)
        return JsonResponse({"error": str(e)}, status=400)

    s3_key = token_data["s3_key"]
    name = token_data["name"]
    filename = token_data["filename"]
    os_slug = token_data["os_slug"]

    # Validate S3 key belongs to this user (defense in depth)
    expected_prefix = f"agents/{request.user.id}/"
    if not s3_key.startswith(expected_prefix):
        _set_upload_in_progress(request, False)
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
    except S3Error as e:
        _set_upload_in_progress(request, False)
        logger.warning(f"Upload completion failed - file not found: {s3_key}")
        return JsonResponse({"error": "File not found in storage. Upload may have failed."}, status=400)

    # Look up OS
    os_obj = OperatingSystem.objects.filter(slug=os_slug).first()
    if not os_obj:
        _set_upload_in_progress(request, False)
        return JsonResponse({"error": f"Operating system '{os_slug}' not found"}, status=400)

    # Tag object as completed (for lifecycle rule)
    try:
        tag_s3_object(s3_key, {"status": "completed", "user_id": str(request.user.id)})
    except S3Error as e:
        logger.warning(f"Failed to tag S3 object: {e}")
        # Non-fatal, continue

    # Create database record
    agent = AgentConfig.objects.create(
        user=request.user,
        os=os_obj,
        name=name,
        s3_key=s3_key,
        original_filename=filename,
        file_size_bytes=file_size,
        sha256_hash=client_sha256 or etag,  # Use client hash or ETag as fallback
    )

    # Log activity
    ActivityLog.log(
        "agent_uploaded",
        user=request.user,
        agent_id=agent.id,
        agent_name=name,
        filename=filename,
        os=os_slug,
        file_size=file_size,
        upload_method="presigned",
    )

    # Clear upload in progress
    _set_upload_in_progress(request, False)

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


@login_required
@require_POST
def cancel_upload(request):
    """
    Cancel an in-progress upload.

    Request body (JSON):
        - upload_token: Token from initiate response (optional)

    Cleans up S3 object if it exists and clears upload lock.
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
    _set_upload_in_progress(request, False)

    return JsonResponse({"success": True})
