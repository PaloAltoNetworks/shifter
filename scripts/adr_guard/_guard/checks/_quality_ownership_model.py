"""Contract shapes and loader for the quality-ownership check (ADR-004-R24).

Split out of ``quality_ownership.py`` to keep each module under the file-length
limit; every public name here is re-imported by that module so the package
surface is unchanged.
"""
from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Protocol

from .._common import Violation
from .._workflow_model import _DwShapeError


_QUALITY_CONTRACT_REL = ".github/quality-path-filters.yaml"
_QUALITY_WORKFLOW_REL = ".github/workflows/_quality.yml"


# The contract objects come from scripts/quality_ownership/contract.py, which is
# loaded by path (not imported), so its dataclasses are described structurally.
class _QualityJobRef(Protocol):
    """A contract job reference: a job id plus an optional matrix selector."""

    job: str
    matrix: tuple[tuple[str, str], ...]


class _QualityUnit(Protocol):
    """A quality unit: the paths and packages it owns and the jobs it declares."""

    id: str
    paths: tuple[str, ...]
    packages: tuple[str, ...]
    responsibilities: dict[str, tuple[_QualityJobRef, ...]]


class _QualityContract(Protocol):
    """The parsed .github/quality-path-filters.yaml contract."""

    units: tuple[_QualityUnit, ...]


# Builds one Violation for this check from a path and a message.
_QualityViol = Callable[[str, str], Violation]
# Jobs of a loaded workflow, keyed by job id.
_QualityJobs = dict[str, dict[str, object]]


def _load_quality_module(repo_root: Path) -> ModuleType:
    """Load scripts/quality_ownership/contract.py as a module (the single
    contract implementation), without mutating sys.path."""
    import importlib.util

    path = repo_root / "scripts" / "quality_ownership" / "contract.py"
    spec = importlib.util.spec_from_file_location("_quality_ownership_contract", path)
    if spec is None or spec.loader is None:
        raise _DwShapeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so the module's dataclasses (with `from __future__
    # import annotations`) can resolve their own namespace during processing.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _quality_load_contract(repo_root: Path) -> tuple[ModuleType, _QualityContract]:
    """Load the single contract implementation and parse the versioned contract,
    reporting either failure as a `_DwShapeError` carrying the message to emit."""
    try:
        module = _load_quality_module(repo_root)
    except Exception as exc:
        raise _DwShapeError(f"cannot load quality-ownership module: {exc}") from exc
    try:
        return module, module.load_contract(repo_root / _QUALITY_CONTRACT_REL)
    # ContractError / OSError
    except Exception as exc:
        raise _DwShapeError(f"contract invalid: {exc}") from exc
