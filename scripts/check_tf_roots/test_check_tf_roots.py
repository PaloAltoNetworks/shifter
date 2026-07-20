"""Tests for check_tf_roots.py.

Run from the repo root:
    python3 -m unittest scripts.check_tf_roots.test_check_tf_roots -v
"""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from .check_tf_roots import (
    CONTRACT_MODES,
    InventoryError,
    build_inventory,
    build_matrix,
    build_module_test_matrix,
    read_lockfile_providers,
    select_roots,
    validate_estate,
    validate_schema,
)

# A minimal, structurally valid inventory used as the base for mutation tests.
VALID: dict = {
    "schema_version": 1,
    "profiles": {
        "aws-1.13.3": {"terraform_version": "1.13.3", "provider_family": "aws"},
        "gcp-1.7.1": {"terraform_version": "1.7.1", "provider_family": "gcp"},
    },
    "roots": [
        {
            "id": "aws-core",
            "path": "envs/core",
            "owner": "@team",
            "toolchain": "aws-1.13.3",
            "providers": ["registry.terraform.io/hashicorp/aws"],
        },
        {
            "id": "gcp-dev",
            "path": "gcp/dev",
            "owner": "@team",
            "toolchain": "gcp-1.7.1",
            "providers": ["registry.terraform.io/hashicorp/google"],
        },
    ],
    "modules": [
        {"path": "modules/vpc", "owner": "@team", "contract": "deferred", "reason": "tracked in #999"},
        {
            "path": "modules/tested",
            "owner": "@team",
            "contract": "terraform_test",
            "test": "tests/main.tftest.hcl",
            "test_profile": "aws-1.13.3",
        },
    ],
}


def _mutate(**overrides) -> dict:
    data = copy.deepcopy(VALID)
    data.update(overrides)
    return data


class ValidateSchemaTest(unittest.TestCase):
    def test_valid_inventory_has_no_errors(self) -> None:
        self.assertEqual(validate_schema(copy.deepcopy(VALID)), [])

    def test_wrong_schema_version_rejected(self) -> None:
        self.assertTrue(validate_schema(_mutate(schema_version=99)))

    def test_unknown_top_level_key_rejected(self) -> None:
        self.assertTrue(validate_schema(_mutate(extra="nope")))

    def test_unknown_root_key_rejected(self) -> None:
        data = copy.deepcopy(VALID)
        data["roots"][0]["surprise"] = "x"
        self.assertTrue(validate_schema(data))

    def test_missing_root_owner_rejected(self) -> None:
        data = copy.deepcopy(VALID)
        del data["roots"][0]["owner"]
        self.assertTrue(validate_schema(data))

    def test_empty_root_owner_rejected(self) -> None:
        data = copy.deepcopy(VALID)
        data["roots"][0]["owner"] = "   "
        self.assertTrue(validate_schema(data))

    def test_duplicate_root_id_rejected(self) -> None:
        data = copy.deepcopy(VALID)
        data["roots"][1]["id"] = data["roots"][0]["id"]
        self.assertTrue(validate_schema(data))

    def test_duplicate_path_across_roots_and_modules_rejected(self) -> None:
        data = copy.deepcopy(VALID)
        data["modules"][0]["path"] = data["roots"][0]["path"]
        self.assertTrue(validate_schema(data))

    def test_absolute_path_rejected(self) -> None:
        data = copy.deepcopy(VALID)
        data["roots"][0]["path"] = "/etc/passwd"
        self.assertTrue(validate_schema(data))

    def test_parent_traversal_path_rejected(self) -> None:
        data = copy.deepcopy(VALID)
        data["roots"][0]["path"] = "../escape"
        self.assertTrue(validate_schema(data))

    def test_toolchain_not_in_profiles_rejected(self) -> None:
        data = copy.deepcopy(VALID)
        data["roots"][0]["toolchain"] = "undefined-profile"
        self.assertTrue(validate_schema(data))

    def test_module_contract_enum_enforced(self) -> None:
        data = copy.deepcopy(VALID)
        data["modules"][0]["contract"] = "sometimes"
        errors = validate_schema(data)
        self.assertTrue(errors)
        self.assertNotIn("sometimes", CONTRACT_MODES)

    def test_deferred_module_requires_reason(self) -> None:
        data = copy.deepcopy(VALID)
        data["modules"][0] = {"path": "modules/vpc", "owner": "@team", "contract": "deferred"}
        self.assertTrue(validate_schema(data))

    def test_terraform_test_module_requires_test_path(self) -> None:
        data = copy.deepcopy(VALID)
        data["modules"][1] = {
            "path": "modules/tested",
            "owner": "@team",
            "contract": "terraform_test",
            "test_profile": "aws-1.13.3",
        }
        self.assertTrue(validate_schema(data))

    def test_terraform_test_module_requires_test_profile(self) -> None:
        data = copy.deepcopy(VALID)
        del data["modules"][1]["test_profile"]
        self.assertTrue(validate_schema(data))

    def test_terraform_test_module_test_profile_must_be_defined(self) -> None:
        data = copy.deepcopy(VALID)
        data["modules"][1]["test_profile"] = "undefined-profile"
        self.assertTrue(validate_schema(data))

    def test_empty_profiles_rejected(self) -> None:
        self.assertTrue(validate_schema(_mutate(profiles={})))

    def test_root_provider_must_be_full_source_address(self) -> None:
        data = copy.deepcopy(VALID)
        data["roots"][0]["providers"] = ["hashicorp/aws"]
        self.assertTrue(validate_schema(data))


