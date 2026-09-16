"""Dependency-free reader for the layer-policy YAML (`layer_imports.yaml`).

Split out of ``layer_imports.py`` to keep each module under the file-length
limit; every public name here is re-imported by that module so the package
surface is unchanged.
"""
from __future__ import annotations

from pathlib import Path


def _is_key_line(stripped: str, indent: int, expected_indent: int) -> bool:
    """True for a ``key:`` line at exactly ``expected_indent`` spaces."""
    return indent == expected_indent and stripped.endswith(":")


def _is_item_line(stripped: str, indent: int, min_indent: int) -> bool:
    """True for a ``- item`` list entry at ``min_indent`` spaces or deeper."""
    return indent >= min_indent and stripped.startswith("- ")


def _section_lines(config_path: Path, section: str) -> list[tuple[str, int]]:
    """Return ``(content, indent)`` pairs for the lines of one top-level section.

    Comment tails and blank lines are dropped. The section's own header line is
    included (at indent 0) so callers can reset their per-block state when a
    section is entered.
    """
    lines: list[tuple[str, int]] = []
    current_section: str | None = None

    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if _is_key_line(stripped, indent, 0):
            current_section = stripped[:-1]
        if current_section == section:
            lines.append((stripped, indent))

    return lines


def _iter_yaml_section(config_path: Path, section: str) -> "list[tuple[str, list[str]]]":
    """Parse one top-level ``section:`` of the layer-policy YAML.

    Minimal, dependency-free reader for the two-level shape used by
    layer_imports.yaml (``section:`` -> ``key:`` -> ``- item`` list). Only the
    requested top-level section is parsed; other sections are ignored, so the
    ``classification`` and ``allowed`` blocks never bleed into each other.
    """
    result: dict[str, list[str]] = {}
    current_key: str | None = None

    for stripped, indent in _section_lines(config_path, section):
        if _is_key_line(stripped, indent, 0):
            current_key = None
        elif _is_key_line(stripped, indent, 2):
            current_key = stripped[:-1]
            result[current_key] = []
        elif current_key is not None and _is_item_line(stripped, indent, 4):
            result[current_key].append(stripped[2:].strip())

    return list(result.items())


def load_allowed_imports(config_path: Path) -> dict[str, list[str]]:
    """Load the simple layer import policy without external YAML dependencies."""
    return dict(_iter_yaml_section(config_path, "allowed"))


def load_allowed_symbols(config_path: Path) -> dict[str, dict[str, list[str]]]:
    """Parse the 3-level ``allowed_symbols:`` block (layer -> facade -> [symbols]).

    Dependency-free reader mirroring ``_iter_yaml_section`` one level deeper, for
    the per-symbol facade allowlists (ADR-001-R4). Only the ``allowed_symbols``
    top-level section is parsed; other sections are ignored.
    """
    result: dict[str, dict[str, list[str]]] = {}
    current_layer: str | None = None
    current_facade: str | None = None

    for stripped, indent in _section_lines(config_path, "allowed_symbols"):
        if _is_key_line(stripped, indent, 0):
            current_layer = None
            current_facade = None
        elif _is_key_line(stripped, indent, 2):
            current_layer = stripped[:-1]
            result[current_layer] = {}
            current_facade = None
        elif _is_key_line(stripped, indent, 4) and current_layer is not None:
            current_facade = stripped[:-1]
            result[current_layer][current_facade] = []
        elif current_layer is not None and current_facade is not None and _is_item_line(stripped, indent, 6):
            result[current_layer][current_facade].append(stripped[2:].strip())

    return result


def load_classification(config_path: Path) -> dict[str, list[str]]:
    """Load the canonical package classification without external YAML deps."""
    return dict(_iter_yaml_section(config_path, "classification"))


__all__ = [
    "_is_item_line",
    "_is_key_line",
    "_iter_yaml_section",
    "_section_lines",
    "load_allowed_imports",
    "load_allowed_symbols",
    "load_classification",
]
