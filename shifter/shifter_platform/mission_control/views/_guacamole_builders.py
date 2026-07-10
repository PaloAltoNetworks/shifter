"""Guacamole credential-resolution and URL-generation building blocks.

Split out of ``mission_control.views._guacamole`` so that module stays under
Sonar S104's 500-line cap. These are the per-protocol "resolve the connection,
then mint the signed Guacamole URL" helpers that the bootstrap worker runs off
the request thread (#929); ``_guacamole`` keeps the request parsing, the
enqueue glue, and the views.

All resolution/generation failures are raised as ``_ViewError`` carrying a
pre-built ``JsonResponse``; the view layer's ``_wrap_bootstrap_error`` converts
them into polled ``BootstrapFailure`` results.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Protocol

from django.http import JsonResponse

from shared.errors import classify_user_message
from shared.log_sanitize import safe_log_value

from ._common import INTERNAL_SERVER_ERROR

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


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


class _ViewError(Exception):
    """Internal exception carrying a pre-built JsonResponse for early return."""

    def __init__(self, response: JsonResponse) -> None:
        super().__init__()
        self.response = response


def _response_error_message(response: JsonResponse, default: str) -> str:
    """Extract a safe error string from a JsonResponse."""
    try:
        payload = json.loads(response.content.decode("utf-8"))
    except (AttributeError, json.JSONDecodeError, UnicodeDecodeError):
        return default
    message = payload.get("error") if isinstance(payload, dict) else None
    return str(message or default)


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
    from mission_control.guacamole import GuacRDPUrlRequest, create_guacamole_rdp_url

    sftp_root_directory = _sftp_root_for_os(conn_info.get("os_type"))
    try:
        return create_guacamole_rdp_url(
            GuacRDPUrlRequest(
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
        )
    except ValueError as e:
        logger.exception("Failed to generate Guacamole URL")
        raise _ViewError(JsonResponse({"error": "Failed to generate RDP URL"}, status=500)) from e


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
    from mission_control.guacamole import GuacSSHUrlRequest, create_guacamole_ssh_url

    try:
        return create_guacamole_ssh_url(
            GuacSSHUrlRequest(
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
    from mission_control.guacamole import GuacSSHUrlRequest, create_guacamole_ssh_url

    try:
        return create_guacamole_ssh_url(
            GuacSSHUrlRequest(
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
