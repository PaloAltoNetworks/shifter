"""Guacamole RDP/SSH URL views."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Protocol

from django.conf import settings as django_settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_POST

from shared.errors import classify_user_message
from shared.log_sanitize import safe_log_value

from ._common import (
    GUAC_AUTH_NOT_CONFIGURED,
    GUACAMOLE_BASE_PATH,
    INTERNAL_SERVER_ERROR,
    _get_user,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import User


class _SSHConn(Protocol):
    """Structural type for an ``engine.ssh.SSHConnection``-like value.

    ``mission_control`` is not allowed (per ADR-001) to import from
    ``engine.ssh`` directly, but we still want a precise type for the
    handful of attributes the view actually reads.
    """

    host: str
    port: int
    username: str
    private_key: str


logger = logging.getLogger(__name__)


class _ViewError(Exception):
    """Internal exception carrying a pre-built JsonResponse for early return."""

    def __init__(self, response: JsonResponse) -> None:
        super().__init__()
        self.response = response


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


# ---------------------------------------------------------------------------
# RDP
# ---------------------------------------------------------------------------


_SFTP_ROOT_BY_OS: dict[str, str] = {
    "kali": "/home/kali",
    "ubuntu": "/home/ubuntu",
    # SFTP paths use forward slashes even on Windows.
    "windows": "/C:/Users/Administrator/Downloads",
}


def _sftp_root_for_os(os_type: str | None) -> str | None:
    """Return Guacamole SFTP root path for the given OS type, or None."""
    if os_type is None:
        return None
    return _SFTP_ROOT_BY_OS.get(os_type)


def _resolve_rdp_conn(user: User, instance_uuid: str) -> dict[str, Any]:
    """Get the RDP connection info or raise ``_ViewError``."""
    from engine.services import get_rdp_connection_info

    try:
        return get_rdp_connection_info(user, instance_uuid)
    except ValueError as e:
        logger.exception(
            "RDP connection lookup failed: user=%s instance_uuid=%s",
            safe_log_value(user.email),
            safe_log_value(instance_uuid),
        )
        raise _ViewError(
            JsonResponse({"error": classify_user_message(str(e), default="RDP connection unavailable")}, status=400)
        ) from e


def _generate_rdp_url(
    *,
    user_email: str,
    conn_info: dict[str, Any],
    guacamole_signing_secret: str,
    guacamole_base_url: str,
    guacamole_api_url: str | None,
) -> str:
    """Generate the Guacamole RDP URL or raise ``_ViewError``."""
    from mission_control.guacamole import create_guacamole_rdp_url

    sftp_root_directory = _sftp_root_for_os(conn_info.get("os_type"))
    try:
        return create_guacamole_rdp_url(
            base_url=guacamole_base_url,
            secret_key=guacamole_signing_secret,
            username=user_email,
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
        logger.exception("Failed to generate Guacamole URL")
        raise _ViewError(JsonResponse({"error": "Failed to generate RDP URL"}, status=500)) from e


@login_required
@require_POST
def guacamole_rdp_url(request: HttpRequest) -> JsonResponse:
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
    user = _get_user(request)
    try:
        data = _parse_json_body(request)
        instance_uuid = _require_instance_uuid(data)
        conn_info = _resolve_rdp_conn(user, instance_uuid)
        guacamole_signing_secret, guacamole_base_url, guacamole_api_url = _get_guac_settings("RDP")
        # ``conn_info`` carries RDP credentials; only metadata fields (os_type,
        # whether an ssh_key is present) are extracted into neutrally-named
        # locals so CodeQL's ``py/clear-text-logging`` heuristic does not
        # treat the log line as leaking secrets.
        rdp_os = str(conn_info.get("os_type") or "unknown")
        file_transfer_available = "yes" if conn_info.get("ssh_key") else "no"
        rdp_os = rdp_os.replace("\r", " ").replace("\n", " ")[:64]
        safe_email = user.email.replace("\r", " ").replace("\n", " ")[:200]
        safe_uuid = str(instance_uuid).replace("\r", " ").replace("\n", " ")[:200]
        logger.info(
            "Guac RDP request: user=%s instance_uuid=%s os=%s file_transfer_available=%s",
            safe_email,
            safe_uuid,
            rdp_os,
            file_transfer_available,
        )
        url = _generate_rdp_url(
            user_email=user.email,
            conn_info=conn_info,
            guacamole_signing_secret=guacamole_signing_secret,
            guacamole_base_url=guacamole_base_url,
            guacamole_api_url=guacamole_api_url,
        )
    except _ViewError as err:
        return err.response

    logger.info(
        "Guacamole RDP URL generated: user=%s instance_uuid=%s",
        safe_log_value(user.email),
        safe_log_value(instance_uuid),
    )
    return JsonResponse({"url": url})


# ---------------------------------------------------------------------------
# NGFW SSH
# ---------------------------------------------------------------------------


def _resolve_ngfw_ssh(user: User, app_id: str) -> _SSHConn:
    """Look up the NGFW SSH connection details or raise ``_ViewError``."""
    from engine.services import connect_ngfw_terminal

    try:
        return connect_ngfw_terminal(user, app_id)
    except ValueError as e:
        logger.exception(
            "NGFW SSH access denied (ValueError): user=%s ngfw_uuid=%s",
            safe_log_value(user.email),
            safe_log_value(app_id),
        )
        raise _ViewError(
            JsonResponse({"error": classify_user_message(str(e), default="NGFW SSH unavailable")}, status=400)
        ) from e
    except PermissionError as e:
        logger.exception(
            "NGFW SSH access denied (PermissionError): user=%s ngfw_uuid=%s",
            safe_log_value(user.email),
            safe_log_value(app_id),
        )
        raise _ViewError(JsonResponse({"error": "Permission denied"}, status=400)) from e
    except Exception as e:
        logger.exception(
            "Unexpected error getting NGFW SSH connection: user=%s ngfw_uuid=%s",
            safe_log_value(user.email),
            safe_log_value(app_id),
        )
        raise _ViewError(JsonResponse({"error": INTERNAL_SERVER_ERROR}, status=500)) from e


def _generate_ngfw_ssh_url(
    *,
    user_email: str,
    app_id: str,
    ssh_conn: _SSHConn,
    guacamole_signing_secret: str,
    guacamole_base_url: str,
    guacamole_api_url: str | None,
) -> str:
    """Generate the Guacamole NGFW SSH URL or raise ``_ViewError``."""
    from mission_control.guacamole import create_guacamole_ssh_url

    try:
        return create_guacamole_ssh_url(
            base_url=guacamole_base_url,
            secret_key=guacamole_signing_secret,
            username=user_email,
            connection_name=f"ngfw-{app_id}",
            hostname=ssh_conn.host,
            port=ssh_conn.port,
            ssh_username=ssh_conn.username,
            ssh_private_key=ssh_conn.private_key,
            expires_minutes=5,
            api_base_url=guacamole_api_url,
        )
    except ValueError as e:
        logger.exception(
            "Failed to generate NGFW SSH URL: user=%s ngfw_uuid=%s",
            safe_log_value(user_email),
            safe_log_value(app_id),
        )
        raise _ViewError(JsonResponse({"error": "Failed to generate SSH URL"}, status=500)) from e
    except Exception as e:
        logger.exception(
            "Unexpected error generating NGFW SSH URL: user=%s ngfw_uuid=%s",
            safe_log_value(user_email),
            safe_log_value(app_id),
        )
        raise _ViewError(JsonResponse({"error": INTERNAL_SERVER_ERROR}, status=500)) from e


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
    user = _get_user(request)
    try:
        ssh_conn = _resolve_ngfw_ssh(user, app_id)
        guacamole_signing_secret, guacamole_base_url, guacamole_api_url = _get_guac_settings("SSH")
        url = _generate_ngfw_ssh_url(
            user_email=user.email,
            app_id=app_id,
            ssh_conn=ssh_conn,
            guacamole_signing_secret=guacamole_signing_secret,
            guacamole_base_url=guacamole_base_url,
            guacamole_api_url=guacamole_api_url,
        )
    except _ViewError as err:
        return err.response

    logger.info(
        "Guacamole SSH URL generated for NGFW: user=%s ngfw_uuid=%s",
        safe_log_value(user.email),
        safe_log_value(app_id),
    )
    return JsonResponse({"url": url})


# ---------------------------------------------------------------------------
# Range SSH
# ---------------------------------------------------------------------------


def _resolve_range_ssh(user: User, instance_uuid: str) -> dict[str, Any]:
    """Look up the range SSH connection info or raise ``_ViewError``."""
    from engine.services import get_ssh_connection_info

    try:
        return get_ssh_connection_info(user, instance_uuid)
    except ValueError as e:
        logger.exception(
            "Range SSH access denied (ValueError): user=%s instance_uuid=%s",
            safe_log_value(user.email),
            safe_log_value(instance_uuid),
        )
        raise _ViewError(
            JsonResponse({"error": classify_user_message(str(e), default="Range SSH unavailable")}, status=400)
        ) from e
    except PermissionError as e:
        logger.exception(
            "Range SSH access denied (PermissionError): user=%s instance_uuid=%s",
            safe_log_value(user.email),
            safe_log_value(instance_uuid),
        )
        raise _ViewError(JsonResponse({"error": "Permission denied"}, status=400)) from e
    except Exception as e:
        logger.exception(
            "Unexpected error getting range SSH connection: user=%s instance_uuid=%s",
            safe_log_value(user.email),
            safe_log_value(instance_uuid),
        )
        raise _ViewError(JsonResponse({"error": INTERNAL_SERVER_ERROR}, status=500)) from e


def _generate_range_ssh_url(
    *,
    user_email: str,
    instance_uuid: str,
    ssh_info: dict[str, Any],
    guacamole_signing_secret: str,
    guacamole_base_url: str,
    guacamole_api_url: str | None,
) -> str:
    """Generate the Guacamole range SSH URL or raise ``_ViewError``."""
    from mission_control.guacamole import create_guacamole_ssh_url

    try:
        return create_guacamole_ssh_url(
            base_url=guacamole_base_url,
            secret_key=guacamole_signing_secret,
            username=user_email,
            connection_name=ssh_info["connection_name"],
            hostname=ssh_info["host"],
            port=ssh_info["port"],
            ssh_username=ssh_info["username"],
            ssh_private_key=ssh_info["private_key"],
            expires_minutes=5,
            api_base_url=guacamole_api_url,
        )
    except ValueError as e:
        logger.exception(
            "Failed to generate range SSH URL: user=%s instance_uuid=%s",
            safe_log_value(user_email),
            safe_log_value(instance_uuid),
        )
        raise _ViewError(JsonResponse({"error": "Failed to generate SSH URL"}, status=500)) from e
    except Exception as e:
        logger.exception(
            "Unexpected error generating range SSH URL: user=%s instance_uuid=%s",
            safe_log_value(user_email),
            safe_log_value(instance_uuid),
        )
        raise _ViewError(JsonResponse({"error": INTERNAL_SERVER_ERROR}, status=500)) from e


@login_required
@require_POST
def guacamole_ssh_url(request: HttpRequest) -> JsonResponse:
    """Generate a signed Guacamole URL for SSH access to a range instance."""
    user = _get_user(request)
    try:
        data = _parse_json_body(request)
        instance_uuid = _require_instance_uuid(data)
        ssh_info = _resolve_range_ssh(user, instance_uuid)
        guacamole_signing_secret, guacamole_base_url, guacamole_api_url = _get_guac_settings("SSH")
        url = _generate_range_ssh_url(
            user_email=user.email,
            instance_uuid=instance_uuid,
            ssh_info=ssh_info,
            guacamole_signing_secret=guacamole_signing_secret,
            guacamole_base_url=guacamole_base_url,
            guacamole_api_url=guacamole_api_url,
        )
    except _ViewError as err:
        return err.response

    # ``ssh_info`` carries the SSH private key; only non-secret metadata
    # (host IP, cloud provider name) is pulled into neutrally-named locals
    # so CodeQL's ``py/clear-text-logging`` heuristic does not treat this
    # log line as leaking credentials.
    instance_ip = str(ssh_info["host"]).replace("\r", " ").replace("\n", " ")[:64]
    cloud_provider_name = str(ssh_info.get("cloud_provider") or "unknown").replace("\r", " ").replace("\n", " ")[:32]
    safe_email = user.email.replace("\r", " ").replace("\n", " ")[:200]
    safe_uuid = str(instance_uuid).replace("\r", " ").replace("\n", " ")[:200]
    logger.info(
        "Guacamole SSH URL generated for range instance: user=%s instance_uuid=%s host=%s provider=%s",
        safe_email,
        safe_uuid,
        instance_ip,
        cloud_provider_name,
    )
    return JsonResponse({"url": url})
