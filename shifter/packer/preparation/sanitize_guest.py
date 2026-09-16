"""Remove this profile's staging and guest identities after first boot completes."""

from __future__ import annotations

import shutil
from pathlib import Path


def _path(root: Path, relative: str) -> Path:
    """Handle path."""
    current = root
    parts = Path(relative).parts
    for part in parts[:-1]:
        current /= part
        if current.is_symlink():
            raise ValueError("guest sanitization parent contains a link")
    return current / parts[-1]


def _remove(path: Path) -> None:
    """Handle remove."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _directory(root: Path, relative: str) -> Path:
    """Handle directory."""
    path = _path(root, relative)
    if path.is_symlink():
        raise ValueError("guest sanitization directory contains a link")
    return path


def sanitize_root(root: Path) -> None:
    """Sanitize only one explicit guest root; do not follow candidate-controlled links."""
    for relative in ("var/lib/shifter-preparation", "var/lib/cloud/instances", "root/.ssh"):
        _remove(_path(root, relative))
    homes = _directory(root, "home")
    if homes.exists():
        for home in homes.iterdir():
            if home.is_symlink():
                raise ValueError("guest user home contains a link")
            if home.is_dir():
                _remove(home / ".ssh")
    for cached in _directory(root, "tmp").glob("metadata-script*"):
        _remove(cached)
    for key in _directory(root, "etc/ssh").glob("ssh_host_*"):
        _remove(key)
    machine_id = _path(root, "etc/machine-id")
    _remove(machine_id)
    machine_id.write_text("")
    machine_id.chmod(0o644)
    dbus = _path(root, "var/lib/dbus/machine-id")
    if dbus.parent.exists():
        _remove(dbus)
        dbus.symlink_to("../../../etc/machine-id")


if __name__ == "__main__":
    sanitize_root(Path("/"))
