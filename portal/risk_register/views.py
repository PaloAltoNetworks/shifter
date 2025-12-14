"""Risk Register UI views."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from risk_register.models import (
    APIKey,
    AuditLog,
    Comment,
    Risk,
    Severity,
    Status,
    StrideCategory,
)


@login_required
def risk_list(request: HttpRequest) -> HttpResponse:
    """Display list of all active risks."""
    include_deleted = request.GET.get("include_deleted") == "true"
    status_filter = request.GET.get("status")
    severity_filter = request.GET.get("severity")

    risks = Risk.objects.all()

    if not include_deleted:
        risks = risks.filter(deleted_at__isnull=True)

    if status_filter:
        risks = risks.filter(status=status_filter)

    if severity_filter:
        risks = risks.filter(severity=severity_filter)

    context = {
        "risks": risks,
        "include_deleted": include_deleted,
        "status_filter": status_filter,
        "severity_filter": severity_filter,
        "status_choices": Status.choices,
        "severity_choices": Severity.choices,
    }
    return render(request, "risk_register/risk_list.html", context)


@login_required
def risk_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Display risk details with comments."""
    risk = get_object_or_404(Risk, pk=pk)
    comments = risk.comments.filter(deleted_at__isnull=True).order_by("created_at")

    context = {
        "risk": risk,
        "comments": comments,
        "stride_choices": StrideCategory.choices,
    }
    return render(request, "risk_register/risk_detail.html", context)


@login_required
def risk_create(request: HttpRequest) -> HttpResponse:
    """Create a new risk."""
    if request.method == "POST":
        # Extract form data
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        severity = request.POST.get("severity", Severity.MEDIUM)
        status = request.POST.get("status", Status.OPEN)

        # Threat modeling fields
        stride_categories = request.POST.getlist("stride_categories")
        likelihood_score = request.POST.get("likelihood_score")
        impact_score = request.POST.get("impact_score")
        attack_vector = request.POST.get("attack_vector", "").strip()
        affected_assets = request.POST.get("affected_assets", "").strip()
        mitigation_status = request.POST.get("mitigation_status", "").strip()

        # Validate required fields
        if not title or not description:
            messages.error(request, "Title and description are required.")
            return render(
                request,
                "risk_register/risk_form.html",
                {
                    "severity_choices": Severity.choices,
                    "status_choices": Status.choices,
                    "stride_choices": StrideCategory.choices,
                },
            )

        # Create risk
        risk = Risk.objects.create(
            title=title,
            description=description,
            severity=severity,
            status=status,
            stride_categories=stride_categories,
            likelihood_score=int(likelihood_score) if likelihood_score else None,
            impact_score=int(impact_score) if impact_score else None,
            attack_vector=attack_vector,
            affected_assets=affected_assets,
            mitigation_status=mitigation_status,
        )

        # Create audit log
        AuditLog.log(
            entity_type=AuditLog.EntityType.RISK,
            entity_id=risk.id,
            action=AuditLog.Action.CREATE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=request.user.id,
            new_state=_risk_to_dict(risk),
        )

        messages.success(request, f"Risk '{risk.title}' created successfully.")
        return redirect("risk_register:risk_detail", pk=risk.pk)

    context = {
        "severity_choices": Severity.choices,
        "status_choices": Status.choices,
        "stride_choices": StrideCategory.choices,
    }
    return render(request, "risk_register/risk_form.html", context)


