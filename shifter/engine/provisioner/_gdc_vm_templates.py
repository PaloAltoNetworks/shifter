"""Jinja-based user_data rendering for GDC VM Runtime guests."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, Template, select_autoescape

from executors.factory import get_ssh_username
from utils.crypto import generate_ssh_host_keypair

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _load_template(name: str) -> Template:
    """Load a Jinja template from the provisioner ``templates/`` directory."""
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(
            enabled_extensions=("html", "xml"),
            default_for_string=False,
            default=False,
        ),
    )
    return env.get_template(name)


def _render_user_data(instance: dict[str, Any], hostname: str, public_key: str) -> tuple[str, str]:
    """Render the cloud-init user_data for a GDC VM Runtime instance.

    Per #762, the per-instance guest password is **not** rendered into
    user_data. The engine provisioner sets it post-boot via SSH (Linux)
    or SSH-driven PowerShell (Windows) using the per-instance SSH key
    already provisioned in ``authorized_keys`` /
    ``administrators_authorized_keys`` by this template. The DC role's
    domain Administrator password (deployment-scoped
    ``DC_DOMAIN_PASSWORD``) is set by the DC promote workflow via
    Ansible/SSM, also post-boot.

    Returns:
        tuple[str, str]: ``(user_data, host_public_key)``. For Linux guests the
        provisioner generates an Ed25519 host keypair, installs the private half
        via cloud-init ``ssh_keys:`` and returns the public half so the caller
        can seed the setup-runner's ``known_hosts`` (trusted-side-channel host
        verification, no TOFU). Windows guests use cloudbase-init (no
        ``ssh_keys`` module) and return an empty host key.
    """
    role = str(instance.get("role", "victim"))
    os_type = str(instance.get("os_type", "ubuntu"))

    if role == "dc":
        template = _load_template("dc_windows.ps1.j2")
        return template.render(public_key=public_key), ""
    if os_type == "windows":
        template = _load_template("victim_windows.ps1.j2")
        return template.render(public_key=public_key), ""

    host_private_key, host_public_key = generate_ssh_host_keypair()
    # Base64 of the private key for the setup script to install directly. The
    # script (cloud-init final stage) writes the host key and restarts sshd, so
    # the guest serves the provisioner-issued key even when sshd already started
    # with a boot-generated key or the NoCloud datasource is detected after the
    # cloud-init ssh module ran. Single-line base64 avoids YAML/heredoc
    # indentation hazards inside the embedded script.
    host_private_key_b64 = base64.b64encode(host_private_key.encode()).decode("ascii")
    if role == "attacker" or os_type == "kali":
        template = _load_template("kali.sh.j2")
        rendered = template.render(
            hostname=hostname,
            public_key=public_key,
            host_private_key=host_private_key,
            host_private_key_b64=host_private_key_b64,
            host_public_key=host_public_key,
        )
    else:
        template = _load_template("victim_linux.sh.j2")
        rendered = template.render(
            public_key=public_key,
            ssh_user=get_ssh_username(os_type, role),
            host_private_key=host_private_key,
            host_private_key_b64=host_private_key_b64,
            host_public_key=host_public_key,
        )
    return rendered, host_public_key