class BuildInventoryTest(unittest.TestCase):
    def test_build_from_valid(self) -> None:
        inv = build_inventory(copy.deepcopy(VALID))
        self.assertEqual(len(inv.roots), 2)
        self.assertEqual(len(inv.modules), 2)
        self.assertEqual(inv.profiles["aws-1.13.3"].terraform_version, "1.13.3")

    def test_build_from_invalid_raises(self) -> None:
        with self.assertRaises(InventoryError):
            build_inventory(_mutate(schema_version=99))


class ReadLockfileProvidersTest(unittest.TestCase):
    def test_parses_provider_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / ".terraform.lock.hcl"
            lock.write_text(
                'provider "registry.terraform.io/hashicorp/aws" {\n'
                '  version = "6.43.0"\n'
                "}\n"
                'provider "registry.terraform.io/hashicorp/random" {\n'
                '  version = "3.6.0"\n'
                "}\n"
            )
            self.assertEqual(
                read_lockfile_providers(lock),
                {
                    "registry.terraform.io/hashicorp/aws",
                    "registry.terraform.io/hashicorp/random",
                },
            )


class ValidateEstateTest(unittest.TestCase):
    def _estate(self, tmp: Path) -> None:
        # Lay down the two roots (each with a lockfile) and two modules.
        for root in VALID["roots"]:
            d = tmp / root["path"]
            d.mkdir(parents=True, exist_ok=True)
            (d / "main.tf").write_text("# root\n")
            lock = d / ".terraform.lock.hcl"
            lock.write_text(
                "".join(f'provider "{p}" {{\n  version = "1.0.0"\n}}\n' for p in root["providers"])
            )
        for mod in VALID["modules"]:
            d = tmp / mod["path"]
            d.mkdir(parents=True, exist_ok=True)
            (d / "main.tf").write_text("# module\n")
            if mod.get("test"):
                test_file = d / mod["test"]
                test_file.parent.mkdir(parents=True, exist_ok=True)
                test_file.write_text("# contract test\n")

    def test_fully_classified_estate_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._estate(root)
            inv = build_inventory(copy.deepcopy(VALID))
            tf_dirs = {r["path"] for r in VALID["roots"]} | {m["path"] for m in VALID["modules"]}
            self.assertEqual(validate_estate(inv, root, tf_dirs=tf_dirs), [])

    def test_unclassified_tf_dir_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._estate(root)
            (root / "modules" / "orphan").mkdir(parents=True)
            (root / "modules" / "orphan" / "main.tf").write_text("# new\n")
            inv = build_inventory(copy.deepcopy(VALID))
            tf_dirs = (
                {r["path"] for r in VALID["roots"]}
                | {m["path"] for m in VALID["modules"]}
                | {"modules/orphan"}
            )
            errors = validate_estate(inv, root, tf_dirs=tf_dirs)
            self.assertTrue(any("modules/orphan" in e for e in errors))

    def test_classified_path_missing_on_disk_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._estate(root)
            inv = build_inventory(copy.deepcopy(VALID))
            tf_dirs = {r["path"] for r in VALID["roots"]} | {m["path"] for m in VALID["modules"]}
            # Inventory references a path that has no .tf on disk.
            inv.modules[0].path = "modules/ghost"
            errors = validate_estate(inv, root, tf_dirs=tf_dirs)
            self.assertTrue(any("modules/ghost" in e for e in errors))

    def test_root_missing_lockfile_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._estate(root)
            (root / "envs" / "core" / ".terraform.lock.hcl").unlink()
            inv = build_inventory(copy.deepcopy(VALID))
            tf_dirs = {r["path"] for r in VALID["roots"]} | {m["path"] for m in VALID["modules"]}
            errors = validate_estate(inv, root, tf_dirs=tf_dirs)
            self.assertTrue(any("lockfile" in e.lower() and "envs/core" in e for e in errors))

    def test_missing_module_test_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._estate(root)
            (root / "modules" / "tested" / "tests" / "main.tftest.hcl").unlink()
            inv = build_inventory(copy.deepcopy(VALID))
            tf_dirs = {r["path"] for r in VALID["roots"]} | {m["path"] for m in VALID["modules"]}
            errors = validate_estate(inv, root, tf_dirs=tf_dirs)
            self.assertTrue(any("main.tftest.hcl" in e for e in errors))

    def test_root_providers_mismatch_lockfile_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._estate(root)
            # Rewrite the aws-core lockfile to include an extra provider the
            # inventory does not declare.
            lock = root / "envs" / "core" / ".terraform.lock.hcl"
            lock.write_text(
                'provider "registry.terraform.io/hashicorp/aws" {\n  version = "6.0.0"\n}\n'
                'provider "registry.terraform.io/hashicorp/tls" {\n  version = "4.0.0"\n}\n'
            )
            inv = build_inventory(copy.deepcopy(VALID))
            tf_dirs = {r["path"] for r in VALID["roots"]} | {m["path"] for m in VALID["modules"]}
            errors = validate_estate(inv, root, tf_dirs=tf_dirs)
            self.assertTrue(any("provider" in e.lower() and "envs/core" in e for e in errors))