@login_required
def risk_edit(request: HttpRequest, pk: int) -> HttpResponse:
    """Edit an existing risk."""
    risk = get_object_or_404(Risk, pk=pk)
    previous_state = _risk_to_dict(risk)

    if request.method == "POST":
        # Update fields
        risk.title = request.POST.get("title", risk.title).strip()
        risk.description = request.POST.get("description", risk.description).strip()
        risk.severity = request.POST.get("severity", risk.severity)
        risk.status = request.POST.get("status", risk.status)
        risk.stride_categories = request.POST.getlist("stride_categories")

        likelihood = request.POST.get("likelihood_score")
        impact = request.POST.get("impact_score")
        risk.likelihood_score = int(likelihood) if likelihood else None
        risk.impact_score = int(impact) if impact else None

        risk.attack_vector = request.POST.get("attack_vector", "").strip()
        risk.affected_assets = request.POST.get("affected_assets", "").strip()
        risk.mitigation_status = request.POST.get("mitigation_status", "").strip()
        risk.resolution_reason = request.POST.get("resolution_reason", "").strip()

        risk.save()

        # Create audit log
        AuditLog.log(
            entity_type=AuditLog.EntityType.RISK,
            entity_id=risk.id,
            action=AuditLog.Action.UPDATE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=request.user.id,
            previous_state=previous_state,
            new_state=_risk_to_dict(risk),
        )

        messages.success(request, f"Risk '{risk.title}' updated successfully.")
        return redirect("risk_register:risk_detail", pk=risk.pk)

    context = {
        "risk": risk,
        "severity_choices": Severity.choices,
        "status_choices": Status.choices,
        "stride_choices": StrideCategory.choices,
        "editing": True,
    }
    return render(request, "risk_register/risk_form.html", context)


