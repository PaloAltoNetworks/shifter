#!/usr/bin/env python3
"""Terraform validation inventory: schema check, estate check, CI matrix.

Issue #1528. Pull-request quality runs TFLint and the repo-native
`check_tf_*` security scanners but never a backendless `terraform init` +
`terraform validate`, so a composition error (a renamed module output, a
provider argument that no longer parses, a variable that lost its type)
could merge before any workflow parsed the affected root. This helper is
the single repo-native surface behind that gate.

It owns three responsibilities, all credential-free and offline:

  1. `--check`  Validate `platform/terraform/validation-inventory.yaml`:
     the schema (closed keys, closed enums, unique ids/paths, contained
     repository-relative paths, toolchain references, per-root provider
     declarations) AND the estate (every git-tracked Terraform directory
     is classified as a root or a module; every classified path exists;
     every root carries a committed lockfile whose provider set matches
     the inventory). Fails closed: a new root added without an inventory
     entry, or a drifted provider set, is an error, not a silent pass.

  2. `--matrix` Emit the GitHub Actions matrix (one entry per selected
     root: id, path, terraform_version, provider_family) as JSON. Runs
     the same validation first so a broken inventory never yields a
     matrix. Root selection is a replaceable policy; `all` (the default)
     validates every registered root on any Terraform-relevant change.

The inventory is data. This helper never interpolates inventory text into
a shell; the workflow invokes Terraform with fixed argv against the
matrix `path`. HCL configuration is never regex-parsed here — provider
facts come from the committed lockfile, which is Terraform's own
machine-generated dependency record.

Usage:

    python3 scripts/check_tf_roots/check_tf_roots.py --check
    python3 scripts/check_tf_roots/check_tf_roots.py --matrix [--mode all]

Exit code 0 on success, 1 on a validation failure, 2 on a usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

SCHEMA_VERSION = 1

CONTRACT_MODES = {"terraform_test", "fixture_plan", "deferred"}

# Provider addresses in the inventory must be full source addresses so the
# comparison against the lockfile (which stores full addresses) is exact.
_PROVIDER_ADDRESS_RE = re.compile(r"^[a-z0-9.-]+/[a-z0-9-]+/[a-z0-9-]+$")

_LOCKFILE_PROVIDER_RE = re.compile(r'^provider\s+"([^"]+)"\s*\{')

_TOP_LEVEL_KEYS = {"schema_version", "profiles", "roots", "modules"}
_ROOT_KEYS = {"id", "path", "owner", "toolchain", "providers"}
_MODULE_KEYS = {"path", "owner", "contract", "reason", "test", "test_profile", "tracking"}
_PROFILE_KEYS = {"terraform_version", "provider_family"}

# Module contract modes that ship an executable test and therefore require a
# `test` path and a `test_profile` (a named toolchain profile).
_TESTED_CONTRACT_MODES = {"terraform_test", "fixture_plan"}

_DEFAULT_INVENTORY = "platform/terraform/validation-inventory.yaml"


class InventoryError(Exception):
    """Raised when the inventory cannot be built from its raw data."""


@dataclass
class Profile:
    name: str
    terraform_version: str
    provider_family: str


@dataclass
class Root:
    id: str
    path: str
    owner: str
    toolchain: str
    providers: list[str]


@dataclass
class Module:
    path: str
    owner: str
    contract: str
    reason: str | None = None
    test: str | None = None
    test_profile: str | None = None


@dataclass
class Inventory:
    schema_version: int
    profiles: dict[str, Profile]
    roots: list[Root]
    modules: list[Module]


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _is_contained_relative(path: str) -> bool:
    """A repository-relative path with no absolute prefix or traversal."""
    if not path or not isinstance(path, str):
        return False
    if path.startswith("/"):
        return False
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    return True


# ---------------------------------------------------------------------------
# Schema validation (pure — operates on the parsed YAML mapping)
# ---------------------------------------------------------------------------


def _validate_profiles(data: dict) -> list[str]:
    errors: list[str] = []
    profiles = data.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        return ["profiles: must be a non-empty mapping of profile name to definition"]
    for name, body in profiles.items():
        if not isinstance(body, dict):
            errors.append(f"profiles.{name}: must be a mapping")
            continue
        extra = set(body) - _PROFILE_KEYS
        if extra:
            errors.append(f"profiles.{name}: unknown key(s) {sorted(extra)}")
        for field in _PROFILE_KEYS:
            value = body.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"profiles.{name}.{field}: must be a non-empty string")
    return errors


def _validate_roots(data: dict, profile_names: set[str]) -> list[str]:
    errors: list[str] = []
    roots = data.get("roots")
    if not isinstance(roots, list) or not roots:
        return ["roots: must be a non-empty list"]
    for idx, root in enumerate(roots):
        where = f"roots[{idx}]"
        if not isinstance(root, dict):
            errors.append(f"{where}: must be a mapping")
            continue
        extra = set(root) - _ROOT_KEYS
        if extra:
            errors.append(f"{where}: unknown key(s) {sorted(extra)}")
        for field in ("id", "path", "owner", "toolchain"):
            value = root.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{where}.{field}: must be a non-empty string")
        path = root.get("path")
        if isinstance(path, str) and path and not _is_contained_relative(path):
            errors.append(f"{where}.path: {path!r} must be a contained repository-relative path")
        toolchain = root.get("toolchain")
        if isinstance(toolchain, str) and toolchain and toolchain not in profile_names:
            errors.append(f"{where}.toolchain: {toolchain!r} is not a defined profile")
        providers = root.get("providers")
        if not isinstance(providers, list) or not providers:
            errors.append(f"{where}.providers: must be a non-empty list of provider source addresses")
        else:
            for provider in providers:
                if not isinstance(provider, str) or not _PROVIDER_ADDRESS_RE.match(provider):
                    errors.append(
                        f"{where}.providers: {provider!r} must be a full source address "
                        "(e.g. registry.terraform.io/hashicorp/aws)"
                    )
    return errors


def _validate_modules(data: dict, profile_names: set[str]) -> list[str]:
    errors: list[str] = []
    modules = data.get("modules")
    if not isinstance(modules, list):
        return ["modules: must be a list"]
    for idx, module in enumerate(modules):
        where = f"modules[{idx}]"
        if not isinstance(module, dict):
            errors.append(f"{where}: must be a mapping")
            continue
        extra = set(module) - _MODULE_KEYS
        if extra:
            errors.append(f"{where}: unknown key(s) {sorted(extra)}")
        for field in ("path", "owner", "contract"):
            value = module.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{where}.{field}: must be a non-empty string")
        path = module.get("path")
        if isinstance(path, str) and path and not _is_contained_relative(path):
            errors.append(f"{where}.path: {path!r} must be a contained repository-relative path")
        contract = module.get("contract")
        if isinstance(contract, str) and contract and contract not in CONTRACT_MODES:
            errors.append(f"{where}.contract: {contract!r} not in {sorted(CONTRACT_MODES)}")
        if contract == "deferred" and not str(module.get("reason") or "").strip():
            errors.append(f"{where}: contract 'deferred' requires a non-empty 'reason'")
        if contract in _TESTED_CONTRACT_MODES:
            test_path = str(module.get("test") or "").strip()
            if not test_path:
                errors.append(f"{where}: contract {contract!r} requires a 'test' path")
            elif not _is_contained_relative(test_path):
                errors.append(f"{where}.test: {test_path!r} must be a contained repository-relative path")
            profile = module.get("test_profile")
            if not isinstance(profile, str) or not profile.strip():
                errors.append(f"{where}: contract {contract!r} requires a 'test_profile'")
            elif profile not in profile_names:
                errors.append(f"{where}.test_profile: {profile!r} is not a defined profile")
    return errors


def _validate_unique_ids_and_paths(data: dict) -> list[str]:
    errors: list[str] = []
    roots = data.get("roots") if isinstance(data.get("roots"), list) else []
    modules = data.get("modules") if isinstance(data.get("modules"), list) else []

    seen_ids: set[str] = set()
    for root in roots:
        if not isinstance(root, dict):
            continue
        rid = root.get("id")
        if isinstance(rid, str):
            if rid in seen_ids:
                errors.append(f"roots: duplicate id {rid!r}")
            seen_ids.add(rid)

    seen_paths: set[str] = set()
    for entry in [*roots, *modules]:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if isinstance(path, str):
            if path in seen_paths:
                errors.append(f"duplicate path {path!r} (a directory is classified twice)")
            seen_paths.add(path)
    return errors


def validate_schema(data: dict) -> list[str]:
    """Return a list of schema errors; empty list means the schema is valid."""
    if not isinstance(data, dict):
        return ["inventory: top-level document must be a mapping"]

    errors: list[str] = []
    extra = set(data) - _TOP_LEVEL_KEYS
    if extra:
        errors.append(f"inventory: unknown top-level key(s) {sorted(extra)}")

    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version: must be {SCHEMA_VERSION}")

    profile_errors = _validate_profiles(data)
    errors.extend(profile_errors)
    profile_names = set(data["profiles"]) if isinstance(data.get("profiles"), dict) else set()

    errors.extend(_validate_roots(data, profile_names))
    errors.extend(_validate_modules(data, profile_names))
    errors.extend(_validate_unique_ids_and_paths(data))
    return errors


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def build_inventory(data: dict) -> Inventory:
    """Validate `data` and construct an Inventory, or raise InventoryError."""
    errors = validate_schema(data)
    if errors:
        raise InventoryError("; ".join(errors))
    profiles = {
        name: Profile(name=name, terraform_version=body["terraform_version"], provider_family=body["provider_family"])
        for name, body in data["profiles"].items()
    }
    roots = [
        Root(
            id=r["id"],
            path=r["path"],
            owner=r["owner"],
            toolchain=r["toolchain"],
            providers=list(r["providers"]),
        )
        for r in data["roots"]
    ]
    modules = [
        Module(
            path=m["path"],
            owner=m["owner"],
            contract=m["contract"],
            reason=m.get("reason"),
            test=m.get("test"),
            test_profile=m.get("test_profile"),
        )
        for m in data.get("modules", [])
    ]
    return Inventory(schema_version=data["schema_version"], profiles=profiles, roots=roots, modules=modules)


def parse_inventory(text: str) -> dict:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise InventoryError("inventory: top-level document must be a mapping")
    return data


def load_inventory(path: Path) -> Inventory:
    return build_inventory(parse_inventory(path.read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# Estate validation (needs the filesystem / git)
# ---------------------------------------------------------------------------


def read_lockfile_providers(lockfile_path: Path) -> set[str]:
    """Extract the provider source addresses recorded in a .terraform.lock.hcl.

    The lock file is Terraform's own machine-generated dependency record with
    a fixed grammar (`provider "<address>" { ... }`); reading it is not the
    same as regex-parsing hand-written HCL configuration.
    """
    providers: set[str] = set()
    for line in lockfile_path.read_text(encoding="utf-8").splitlines():
        match = _LOCKFILE_PROVIDER_RE.match(line.strip())
        if match:
            providers.add(match.group(1))
    return providers


def discover_tf_dirs(repo_root: Path) -> set[str]:
    """Return the set of git-tracked directories that contain a *.tf file."""
    out = subprocess.check_output(
        ["git", "-C", str(repo_root), "ls-files", "*.tf"], text=True
    )
    dirs: set[str] = set()
    for line in out.splitlines():
        line = line.strip()
        if line:
            dirs.add(str(Path(line).parent).replace("\\", "/"))
    return dirs


def validate_estate(
    inventory: Inventory,
    repo_root: Path,
    tf_dirs: set[str] | None = None,
) -> list[str]:
    """Validate the inventory against the on-disk Terraform estate."""
    errors: list[str] = []
    if tf_dirs is None:
        tf_dirs = discover_tf_dirs(repo_root)

    classified = {r.path for r in inventory.roots} | {m.path for m in inventory.modules}

    # AC4: every tracked Terraform directory must be classified. A new root or
    # module that skipped the inventory fails closed here.
    for tf_dir in sorted(tf_dirs - classified):
        errors.append(
            f"unclassified Terraform directory {tf_dir!r}: add it to the "
            "validation inventory as a root or a module"
        )

    # Every classified path must actually contain Terraform source.
    for path in sorted(classified - tf_dirs):
        if not (repo_root / path).is_dir():
            errors.append(f"inventory path {path!r} does not exist on disk")
        else:
            errors.append(f"inventory path {path!r} contains no tracked Terraform source")

    # Every root must carry a committed lockfile whose provider set matches.
    for root in inventory.roots:
        lockfile = repo_root / root.path / ".terraform.lock.hcl"
        if not lockfile.is_file():
            errors.append(f"root {root.path!r}: missing committed lockfile (.terraform.lock.hcl)")
            continue
        locked = read_lockfile_providers(lockfile)
        declared = set(root.providers)
        if locked != declared:
            missing = sorted(locked - declared)
            spurious = sorted(declared - locked)
            detail = []
            if missing:
                detail.append(f"lockfile declares un-inventoried provider(s) {missing}")
            if spurious:
                detail.append(f"inventory declares provider(s) {spurious} absent from the lockfile")
            errors.append(f"root {root.path!r}: provider drift ({'; '.join(detail)})")

    # Every module that claims an executable contract must ship the test file.
    for module in inventory.modules:
        if module.contract in _TESTED_CONTRACT_MODES and module.test:
            test_file = repo_root / module.path / module.test
            if not test_file.is_file():
                errors.append(
                    f"module {module.path!r}: contract {module.contract!r} names test "
                    f"{module.test!r} which does not exist"
                )
    return errors


# ---------------------------------------------------------------------------
# Selection + matrix
# ---------------------------------------------------------------------------


def select_roots(inventory: Inventory, mode: str = "all") -> list[Root]:
    """Select the roots to validate. Only the conservative 'all' mode exists
    today; the parameter is the seam for a future affected-root selector."""
    if mode != "all":
        raise ValueError(f"unknown selection mode {mode!r}")
    return list(inventory.roots)


def build_matrix(roots: list[Root], profiles: dict[str, Profile]) -> list[dict]:
    matrix: list[dict] = []
    for root in roots:
        profile = profiles[root.toolchain]
        matrix.append(
            {
                "id": root.id,
                "path": root.path,
                "terraform_version": profile.terraform_version,
                "provider_family": profile.provider_family,
            }
        )
    return matrix


def build_module_test_matrix(
    modules: list[Module], profiles: dict[str, Profile]
) -> list[dict]:
    """CI matrix for reusable-module contract tests (contract carries a test)."""
    matrix: list[dict] = []
    for module in modules:
        if module.contract not in _TESTED_CONTRACT_MODES:
            continue
        profile = profiles[module.test_profile]
        matrix.append(
            {
                "path": module.path,
                "contract": module.contract,
                "test": module.test,
                "terraform_version": profile.terraform_version,
                "provider_family": profile.provider_family,
            }
        )
    return matrix


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run_check(repo_root: Path, inventory_path: Path) -> int:
    try:
        inventory = load_inventory(inventory_path)
    except InventoryError as exc:
        print(f"{inventory_path}: schema invalid:", file=sys.stderr)
        for line in str(exc).split("; "):
            print(f"  - {line}", file=sys.stderr)
        return 1
    errors = validate_estate(inventory, repo_root)
    if errors:
        print(f"{inventory_path}: estate invalid:", file=sys.stderr)
        for line in errors:
            print(f"  - {line}", file=sys.stderr)
        return 1
    print(
        f"OK: {len(inventory.roots)} roots, {len(inventory.modules)} modules classified and consistent."
    )
    return 0


def run_matrix(repo_root: Path, inventory_path: Path, mode: str) -> int:
    try:
        inventory = load_inventory(inventory_path)
    except InventoryError as exc:
        print(f"{inventory_path}: schema invalid: {exc}", file=sys.stderr)
        return 1
    errors = validate_estate(inventory, repo_root)
    if errors:
        print(f"{inventory_path}: estate invalid; refusing to emit matrix:", file=sys.stderr)
        for line in errors:
            print(f"  - {line}", file=sys.stderr)
        return 1
    matrix = build_matrix(select_roots(inventory, mode=mode), inventory.profiles)
    print(json.dumps(matrix))
    return 0


def run_module_tests(repo_root: Path, inventory_path: Path) -> int:
    try:
        inventory = load_inventory(inventory_path)
    except InventoryError as exc:
        print(f"{inventory_path}: schema invalid: {exc}", file=sys.stderr)
        return 1
    errors = validate_estate(inventory, repo_root)
    if errors:
        print(f"{inventory_path}: estate invalid; refusing to emit matrix:", file=sys.stderr)
        for line in errors:
            print(f"  - {line}", file=sys.stderr)
        return 1
    print(json.dumps(build_module_test_matrix(inventory.modules, inventory.profiles)))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Terraform validation inventory helper")
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root (default: current directory)",
    )
    parser.add_argument(
        "--inventory",
        default=None,
        help=f"Path to the inventory (default: {_DEFAULT_INVENTORY} under --repo-root)",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="Validate the inventory and estate")
    group.add_argument("--matrix", action="store_true", help="Emit the root-validation CI matrix as JSON")
    group.add_argument(
        "--module-tests",
        action="store_true",
        help="Emit the module contract-test CI matrix as JSON",
    )
    parser.add_argument("--mode", default="all", help="Root selection mode (default: all)")

    args = parser.parse_args(argv[1:])
    repo_root = Path(args.repo_root).resolve()
    inventory_path = Path(args.inventory) if args.inventory else repo_root / _DEFAULT_INVENTORY

    if args.check:
        return run_check(repo_root, inventory_path)
    if args.module_tests:
        return run_module_tests(repo_root, inventory_path)
    try:
        return run_matrix(repo_root, inventory_path, args.mode)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
