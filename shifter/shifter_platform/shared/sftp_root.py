"""Validation for the non-secret Guacamole SFTP root directory (#375).

The SFTP root is per-image realized connection metadata, not a secret, but it is
still untrusted configuration until these shape checks run. This module is
deliberately Django-free so the standalone provisioner image (which validates it
at image-config load) and the platform's closed RAES result parser can share one
validator instead of duplicating the parser.

The value is a guest-visible path in Guacamole's SFTP form: absolute, forward
slashes only (Windows uses the ``/C:/...`` syntax), no traversal, no control
characters. It never reaches a shell, argv, Terraform command, log, or error
body; it travels to Guacamole only inside the encrypted JSON-auth payload.
"""

from __future__ import annotations

_MAX_SFTP_ROOT_LEN = 512

# The built-in range images' default SFTP roots, keyed by ``os_type``. These are
# the "initial image records" the #375 preflight preserves: they seed the GCE
# image-profile defaults and back the GDC/VM-runtime provisioning helper, so a
# freshly provisioned stock guest carries its declared root without Mission
# Control ever guessing from ``os_type`` at connection time.
DEFAULT_SFTP_ROOT_BY_OS: dict[str, str] = {
    "kali": "/home/kali",
    "ubuntu": "/home/ubuntu",
    # SFTP paths use forward slashes even on Windows.
    "windows": "/C:/Users/Administrator/Downloads",
}


def default_sftp_root_directory(os_type: str) -> str:
    """Return the built-in image's default SFTP root for ``os_type``, or ``""``."""
    return DEFAULT_SFTP_ROOT_BY_OS.get((os_type or "").strip().lower(), "")


def sftp_root_output_field(value: object) -> dict[str, str]:
    """Return ``{"sftp_root_directory": <root>}`` when an image declares one, else ``{}``.

    Pure emit decision for a realized provisioner output (#375): a blank/absent
    root emits no key, so the connection layer disables SFTP rather than pinning a
    guessed directory. Kept here so producers get a tested omit-branch without
    patching their cloud boundaries.
    """
    root = str(value or "")
    return {"sftp_root_directory": root} if root else {}


class SftpRootError(ValueError):
    """Raised when an SFTP root directory is malformed or unsafe."""


def normalize_sftp_root_directory(value: str) -> str:
    """Return the validated, stripped SFTP root, or raise ``SftpRootError``.

    Rejects a non-string, empty/whitespace-only, non-absolute, over-length,
    backslash (ambiguous Windows form), control-character/NUL, or path-traversal
    value. Never substitutes a default: a caller that has no root must not call
    this with a placeholder.
    """
    if not isinstance(value, str):
        raise SftpRootError("sftp root directory must be a string")
    stripped = value.strip()
    if not stripped:
        raise SftpRootError("sftp root directory must be a non-empty string")
    if len(stripped) > _MAX_SFTP_ROOT_LEN:
        raise SftpRootError(f"sftp root directory exceeds the {_MAX_SFTP_ROOT_LEN}-character limit")
    if not stripped.startswith("/"):
        raise SftpRootError("sftp root directory must be an absolute Guacamole path starting with '/'")
    if "\\" in stripped:
        raise SftpRootError("sftp root directory must use forward slashes, not backslashes")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in stripped):
        raise SftpRootError("sftp root directory must not contain control characters")
    if ".." in stripped.split("/"):
        raise SftpRootError("sftp root directory must not contain path traversal segments")
    return stripped
