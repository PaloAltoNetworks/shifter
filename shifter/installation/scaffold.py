"""Scaffold a starting ``shifter.yaml`` from a checked backend example (``init`` UX, #727).

``init`` is the local-only half of the backend-aware setup UX: it copies one of the
checked ``examples/<backend>.yaml`` files to the operator's ``shifter.yaml`` so they start
from a valid, backend-shaped config rather than a blank file, then run ``doctor`` to
validate it. It authenticates to nothing, writes no secrets, and touches no cloud API — it
is a single file copy of committed, non-sensitive example text (preflight #727).

The examples are the same files the AWS/GCP backend bundles declare under
``owned_files.examples``; there is no second template source.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .registry import KNOWN_BACKENDS

#: Directory holding the checked per-backend example configs, relative to this package.
EXAMPLES_DIR: Path = Path(__file__).resolve().parent / "examples"

#: The default destination for a scaffolded root config: ``shifter.yaml`` in the CWD.
DEFAULT_DESTINATION = Path("shifter.yaml")


class ScaffoldError(Exception):
    """Raised when a config cannot be scaffolded (unknown backend, refused overwrite, I/O)."""


@dataclass(frozen=True)
class ScaffoldResult:
    """The outcome of a successful :func:`scaffold_config` call."""

    backend: str
    destination: Path
    source: Path


def _example_path(backend: str, examples_dir: Path) -> Path:
    """The checked example config path for ``backend`` under ``examples_dir``."""
    return examples_dir / f"{backend}.yaml"


def _validated_destination(destination: str | Path | None) -> Path:
    """Normalize the operator-supplied output path, rejecting a NUL byte before any I/O."""
    raw = destination if destination is not None else DEFAULT_DESTINATION
    if "\x00" in str(raw):
        raise ScaffoldError("destination path contains a NUL byte")
    return Path(raw)


def available_backends(examples_dir: Path = EXAMPLES_DIR) -> list[str]:
    """Backend names that ship a checked example config, sorted.

    A backend is offered by ``init`` only when it is a known registry backend *and* it has a
    committed ``examples/<backend>.yaml`` to copy.
    """
    return sorted(name for name in KNOWN_BACKENDS if _example_path(name, examples_dir).is_file())


def scaffold_config(
    backend: str,
    destination: str | Path | None = None,
    *,
    force: bool = False,
    examples_dir: Path = EXAMPLES_DIR,
) -> ScaffoldResult:
    """Copy the checked example for ``backend`` to ``destination`` (default ``./shifter.yaml``).

    The example is copied verbatim so the operator starts from the same committed,
    non-sensitive text the backend bundle declares. Raises :class:`ScaffoldError` for an
    unknown backend, a missing example, an existing destination without ``force``, or a
    write failure — messages name the backend and paths only, never file contents.
    """
    backends = available_backends(examples_dir)
    if backend not in backends:
        offered = ", ".join(backends) or "(none)"
        raise ScaffoldError(f"unknown backend {backend!r}; available backends: {offered}")

    source = _example_path(backend, examples_dir)
    dest = _validated_destination(destination)

    if dest.exists() and not force:
        raise ScaffoldError(f"{dest}: already exists; pass --force to overwrite it")

    content = source.read_text(encoding="utf-8")
    try:
        # The operator explicitly chooses this local output path (like `cp` or the render
        # command's --output); there is no privilege boundary to escape, and the path is
        # NUL-checked in _validated_destination.
        dest.write_text(content, encoding="utf-8")  # NOSONAR
    except OSError as exc:
        detail = getattr(exc, "strerror", None) or str(exc)
        raise ScaffoldError(f"{dest}: could not write scaffolded config: {detail}") from exc

    return ScaffoldResult(backend=backend, destination=dest, source=source)
