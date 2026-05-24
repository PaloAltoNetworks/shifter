"""NGFW management views (HTML pages + JSON API)."""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_GET, require_POST

from cms.services import (
    create_ngfw as cms_create_ngfw,
)
from cms.services import (
    destroy_ngfw as cms_destroy_ngfw,
)
from cms.services import (
    list_credentials as cms_list_credentials,
)
from cms.services import (
    list_ngfws as cms_list_ngfws,
)
from shared.errors import classify_user_message
from shared.exceptions import CMSError
from shared.log_sanitize import safe_log_value

from ._common import (
    NGFW_NOT_FOUND,
    _cms_get_ngfw_via_pkg,
    _get_user,
    _render_via_pkg,
)

logger = logging.getLogger(__name__)


class _NgfwError(Exception):
    """Internal exception carrying a JsonResponse for early-return guards."""

    def __init__(self, response: JsonResponse) -> None:
        super().__init__()
        self.response = response


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
    return _render_via_pkg(request, "mission_control/ngfw/list.html", context)


@login_required
@require_GET
def ngfw_detail(request: HttpRequest, app_id: str) -> HttpResponse:
    """View NGFW details."""
    from engine.services import get_ranges_for_ngfw

    user = _get_user(request)
    try:
        ngfw = _cms_get_ngfw_via_pkg(user, app_id)
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
    return _render_via_pkg(request, "mission_control/ngfw/detail.html", context)


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
    return _render_via_pkg(request, "mission_control/ngfw/wizard.html", context)


@login_required
@require_GET
def ngfw_deprovision(request: HttpRequest, app_id: str) -> HttpResponse:
    """NGFW deprovision confirmation page."""
    user = _get_user(request)
    try:
        ngfw = _cms_get_ngfw_via_pkg(user, app_id)
    except CMSError:
        # NGFW not found - redirect to list page
        messages.warning(request, "NGFW not found.")
        return redirect("mission_control:ngfw_list")

    context = {
        "page_title": f"Deprovision {ngfw.name}",
        "active_nav": "ngfw",
        "ngfw": ngfw,
    }
    return _render_via_pkg(request, "mission_control/ngfw/deprovision.html", context)


def _extract_ngfw_create_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Normalise the api_ngfw_create payload (string IDs → ints, strip OTP fields)."""
    deployment_profile_id = data.get("deployment_profile_id")
    scm_credential_id = data.get("scm_credential_id")
    if deployment_profile_id:
        deployment_profile_id = int(deployment_profile_id)
    if scm_credential_id:
        scm_credential_id = int(scm_credential_id)
    return {
        "name": data.get("name", "").strip(),
        "deployment_profile_id": deployment_profile_id,
        "registration_method": data.get("registration_method"),
        "scm_credential_id": scm_credential_id,
        "otp_value": data.get("otp_value", "").strip() if data.get("otp_value") else None,
        "otp_folder": data.get("otp_folder", "").strip() if data.get("otp_folder") else None,
    }


@login_required
@require_POST
def api_ngfw_create(request: HttpRequest) -> JsonResponse:
    """Create a new NGFW."""
    user = _get_user(request)
    try:
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError as e:
            raise _NgfwError(JsonResponse({"error": "Invalid JSON"}, status=400)) from e

        payload = _extract_ngfw_create_payload(data)
        try:
            ngfw_ref = cms_create_ngfw(user=user, **payload)
        except (TypeError, ValueError, CMSError) as e:
            logger.exception("NGFW creation failed: user=%s name=%s", user.pk, safe_log_value(payload.get("name", "")))
            raise _NgfwError(
                JsonResponse({"error": classify_user_message(str(e), default="NGFW could not be created")}, status=400)
            ) from e
    except _NgfwError as err:
        return err.response

    logger.info(
        "NGFW provisioning started: user=%s app_id=%s",
        safe_log_value(user.email),
        ngfw_ref.app_id,
    )
    return JsonResponse(
        {"id": str(ngfw_ref.app_id), "name": payload["name"], "status": "provisioning"},
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


def _run_ngfw_destroy(user: User, app_id: str, confirm_name: str) -> None:
    """Invoke ``cms_destroy_ngfw`` and translate errors to ``_NgfwError`` or Http404."""
    try:
        cms_destroy_ngfw(user, app_id, confirm_name)
    except CMSError as e:
        if "not found" in str(e).lower():
            raise Http404(NGFW_NOT_FOUND) from None
        logger.exception("NGFW destroy failed (CMSError): user=%s app_id=%s", user.pk, safe_log_value(app_id))
        raise _NgfwError(
            JsonResponse({"error": classify_user_message(str(e), default="NGFW could not be destroyed")}, status=400)
        ) from e
    except ValueError as e:
        logger.exception("NGFW destroy failed (ValueError): user=%s app_id=%s", user.pk, safe_log_value(app_id))
        raise _NgfwError(
            JsonResponse({"error": classify_user_message(str(e), default="Invalid destroy request")}, status=400)
        ) from e


@login_required
@require_POST
def api_ngfw_destroy(request: HttpRequest, app_id: str) -> JsonResponse:
    """Destroy an NGFW."""
    user = _get_user(request)
    try:
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError as e:
            raise _NgfwError(JsonResponse({"error": "Invalid JSON"}, status=400)) from e
        confirm_name = data.get("confirm_name", "").strip()
        _run_ngfw_destroy(user, app_id, confirm_name)
    except _NgfwError as err:
        return err.response

    logger.info(
        "NGFW deprovisioning started: user=%s app_id=%s",
        safe_log_value(user.email),
        safe_log_value(app_id),
    )
    return JsonResponse({"status": "deprovisioning"})
