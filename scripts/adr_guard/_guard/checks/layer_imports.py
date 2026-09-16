"""Layer-import boundaries, INSTALLED_APPS classification, cloud-factory seam."""
from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from pathlib import Path

from .._common import (
    LAYERS,
    Violation,
    _repo_relative,
)
from ._layer_imports_installed_apps import (
    _INSTALLED_APPS,
    _LAYER_POLICY_REL,
    _OPAQUE_INSTALLED_APPS_METHODS,
    _PLATFORM_REL,
    _SETTINGS_REL,
    _classified_packages,
    _installed_apps_append_entries,
    _installed_apps_call_entries,
    _is_installed_apps_add,
    _is_installed_apps_attribute,
    _local_appconfig_packages,
    _parse_installed_apps,
    _sequence_entries,
    _targets_installed_apps,
    check_installed_apps_classified,
)
from ._layer_imports_policy import (
    _is_item_line,
    _is_key_line,
    _iter_yaml_section,
    _section_lines,
    load_allowed_imports,
    load_allowed_symbols,
    load_classification,
)


IMPORT_PATTERN = re.compile(
    r"^\s*(?:from|import)\s+"
    r"((?:shared|engine|cms|management|mission_control|ctf|config|workspaces)(?:\.\w+)*)",
    re.MULTILINE,
)
CYBERSCRIPT_IMPORT_PATTERN = re.compile(
    r"^\s*(?:from|import)\s+(cyberscript(?:\.\w+)*)",
    re.MULTILINE,
)
RAES_PACKAGE_ROOTS = frozenset(
    {"raes", "raes_contracts", "raes_runtime", "raes_processor", "raes_conformance", "raes_backend_protocols"}
)


def _facade_entry_allows(entry: str, module_path: str) -> bool:
    """True when a dotted facade entry sanctions ``module_path`` (ADR-001-R1).

    The exact facade and its public submodules are allowed; a private
    split-package submodule — any path component after the facade that starts
    with ``_`` (``cms.services._range_pause``) — is not a cross-layer seam.
    """
    if module_path == entry:
        return True
    if not module_path.startswith(entry + "."):
        return False
    remainder = module_path[len(entry) + 1 :]
    return not any(part.startswith("_") for part in remainder.split("."))


def _entry_allows_module(entry: str, module_path: str) -> bool:
    """True when one ``allowed:`` policy entry sanctions ``module_path``."""
    if entry == "shared":
        return module_path == "shared" or module_path.startswith("shared.")
    if "." in entry:
        return _facade_entry_allows(entry, module_path)
    return module_path == entry


def is_import_allowed(from_layer: str, module_path: str, allowed: dict[str, list[str]]) -> bool:
    """Check whether an import is allowed by the layer policy.

    A dotted entry (e.g. ``cms.services``) is the public facade: the exact
    facade and its public submodules are allowed, but a private split-package
    submodule — any path component after the facade that starts with ``_``
    (``cms.services._range_pause``) — is not a cross-layer seam (ADR-001-R1).
    ``shared`` is the contracts layer and stays freely importable.
    """
    return any(_entry_allows_module(entry, module_path) for entry in allowed.get(from_layer, []))


def iter_layer_files(repo_root: Path, files: list[str] | None) -> list[tuple[str, str]]:
    """Return repo-relative Python files grouped by originating layer."""
    candidates: list[Path]
    if files is None:
        candidates = list((repo_root / "shifter" / "shifter_platform").rglob("*.py"))
    else:
        candidates = [repo_root / rel for rel in files if rel.endswith(".py")]

    layer_files: list[tuple[str, str]] = []
    for path in candidates:
        if not path.exists():
            continue
        rel = _repo_relative(path, repo_root)
        parts = Path(rel).parts
        if len(parts) < 4:
            continue
        if parts[0:2] != ("shifter", "shifter_platform"):
            continue
        layer = parts[2]
        if layer in LAYERS:
            layer_files.append((rel, layer))

    return sorted(set(layer_files))


