"""Tests for the ADR guard."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "adr_guard.py"
SPEC = importlib.util.spec_from_file_location("adr_guard", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
ADR_GUARD = importlib.util.module_from_spec(SPEC)
sys.modules["adr_guard"] = ADR_GUARD
SPEC.loader.exec_module(ADR_GUARD)


class AdrGuardTests(unittest.TestCase):
    def test_load_allowed_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "layer_imports.yaml"
            config.write_text(
                "allowed:\n"
                "  engine:\n"
                "    - shared\n"
                "    - cms.services\n",
                encoding="utf-8",
            )

            loaded = ADR_GUARD.load_allowed_imports(config)

            self.assertEqual(loaded["engine"], ["shared", "cms.services"])

    def test_guardrail_docs_requires_docs_update(self) -> None:
        violations = ADR_GUARD.check_guardrail_docs(
            ADR_GUARD.REPO_ROOT,
            [".github/workflows/_quality.yml", "scripts/adr_guard/adr_guard.py"],
        )

        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].rule_id, "ADR-002-R1")

    def test_adr_registry_rejects_unknown_exception_rule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            (repo_root / "docs" / "adr").mkdir(parents=True)
            (repo_root / "docs" / "adr" / "index.yaml").write_text(
                '[{"id":"ADR-001","title":"t","status":"accepted","scope":"repo","decision":"d",'
                '"rules":[{"id":"ADR-001-R1","description":"x","checks":["layer-imports"]}],'
                '"exceptions":[],"enforcement":["ci"],"evidence":["x"]}]',
                encoding="utf-8",
            )
            (repo_root / "docs" / "adr" / "exceptions.yaml").write_text(
                '[{"rule_id":"ADR-404-R9","owner":"me","reason":"tmp","expires_on":"2026-12-31"}]',
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_adr_registry(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertIn("unknown rule id", violations[0].message)

    def test_validate_adr_exceptions_rejects_expired_entries(self) -> None:
        errors = ADR_GUARD.validate_adr_exceptions(
            [
                {
                    "rule_id": "ADR-001-R1",
                    "owner": "platform",
                    "reason": "temporary",
                    "expires_on": "2020-01-01",
                }
            ]
        )

        self.assertEqual(len(errors), 1)
        self.assertIn("expired", errors[0])

    def test_filter_excepted_violations(self) -> None:
        violations = [
            ADR_GUARD.Violation(
                "layer-imports",
                "ADR-001-R1",
                "shifter/shifter_platform/cms/example.py",
                "example",
            ),
            ADR_GUARD.Violation(
                "guardrail-docs",
                "ADR-002-R1",
                ".github/workflows/_quality.yml",
                "example",
            ),
        ]
        exceptions = [
            {
                "rule_id": "ADR-001-R1",
                "owner": "platform",
                "reason": "temporary",
                "expires_on": "2099-12-31",
                "paths": ["shifter/shifter_platform/cms/*"],
                "checks": ["layer-imports"],
            }
        ]

        filtered = ADR_GUARD.filter_excepted_violations(violations, exceptions)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].rule_id, "ADR-002-R1")


class CloudFactorySeamTests(unittest.TestCase):
    def _make_cloud_tree(self, tmp: str, aws_files: list[str], gcp_files: list[str]) -> Path:
        """Create a minimal cloud adapter tree under a fake repo root."""
        repo_root = Path(tmp)
        for cloud_root in ADR_GUARD.CLOUD_ROOTS:
            aws_dir = repo_root / cloud_root / "aws"
            gcp_dir = repo_root / cloud_root / "gcp"
            aws_dir.mkdir(parents=True, exist_ok=True)
            gcp_dir.mkdir(parents=True, exist_ok=True)
            for name in aws_files:
                (aws_dir / name).write_text("", encoding="utf-8")
            for name in gcp_files:
                (gcp_dir / name).write_text("", encoding="utf-8")
        return repo_root

    def test_parity_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = self._make_cloud_tree(
                tmp,
                ["__init__.py", "base.py", "storage.py", "secrets.py"],
                ["__init__.py", "base.py", "storage.py", "secrets.py"],
            )
            violations = ADR_GUARD.check_cloud_factory_seam(repo_root, None)
            self.assertEqual(violations, [])

    def test_missing_gcp_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = self._make_cloud_tree(
                tmp,
                ["__init__.py", "storage.py", "queue.py"],
                ["__init__.py", "storage.py"],
            )
            violations = ADR_GUARD.check_cloud_factory_seam(repo_root, None)
            self.assertTrue(len(violations) >= 1)
            self.assertTrue(any("queue.py" in v.message and "no GCP counterpart" in v.message for v in violations))

    def test_missing_aws_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = self._make_cloud_tree(
                tmp,
                ["__init__.py", "storage.py"],
                ["__init__.py", "storage.py", "task_runner.py"],
            )
            violations = ADR_GUARD.check_cloud_factory_seam(repo_root, None)
            self.assertTrue(len(violations) >= 1)
            self.assertTrue(any("task_runner.py" in v.message and "no AWS counterpart" in v.message for v in violations))

    def test_skips_init_and_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = self._make_cloud_tree(
                tmp,
                ["__init__.py", "base.py"],
                ["__init__.py"],
            )
            violations = ADR_GUARD.check_cloud_factory_seam(repo_root, None)
            self.assertEqual(violations, [])

    def test_skipped_when_no_cloud_files_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = self._make_cloud_tree(
                tmp,
                ["__init__.py", "storage.py", "queue.py"],
                ["__init__.py", "storage.py"],
            )
            violations = ADR_GUARD.check_cloud_factory_seam(
                repo_root,
                ["shifter/shifter_platform/cms/views.py"],
            )
            self.assertEqual(violations, [])

    def test_runs_when_cloud_files_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = self._make_cloud_tree(
                tmp,
                ["__init__.py", "storage.py", "queue.py"],
                ["__init__.py", "storage.py"],
            )
            violations = ADR_GUARD.check_cloud_factory_seam(
                repo_root,
                ["shifter/shifter_platform/shared/cloud/gcp/storage.py"],
            )
            self.assertTrue(len(violations) >= 1)

    def test_real_repo_passes(self) -> None:
        """The actual repo cloud adapters should be in parity."""
        violations = ADR_GUARD.check_cloud_factory_seam(ADR_GUARD.REPO_ROOT, None)
        self.assertEqual(violations, [])


class McpNoShellExecTests(unittest.TestCase):
    """Tests for the mcp-no-shell-exec ADR-010-R1 check."""

    def _write(self, repo_root: Path, rel: str, body: str) -> None:
        path = repo_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def _run(self, repo_root: Path) -> list:
        return ADR_GUARD.check_mcp_no_shell_exec(repo_root, None)

    def test_clean_file_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { spawnSync } from "node:child_process";\n'
                "spawnSync('aws', ['s3', 'ls']);\n",
            )
            self.assertEqual(self._run(repo_root), [])

    def test_named_esm_import_with_node_prefix_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { execSync } from "node:child_process";\n'
                "execSync('aws s3 ls');\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-010-R1")

    def test_named_esm_import_without_node_prefix_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                "import { execSync } from 'child_process';\n"
                "execSync('aws s3 ls');\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)

    def test_namespace_esm_import_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import * as cp from "node:child_process";\n'
                "cp.execSync('aws s3 ls');\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)

    def test_default_esm_import_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import cp from "node:child_process";\n'
                "cp.execSync('aws s3 ls');\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)

    def test_destructured_cjs_require_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.cjs",
                'const { execSync } = require("child_process");\n'
                "execSync('aws s3 ls');\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)

    def test_bare_cjs_require_with_property_access_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.cjs",
                'const cp = require("node:child_process");\n'
                "cp.execSync('aws s3 ls');\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)

    def test_mjs_extension_is_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.mjs",
                'import { execSync } from "child_process";\n'
                "execSync('aws s3 ls');\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)

    def test_execSync_in_a_comment_does_not_trip_the_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { spawnSync } from "node:child_process";\n'
                "// We used to call execSync('aws s3 ls') here.\n"
                "/* execSync('legacy') */\n"
                "spawnSync('aws', ['s3', 'ls']);\n",
            )
            self.assertEqual(self._run(repo_root), [])

    def test_execSync_without_child_process_import_is_not_flagged(self) -> None:
        # An unrelated function happens to be named execSync but is
        # not Node's child_process.execSync; the check requires both
        # the import and the call site.
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                "function execSync(query) { return query; }\n"
                "execSync('select 1');\n",
            )
            self.assertEqual(self._run(repo_root), [])

    def test_node_modules_is_not_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/node_modules/something/dist.js",
                'import { execSync } from "child_process";\n'
                "execSync('aws s3 ls');\n",
            )
            self.assertEqual(self._run(repo_root), [])

    def test_real_repo_passes_with_ngfw_exception(self) -> None:
        """Live repo: ops is clean; ngfw violates but is excepted."""
        raw = ADR_GUARD.check_mcp_no_shell_exec(ADR_GUARD.REPO_ROOT, None)
        # ngfw is a real violator and should be in the raw list.
        self.assertTrue(any(v.path.startswith("mcp/ngfw/") for v in raw))
        # ops should never appear in the raw list.
        self.assertFalse(any(v.path.startswith("mcp/ops/") for v in raw))
        # After applying exceptions, the live repo passes ci-level.
        exceptions = ADR_GUARD.load_adr_exceptions(ADR_GUARD.REPO_ROOT)
        filtered = ADR_GUARD.filter_excepted_violations(raw, exceptions)
        self.assertEqual(filtered, [])


if __name__ == "__main__":
    unittest.main()