class SelectAndMatrixTest(unittest.TestCase):
    def test_select_all_returns_every_root(self) -> None:
        inv = build_inventory(copy.deepcopy(VALID))
        self.assertEqual(len(select_roots(inv, mode="all")), 2)

    def test_unknown_mode_raises(self) -> None:
        inv = build_inventory(copy.deepcopy(VALID))
        with self.assertRaises(ValueError):
            select_roots(inv, mode="magic")

    def test_matrix_shape(self) -> None:
        inv = build_inventory(copy.deepcopy(VALID))
        matrix = build_matrix(select_roots(inv, mode="all"), inv.profiles)
        self.assertEqual(len(matrix), 2)
        entry = next(e for e in matrix if e["id"] == "aws-core")
        self.assertEqual(entry["path"], "envs/core")
        self.assertEqual(entry["terraform_version"], "1.13.3")
        self.assertEqual(entry["provider_family"], "aws")

    def test_module_test_matrix_only_includes_tested_modules(self) -> None:
        inv = build_inventory(copy.deepcopy(VALID))
        matrix = build_module_test_matrix(inv.modules, inv.profiles)
        self.assertEqual(len(matrix), 1)
        entry = matrix[0]
        self.assertEqual(entry["path"], "modules/tested")
        self.assertEqual(entry["test"], "tests/main.tftest.hcl")
        self.assertEqual(entry["terraform_version"], "1.13.3")
        self.assertEqual(entry["provider_family"], "aws")

    def test_module_test_matrix_empty_when_all_deferred(self) -> None:
        data = copy.deepcopy(VALID)
        data["modules"][1] = {
            "path": "modules/tested",
            "owner": "@team",
            "contract": "deferred",
            "reason": "later",
        }
        inv = build_inventory(data)
        self.assertEqual(build_module_test_matrix(inv.modules, inv.profiles), [])


if __name__ == "__main__":
    unittest.main()
