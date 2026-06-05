"""Jinja-based user_data rendering for GDC VM Runtime guests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, Template, select_autoescape

from executors.factory import get_ssh_username

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


def _render_user_data(instance: dict[str, Any], hostname: str, public_key: str) -> str:
    """Render the cloud-init user_data for a GDC VM Runtime instance.

    Per #762, the per-instance guest password is **not** rendered into
    user_data. The engine provisioner sets it post-boot via SSH (Linux)
    or SSH-driven PowerShell (Windows) using the per-instance SSH key
    already provisioned in ``authorized_keys`` /
    ``administrators_authorized_keys`` by this template. The DC role's
    domain Administrator password (deployment-scoped
    ``DC_DOMAIN_PASSWORD``) is set by the DC promote workflow via
    Ansible/SSM, also post-boot.
    """
    role = str(instance.get("role", "victim"))
    os_type = str(instance.get("os_type", "ubuntu"))

    if role == "dc":
        template = _load_template("dc_windows.ps1.j2")
        rendered = template.render(public_key=public_key)
    elif os_type == "windows":
        template = _load_template("victim_windows.ps1.j2")
        rendered = template.render(public_key=public_key)
    elif role == "attacker" or os_type == "kali":
        template = _load_template("kali.sh.j2")
        rendered = template.render(hostname=hostname, public_key=public_key)
    else:
        template = _load_template("victim_linux.sh.j2")
        rendered = template.render(public_key=public_key, ssh_user=get_ssh_username(os_type, role))
    return rendered
