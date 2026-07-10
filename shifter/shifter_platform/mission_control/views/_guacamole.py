"""Guacamole RDP/SSH URL views.

The views only parse, authenticate, and enqueue; the per-protocol credential
resolution and URL generation live in ``_guacamole_builders`` and run inside the
bootstrap worker off the request thread (#929). The split also keeps this module
under Sonar S104's 500-line cap.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from django.conf import settings as django_settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_POST

from mission_control.models import GuacamoleBootstrapRequest
from shared.log_sanitize import safe_log_fingerprint, safe_log_value

from ._common import (
    GUAC_AUTH_NOT_CONFIGURED,
    GUACAMOLE_BASE_PATH,
    _get_user,
)
from ._guacamole_bootstrap import guacamole_bootstrap_response
from ._guacamole_builders import (
    _generate_ngfw_ssh_url,
    _generate_range_ssh_url,
    _generate_rdp_url,
    _resolve_ngfw_ssh,
    _resolve_range_ssh,
    _resolve_rdp_conn,
    _response_error_message,
    _ViewError,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared parsing helpers
# ---------------------------------------------------------------------------


def _parse_json_body(request: HttpRequest) -> dict[str, Any]:
    """Parse the JSON body or raise ``_ViewError``."""
    try:
        return json.loads(request.body)
    except json.JSONDecodeError as e:
        raise _ViewError(JsonResponse({"error": "Invalid JSON"}, status=400)) from e


def _require_instance_uuid(data: dict[str, Any]) -> str:
    """Extract instance_uuid from request data or raise ``_ViewError``."""
    instance_uuid = data.get("instance_uuid", "").strip()
    if not instance_uuid:
        raise _ViewError(JsonResponse({"error": "instance_uuid is required"}, status=400))
    return instance_uuid


def _get_guac_settings(service_name: str) -> tuple[str, str, str | None]:
    """Read Guacamole settings or raise ``_ViewError``."""
    guacamole_signing_secret = getattr(django_settings, "GUACAMOLE_JSON_AUTH_SECRET", "")
    if not guacamole_signing_secret:
        logger.error(GUAC_AUTH_NOT_CONFIGURED)
        raise _ViewError(JsonResponse({"error": f"{service_name} service not configured"}, status=503))
    base_url = getattr(django_settings, "GUACAMOLE_BASE_URL", GUACAMOLE_BASE_PATH)
    api_url = getattr(django_settings, "GUACAMOLE_API_BASE_URL", None)
    return guacamole_signing_secret, base_url, api_url


def _wrap_bootstrap_error[BootstrapResultT](
    operation: str, callback: Callable[[], BootstrapResultT]
) -> BootstrapResultT:
    """Turn view-style URL generation errors into bootstrap failures."""
    from mission_control.guacamole_bootstrap import BootstrapFailure

    try:
        return callback()
    except _ViewError as err:
        message = _response_error_message(err.response, f"Failed to generate {operation} URL")
        raise BootstrapFailure(message, status_code=err.response.status_code) from err


# ---------------------------------------------------------------------------
# RDP
# ---------------------------------------------------------------------------


def _resolve_and_build_rdp_url(
    *,
    user: User,
    instance_uuid: str,
    guac_settings: tuple[str, str, str | None],
) -> str:
    """Resolve RDP credentials and build the signed URL — runs in the worker.

    Credential resolution (the Secrets Manager fetch) happens here, inside the
    bootstrap worker, not on the request thread (#929). ``_ViewError`` raised by
    resolution is converted to a polled ``BootstrapFailure`` by the caller's
    ``_wrap_bootstrap_error``.
    """
    conn_info = _resolve_rdp_conn(user, instance_uuid)
    guacamole_signing_secret, guacamole_base_url, guacamole_api_url = guac_settings
    # ``conn_info`` carries RDP credentials, so only non-secret metadata is
    # logged. ``os_type`` is read from the credential-bearing dict, so CodeQL
    # taints it regardless of naming; it goes through ``safe_log_fingerprint``
    # (a true ``py/clear-text-logging-sensitive-data`` taint-break). The
    # user/instance correlation IDs go through ``safe_log_value``.
    rdp_os = str(conn_info.get("os_type") or "unknown")
    file_transfer_available = "yes" if conn_info.get("ssh_key") else "no"
    logger.info(
        "Guac RDP request: user=%s instance_uuid=%s os=%s file_transfer_available=%s",
        safe_log_value(user.email),
        safe_log_value(instance_uuid),
        safe_log_fingerprint(rdp_os),
        file_transfer_available,
    )
    return _generate_rdp_url(
        user_email=user.email,
        conn_info=conn_info,
        guacamole_signing_secret=guacamole_signing_secret,
        guacamole_base_url=guacamole_base_url,
        guacamole_api_url=guacamole_api_url,
    )


@login_required
@require_POST
def guacamole_rdp_url(request: HttpRequest) -> JsonResponse:
    """
    Queue Guacamole URL bootstrap for RDP access to a range instance.

    Request body (JSON):
        - instance_uuid: UUID of the instance to connect to

    Response (JSON):
        - request_id: bootstrap request UUID
        - status_url: URL to poll for the signed Guacamole URL

    The request thread only parses, authenticates, and enqueues; credential
    resolution and URL generation run in the bootstrap worker so a stalled
    Secrets Manager cannot block this request thread (#929). A target that fails
    resolution (no active range, bad instance, secrets error) surfaces as a
    polled FAILED bootstrap rather than a synchronous error.

    Security:
        - User must have an active range in READY status
        - URL is signed with HMAC-SHA256 and expires in 5 minutes
        - Only works for instances with GUI (kali, ubuntu, windows)
    """
    user = _get_user(request)
    try:
        data = _parse_json_body(request)
        instance_uuid = _require_instance_uuid(data)
        guac_settings = _get_guac_settings("RDP")
    except _ViewError as err:
        return err.response

    return guacamole_bootstrap_response(
        user=user,
        protocol=GuacamoleBootstrapRequest.Protocol.RDP,
        target_id=instance_uuid,
        build_url=lambda: _wrap_bootstrap_error(
            "RDP",
            lambda: _resolve_and_build_rdp_url(
                user=user,
                instance_uuid=instance_uuid,
                guac_settings=guac_settings,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# NGFW SSH
# ---------------------------------------------------------------------------


def _resolve_and_build_ngfw_ssh_url(
    *,
    user: User,
    app_id: str,
    guac_settings: tuple[str, str, str | None],
) -> str:
    """Resolve NGFW SSH credentials and build the signed URL — runs in the worker.

    The ownership check and Secrets Manager fetch happen here, off the request
    thread (#929); ``_ViewError`` becomes a polled ``BootstrapFailure``.
    """
    ssh_conn = _resolve_ngfw_ssh(user, app_id)
    guacamole_signing_secret, guacamole_base_url, guacamole_api_url = guac_settings
    return _generate_ngfw_ssh_url(
        user_email=user.email,
        app_id=app_id,
        ssh_conn=ssh_conn,
        guacamole_signing_secret=guacamole_signing_secret,
        guacamole_base_url=guacamole_base_url,
        guacamole_api_url=guacamole_api_url,
    )


@login_required
@require_POST
def api_ngfw_ssh_url(request: HttpRequest, app_id: str) -> JsonResponse:
    """Queue Guacamole SSH URL bootstrap for NGFW CLI access.

    POST /mc/ngfw/<app_id>/ssh-url/

    The request thread only authenticates and enqueues; ownership resolution and
    the Secrets Manager fetch run in the bootstrap worker (#929). NGFW
    not-found / not-accessible / permission-denied surface as a polled FAILED
    bootstrap (HTTP error via the status endpoint) rather than a synchronous
    error.

    Args:
        request: HTTP request
        app_id: NGFW UUID

    Returns:
        JsonResponse with {"request_id": "...", "status_url": "..."}

    Security:
        - User must own the NGFW (validated via Request chain)
        - NGFW must be in ready status
        - URL is signed with HMAC-SHA256 and expires in 5 minutes
    """
    user = _get_user(request)
    try:
        guac_settings = _get_guac_settings("SSH")
    except _ViewError as err:
        return err.response

    logger.info(
        "Guacamole SSH bootstrap queued for NGFW: user=%s ngfw_uuid=%s",
        safe_log_value(user.email),
        safe_log_value(app_id),
    )
    return guacamole_bootstrap_response(
        user=user,
        protocol=GuacamoleBootstrapRequest.Protocol.NGFW_SSH,
        target_id=str(app_id),
        build_url=lambda: _wrap_bootstrap_error(
            "SSH",
            lambda: _resolve_and_build_ngfw_ssh_url(
                user=user,
                app_id=app_id,
                guac_settings=guac_settings,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Range SSH
# ---------------------------------------------------------------------------


def _resolve_and_build_range_ssh_url(
    *,
    user: User,
    instance_uuid: str,
    guac_settings: tuple[str, str, str | None],
) -> str:
    """Resolve range SSH credentials and build the signed URL — runs in the worker.

    Credential resolution (the Secrets Manager fetch) happens here, off the
    request thread (#929); ``_ViewError`` becomes a polled ``BootstrapFailure``.
    """
    ssh_info = _resolve_range_ssh(user, instance_uuid)
    guacamole_signing_secret, guacamole_base_url, guacamole_api_url = guac_settings
    # ``ssh_info`` carries the SSH private key. Only non-secret metadata is
    # logged: the host IP and cloud provider name. Both are read from the
    # credential-bearing dict, so CodeQL taints them regardless of naming; they
    # go through ``safe_log_fingerprint`` (a true taint-break) and stay
    # correlatable across log lines within the process. The user/instance
    # correlation IDs go through ``safe_log_value``.
    logger.info(
        "Guacamole SSH bootstrap queued for range instance: user=%s instance_uuid=%s host=%s provider=%s",
        safe_log_value(user.email),
        safe_log_value(instance_uuid),
        safe_log_fingerprint(ssh_info["host"]),
        safe_log_fingerprint(ssh_info.get("cloud_provider") or "unknown"),
    )
    return _generate_range_ssh_url(
        user_email=user.email,
        instance_uuid=instance_uuid,
        ssh_info=ssh_info,
        guacamole_signing_secret=guacamole_signing_secret,
        guacamole_base_url=guacamole_base_url,
        guacamole_api_url=guacamole_api_url,
    )


@login_required
@require_POST
def guacamole_ssh_url(request: HttpRequest) -> JsonResponse:
    """Queue signed Guacamole URL bootstrap for SSH access to a range instance.

    The request thread only parses, authenticates, and enqueues; credential
    resolution and URL generation run in the bootstrap worker so a stalled
    Secrets Manager cannot block this request thread (#929). A target that fails
    resolution surfaces as a polled FAILED bootstrap.
    """
    user = _get_user(request)
    try:
        data = _parse_json_body(request)
        instance_uuid = _require_instance_uuid(data)
        guac_settings = _get_guac_settings("SSH")
    except _ViewError as err:
        return err.response

    return guacamole_bootstrap_response(
        user=user,
        protocol=GuacamoleBootstrapRequest.Protocol.RANGE_SSH,
        target_id=instance_uuid,
        build_url=lambda: _wrap_bootstrap_error(
            "SSH",
            lambda: _resolve_and_build_range_ssh_url(
                user=user,
                instance_uuid=instance_uuid,
                guac_settings=guac_settings,
            ),
        ),
    )
