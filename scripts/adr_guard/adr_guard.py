#!/usr/bin/env python3
"""Repo-native ADR enforcement checks.

Executable compatibility facade for the ``adr_guard`` package. The check
logic lives in per-family modules under this directory (``checks/*``) plus
the shared kernels ``_common`` / ``_workflow_model`` and the ``_registry`` /
``_cli`` wiring; this module is the CLI entry point and re-exports the full
public surface so ``python3 scripts/adr_guard/adr_guard.py`` and the tests
that load this file by path keep working unchanged.

The surface is large (400+ checks, helpers, and constants). Enumerating every
name explicitly would push this shim past the file-length limit, so instead we
copy each source module's namespace once at import time. That keeps the facade
small while still exposing every check and helper as an ``adr_guard`` attribute
for the CLI and for tests that load this file via ``spec_from_file_location``.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

# Bootstrap the package once: make this directory importable so `_guard`
# resolves both when run as __main__ (sys.path[0] is this dir) and when a test
# loads this file via importlib.util.spec_from_file_location (which does not add
# the dir). All internal wiring uses package-relative imports inside `_guard`.
_PKG_DIR = str(Path(__file__).resolve().parent)
if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)

# Source modules whose public surface this facade re-exports, in dependency
# order (shared kernels first, then the check families, then the CLI wiring).
_SOURCE_MODULES = (
    "_guard._common",
    "_guard._workflow_model",
    "_guard.checks.adr_registry",
    "_guard.checks.layer_imports",
    "_guard.checks.documentation",
    "_guard.checks.mcp_policy",
    "_guard.checks.k8s_security",
    "_guard.checks.secret_hygiene",
    "_guard.checks.deploy_workflow",
    "_guard.checks.boundary_mock",
    "_guard.checks.complexity",
    "_guard.checks.cloud_identifiers",
    "_guard.checks.accessibility_baseline",
    "_guard.checks.published_contract",
    "_guard.checks.quality_ownership",
    "_guard.checks.eks_cross_stack_sourcing",
    "_guard._registry",
    "_guard._cli",
)

# Names re-exported onto this module. A name is copied when it is a genuine
# member of a source module (not a dunder, an imported submodule, or the
# ``from __future__`` marker), which reproduces the historical facade surface
# without listing every symbol by hand.
_exported: set[str] = set()


def _reexport(module: types.ModuleType) -> None:
    """Copy ``module``'s public members onto this facade's namespace."""
    for name, value in vars(module).items():
        if name.startswith("__") or name == "annotations":
            continue
        if isinstance(value, types.ModuleType):
            continue
        globals()[name] = value
        _exported.add(name)


for _module_name in _SOURCE_MODULES:
    _reexport(importlib.import_module(_module_name))

# Expose the check submodules themselves (e.g. ``adr_guard.boundary_mock``),
# which several tests reference directly rather than through a member symbol.
from _guard.checks import (  # noqa: E402
    accessibility_baseline,
    adr_registry,
    boundary_mock,
    cloud_identifiers,
    complexity,
    deploy_workflow,
    documentation,
    eks_cross_stack_sourcing,
    k8s_security,
    layer_imports,
    mcp_policy,
    published_contract,
    quality_ownership,
    secret_hygiene,
)

_SUBMODULES = (
    "accessibility_baseline",
    "adr_registry",
    "boundary_mock",
    "cloud_identifiers",
    "complexity",
    "deploy_workflow",
    "documentation",
    "eks_cross_stack_sourcing",
    "k8s_security",
    "layer_imports",
    "mcp_policy",
    "published_contract",
    "quality_ownership",
    "secret_hygiene",
)

__all__ = sorted(_exported | set(_SUBMODULES))

# The CLI entry point. Also re-exported by the loop above; imported explicitly
# here so the ``__main__`` dispatch resolves statically.
from _guard._cli import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
