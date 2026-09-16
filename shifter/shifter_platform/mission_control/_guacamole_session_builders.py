"""Per-protocol resolve-and-mint building blocks for the Guacamole session service.

Split out of :mod:`mission_control.guacamole_session` (issue #991) so that module
stays under Sonar S104's 500-line cap, mirroring the prior
``views/_guacamole`` + ``views/_guacamole_builders`` split. These are the
worker-side "resolve the sanctioned ``engine.services`` connection projection,
adapt it into the existing ``mission_control.guacamole`` request dataclass, then
mint the signed URL" helpers that the bootstrap worker runs off the request
thread (#929); the session module keeps the HTTP-neutral entry point, the
closed access-kind dispatch, and the enqueue glue.

All resolution/generation failures are raised as
:class:`~mission_control.guacamole_bootstrap.BootstrapFailure` (a safe message +
HTTP status code); the bootstrap worker persists them and the status endpoint
surfaces them. There is no presentation coupling here — no ``JsonResponse``, no
response-body re-parsing, and only the ADR-001-R4 allowlisted ``engine.services``
symbols are consumed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from mission_control.guacamole_bootstrap import BootstrapFailure
from shared.errors import classify_user_message
from shared.log_sanitize import safe_log_fingerprint, safe_log_value

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from mission_control.guacamole import GuacamoleClient

logger = logging.getLogger(__name__)

_INTERNAL_SERVER_ERROR = "Internal server error"


class _SSHConn(Protocol):
    """Structural type for an ``engine.services.SSHConnection``-like value.

    ``mission_control`` reads only the handful of attributes below from the
    sanctioned public Engine projection; this is not a second connection schema.
    """

    host: str
    port: int
    username: str
    private_key: str


# ---------------------------------------------------------------------------
# Session identity and configuration binding
# ---------------------------------------------------------------------------


def guacamole_identity(user: User) -> str:
    """Return the Guacamole JSON-auth session identity for ``user``.

    The Guacamole session username is an identity label, not an email. Platform
    (OIDC) users carry an email and use it, but isolated temporary CTF accounts
    (issue #1206) are created with a blank ``email`` and a unique ``range-<hex>``
    username. Passing the blank email to Guacamole is rejected with
    ``400 "The username must not be blank."``, so fall back to the account's
    unique username, which is also a correct per-user-isolated session identity.
    """
    return user.email or user.get_username()


# ---------------------------------------------------------------------------
# RDP
# ---------------------------------------------------------------------------


# Guacamole's RDP security mode, the same for every target: the mode is left to
# the RDP handshake rather than pinned per OS.
#
# Issue #1801 pinned Kali to ``tls`` on the assumption that xrdp only speaks
# TLS. That is not true of the range's Kali guest, and pinning breaks it: an
# X.224 negotiation probe against a live range host shows the server answering
# ``RDP_NEG_RSP`` with ``PROTOCOL_RDP`` (0) for *every* request — including
# requests for TLS, HYBRID/NLA, and RDSTLS. Pinning ``tls`` therefore makes
# guacd demand a protocol the guest never selects, and the session dies with
# "Security negotiation failed (wrong security type?)" after the tunnel and
# Guacamole authentication have both succeeded (issue #987).
#
# ``any`` lets the handshake settle it, so a guest that offers only legacy RDP
# security and a guest that offers TLS both connect without a per-image
# allowlist here.
_RDP_SECURITY_MODE = "any"


def _resolve_rdp_conn(user: User, instance_uuid: str) -> dict[str, Any]:
    """Resolve the RDP connection info or raise ``BootstrapFailure``."""
    from cms.services import get_range_rdp_connection_info

    try:
        return get_range_rdp_connection_info(user, instance_uuid)
    except (PermissionError, ValueError) as e:
        logger.warning(
            "RDP connection lookup failed: user=%s instance_uuid=%s reason=%s",
            safe_log_fingerprint(user.email),
            safe_log_value(instance_uuid),
            safe_log_fingerprint(e),
        )
        raise BootstrapFailure(
            classify_user_message(str(e), default="RDP connection unavailable"), status_code=400
        ) from e


def _generate_rdp_url(
    *,
    username: str,
    conn_info: dict[str, Any],
    guac_client: GuacamoleClient,
) -> str:
    """Generate the Guacamole RDP URL or raise ``BootstrapFailure``."""
    from mission_control.guacamole import GuacRDPUrlRequest

    # The SFTP root is realized per-image metadata resolved by the engine (#375);
    # Mission Control consumes it and never derives it from ``os_type``. SFTP
    # requires a pinned root: when the realized instance carries none (an older
    # record, or a producer that omitted it), fail closed by disabling SFTP
    # entirely rather than letting Guacamole fall back to its unrestricted default
    # root, which would expose the guest filesystem beyond the intended directory.
    sftp_root_directory = conn_info.get("sftp_root_directory")
    sftp_enabled = conn_info.get("sftp_enabled") is not False and bool(sftp_root_directory)
    try:
        return guac_client.create_rdp_url(
            GuacRDPUrlRequest(
                username=username,
                connection_name=conn_info["connection_name"],
                hostname=conn_info["private_ip"],
                expires_minutes=5,
                rdp_username=conn_info.get("rdp_username"),
                rdp_password=conn_info.get("rdp_password"),
                sftp_root_directory=sftp_root_directory,
                sftp_private_key=conn_info.get("ssh_key"),
                sftp_enabled=sftp_enabled,
                security=_RDP_SECURITY_MODE,
            )
        )
    except ValueError as e:
        logger.warning("Failed to generate Guacamole RDP URL: reason=%s", safe_log_fingerprint(e))
        raise BootstrapFailure("Failed to generate RDP URL", status_code=500) from e


def _build_rdp_url(*, user: User, instance_uuid: str, guac_client: GuacamoleClient) -> str:
    """Resolve RDP credentials and build the signed URL — runs in the worker.

    Credential resolution (the Secrets Manager fetch) happens here, inside the
    bootstrap worker, not on the request thread (#929).
    """
    conn_info = _resolve_rdp_conn(user, instance_uuid)
    # ``conn_info`` carries RDP credentials, so only non-secret metadata is
    # logged. ``os_type`` is read from the credential-bearing dict, so CodeQL
    # taints it regardless of naming; it goes through ``safe_log_fingerprint``
    # (a true ``py/clear-text-logging-sensitive-data`` taint-break). The
    # user identities are fingerprinted; the instance correlation ID goes
    # through ``safe_log_value``.
    rdp_os = str(conn_info.get("os_type") or "unknown")
    file_transfer_available = "yes" if conn_info.get("sftp_enabled") is not False else "no"
    logger.info(
        "Guac RDP request: user=%s instance_uuid=%s os=%s file_transfer_available=%s",
        safe_log_fingerprint(user.email),
        safe_log_value(instance_uuid),
        safe_log_fingerprint(rdp_os),
        file_transfer_available,
    )
    return _generate_rdp_url(
        username=guacamole_identity(user),
        conn_info=conn_info,
        guac_client=guac_client,
    )


# ---------------------------------------------------------------------------
# NGFW SSH
# ---------------------------------------------------------------------------


def _resolve_ngfw_ssh(user: User, app_id: str) -> _SSHConn:
    """Look up the NGFW SSH connection details or raise ``BootstrapFailure``."""
    from engine.services import connect_ngfw_terminal

    try:
        return connect_ngfw_terminal(user, app_id)
    except ValueError as e:
        logger.warning(
            "NGFW SSH access denied: user=%s ngfw_uuid=%s reason=%s",
            safe_log_fingerprint(user.email),
            safe_log_value(app_id),
            safe_log_fingerprint(e),
        )
        raise BootstrapFailure(classify_user_message(str(e), default="NGFW SSH unavailable"), status_code=400) from e
    except PermissionError as e:
        logger.warning(
            "NGFW SSH access denied: user=%s ngfw_uuid=%s reason=%s",
            safe_log_fingerprint(user.email),
            safe_log_value(app_id),
            safe_log_fingerprint(e),
        )
        raise BootstrapFailure("Permission denied", status_code=400) from e
    except Exception as e:
        logger.exception(
            "Unexpected error getting NGFW SSH connection: user=%s ngfw_uuid=%s reason=%s",
            safe_log_fingerprint(user.email),
            safe_log_value(app_id),
            safe_log_fingerprint(e),
            # Never append the original exception text; upstream connection
            # failures can carry credential-bearing values.
            exc_info=False,
        )
        raise BootstrapFailure(_INTERNAL_SERVER_ERROR, status_code=500) from e


def _generate_ngfw_ssh_url(
    *,
    username: str,
    app_id: str,
    ssh_conn: _SSHConn,
    guac_client: GuacamoleClient,
) -> str:
    """Generate the Guacamole NGFW SSH URL or raise ``BootstrapFailure``."""
    from mission_control.guacamole import GuacSSHUrlRequest

    try:
        return guac_client.create_ssh_url(
            GuacSSHUrlRequest(
                username=username,
                connection_name=f"ngfw-{app_id}",
                hostname=ssh_conn.host,
                port=ssh_conn.port,
                ssh_username=ssh_conn.username,
                ssh_private_key=ssh_conn.private_key,
                expires_minutes=5,
            )
        )
    except ValueError as e:
        logger.warning(
            "Failed to generate NGFW SSH URL: ngfw_uuid=%s reason=%s",
            safe_log_value(app_id),
            safe_log_fingerprint(e),
        )
        raise BootstrapFailure("Failed to generate SSH URL", status_code=500) from e
    except Exception as e:
        logger.exception(
            "Unexpected error generating NGFW SSH URL: ngfw_uuid=%s reason=%s",
            safe_log_value(app_id),
            safe_log_fingerprint(e),
            exc_info=False,
        )
        raise BootstrapFailure(_INTERNAL_SERVER_ERROR, status_code=500) from e


def _build_ngfw_ssh_url(*, user: User, app_id: str, guac_client: GuacamoleClient) -> str:
    """Resolve NGFW SSH credentials and build the signed URL — runs in the worker.

    The ownership check and Secrets Manager fetch happen here, off the request
    thread (#929).
    """
    ssh_conn = _resolve_ngfw_ssh(user, app_id)
    return _generate_ngfw_ssh_url(
        username=guacamole_identity(user),
        app_id=app_id,
        ssh_conn=ssh_conn,
        guac_client=guac_client,
    )


# ---------------------------------------------------------------------------
# Range SSH
# ---------------------------------------------------------------------------


def _resolve_range_ssh(user: User, instance_uuid: str) -> dict[str, Any]:
    """Look up the range SSH connection info or raise ``BootstrapFailure``."""
    from cms.services import get_range_ssh_connection_info

    try:
        return get_range_ssh_connection_info(user, instance_uuid)
    except ValueError as e:
        logger.warning(
            "Range SSH access denied: user=%s instance_uuid=%s reason=%s",
            safe_log_fingerprint(user.email),
            safe_log_value(instance_uuid),
            safe_log_fingerprint(e),
        )
        raise BootstrapFailure(classify_user_message(str(e), default="Range SSH unavailable"), status_code=400) from e
    except PermissionError as e:
        logger.warning(
            "Range SSH access denied: user=%s instance_uuid=%s reason=%s",
            safe_log_fingerprint(user.email),
            safe_log_value(instance_uuid),
            safe_log_fingerprint(e),
        )
        raise BootstrapFailure("Permission denied", status_code=400) from e
    except Exception as e:
        logger.exception(
            "Unexpected error getting range SSH connection: user=%s instance_uuid=%s reason=%s",
            safe_log_fingerprint(user.email),
            safe_log_value(instance_uuid),
            safe_log_fingerprint(e),
            # Never append the original exception text; range connection data
            # may contain private keys or passwords.
            exc_info=False,
        )
        raise BootstrapFailure(_INTERNAL_SERVER_ERROR, status_code=500) from e


def _generate_range_ssh_url(
    *,
    username: str,
    instance_uuid: str,
    ssh_info: dict[str, Any],
    guac_client: GuacamoleClient,
) -> str:
    """Generate the Guacamole range SSH URL or raise ``BootstrapFailure``."""
    from mission_control.guacamole import GuacSSHUrlRequest

    try:
        return guac_client.create_ssh_url(
            GuacSSHUrlRequest(
                username=username,
                connection_name=ssh_info["connection_name"],
                hostname=ssh_info["host"],
                port=ssh_info["port"],
                ssh_username=ssh_info["username"],
                ssh_private_key=ssh_info["private_key"],
                expires_minutes=5,
            )
        )
    except ValueError as e:
        logger.warning(
            "Failed to generate range SSH URL: instance_uuid=%s reason=%s",
            safe_log_value(instance_uuid),
            safe_log_fingerprint(e),
        )
        raise BootstrapFailure("Failed to generate SSH URL", status_code=500) from e
    except Exception as e:
        logger.exception(
            "Unexpected error generating range SSH URL: instance_uuid=%s reason=%s",
            safe_log_value(instance_uuid),
            safe_log_fingerprint(e),
            exc_info=False,
        )
        raise BootstrapFailure(_INTERNAL_SERVER_ERROR, status_code=500) from e


def _build_range_ssh_url(*, user: User, instance_uuid: str, guac_client: GuacamoleClient) -> str:
    """Resolve range SSH credentials and build the signed URL — runs in the worker.

    Credential resolution (the Secrets Manager fetch) happens here, off the
    request thread (#929).
    """
    ssh_info = _resolve_range_ssh(user, instance_uuid)
    # ``ssh_info`` carries the SSH private key. Only non-secret metadata is
    # logged: the host IP and cloud provider name. Both are read from the
    # credential-bearing dict, so CodeQL taints them regardless of naming; they
    # go through ``safe_log_fingerprint`` (a true taint-break) and stay
    # correlatable across log lines within the process. User identity is
    # fingerprinted; the instance correlation ID goes through ``safe_log_value``.
    logger.info(
        "Guacamole SSH bootstrap queued for range instance: user=%s instance_uuid=%s host=%s provider=%s",
        safe_log_fingerprint(user.email),
        safe_log_value(instance_uuid),
        safe_log_fingerprint(ssh_info["host"]),
        safe_log_fingerprint(ssh_info.get("cloud_provider") or "unknown"),
    )
    return _generate_range_ssh_url(
        username=guacamole_identity(user),
        instance_uuid=instance_uuid,
        ssh_info=ssh_info,
        guac_client=guac_client,
    )