@login_required
def risk_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Soft-delete a risk."""
    risk = get_object_or_404(Risk, pk=pk)

    if request.method == "POST":
        previous_state = _risk_to_dict(risk)
        risk.soft_delete()

        AuditLog.log(
            entity_type=AuditLog.EntityType.RISK,
            entity_id=risk.id,
            action=AuditLog.Action.DELETE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=request.user.id,
            previous_state=previous_state,
            new_state=_risk_to_dict(risk),
        )

        messages.success(request, f"Risk '{risk.title}' deleted.")
        return redirect("risk_register:risk_list")

    return redirect("risk_register:risk_detail", pk=pk)


@login_required
def risk_restore(request: HttpRequest, pk: int) -> HttpResponse:
    """Restore a soft-deleted risk."""
    risk = get_object_or_404(Risk, pk=pk)

    if request.method == "POST" and risk.is_deleted:
        previous_state = _risk_to_dict(risk)
        risk.restore()

        AuditLog.log(
            entity_type=AuditLog.EntityType.RISK,
            entity_id=risk.id,
            action=AuditLog.Action.RESTORE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=request.user.id,
            previous_state=previous_state,
            new_state=_risk_to_dict(risk),
        )

        messages.success(request, f"Risk '{risk.title}' restored.")

    return redirect("risk_register:risk_detail", pk=pk)


@login_required
def risk_close(request: HttpRequest, pk: int) -> HttpResponse:
    """Close a risk."""
    risk = get_object_or_404(Risk, pk=pk)

    if request.method == "POST":
        previous_state = _risk_to_dict(risk)
        resolution_reason = request.POST.get("resolution_reason", "").strip()

        risk.status = Status.CLOSED
        risk.resolution_reason = resolution_reason
        risk.save()

        AuditLog.log(
            entity_type=AuditLog.EntityType.RISK,
            entity_id=risk.id,
            action=AuditLog.Action.CLOSE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=request.user.id,
            previous_state=previous_state,
            new_state=_risk_to_dict(risk),
            context=resolution_reason,
        )

        messages.success(request, f"Risk '{risk.title}' closed.")

    return redirect("risk_register:risk_detail", pk=pk)


@login_required
def risk_reopen(request: HttpRequest, pk: int) -> HttpResponse:
    """Reopen a closed risk."""
    risk = get_object_or_404(Risk, pk=pk)

    if request.method == "POST" and risk.status == Status.CLOSED:
        previous_state = _risk_to_dict(risk)
        risk.status = Status.OPEN
        risk.save()

        AuditLog.log(
            entity_type=AuditLog.EntityType.RISK,
            entity_id=risk.id,
            action=AuditLog.Action.REOPEN,
            actor_type=AuditLog.ActorType.USER,
            actor_id=request.user.id,
            previous_state=previous_state,
            new_state=_risk_to_dict(risk),
        )

        messages.success(request, f"Risk '{risk.title}' reopened.")

    return redirect("risk_register:risk_detail", pk=pk)


@login_required
def comment_add(request: HttpRequest, risk_pk: int) -> HttpResponse:
    """Add a comment to a risk."""
    risk = get_object_or_404(Risk, pk=risk_pk)

    if request.method == "POST":
        content = request.POST.get("content", "").strip()

        if content:
            comment = Comment.objects.create(
                risk=risk,
                content=content,
                author_user=request.user,
            )

            AuditLog.log(
                entity_type=AuditLog.EntityType.COMMENT,
                entity_id=comment.id,
                action=AuditLog.Action.CREATE,
                actor_type=AuditLog.ActorType.USER,
                actor_id=request.user.id,
                new_state={"risk_id": risk.id, "content": content},
            )

            messages.success(request, "Comment added.")
        else:
            messages.error(request, "Comment cannot be empty.")

    return redirect("risk_register:risk_detail", pk=risk_pk)


@login_required
def comment_delete(request: HttpRequest, risk_pk: int, pk: int) -> HttpResponse:
    """Soft-delete a comment."""
    comment = get_object_or_404(Comment, pk=pk, risk__pk=risk_pk)

    if request.method == "POST":
        comment.soft_delete()

        AuditLog.log(
            entity_type=AuditLog.EntityType.COMMENT,
            entity_id=comment.id,
            action=AuditLog.Action.DELETE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=request.user.id,
        )

        messages.success(request, "Comment deleted.")

    return redirect("risk_register:risk_detail", pk=risk_pk)


@login_required
def apikey_list(request: HttpRequest) -> HttpResponse:
    """List API keys for the current user."""
    # Show all keys for staff, own keys for regular users
    if request.user.is_staff:
        keys = APIKey.objects.all()
    else:
        keys = APIKey.objects.filter(created_by=request.user)

    context = {
        "keys": keys,
        "is_admin": request.user.is_staff,
    }
    return render(request, "risk_register/apikey_list.html", context)


@login_required
def apikey_create(request: HttpRequest) -> HttpResponse:
    """Create a new API key."""
    if request.method == "POST":
        name = request.POST.get("name", "").strip()

        if not name:
            messages.error(request, "Key name is required.")
            return redirect("risk_register:apikey_list")

        api_key, raw_key = APIKey.create_key(name=name, created_by=request.user)

        AuditLog.log(
            entity_type=AuditLog.EntityType.APIKEY,
            entity_id=api_key.id,
            action=AuditLog.Action.CREATE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=request.user.id,
            new_state={"name": name, "prefix": api_key.prefix},
        )

        # Show the raw key once
        context = {
            "api_key": api_key,
            "raw_key": raw_key,
            "show_key": True,
        }
        return render(request, "risk_register/apikey_list.html", context)

    return redirect("risk_register:apikey_list")


@login_required
def apikey_revoke(request: HttpRequest, pk: int) -> HttpResponse:
    """Revoke an API key."""
    api_key = get_object_or_404(APIKey, pk=pk)

    # Only allow revoking own keys unless admin
    if not request.user.is_staff and api_key.created_by != request.user:
        messages.error(request, "You can only revoke your own API keys.")
        return redirect("risk_register:apikey_list")

    if request.method == "POST":
        api_key.revoke()

        AuditLog.log(
            entity_type=AuditLog.EntityType.APIKEY,
            entity_id=api_key.id,
            action=AuditLog.Action.DELETE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=request.user.id,
        )

        messages.success(request, f"API key '{api_key.name}' revoked.")

    return redirect("risk_register:apikey_list")


def _risk_to_dict(risk: Risk) -> dict:
    """Convert risk to dictionary for audit logging."""
    return {
        "id": risk.id,
        "title": risk.title,
        "description": risk.description,
        "severity": risk.severity,
        "status": risk.status,
        "stride_categories": risk.stride_categories,
        "likelihood_score": risk.likelihood_score,
        "impact_score": risk.impact_score,
        "attack_vector": risk.attack_vector,
        "affected_assets": risk.affected_assets,
        "mitigation_status": risk.mitigation_status,
        "resolution_reason": risk.resolution_reason,
        "deleted_at": risk.deleted_at.isoformat() if risk.deleted_at else None,
    }
