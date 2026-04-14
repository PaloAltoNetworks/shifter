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


if __name__ == "__main__":
    unittest.main()
