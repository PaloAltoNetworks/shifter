"""Mission Control views."""

import logging
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import ActivityLog, AgentConfig, OperatingSystem
from .services.s3 import S3Error, delete_agent as s3_delete, upload_agent as s3_upload
from .services.validation import ValidationError, get_allowed_extensions, validate_agent_file

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
    from django.conf import settings as django_settings

    context = {
        "page_title": "Help",
        "active_nav": "help",
        "support_email": django_settings.SHIFTER_SUPPORT_EMAIL,
    }
    return render(request, "mission_control/help.html", context)