def iter_private_facade_imports(text: str) -> set[str]:
    """Return ``layer.path._private`` targets imported via ``from ... import``.

    The ``IMPORT_PATTERN`` regex only captures the module path, so
    ``from cms.services import _range_pause`` looks like an allowed
    ``cms.services`` facade import. This AST pass recovers the imported name and,
    when it is private (starts with ``_``) and the module belongs to one of our
    layers, reconstructs the effective dotted target (``cms.services._range_pause``).
    Relative imports (``from ._x import y``) and public names are ignored.
    """
    targets: set[str] = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return targets

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level != 0 or not node.module:
            continue
        if node.module.split(".")[0] not in LAYERS:
            continue
        targets.update(f"{node.module}.{alias.name}" for alias in node.names if alias.name.startswith("_"))
    return targets


def _is_public_facade_descendant(module: str, facade: str) -> bool:
    """True when ``module`` is a PUBLIC descendant module of ``facade``.

    ``engine.services.runtime`` is a descendant of ``engine.services``. A private
    component anywhere in the remainder (``engine.services._x``) is not, because
    private split-package modules are already rejected by ADR-001-R1; this keeps
    the two rules from double-reporting the same import.
    """
    if not module.startswith(facade + "."):
        return False
    remainder = module[len(facade) + 1 :]
    return not any(part.startswith("_") for part in remainder.split("."))


def _reaches_facade(module: str, facade: str) -> bool:
    """True when ``module`` is the restricted facade itself or a public descendant."""
    return module == facade or _is_public_facade_descendant(module, facade)


def _classify_import_from(
    node: ast.ImportFrom,
    restricted_facades: set[str],
    from_symbols: dict[str, set[str]],
    module_bypass: set[str],
) -> None:
    """Record the sanctioned symbols and facade bypasses of one ``from ... import``."""
    module = node.module
    if not module:
        return
    for facade in restricted_facades:
        if node.level == 0 and module == facade:
            public = {alias.name for alias in node.names if not alias.name.startswith("_")}
            if public:
                from_symbols.setdefault(facade, set()).update(public)
        elif _reaches_facade(module, facade):
            # Relative facade import (level > 0) or a facade descendant.
            module_bypass.add(module)


def _classify_bare_import(node: ast.Import, restricted_facades: set[str], module_bypass: set[str]) -> None:
    """Record ``import <facade>`` / ``import <facade>.sub`` bypasses of one statement."""
    for alias in node.names:
        for facade in restricted_facades:
            if _reaches_facade(alias.name, facade):
                module_bypass.add(alias.name)


def iter_facade_symbol_imports(text: str, restricted_facades: set[str]) -> "tuple[dict[str, set[str]], set[str]]":
    """Return (public symbols imported per restricted facade, non-facade bypasses).

    The only sanctioned shape for a symbol-restricted facade (ADR-001-R4) is an
    absolute ``from <facade> import <name>``; its public names feed the allowlist
    check. Every other shape that reaches the facade or one of its public
    descendants is a bypass: a relative ``from ..<facade> import name``, a
    descendant ``from <facade>.sub import name``, a bare ``import <facade>``, or
    ``import <facade>.sub``. Private ``_``-prefixed targets are left to the
    public-facade rule (ADR-001-R1) so the two rules do not double-report.
    """
    from_symbols: dict[str, set[str]] = {}
    module_bypass: set[str] = set()
    if not restricted_facades:
        return from_symbols, module_bypass
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return from_symbols, module_bypass

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            _classify_import_from(node, restricted_facades, from_symbols, module_bypass)
        elif isinstance(node, ast.Import):
            _classify_bare_import(node, restricted_facades, module_bypass)
    return from_symbols, module_bypass


