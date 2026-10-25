"""Tests for check_checkov_invocation_parity.py.

Run from the repo root:
    python3 -m unittest scripts.check_checkov_invocation_parity.test_check_checkov_invocation_parity -v
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from .check_checkov_invocation_parity import check_repo


class CheckCheckovInvocationParityTest(unittest.TestCase):
    def test_repo_root_passes_when_precommit_and_ci_match(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        violations = check_repo(repo_root)
        self.assertEqual(violations, [], f"unexpected violations: {violations}")

    def test_ci_policy_is_enforced_without_a_local_hook(self) -> None:
        for replacement in (None, "soft_fail: true", "download_external_modules: false"):
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / ".pre-commit-config.yaml").write_text("repos: []\n", encoding="utf-8")
                workflow = root / ".github/workflows/_quality.yml"
                workflow.parent.mkdir(parents=True)
                text = _valid_ci_workflow()
                if replacement:
                    key = replacement.split(":")[0]
                    text = text.replace(
                        f"{key}: {'false' if key == 'soft_fail' else 'true'}", replacement
                    )
                workflow.write_text(text, encoding="utf-8")
                violations = check_repo(root)
                if replacement:
                    self.assertTrue(any(key in item for item in violations), violations)
                else:
                    self.assertEqual(violations, [])

    def test_present_local_hook_without_arguments_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".pre-commit-config.yaml").write_text(
                "repos:\n  - repo: local\n    hooks:\n      - id: checkov\n", encoding="utf-8"
            )
            workflow = root / ".github/workflows/_quality.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(_valid_ci_workflow(), encoding="utf-8")
            self.assertTrue(check_repo(root))

    def test_missing_download_external_modules_in_precommit_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".pre-commit-config.yaml").write_text(
                textwrap.dedent(
                    """
                    repos:
                      - repo: https://github.com/bridgecrewio/checkov
                        hooks:
                          - id: checkov
                            args:
                              [--config-file, platform/terraform/.checkov.yaml, --directory, platform/terraform/]
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            (root / ".github").mkdir()
            (root / ".github" / "workflows").mkdir()
            (root / ".github" / "workflows" / "_quality.yml").write_text(
                textwrap.dedent(
                    """
                    jobs:
                      security-iac:
                        steps:
                          - name: Checkov IaC Security
                            uses: bridgecrewio/checkov-action@v12
                            with:
                              directory: platform/terraform/
                              config_file: platform/terraform/.checkov.yaml
                              download_external_modules: true
                              soft_fail: false
                    """
                ).lstrip(),
                encoding="utf-8",
            )

            violations = check_repo(root)

        self.assertTrue(
            any("download-external-modules" in v for v in violations),
            f"expected download-external-modules violation, got: {violations}",
        )

    def test_precommit_soft_fail_arg_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".pre-commit-config.yaml").write_text(
                textwrap.dedent(
                    """
                    repos:
                      - repo: https://github.com/bridgecrewio/checkov
                        hooks:
                          - id: checkov
                            args:
                              [--config-file, platform/terraform/.checkov.yaml, --directory, platform/terraform/, --download-external-modules, --soft-fail]
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            (root / ".github").mkdir()
            (root / ".github" / "workflows").mkdir()
            (root / ".github" / "workflows" / "_quality.yml").write_text(
                textwrap.dedent(
                    """
                    jobs:
                      security-iac:
                        steps:
                          - name: Checkov IaC Security
                            uses: bridgecrewio/checkov-action@v12
                            with:
                              directory: platform/terraform/
                              config_file: platform/terraform/.checkov.yaml
                              download_external_modules: true
                              soft_fail: false
                    """
                ).lstrip(),
                encoding="utf-8",
            )

            violations = check_repo(root)

        self.assertTrue(
            any("soft-fail" in v for v in violations),
            f"expected soft-fail violation, got: {violations}",
        )

    def test_missing_quality_workflow_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".pre-commit-config.yaml").write_text("repos: []\n")
            self.assertEqual(check_repo(root), ["missing .github/workflows/_quality.yml"])

    def test_ci_soft_fail_true_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".pre-commit-config.yaml").write_text(
                textwrap.dedent(
                    """
                    repos:
                      - repo: https://github.com/bridgecrewio/checkov
                        hooks:
                          - id: checkov
                            args:
                              [--config-file, platform/terraform/.checkov.yaml, --directory, platform/terraform/, --download-external-modules, "true"]
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            (root / ".github").mkdir()
            (root / ".github" / "workflows").mkdir()
            (root / ".github" / "workflows" / "_quality.yml").write_text(
                textwrap.dedent(
                    """
                    jobs:
                      security-iac:
                        steps:
                          - name: Checkov IaC Security
                            uses: bridgecrewio/checkov-action@v12
                            with:
                              directory: platform/terraform/
                              config_file: platform/terraform/.checkov.yaml
                              download_external_modules: true
                              soft_fail: true
                    """
                ).lstrip(),
                encoding="utf-8",
            )

            violations = check_repo(root)

        self.assertTrue(
            any("soft_fail" in v for v in violations),
            f"expected soft_fail violation, got: {violations}",
        )

    def test_wrong_config_file_in_precommit_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".pre-commit-config.yaml").write_text(
                textwrap.dedent(
                    """
                    repos:
                      - repo: https://github.com/bridgecrewio/checkov
                        hooks:
                          - id: checkov
                            args:
                              [--config-file, wrong/.checkov.yaml, --directory, platform/terraform/, --download-external-modules, "true"]
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            (root / ".github").mkdir()
            (root / ".github" / "workflows").mkdir()
            (root / ".github" / "workflows" / "_quality.yml").write_text(
                _valid_ci_workflow(),
                encoding="utf-8",
            )
            violations = check_repo(root)

        self.assertTrue(
            any("config-file" in v and "pre-commit" in v for v in violations),
            f"expected pre-commit config violation, got: {violations}",
        )

    def test_wrong_directory_in_precommit_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".pre-commit-config.yaml").write_text(
                textwrap.dedent(
                    """
                    repos:
                      - repo: https://github.com/bridgecrewio/checkov
                        hooks:
                          - id: checkov
                            args:
                              [--config-file, platform/terraform/.checkov.yaml, --directory, wrong/, --download-external-modules, "true"]
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            (root / ".github").mkdir()
            (root / ".github" / "workflows").mkdir()
            (root / ".github" / "workflows" / "_quality.yml").write_text(
                _valid_ci_workflow(),
                encoding="utf-8",
            )
            violations = check_repo(root)

        self.assertTrue(
            any("directory" in v and "pre-commit" in v for v in violations),
            f"expected pre-commit directory violation, got: {violations}",
        )

    def test_wrong_config_file_in_ci_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".pre-commit-config.yaml").write_text(
                _valid_precommit_config(),
                encoding="utf-8",
            )
            (root / ".github").mkdir()
            (root / ".github" / "workflows").mkdir()
            (root / ".github" / "workflows" / "_quality.yml").write_text(
                textwrap.dedent(
                    """
                    jobs:
                      security-iac:
                        steps:
                          - name: Checkov IaC Security
                            uses: bridgecrewio/checkov-action@v12
                            with:
                              directory: platform/terraform/
                              config_file: wrong/.checkov.yaml
                              download_external_modules: true
                              soft_fail: false
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            violations = check_repo(root)

        self.assertTrue(
            any("config_file" in v for v in violations),
            f"expected CI config_file violation, got: {violations}",
        )

    def test_wrong_directory_in_ci_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".pre-commit-config.yaml").write_text(
                _valid_precommit_config(),
                encoding="utf-8",
            )
            (root / ".github").mkdir()
            (root / ".github" / "workflows").mkdir()
            (root / ".github" / "workflows" / "_quality.yml").write_text(
                textwrap.dedent(
                    """
                    jobs:
                      security-iac:
                        steps:
                          - name: Checkov IaC Security
                            uses: bridgecrewio/checkov-action@v12
                            with:
                              directory: wrong/
                              config_file: platform/terraform/.checkov.yaml
                              download_external_modules: true
                              soft_fail: false
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            violations = check_repo(root)

        self.assertTrue(
            any("directory" in v and "CI" in v for v in violations),
            f"expected CI directory violation, got: {violations}",
        )

    def test_missing_download_external_modules_in_ci_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".pre-commit-config.yaml").write_text(
                _valid_precommit_config(),
                encoding="utf-8",
            )
            (root / ".github").mkdir()
            (root / ".github" / "workflows").mkdir()
            (root / ".github" / "workflows" / "_quality.yml").write_text(
                textwrap.dedent(
                    """
                    jobs:
                      security-iac:
                        steps:
                          - name: Checkov IaC Security
                            uses: bridgecrewio/checkov-action@v12
                            with:
                              directory: platform/terraform/
                              config_file: platform/terraform/.checkov.yaml
                              download_external_modules: false
                              soft_fail: false
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            violations = check_repo(root)

        self.assertTrue(
            any("download_external_modules" in v for v in violations),
            f"expected CI download_external_modules violation, got: {violations}",
        )


def _valid_precommit_config() -> str:
    return textwrap.dedent(
        """
        repos:
          - repo: https://github.com/bridgecrewio/checkov
            hooks:
              - id: checkov
                args:
                  [--config-file, platform/terraform/.checkov.yaml, --directory, platform/terraform/, --download-external-modules, "true"]
        """
    ).lstrip()


def _valid_ci_workflow() -> str:
    return textwrap.dedent(
        """
        jobs:
          security-iac:
            steps:
              - name: Checkov IaC Security
                uses: bridgecrewio/checkov-action@v12
                with:
                  directory: platform/terraform/
                  config_file: platform/terraform/.checkov.yaml
                  download_external_modules: true
                  soft_fail: false
        """
    ).lstrip()
