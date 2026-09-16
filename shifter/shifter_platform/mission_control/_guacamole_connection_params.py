"""Guacamole connection-parameter builders.

Extracted from :mod:`mission_control.guacamole` to keep that module under the
file-length limit (Sonar S104). These builders construct the protocol
parameter dictionaries and are re-exported by ``guacamole`` for callers that
import them from there.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RDPConnectionParams:
    """Inputs for ``create_rdp_connection_params``.

    Bundling avoids the function's long positional/keyword signature
    (Sonar python:S107) while preserving every field's semantics.
    """

    hostname: str
    port: int = 3389
    username: str | None = None
    password: str | None = None
    ignore_cert: bool = True
    security: str = "any"
    sftp_root_directory: str | None = None
    sftp_private_key: str | None = None
    sftp_enabled: bool = True


def create_rdp_connection_params(req: RDPConnectionParams) -> dict[str, str]:
    """Create RDP connection parameters for Guacamole.

    Args:
        req: Bundled RDP connection inputs (see ``RDPConnectionParams``).

    Returns:
        Dictionary of RDP parameters for Guacamole
    """
    hostname = req.hostname
    port = req.port
    username = req.username
    password = req.password
    sftp_root_directory = req.sftp_root_directory
    sftp_private_key = req.sftp_private_key

    params: dict[str, str] = {
        "hostname": hostname,
        "port": str(port),
        "ignore-cert": "true" if req.ignore_cert else "false",
        "security": req.security,
        "resize-method": "display-update",
        # Clipboard support
        "disable-copy": "false",
        "disable-paste": "false",
        # Performance optimizations - reduce bandwidth and server-side rendering load
        "color-depth": "16",
        "disable-audio": "true",
        "enable-wallpaper": "false",
        "enable-theming": "false",
        "enable-font-smoothing": "false",
        "enable-full-window-drag": "false",
        "enable-desktop-composition": "false",
        "enable-menu-animations": "false",
    }

    # SFTP file transfer - works reliably for both Windows and Linux (xrdp)
    # Uses SSH connection for file transfers via Guacamole menu (Ctrl+Alt+Shift)
    if req.sftp_enabled and username and (password or sftp_private_key):
        params["enable-sftp"] = "true"
        params["sftp-hostname"] = hostname
        params["sftp-port"] = "22"
        params["sftp-username"] = username
        # Prefer key-based auth (required for Windows OpenSSH)
        if sftp_private_key:
            params["sftp-private-key"] = sftp_private_key
        elif password:
            params["sftp-password"] = password
        if sftp_root_directory:
            params["sftp-root-directory"] = sftp_root_directory
            # sftp-directory is the upload destination for drag-and-drop transfers
            params["sftp-directory"] = sftp_root_directory

    if username:
        params["username"] = username
    if password:
        params["password"] = password

    return params


def create_ssh_connection_params(
    username: str,
    hostname: str,
    port: int = 22,
    ssh_private_key: str | None = None,
) -> dict[str, str]:
    """Create SSH connection parameters for Guacamole.

    Args:
        username: SSH username for login
        hostname: Target host IP or hostname
        port: SSH port (default 22)
        ssh_private_key: PEM-encoded private key for authentication

    Returns:
        Dictionary of SSH parameters for Guacamole
    """
    params: dict[str, str] = {
        "hostname": hostname,
        "port": str(port),
        "username": username,
        # Terminal settings
        "color-scheme": "green-black",
        "font-name": "monospace",
        "font-size": "12",
        # Clipboard support
        "enable-clipboard": "true",
    }

    if ssh_private_key:
        params["private-key"] = ssh_private_key

    return params