def _symbol_facade_violations(
    rel: str,
    from_layer: str,
    text: str,
    allowed_symbols: dict[str, dict[str, list[str]]],
) -> list[Violation]:
    """Return ADR-001-R4 per-symbol facade-allowlist violations for one file."""
    restrictions = allowed_symbols.get(from_layer, {})
    if not restrictions:
        return []

    violations: list[Violation] = []
    from_symbols, module_bypass = iter_facade_symbol_imports(text, set(restrictions))
    for facade, names in sorted(from_symbols.items()):
        allowed_names = set(restrictions.get(facade, []))
        for name in sorted(names):
            if name not in allowed_names:
                violations.append(
                    Violation(
                        "layer-imports",
                        "ADR-001-R4",
                        rel,
                        f"{from_layer} may import only sanctioned symbols from {facade}; "
                        f"'{name}' is not allowed (front control-plane operations through cms.services)",
                    )
                )
    for module in sorted(module_bypass):
        violations.append(
            Violation(
                "layer-imports",
                "ADR-001-R4",
                rel,
                f"{from_layer} may not reach {module} except via 'from <facade> import <sanctioned symbol>' "
                "(no relative, descendant, or bare-module imports of the restricted facade)",
            )
        )
    return violations


def check_layer_imports(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Check the layer import policy against selected files."""
    violations: list[Violation] = []
    config_path = repo_root / "scripts" / "check_layer_imports" / "layer_imports.yaml"
    allowed = load_allowed_imports(config_path)
    allowed_symbols = load_allowed_symbols(config_path)

    for rel, from_layer in iter_layer_files(repo_root, files):
        text = (repo_root / rel).read_text(encoding="utf-8")
        regex_modules = set(IMPORT_PATTERN.findall(text))
        # AST recovers `from facade import _private`, which the regex sees only
        # as the allowed facade module path.
        private_modules = iter_private_facade_imports(text)
        for module in sorted(regex_modules | private_modules):
            to_layer = module.split(".", 1)[0]
            if to_layer == from_layer:
                continue
            if not is_import_allowed(from_layer, module, allowed):
                violations.append(
                    Violation(
                        "layer-imports",
                        "ADR-001-R1",
                        rel,
                        f"{from_layer} may not import {module}",
                    )
                )
        # ADR-001-R4: symbol-restricted facade seams (e.g. mission_control ->
        # engine.services) permit only the enumerated data-plane symbols.
        violations.extend(_symbol_facade_violations(rel, from_layer, text, allowed_symbols))
        for module in sorted(set(CYBERSCRIPT_IMPORT_PATTERN.findall(text))):
            violations.append(
                Violation(
                    "layer-imports",
                    "ADR-001-R1",
                    rel,
                    f"{from_layer} may not import retired package {module}",
                )
            )

    violations.extend(_preparation_worker_import_violations(repo_root, files))
    return violations


def _preparation_worker_import_violations(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Keep the separately built worker behind the shared RAES facade."""
    violations: list[Violation] = []
    for path in _preparation_worker_candidates(repo_root, files):
        if not path.exists():
            continue
        rel = _repo_relative(path, repo_root)
        for package in sorted(_imported_package_roots(path, rel) & RAES_PACKAGE_ROOTS):
            violations.append(
                Violation(
                    "layer-imports",
                    "ADR-031-R1",
                    rel,
                    f"preparation worker may not import {package}; use the shared.raes facade",
                )
            )

    return violations


def _preparation_worker_candidates(repo_root: Path, files: list[str] | None) -> Iterable[Path]:
    """Select preparation worker Python files for a full or changed-file scan."""
    if files is None:
        return (repo_root / "shifter" / "packer" / "preparation").rglob("*.py")
    return (
        repo_root / rel
        for rel in files
        if rel.startswith("shifter/packer/preparation/") and rel.endswith(".py")
    )


def _imported_package_roots(path: Path, relative_path: str) -> set[str]:
    """Return absolute top-level imports, or an empty set for invalid Python."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative_path)
    except SyntaxError:
        return set()
    imported = {
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
    }
    imported.update(
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    return imported


def check_cross_layer_model_imports(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Find direct cross-layer model imports in selected runtime files."""
    violations: list[Violation] = []

    for rel, from_layer in iter_layer_files(repo_root, files):
        text = (repo_root / rel).read_text(encoding="utf-8")
        for module in sorted(set(IMPORT_PATTERN.findall(text))):
            parts = module.split(".")
            to_layer = parts[0]
            if to_layer == from_layer:
                continue
            if len(parts) >= 2 and parts[1] == "models":
                violations.append(
                    Violation(
                        "cross-layer-model-imports",
                        "ADR-001-R2",
                        rel,
                        f"{from_layer} imports {module}; prefer a service seam or shared contract",
                    )
                )

    return violations


CLOUD_ROOTS = (
    "shifter/shifter_platform/shared/cloud",
    "shifter/engine/provisioner/cloud",
)
CLOUD_SKIP_FILES = {"__init__.py", "base.py"}


def check_cloud_factory_seam(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Ensure cloud adapter parity between AWS and GCP (ADR-005-R1).

    Every adapter module in cloud/aws/ must have a counterpart in cloud/gcp/
    and vice versa.  Modules named __init__.py and base.py are excluded since
    they serve structural rather than adapter roles.
    """
    if files is not None:
        cloud_touched = any(any(f.startswith(root + "/") for root in CLOUD_ROOTS) for f in files)
        if not cloud_touched:
            return []

    violations: list[Violation] = []
    for root in CLOUD_ROOTS:
        aws_dir = repo_root / root / "aws"
        gcp_dir = repo_root / root / "gcp"
        if not aws_dir.exists() or not gcp_dir.exists():
            continue
        aws_modules = {f.name for f in aws_dir.glob("*.py")} - CLOUD_SKIP_FILES
        gcp_modules = {f.name for f in gcp_dir.glob("*.py")} - CLOUD_SKIP_FILES
        for missing in sorted(aws_modules - gcp_modules):
            violations.append(
                Violation(
                    "cloud-factory-seam",
                    "ADR-005-R1",
                    f"{root}/gcp/{missing}",
                    f"AWS adapter {missing} has no GCP counterpart",
                )
            )
        for missing in sorted(gcp_modules - aws_modules):
            violations.append(
                Violation(
                    "cloud-factory-seam",
                    "ADR-005-R1",
                    f"{root}/aws/{missing}",
                    f"GCP adapter {missing} has no AWS counterpart",
                )
            )
    return violations


# The policy reader and the INSTALLED_APPS check live in the two private
# sibling modules imported above; their names are re-exported here so
# `_guard.checks.layer_imports` keeps the single, stable import-time surface
# that `adr_guard.py` copies and the tests reach through.
__all__ = [
    "CLOUD_ROOTS",
    "CLOUD_SKIP_FILES",
    "CYBERSCRIPT_IMPORT_PATTERN",
    "IMPORT_PATTERN",
    "RAES_PACKAGE_ROOTS",
    "_INSTALLED_APPS",
    "_LAYER_POLICY_REL",
    "_OPAQUE_INSTALLED_APPS_METHODS",
    "_PLATFORM_REL",
    "_SETTINGS_REL",
    "_classified_packages",
    "_classify_bare_import",
    "_classify_import_from",
    "_entry_allows_module",
    "_facade_entry_allows",
    "_installed_apps_append_entries",
    "_installed_apps_call_entries",
    "_is_installed_apps_add",
    "_is_installed_apps_attribute",
    "_is_item_line",
    "_is_key_line",
    "_is_public_facade_descendant",
    "_iter_yaml_section",
    "_local_appconfig_packages",
    "_parse_installed_apps",
    "_reaches_facade",
    "_section_lines",
    "_sequence_entries",
    "_symbol_facade_violations",
    "_targets_installed_apps",
    "check_cloud_factory_seam",
    "check_cross_layer_model_imports",
    "check_installed_apps_classified",
    "check_layer_imports",
    "is_import_allowed",
    "iter_facade_symbol_imports",
    "iter_layer_files",
    "iter_private_facade_imports",
    "load_allowed_imports",
    "load_allowed_symbols",
    "load_classification",
]
