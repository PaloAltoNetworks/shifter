"""Tests for the ADR guard."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

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


class DeployWorkflowPlanScopeTests(unittest.TestCase):
    """Tests for the AWS platform plan trigger and lock-timeout guardrail."""

    def _write_workflows(
        self,
        repo_root: Path,
        deploy: str,
        platform: str,
        core: str | None = None,
        range_workflow: str | None = None,
    ) -> None:
        workflow_dir = repo_root / ".github" / "workflows"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "deploy.yml").write_text(deploy, encoding="utf-8")
        (workflow_dir / "_shifter-platform.yml").write_text(platform, encoding="utf-8")
        (workflow_dir / "_core.yml").write_text(
            core or self._terraform_workflow_text("core"), encoding="utf-8"
        )
        (workflow_dir / "_range.yml").write_text(
            range_workflow or self._terraform_workflow_text("range"), encoding="utf-8"
        )

    def _deploy_text(
        self,
        *,
        platform_globs: list[str] | None = None,
        quality_non_doc_globs: list[str] | None = None,
        guardrail_doc_globs: list[str] | None = None,
        portal_image_globs: list[str] | None = None,
        quality_condition: str = "needs.changes.outputs.quality_relevant == 'true'",
        quality_output: str = "quality_relevant: ${{ steps.quality_non_docs.outputs.non_docs == 'true' || steps.quality_guardrails.outputs.guardrail_docs == 'true' }}",
        include_quality_non_docs_filter: bool = True,
        include_guardrail_docs_filter: bool = True,
        quality_predicate: str = "predicate-quantifier: every",
        pr_gate_guard: str = 'if [ "$quality_result" = "skipped" ] && [ "$quality_relevant" != "false" ]; then',
        include_portal_image_filter: bool = True,
        portal_image_output: str = "portal_image: ${{ steps.filter.outputs.portal_image }}",
        platform_job_condition: str = "needs.changes.outputs.portal_image == 'true'",
        cancel_in_progress: str = "${{ github.event_name == 'pull_request' }}",
    ) -> str:
        platform_globs = platform_globs or ["platform/terraform/modules/portal/**"]
        quality_non_doc_globs = quality_non_doc_globs or [
            "**",
            "!docs/**",
            "!**/*.md",
            "!shifter/shifter_platform/documentation/**",
        ]
        guardrail_doc_globs = guardrail_doc_globs or [
            ".github/pull_request_template.md",
            ".github/copilot-instructions.md",
            "docs/adr/**",
            "shifter/shifter_platform/documentation/docs/technical/dev/adr-enforcement.md",
        ]
        portal_image_globs = portal_image_globs or ["shifter/shifter_platform/**"]
        platform_lines = "".join(f"              - '{glob}'\n" for glob in platform_globs)
        quality_non_docs_filter = ""
        if include_quality_non_docs_filter:
            quality_non_doc_lines = "".join(
                f"              - '{glob}'\n" for glob in quality_non_doc_globs
            )
            quality_non_docs_filter = (
                "      - id: quality_non_docs\n"
                "        with:\n"
                f"          {quality_predicate}\n"
                "          filters: |\n"
                "            non_docs:\n"
                f"{quality_non_doc_lines}"
            )
        guardrail_docs_filter = ""
        if include_guardrail_docs_filter:
            guardrail_doc_lines = "".join(
                f"              - '{glob}'\n" for glob in guardrail_doc_globs
            )
            guardrail_docs_filter = (
                "      - id: quality_guardrails\n"
                "        with:\n"
                "          filters: |\n"
                "            guardrail_docs:\n"
                f"{guardrail_doc_lines}"
            )
        portal_image_filter = ""
        if include_portal_image_filter:
            portal_image_lines = "".join(
                f"              - '{glob}'\n" for glob in portal_image_globs
            )
            portal_image_filter = f"            portal_image:\n{portal_image_lines}"
        return (
            "concurrency:\n"
            "  group: deploy-${{ github.ref }}\n"
            f"  cancel-in-progress: {cancel_in_progress}\n"
            "jobs:\n"
            "  changes:\n"
            "    outputs:\n"
            f"      {quality_output}\n"
            f"      {portal_image_output}\n"
            "    steps:\n"
            "      - id: filter\n"
            "        with:\n"
            "          filters: |\n"
            "            shifter_platform:\n"
            f"{platform_lines}"
            f"{portal_image_filter}"
            f"{quality_non_docs_filter}"
            f"{guardrail_docs_filter}"
            "  quality:\n"
            "    if: |\n"
            f"      {quality_condition}\n"
            "  pr-gate:\n"
            "    steps:\n"
            "      - run: |\n"
            "          quality_result='${{ needs.quality.result }}'\n"
            "          quality_relevant='${{ needs.changes.outputs.quality_relevant }}'\n"
            f"          {pr_gate_guard}\n"
            "            exit 1\n"
            "          fi\n"
            "  shifter_platform:\n"
            "    if: |\n"
            f"      {platform_job_condition}\n"
        )

    def _platform_text(
        self,
        plan_args: str = "-no-color -lock-timeout=5m -out=tfplan",
        build_condition: str = "inputs.portal_image_changes",
        apply_plan_command: str | None = "terraform plan -lock-timeout=5m -out=tfplan",
        before_apply_command: str | None = None,
        apply_command: str = "terraform apply -lock-timeout=5m tfplan",
    ) -> str:
        apply_plan_step = f"      - run: {apply_plan_command}\n" if apply_plan_command else ""
        before_apply_step = f"      - run: {before_apply_command}\n" if before_apply_command else ""
        return (
            "jobs:\n"
            "  plan:\n"
            "    steps:\n"
            f"      - run: terraform plan {plan_args}\n"
            "  apply:\n"
            "    steps:\n"
            f"{apply_plan_step}"
            f"{before_apply_step}"
            f"      - run: {apply_command}\n"
            "  build:\n"
            "    if: |\n"
            f"      {build_condition}\n"
        )

    def _terraform_workflow_text(
        self,
        component: str,
        *,
        plan_args: str = "-no-color -lock-timeout=5m -out=tfplan",
        apply_plan_command: str | None = "terraform plan -lock-timeout=5m -out=tfplan",
        apply_command: str = "terraform apply -lock-timeout=5m tfplan",
    ) -> str:
        apply_plan_step = f"      - run: {apply_plan_command}\n" if apply_plan_command else ""
        return (
            "jobs:\n"
            "  plan:\n"
            "    steps:\n"
            f"      - run: terraform plan {plan_args}\n"
            "  apply:\n"
            "    steps:\n"
            f"{apply_plan_step}"
            f"      - run: {apply_command}\n"
        )

    def test_flags_deploy_workflow_that_cancels_env_branch_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_workflows(
                repo_root,
                self._deploy_text(cancel_in_progress="true"),
                self._platform_text(),
            )

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-003-R2")
            self.assertIn("queue", violations[0].message)

    def test_flags_core_and_range_plan_without_lock_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_workflows(
                repo_root,
                self._deploy_text(),
                self._platform_text(),
                core=self._terraform_workflow_text("core", plan_args="-no-color -out=tfplan"),
                range_workflow=self._terraform_workflow_text(
                    "range", plan_args="-no-color -out=tfplan"
                ),
            )

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

            flagged = {violation.path.split(":", 1)[0] for violation in violations}
            self.assertIn(".github/workflows/_core.yml", flagged)
            self.assertIn(".github/workflows/_range.yml", flagged)
            self.assertTrue(all(violation.rule_id == "ADR-003-R2" for violation in violations))

    def test_flags_core_apply_without_local_saved_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_workflows(
                repo_root,
                self._deploy_text(),
                self._platform_text(),
                core=self._terraform_workflow_text(
                    "core",
                    apply_plan_command=None,
                    apply_command="terraform apply -auto-approve",
                ),
            )

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

            core_violations = [
                violation
                for violation in violations
                if violation.path.startswith(".github/workflows/_core.yml")
            ]
            self.assertGreaterEqual(len(core_violations), 1)
            self.assertTrue(
                all(violation.rule_id == "ADR-003-R2" for violation in core_violations)
            )
            self.assertTrue(
                any(
                    "local saved Terraform plan" in violation.message
                    for violation in core_violations
                )
            )

    def test_flags_apply_without_local_saved_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_workflows(
                repo_root,
                self._deploy_text(),
                self._platform_text(
                    apply_plan_command=None,
                    apply_command="terraform apply -auto-approve",
                ),
            )

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

            messages = "\n".join(violation.message for violation in violations)
            self.assertIn("local saved Terraform plan", messages)
            self.assertIn("saved Terraform plan", messages)

    def test_flags_apply_job_that_removes_saved_plan_before_applying(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_workflows(
                repo_root,
                self._deploy_text(),
                self._platform_text(
                    before_apply_command="rm -f tfplan",
                ),
            )

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertIn("must not remove `tfplan`", violations[0].message)

    def test_flags_python_glob_in_platform_plan_scope(self) -> None:
        cases = ("shifter/**", "shifter/shifter_platform/**", "shifter/**/*.py")
        for app_glob in cases:
            with self.subTest(app_glob=app_glob), tempfile.TemporaryDirectory() as tmp:
                repo_root = Path(tmp)
                self._write_workflows(
                    repo_root,
                    self._deploy_text(platform_globs=["platform/terraform/modules/portal/**", app_glob]),
                    self._platform_text(),
                )

                violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

                self.assertEqual(len(violations), 1)
                self.assertEqual(violations[0].rule_id, "ADR-003-R2")
                self.assertIn(app_glob, violations[0].message)

    def test_flags_platform_plan_without_lock_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_workflows(
                repo_root,
                self._deploy_text(),
                self._platform_text("-no-color -out=tfplan"),
            )

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-003-R2")
            self.assertIn("-lock-timeout=5m", violations[0].message)

    def test_targeted_mode_runs_for_relevant_workflow_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            app_glob = "shifter/**"
            self._write_workflows(
                repo_root,
                self._deploy_text(platform_globs=[app_glob]),
                self._platform_text(),
            )

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(
                repo_root, [".github/workflows/deploy.yml"]
            )

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-003-R2")
            self.assertIn(app_glob, violations[0].message)

    def test_flags_missing_quality_relevant_scope_after_platform_scope_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_workflows(
                repo_root,
                "jobs:\n"
                "  changes:\n"
                "    outputs:\n"
                "      portal_image: ${{ steps.filter.outputs.portal_image }}\n"
                "    steps:\n"
                "      - id: filter\n"
                "        with:\n"
                "          filters: |\n"
                "            shifter_platform:\n"
                "              - 'platform/terraform/modules/portal/**'\n"
                "            portal_image:\n"
                "              - 'shifter/shifter_platform/**'\n"
                "  pr-gate:\n"
                "    steps:\n"
                "      - run: |\n"
                "          quality_result='${{ needs.quality.result }}'\n"
                "          quality_relevant='${{ needs.changes.outputs.quality_relevant }}'\n"
                "          if [ \"$quality_result\" = \"skipped\" ] && [ \"$quality_relevant\" != \"false\" ]; then\n"
                "            exit 1\n"
                "          fi\n"
                "  shifter_platform:\n"
                "    if: |\n"
                "      needs.changes.outputs.portal_image == 'true'\n",
                self._platform_text(),
            )

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertIn("quality_relevant", violations[0].message)

    def test_flags_non_docs_filter_without_docs_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_workflows(
                repo_root,
                self._deploy_text(quality_non_doc_globs=["**", "!**/*.md"]),
                self._platform_text(),
            )

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertIn("!docs/**", violations[0].message)

    def test_flags_non_docs_filter_without_every_predicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_workflows(
                repo_root,
                self._deploy_text(quality_predicate="# predicate-quantifier: every"),
                self._platform_text(),
            )

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertIn("predicate-quantifier: every", violations[0].message)

    def test_flags_missing_guardrail_docs_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_workflows(
                repo_root,
                self._deploy_text(include_guardrail_docs_filter=False),
                self._platform_text(),
            )

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertIn("guardrail_docs", violations[0].message)

    def test_flags_guardrail_docs_filter_without_github_markdown_guardrails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_workflows(
                repo_root,
                self._deploy_text(
                    guardrail_doc_globs=[
                        "docs/adr/**",
                        "shifter/shifter_platform/documentation/docs/technical/dev/adr-enforcement.md",
                    ]
                ),
                self._platform_text(),
            )

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertIn(".github/pull_request_template.md", violations[0].message)

    def test_flags_quality_relevant_condition_outside_quality_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            deploy = self._deploy_text(quality_condition="needs.changes.outputs.mcp == 'true'")
            deploy += "  gcp-dev:\n    if: needs.changes.outputs.quality_relevant == 'true'\n"
            self._write_workflows(repo_root, deploy, self._platform_text())

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertIn("Quality", violations[0].message)

    def test_flags_pr_gate_that_accepts_skipped_quality_without_docs_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_workflows(
                repo_root,
                self._deploy_text(pr_gate_guard='if [ "$quality_result" = "cancelled" ]; then'),
                self._platform_text(),
            )

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertIn("skipped Quality", violations[0].message)

    def test_flags_missing_portal_image_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_workflows(
                repo_root,
                self._deploy_text(include_portal_image_filter=False),
                self._platform_text(),
            )

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-003-R2")
            self.assertIn("portal_image", violations[0].message)

    def test_flags_portal_image_filter_without_platform_source_glob(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_workflows(
                repo_root,
                self._deploy_text(portal_image_globs=["shifter/cyberscript/**"]),
                self._platform_text(),
            )

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertIn("shifter/shifter_platform/**", violations[0].message)

    def test_flags_missing_portal_image_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_workflows(
                repo_root,
                self._deploy_text(
                    portal_image_output="# portal_image: ${{ steps.filter.outputs.portal_image }}"
                ),
                self._platform_text(),
            )

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertIn("output", violations[0].message)

    def test_flags_platform_job_without_portal_image_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_workflows(
                repo_root,
                self._deploy_text(
                    platform_job_condition="needs.changes.outputs.shifter_platform == 'true'"
                ),
                self._platform_text(),
            )

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertIn("needs.changes.outputs.portal_image == 'true'", violations[0].message)

    def test_flags_commented_portal_image_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_workflows(
                repo_root,
                self._deploy_text(
                    platform_job_condition="# needs.changes.outputs.portal_image == 'true'"
                ),
                self._platform_text(),
            )

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertIn("needs.changes.outputs.portal_image == 'true'", violations[0].message)

    def test_flags_platform_build_without_portal_image_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_workflows(
                repo_root,
                self._deploy_text(),
                self._platform_text(build_condition="inputs.apply_changes"),
            )

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertIn("inputs.portal_image_changes", violations[0].message)

    def test_flags_missing_required_workflow_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            (repo_root / ".github" / "workflows").mkdir(parents=True)

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

            flagged = {violation.path for violation in violations}
            self.assertIn(".github/workflows/deploy.yml", flagged)
            self.assertIn(".github/workflows/_shifter-platform.yml", flagged)

    def test_ignores_commented_quality_relevant_output_and_condition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            deploy = (
                "jobs:\n"
                "  changes:\n"
                "    outputs:\n"
                "      # quality_relevant: ${{ steps.quality_non_docs.outputs.non_docs == 'true' || steps.quality_guardrails.outputs.guardrail_docs == 'true' }}\n"
                "      portal_image: ${{ steps.filter.outputs.portal_image }}\n"
                "    steps:\n"
                "      - id: filter\n"
                "        with:\n"
                "          filters: |\n"
                "            shifter_platform:\n"
                "              - 'platform/terraform/modules/portal/**'\n"
                "            portal_image:\n"
                "              - 'shifter/shifter_platform/**'\n"
                "      - id: quality_non_docs\n"
                "        with:\n"
                "          predicate-quantifier: every\n"
                "          filters: |\n"
                "            non_docs:\n"
                "              - '**'\n"
                "              - '!docs/**'\n"
                "              - '!**/*.md'\n"
                "              - '!shifter/shifter_platform/documentation/**'\n"
                "      - id: quality_guardrails\n"
                "        with:\n"
                "          filters: |\n"
                "            guardrail_docs:\n"
                "              - '.github/pull_request_template.md'\n"
                "              - '.github/copilot-instructions.md'\n"
                "              - 'docs/adr/**'\n"
                "              - 'shifter/shifter_platform/documentation/docs/technical/dev/adr-enforcement.md'\n"
                "  quality:\n"
                "    if: |\n"
                "      # needs.changes.outputs.quality_relevant == 'true'\n"
                "  pr-gate:\n"
                "    steps:\n"
                "      - run: |\n"
                "          quality_result='${{ needs.quality.result }}'\n"
                "          quality_relevant='${{ needs.changes.outputs.quality_relevant }}'\n"
                "          if [ \"$quality_result\" = \"skipped\" ] && [ \"$quality_relevant\" != \"false\" ]; then\n"
                "            exit 1\n"
                "          fi\n"
                "  shifter_platform:\n"
                "    if: |\n"
                "      needs.changes.outputs.portal_image == 'true'\n"
            )
            self._write_workflows(repo_root, deploy, self._platform_text())

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertIn("output", violations[0].message)

    def test_ignores_commented_lock_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_workflows(
                repo_root,
                self._deploy_text(),
                self._platform_text("-no-color -out=tfplan # -lock-timeout=5m"),
            )

            violations = ADR_GUARD.check_deploy_workflow_plan_scope(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertIn("-lock-timeout=5m", violations[0].message)

    def test_clean_real_repo_passes(self) -> None:
        violations = ADR_GUARD.check_deploy_workflow_plan_scope(ADR_GUARD.REPO_ROOT, None)
        self.assertEqual(violations, [], msg=f"Unexpected deploy workflow violations: {violations}")


class PortalDeployModeSourceOfTruthTests(unittest.TestCase):
    """Tests for the AWS portal deployment-mode source-of-truth guardrail."""

    _WORKFLOW = (
        "name: Platform\n"
        "jobs:\n"
        "  deploy:\n"
        "    runs-on: self-hosted\n"
        "    steps:\n"
        "      - uses: hashicorp/setup-terraform@v3\n"
        "      - name: Get deployment config\n"
        "        run: |\n"
        "          python3 \"${GITHUB_WORKSPACE}/scripts/portal_deploy/portal_deploy.py\" resolve-topology \\\n"
        "            --terraform-dir \"platform/terraform/environments/${ENV}/portal\" \\\n"
        "            --backend-config \"${ENV}.s3.tfbackend\" \\\n"
        "            --instance-tag \"$INSTANCE_TAG\" \\\n"
        "            --github-output \"$GITHUB_OUTPUT\"\n"
        "      - name: Deploy via SSM (single instance mode)\n"
        "        if: steps.config.outputs.enable_autoscaling != 'true'\n"
        "        run: echo deploy single\n"
        "      - name: Trigger ASG instance refresh\n"
        "        if: steps.config.outputs.enable_autoscaling == 'true'\n"
        "        run: echo refresh asg\n"
        "      - name: Verify ASG image tag\n"
        "        if: steps.config.outputs.enable_autoscaling == 'true'\n"
        "        run: |\n"
        "          python3 \"${GITHUB_WORKSPACE}/scripts/portal_deploy/portal_deploy.py\" verify-asg-image \\\n"
        "            --asg-name \"${ASG_NAME}\" \\\n"
        "            --image-tag \"${IMAGE_TAG}\"\n"
    )
    _OUTPUTS = (
        'output "enable_autoscaling" {\n'
        '  description = "Whether the portal EC2 tier is deployed as an Auto Scaling Group."\n'
        "  value       = var.enable_autoscaling\n"
        "}\n"
    )
    _HELPER = (
        "terraform output -json\n"
        "aws ec2 describe-instances --query Reservations[].Instances[].InstanceId\n"
        "if len(running_instance_ids) != 1: raise PortalDeployError('exactly one')\n"
        "aws autoscaling describe-auto-scaling-groups\n"
        "aws ssm send-command\n"
        "docker inspect\n"
        "aws ssm get-command-invocation\n"
    )

    def _write_repo(
        self,
        repo_root: Path,
        *,
        workflow: str | None = None,
        outputs: str | None = None,
        helper: str | None = None,
    ) -> None:
        workflow_dir = repo_root / ".github" / "workflows"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "_shifter-platform.yml").write_text(
            self._WORKFLOW if workflow is None else workflow,
            encoding="utf-8",
        )
        for environment in ("dev", "prod"):
            output_dir = repo_root / "platform" / "terraform" / "environments" / environment / "portal"
            output_dir.mkdir(parents=True)
            (output_dir / "outputs.tf").write_text(
                self._OUTPUTS if outputs is None else outputs,
                encoding="utf-8",
            )
        helper_dir = repo_root / "scripts" / "portal_deploy"
        helper_dir.mkdir(parents=True)
        (helper_dir / "portal_deploy.py").write_text(
            self._HELPER if helper is None else helper,
            encoding="utf-8",
        )

    def test_clean_fixture_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_repo(repo_root)

            violations = ADR_GUARD.check_portal_deploy_mode_source_of_truth(repo_root, None)

            self.assertEqual(violations, [])

    def test_flags_github_variable_as_deployment_mode_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_repo(
                repo_root,
                workflow=self._WORKFLOW
                + "      - name: Legacy mode\n"
                + "        env:\n"
                + "          ENABLE_AUTOSCALING: ${{ vars.AWS_PORTAL_ENABLE_AUTOSCALING || 'false' }}\n",
            )

            violations = ADR_GUARD.check_portal_deploy_mode_source_of_truth(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertIn("AWS_PORTAL_ENABLE_AUTOSCALING", violations[0].message)

    def test_flags_missing_terraform_mode_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_repo(repo_root, outputs='output "asg_name" { value = module.ec2.asg_name }\n')

            violations = ADR_GUARD.check_portal_deploy_mode_source_of_truth(repo_root, None)

            self.assertTrue(violations)
            self.assertIn('output "enable_autoscaling"', violations[0].message)

    def test_flags_helper_without_single_instance_cardinality_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_repo(
                repo_root,
                helper=(
                    "terraform output -json\n"
                    "aws ec2 describe-instances --query Reservations[0].Instances[0].InstanceId\n"
                    "aws autoscaling describe-auto-scaling-groups\n"
                    "aws ssm send-command\n"
                    "docker inspect\n"
                    "aws ssm get-command-invocation\n"
                ),
            )

            violations = ADR_GUARD.check_portal_deploy_mode_source_of_truth(repo_root, None)

            self.assertTrue(violations)
            self.assertIn("exactly one", violations[0].message)

    def test_flags_workflow_without_asg_image_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_repo(
                repo_root,
                workflow=self._WORKFLOW.replace("verify-asg-image", "echo-no-verification"),
            )

            violations = ADR_GUARD.check_portal_deploy_mode_source_of_truth(repo_root, None)

            self.assertTrue(violations)
            self.assertIn("verify-asg-image", violations[0].message)

    def test_clean_real_repo_passes(self) -> None:
        violations = ADR_GUARD.check_portal_deploy_mode_source_of_truth(
            ADR_GUARD.REPO_ROOT, None
        )
        self.assertEqual(violations, [], msg=f"Unexpected portal deploy mode violations: {violations}")


class PlatformRendersDeployTfvarsTests(unittest.TestCase):
    """Tests for the AWS platform deploy tfvars-render guardrail (ADR-011-R7)."""

    _RENDER_STEP = (
        "      - name: Render local.auto.tfvars from deployment secret\n"
        "        run: printf '%s\\n' \"${TF_VARS_PORTAL}\" > local.auto.tfvars\n"
    )
    _FMT_STEP = "      - run: terraform fmt -check -recursive\n"
    _INIT_STEP = "      - run: terraform init -backend-config=dev.s3.tfbackend\n"
    # A step whose *name* mentions local.auto.tfvars but whose `run:` never
    # writes the file — a label, not a render.
    _NAME_ONLY_STEP = (
        "      - name: Render local.auto.tfvars from deployment secret\n"
        "        run: echo 'no write here'\n"
    )

    def _write_platform(self, repo_root: Path, platform_text: str) -> None:
        workflow_dir = repo_root / ".github" / "workflows"
        workflow_dir.mkdir(parents=True, exist_ok=True)
        (workflow_dir / "_shifter-platform.yml").write_text(platform_text, encoding="utf-8")

    def _platform_text(self, *, plan_steps: str, apply_steps: str) -> str:
        return (
            "name: Platform\n"
            "jobs:\n"
            "  plan:\n"
            "    runs-on: self-hosted\n"
            "    steps:\n"
            f"{plan_steps}"
            "  apply:\n"
            "    runs-on: self-hosted\n"
            "    steps:\n"
            f"{apply_steps}"
            "  build:\n"
            "    runs-on: self-hosted\n"
        )

    def test_passes_when_both_jobs_render_before_terraform(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_platform(
                repo_root,
                self._platform_text(
                    plan_steps=self._FMT_STEP + self._RENDER_STEP + self._INIT_STEP,
                    apply_steps=self._RENDER_STEP + self._INIT_STEP,
                ),
            )

            violations = ADR_GUARD.check_platform_renders_deploy_tfvars(repo_root, None)

            self.assertEqual(violations, [], msg=f"Unexpected violations: {violations}")

    def test_flags_job_missing_render(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_platform(
                repo_root,
                self._platform_text(
                    plan_steps=self._FMT_STEP + self._INIT_STEP,
                    apply_steps=self._RENDER_STEP + self._INIT_STEP,
                ),
            )

            violations = ADR_GUARD.check_platform_renders_deploy_tfvars(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-011-R7")
            self.assertIn("plan", violations[0].message)

    def test_flags_render_after_terraform(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_platform(
                repo_root,
                self._platform_text(
                    plan_steps=self._FMT_STEP + self._RENDER_STEP + self._INIT_STEP,
                    apply_steps=self._INIT_STEP + self._RENDER_STEP,
                ),
            )

            violations = ADR_GUARD.check_platform_renders_deploy_tfvars(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-011-R7")
            self.assertIn("apply", violations[0].message)

    def test_flags_missing_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_platform(
                repo_root,
                "name: Platform\n"
                "jobs:\n"
                "  plan:\n"
                "    runs-on: self-hosted\n"
                "    steps:\n"
                f"{self._RENDER_STEP}{self._INIT_STEP}",
            )

            violations = ADR_GUARD.check_platform_renders_deploy_tfvars(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-011-R7")
            self.assertIn("apply", violations[0].message)

    def test_flags_missing_workflow_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            (repo_root / ".github" / "workflows").mkdir(parents=True)

            violations = ADR_GUARD.check_platform_renders_deploy_tfvars(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-011-R7")
            self.assertEqual(violations[0].path, ".github/workflows/_shifter-platform.yml")

    def test_ignores_commented_render_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            commented_render = "      # run: printf '%s' x > local.auto.tfvars\n"
            self._write_platform(
                repo_root,
                self._platform_text(
                    plan_steps=self._FMT_STEP + commented_render + self._INIT_STEP,
                    apply_steps=self._RENDER_STEP + self._INIT_STEP,
                ),
            )

            violations = ADR_GUARD.check_platform_renders_deploy_tfvars(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-011-R7")
            self.assertIn("plan", violations[0].message)

    def test_flags_step_name_without_render_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_platform(
                repo_root,
                self._platform_text(
                    plan_steps=self._FMT_STEP + self._NAME_ONLY_STEP + self._INIT_STEP,
                    apply_steps=self._RENDER_STEP + self._INIT_STEP,
                ),
            )

            violations = ADR_GUARD.check_platform_renders_deploy_tfvars(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-011-R7")
            self.assertIn("plan", violations[0].message)

    def test_targeted_mode_runs_for_relevant_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_platform(
                repo_root,
                self._platform_text(
                    plan_steps=self._FMT_STEP + self._INIT_STEP,
                    apply_steps=self._RENDER_STEP + self._INIT_STEP,
                ),
            )

            for relevant in (
                [".github/workflows/_shifter-platform.yml"],
                ["scripts/adr_guard/adr_guard.py"],
            ):
                with self.subTest(files=relevant):
                    violations = ADR_GUARD.check_platform_renders_deploy_tfvars(repo_root, relevant)
                    self.assertEqual(len(violations), 1)
                    self.assertEqual(violations[0].rule_id, "ADR-011-R7")
                    self.assertIn("plan", violations[0].message)

    def test_targeted_mode_skips_unrelated_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_platform(
                repo_root,
                self._platform_text(
                    plan_steps=self._FMT_STEP + self._INIT_STEP,
                    apply_steps=self._RENDER_STEP + self._INIT_STEP,
                ),
            )

            violations = ADR_GUARD.check_platform_renders_deploy_tfvars(
                repo_root, ["shifter/shifter_platform/config/settings.py"]
            )

            self.assertEqual(violations, [])

    def test_clean_real_repo_passes(self) -> None:
        violations = ADR_GUARD.check_platform_renders_deploy_tfvars(ADR_GUARD.REPO_ROOT, None)
        self.assertEqual(violations, [], msg=f"Unexpected platform render violations: {violations}")


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

    def test_child_process_exec_import_forms_are_flagged(self) -> None:
        """Every child_process import + exec-call shape trips ADR-010-R1.

        Parameterized so each import variant asserts the same contract —
        exactly one violation *and* the right rule_id — and adding a new
        import shape is atomic (one table row, both assertions inherited).
        """
        cases = {
            "named ESM import, node: prefix": (
                "mcp/foo/index.js",
                'import { execSync } from "node:child_process";\n'
                "execSync('aws s3 ls');\n",
            ),
            "named ESM import, no node: prefix": (
                "mcp/foo/index.js",
                "import { execSync } from 'child_process';\n"
                "execSync('aws s3 ls');\n",
            ),
            "namespace ESM import": (
                "mcp/foo/index.js",
                'import * as cp from "node:child_process";\n'
                "cp.execSync('aws s3 ls');\n",
            ),
            "default ESM import": (
                "mcp/foo/index.js",
                'import cp from "node:child_process";\n'
                "cp.execSync('aws s3 ls');\n",
            ),
            "destructured CJS require, .cjs": (
                "mcp/foo/index.cjs",
                'const { execSync } = require("child_process");\n'
                "execSync('aws s3 ls');\n",
            ),
            "bare CJS require with property access, .cjs": (
                "mcp/foo/index.cjs",
                'const cp = require("node:child_process");\n'
                "cp.execSync('aws s3 ls');\n",
            ),
            "named ESM import, .mjs extension": (
                "mcp/foo/index.mjs",
                'import { execSync } from "child_process";\n'
                "execSync('aws s3 ls');\n",
            ),
        }
        for label, (rel, body) in cases.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as tmp:
                repo_root = Path(tmp)
                self._write(repo_root, rel, body)
                violations = self._run(repo_root)
                self.assertEqual(len(violations), 1)
                self.assertEqual(violations[0].rule_id, "ADR-010-R1")

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

    def test_aliased_named_import_is_flagged(self) -> None:
        """`import { execSync as run } ... run('aws ...')` is a bypass."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { execSync as run } from "node:child_process";\n'
                "run('aws s3 ls');\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-010-R1")

    def test_double_slashes_inside_a_string_do_not_eat_the_call_site(self) -> None:
        """`https://...` URL must not flatten the call line into a comment."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { execSync } from "node:child_process";\n'
                'const endpoint = "https://example.com/foo";\n'
                "execSync('aws s3 ls');\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)

    def test_block_comment_containing_call_text_does_not_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { spawnSync } from "node:child_process";\n'
                "/*\n * old: execSync('aws s3 ls')\n */\n"
                "spawnSync('aws', ['s3', 'ls']);\n",
            )
            self.assertEqual(self._run(repo_root), [])

    def test_template_string_containing_call_text_does_not_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { spawnSync } from "node:child_process";\n'
                "const note = `we used to call execSync('aws ...') here`;\n"
                "spawnSync('aws', ['s3', 'ls']);\n",
            )
            self.assertEqual(self._run(repo_root), [])

    def test_bare_exec_is_flagged(self) -> None:
        """`exec(shellString)` is shell-string execution, same as execSync."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { exec } from "node:child_process";\n'
                "exec('aws s3 ls');\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)

    def test_namespace_exec_call_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import * as cp from "node:child_process";\n'
                "cp.exec('aws s3 ls');\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)

    def test_spawn_with_shell_true_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { spawn } from "node:child_process";\n'
                "spawn('aws s3 ls', { shell: true });\n",
            )
            violations = self._run(repo_root)
            self.assertEqual(len(violations), 1)
            self.assertIn("shell: true", violations[0].message)

    def test_spawn_without_shell_option_is_not_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { spawn } from "node:child_process";\n'
                "spawn('aws', ['s3', 'ls']);\n",
            )
            self.assertEqual(self._run(repo_root), [])

    def test_spawn_with_shell_false_is_not_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { spawn } from "node:child_process";\n'
                "spawn('aws', ['s3', 'ls'], { shell: false });\n",
            )
            self.assertEqual(self._run(repo_root), [])

    def test_string_containing_alias_pattern_does_not_force_a_false_positive(self) -> None:
        """A comment or string with the literal `execSync as run` text
        must not turn an unrelated `run(` call into a flagged call site."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "mcp/foo/index.js",
                'import { spawnSync } from "node:child_process";\n'
                'const note = "we used to import { execSync as run } here";\n'
                "function run(x) { return x; }\n"
                "run('legacy');\n"
                "spawnSync('aws', ['s3', 'ls']);\n",
            )
            self.assertEqual(self._run(repo_root), [])

    def test_synthetic_repo_with_violator_and_exception(self) -> None:
        """A violator in an excepted path is filtered; a violator outside is not.

        Replaces the older live-repo regression test, which would have
        broken when the deferred mcp/ngfw migration removed those
        violations.
        """
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "docs/adr/index.yaml",
                '[{"id":"ADR-010","title":"t","status":"accepted",'
                '"scope":"repository","decision":"d",'
                '"rules":[{"id":"ADR-010-R1","description":"x",'
                '"checks":["mcp-no-shell-exec"]}],'
                '"exceptions":[],"enforcement":["agent-policy"],'
                '"evidence":["scripts/adr_guard/adr_guard.py"]}]',
            )
            self._write(
                repo_root,
                "docs/adr/exceptions.yaml",
                '[{"rule_id":"ADR-010-R1","owner":"team",'
                '"reason":"deferred migration","expires_on":"2099-01-01",'
                '"checks":["mcp-no-shell-exec"],'
                '"paths":["mcp/legacy/*"]}]',
            )
            self._write(
                repo_root,
                "mcp/legacy/index.js",
                'import { execSync } from "child_process";\n'
                "execSync('aws s3 ls');\n",
            )
            self._write(
                repo_root,
                "mcp/fresh/index.js",
                'import { execSync } from "child_process";\n'
                "execSync('aws s3 ls');\n",
            )

            raw = ADR_GUARD.check_mcp_no_shell_exec(repo_root, None)
            paths = sorted(v.path for v in raw)
            self.assertEqual(paths, ["mcp/fresh/index.js", "mcp/legacy/index.js"])

            exceptions = ADR_GUARD.load_adr_exceptions(repo_root)
            filtered = ADR_GUARD.filter_excepted_violations(raw, exceptions)
            self.assertEqual(
                [v.path for v in filtered], ["mcp/fresh/index.js"]
            )

    def test_no_plaintext_secrets_flags_literal_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tfvars_dir = repo_root / "platform" / "terraform" / "environments" / "prod" / "portal"
            tfvars_dir.mkdir(parents=True)
            (tfvars_dir / "terraform.tfvars").write_text(
                'dc_domain_name = "internal.example"\n'
                'dc_domain_password = "P@ssw0rd!"  # pragma: allowlist secret\n',
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-004-R7")
            self.assertEqual(
                violations[0].path,
                "platform/terraform/environments/prod/portal/terraform.tfvars",
            )
            self.assertIn("dc_domain_password", violations[0].message)

    def test_no_plaintext_secrets_allows_var_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tfvars_dir = repo_root / "platform" / "terraform" / "environments" / "dev" / "portal"
            tfvars_dir.mkdir(parents=True)
            (tfvars_dir / "terraform.tfvars").write_text(
                "dc_domain_password = var.dc_domain_password\n"
                "db_password         = local.db_password\n"
                'app_secret_arn      = data.aws_secretsmanager_secret.app.arn\n',
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(repo_root, None)

            self.assertEqual(violations, [])

    def test_no_plaintext_secrets_allows_empty_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tfvars_dir = repo_root / "platform" / "terraform" / "environments" / "dev" / "portal"
            tfvars_dir.mkdir(parents=True)
            (tfvars_dir / "terraform.tfvars").write_text(
                'dc_domain_password = ""\n',
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(repo_root, None)

            self.assertEqual(violations, [])

    def test_no_plaintext_secrets_ignores_non_secret_vars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tfvars_dir = repo_root / "platform" / "terraform" / "environments" / "prod" / "portal"
            tfvars_dir.mkdir(parents=True)
            (tfvars_dir / "terraform.tfvars").write_text(
                'dc_domain_name = "internal.example"\n'
                'environment    = "prod"\n'
                'aws_region     = "us-east-2"\n',
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(repo_root, None)

            self.assertEqual(violations, [])

    def test_no_plaintext_secrets_flags_heredoc_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tfvars_dir = repo_root / "platform" / "terraform" / "environments" / "prod" / "portal"
            tfvars_dir.mkdir(parents=True)
            (tfvars_dir / "terraform.tfvars").write_text(
                'dc_domain_password = <<EOF\n'
                "P@ssw0rd!\n"
                "EOF\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-004-R7")
            self.assertIn("dc_domain_password", violations[0].message)

    def test_no_plaintext_secrets_flags_indented_heredoc_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tfvars_dir = repo_root / "platform" / "terraform" / "environments" / "prod" / "portal"
            tfvars_dir.mkdir(parents=True)
            (tfvars_dir / "terraform.tfvars").write_text(
                "db_password = <<-MARKER\n"
                "  hunter2\n"
                "  MARKER\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-004-R7")
            self.assertIn("db_password", violations[0].message)

    def test_no_plaintext_secrets_allows_public_key_assignments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tfvars_dir = repo_root / "platform" / "terraform" / "environments" / "dev" / "portal"
            tfvars_dir.mkdir(parents=True)
            (tfvars_dir / "terraform.tfvars").write_text(
                'ctfd_ssh_public_key  = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQ== user@host"\n'
                'jwt_public_cert      = "-----BEGIN PUBLIC KEY-----..."\n'
                'authorized_keys      = "ssh-ed25519 AAAA..."\n'
                'pubkey               = "ssh-rsa AAAA..."\n',
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(repo_root, None)

            self.assertEqual(violations, [])

    def test_no_plaintext_secrets_flags_multiline_jsonencode_with_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tfvars_dir = repo_root / "platform" / "terraform" / "environments" / "prod" / "portal"
            tfvars_dir.mkdir(parents=True)
            (tfvars_dir / "terraform.tfvars").write_text(
                "db_credentials = jsonencode({\n"
                '  password = "leak"\n'
                "})\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-004-R7")
            self.assertIn("db_credentials", violations[0].message)

    def test_no_plaintext_secrets_allows_multiline_jsonencode_with_var(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tfvars_dir = repo_root / "platform" / "terraform" / "environments" / "prod" / "portal"
            tfvars_dir.mkdir(parents=True)
            (tfvars_dir / "terraform.tfvars").write_text(
                "db_credentials = jsonencode({\n"
                "  password = var.db_password\n"
                "  username = var.db_username\n"
                "})\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(repo_root, None)

            self.assertEqual(violations, [])

    def test_no_plaintext_secrets_flags_multiline_function_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tfvars_dir = repo_root / "platform" / "terraform" / "environments" / "prod" / "portal"
            tfvars_dir.mkdir(parents=True)
            (tfvars_dir / "terraform.tfvars").write_text(
                "api_token = sensitive(\n"
                '  trimspace("ghp_AAAAAAAAAAAA")\n'
                ")\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-004-R7")
            self.assertIn("api_token", violations[0].message)

    def test_no_plaintext_secrets_does_not_exempt_secret_after_public_key(self) -> None:
        # Regression: the public-key exemption used to be a substring
        # match, which let `public_key_password = "..."` and
        # `authorized_keys_token = "..."` slip through even though the
        # secret-suffix regex matched. The exemption is now suffix-based
        # so these names stay flagged.
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tfvars_dir = repo_root / "platform" / "terraform" / "environments" / "prod" / "portal"
            tfvars_dir.mkdir(parents=True)
            (tfvars_dir / "terraform.tfvars").write_text(
                'public_key_password   = "leak1"\n'
                'authorized_keys_token = "leak2"\n'
                'pubkey_secret         = "leak3"\n',
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(repo_root, None)

            self.assertEqual(len(violations), 3)
            for violation in violations:
                self.assertEqual(violation.rule_id, "ADR-004-R7")

    def test_no_plaintext_secrets_excludes_example_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tfvars_dir = repo_root / "platform" / "terraform" / "environments" / "prod" / "portal"
            tfvars_dir.mkdir(parents=True)
            (tfvars_dir / "terraform.tfvars.example").write_text(
                'dc_domain_password = "REPLACE_ME"\n',
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(repo_root, None)

            self.assertEqual(violations, [])

    def test_no_plaintext_secrets_ignores_commented_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tfvars_dir = repo_root / "platform" / "terraform" / "environments" / "prod" / "portal"
            tfvars_dir.mkdir(parents=True)
            (tfvars_dir / "terraform.tfvars").write_text(
                '# dc_domain_password = "old-value"\n'
                '#   db_password = "another-old"\n',
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(repo_root, None)

            self.assertEqual(violations, [])

    def test_no_plaintext_secrets_ignores_double_slash_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tfvars_dir = repo_root / "platform" / "terraform" / "environments" / "prod" / "portal"
            tfvars_dir.mkdir(parents=True)
            (tfvars_dir / "terraform.tfvars").write_text(
                '// dc_domain_password = "old-value"\n'
                '//   db_password         = "another-old"\n',
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(repo_root, None)

            self.assertEqual(violations, [])

    def test_no_plaintext_secrets_ignores_block_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tfvars_dir = repo_root / "platform" / "terraform" / "environments" / "prod" / "portal"
            tfvars_dir.mkdir(parents=True)
            (tfvars_dir / "terraform.tfvars").write_text(
                "/* historical example:\n"
                'dc_domain_password = "obsolete-literal"\n'
                "*/\n"
                'dc_domain_name = "internal.shifter"\n',
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(repo_root, None)

            self.assertEqual(violations, [])

    def test_no_plaintext_secrets_flags_object_with_string_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tfvars_dir = repo_root / "platform" / "terraform" / "environments" / "prod" / "portal"
            tfvars_dir.mkdir(parents=True)
            (tfvars_dir / "terraform.tfvars").write_text(
                "db_credentials = {\n"
                '  username = "admin"\n'
                '  password = "hunter2"\n'
                "}\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-004-R7")
            self.assertIn("db_credentials", violations[0].message)

    def test_no_plaintext_secrets_allows_object_with_only_var_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tfvars_dir = repo_root / "platform" / "terraform" / "environments" / "prod" / "portal"
            tfvars_dir.mkdir(parents=True)
            (tfvars_dir / "terraform.tfvars").write_text(
                "db_credentials = {\n"
                "  username = var.db_username\n"
                "  password = data.aws_secretsmanager_secret_version.db.secret_string\n"
                "}\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(repo_root, None)

            self.assertEqual(violations, [])

    def test_no_plaintext_secrets_flags_list_with_string_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tfvars_dir = repo_root / "platform" / "terraform" / "environments" / "prod" / "portal"
            tfvars_dir.mkdir(parents=True)
            (tfvars_dir / "terraform.tfvars").write_text(
                "api_tokens = [\n"
                '  "token-one",\n'
                '  "token-two",\n'
                "]\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-004-R7")
            self.assertIn("api_tokens", violations[0].message)

    def test_no_plaintext_secrets_flags_function_wrapped_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tfvars_dir = repo_root / "platform" / "terraform" / "environments" / "prod" / "portal"
            tfvars_dir.mkdir(parents=True)
            (tfvars_dir / "terraform.tfvars").write_text(
                'db_password = trimspace("hunter2")\n'
                'api_token   = sensitive("ghp_AAAA")\n',
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(repo_root, None)

            self.assertEqual(len(violations), 2)
            for violation in violations:
                self.assertEqual(violation.rule_id, "ADR-004-R7")

    def test_no_plaintext_secrets_flags_jsonencode_with_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tfvars_dir = repo_root / "platform" / "terraform" / "environments" / "prod" / "portal"
            tfvars_dir.mkdir(parents=True)
            (tfvars_dir / "terraform.tfvars").write_text(
                'db_credentials = jsonencode({ password = "hunter2" })\n',
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-004-R7")
            self.assertIn("db_credentials", violations[0].message)

    def test_no_plaintext_secrets_allows_function_with_var_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tfvars_dir = repo_root / "platform" / "terraform" / "environments" / "prod" / "portal"
            tfvars_dir.mkdir(parents=True)
            (tfvars_dir / "terraform.tfvars").write_text(
                "db_password = trimspace(var.db_password_raw)\n"
                "api_token   = sensitive(local.token)\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(repo_root, None)

            self.assertEqual(violations, [])

    def test_no_plaintext_secrets_ignores_inline_comment_in_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tfvars_dir = repo_root / "platform" / "terraform" / "environments" / "prod" / "portal"
            tfvars_dir.mkdir(parents=True)
            (tfvars_dir / "terraform.tfvars").write_text(
                "db_credentials = {\n"
                '  username = var.db_username  # "old example"\n'
                "  password = var.db_password  // legacy: was a literal once\n"
                "}\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(repo_root, None)

            self.assertEqual(violations, [])

    def test_no_plaintext_secrets_honors_explicit_file_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            scoped_dir = repo_root / "platform" / "terraform" / "environments" / "prod" / "portal"
            scoped_dir.mkdir(parents=True)
            (scoped_dir / "terraform.tfvars").write_text(
                'dc_domain_password = "leak"\n',
                encoding="utf-8",
            )
            other_dir = repo_root / "platform" / "terraform" / "environments" / "dev" / "portal"
            other_dir.mkdir(parents=True)
            (other_dir / "terraform.tfvars").write_text(
                'dc_domain_password = "also-leak"\n',
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_plaintext_secrets_in_tfvars(
                repo_root,
                ["platform/terraform/environments/prod/portal/terraform.tfvars"],
            )

            self.assertEqual(len(violations), 1)
            self.assertEqual(
                violations[0].path,
                "platform/terraform/environments/prod/portal/terraform.tfvars",
            )


class K8sDeploymentSecurityContextTests(unittest.TestCase):
    """Tests for the k8s-deployment-security-context ADR-006-R2 check."""

    HARDENED_POD = (
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: web\n"
        "spec:\n"
        "  template:\n"
        "    spec:\n"
        "      securityContext:\n"
        "        seccompProfile:\n"
        "          type: RuntimeDefault\n"
        "      containers:\n"
        "        - name: web\n"
        "          image: example/web:1\n"
        "          securityContext:\n"
        "            allowPrivilegeEscalation: false\n"
        "            capabilities:\n"
        "              drop: [\"ALL\"]\n"
        "            readOnlyRootFilesystem: true\n"
        "            runAsNonRoot: true\n"
        "            runAsUser: 1000\n"
        "            runAsGroup: 1000\n"
    )

    def _write(self, repo_root: Path, rel: str, body: str) -> None:
        path = repo_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def _run(self, repo_root: Path, files: list[str] | None = None) -> list:
        if files is None:
            base = repo_root / ADR_GUARD.K8S_BASE_DEPLOYMENT_DIR
            files = sorted(
                ADR_GUARD._repo_relative(p, repo_root)
                for p in list(base.rglob("*.yaml")) + list(base.rglob("*.yml"))
            )
        return ADR_GUARD.check_k8s_deployment_security_context(repo_root, files)

    def test_compliant_deployment_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", self.HARDENED_POD)
            self.assertEqual(self._run(repo_root), [])

    def test_missing_pod_seccomp_profile_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace(
                "      securityContext:\n        seccompProfile:\n          type: RuntimeDefault\n",
                "",
            )
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("seccompProfile" in v.message for v in violations))
            self.assertTrue(all(v.rule_id == "ADR-006-R2" for v in violations))

    def test_wrong_seccomp_profile_type_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace("RuntimeDefault", "Unconfined")
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("Unconfined" in v.message for v in violations))

    def test_allow_privilege_escalation_true_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace(
                "allowPrivilegeEscalation: false", "allowPrivilegeEscalation: true"
            )
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("allowPrivilegeEscalation" in v.message for v in violations))

    def test_missing_read_only_root_fs_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace("            readOnlyRootFilesystem: true\n", "")
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("readOnlyRootFilesystem" in v.message for v in violations))

    def test_missing_run_as_non_root_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace("            runAsNonRoot: true\n", "")
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("runAsNonRoot" in v.message for v in violations))

    def test_missing_capabilities_drop_all_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace(
                "            capabilities:\n              drop: [\"ALL\"]\n", ""
            )
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("drop ALL" in v.message for v in violations))

    def test_capabilities_drop_partial_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace('drop: ["ALL"]', 'drop: ["NET_RAW"]')
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("drop ALL" in v.message for v in violations))

    def test_run_as_root_uid_zero_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace("runAsUser: 1000", "runAsUser: 0")
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("runAsUser" in v.message for v in violations))

    def test_missing_run_as_user_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace("            runAsUser: 1000\n", "")
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("runAsUser" in v.message for v in violations))

    def test_missing_run_as_group_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace("            runAsGroup: 1000\n", "")
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("runAsGroup" in v.message for v in violations))

    def test_missing_container_security_context_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = (
                "apiVersion: apps/v1\n"
                "kind: Deployment\n"
                "metadata:\n"
                "  name: bare\n"
                "spec:\n"
                "  template:\n"
                "    spec:\n"
                "      securityContext:\n"
                "        seccompProfile:\n"
                "          type: RuntimeDefault\n"
                "      containers:\n"
                "        - name: bare\n"
                "          image: example/bare:1\n"
            )
            self._write(repo_root, "platform/k8s/gcp/base/bare-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(len(violations) >= 4)
            self.assertTrue(all(v.rule_id == "ADR-006-R2" for v in violations))

    def test_skips_when_no_relevant_files_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace("RuntimeDefault", "Unconfined")
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            self.assertEqual(
                self._run(repo_root, ["shifter/shifter_platform/cms/views.py"]), []
            )

    def test_runs_when_relevant_files_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace("RuntimeDefault", "Unconfined")
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(
                repo_root, ["platform/k8s/gcp/base/web-deployment.yaml"]
            )
            self.assertTrue(any("Unconfined" in v.message for v in violations))

    def test_skips_non_deployment_kinds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "platform/k8s/gcp/base/foo-deployment.yaml",
                "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: foo\n",
            )
            self.assertEqual(self._run(repo_root), [])

    def test_real_repo_base_manifests_pass(self) -> None:
        """The actual repo's base deployments must comply with ADR-006-R2.

        Restricted to base files so the test doesn't depend on `helm`
        being on PATH; the chart-rendered validation has its own test
        guarded by skipUnless.
        """
        base = ADR_GUARD.REPO_ROOT / ADR_GUARD.K8S_BASE_DEPLOYMENT_DIR
        files = sorted(
            ADR_GUARD._repo_relative(p, ADR_GUARD.REPO_ROOT)
            for p in list(base.rglob("*.yaml")) + list(base.rglob("*.yml"))
        )
        violations = ADR_GUARD.check_k8s_deployment_security_context(
            ADR_GUARD.REPO_ROOT, files
        )
        self.assertEqual(violations, [], msg=str(violations))

    def test_privileged_container_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace(
                "          securityContext:\n",
                "          securityContext:\n            privileged: true\n",
            )
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("privileged" in v.message for v in violations))

    def test_capabilities_add_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace(
                "            capabilities:\n              drop: [\"ALL\"]\n",
                "            capabilities:\n              drop: [\"ALL\"]\n              add: [\"SYS_ADMIN\"]\n",
            )
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(
                any("capabilities.add" in v.message for v in violations)
            )

    def test_container_level_seccomp_unconfined_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace(
                "            runAsGroup: 1000\n",
                "            runAsGroup: 1000\n"
                "            seccompProfile:\n"
                "              type: Unconfined\n",
            )
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(
                any("container-level seccompProfile" in v.message for v in violations)
            )

    def test_container_level_seccomp_runtime_default_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace(
                "            runAsGroup: 1000\n",
                "            runAsGroup: 1000\n"
                "            seccompProfile:\n"
                "              type: RuntimeDefault\n",
            )
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            self.assertEqual(self._run(repo_root), [])

    def test_init_container_unsafe_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = (
                self.HARDENED_POD
                + "      initContainers:\n"
                "        - name: setup\n"
                "          image: example/setup:1\n"
                "          securityContext:\n"
                "            allowPrivilegeEscalation: true\n"
                "            capabilities:\n"
                "              drop: []\n"
                "            readOnlyRootFilesystem: false\n"
                "            runAsNonRoot: false\n"
                "            runAsUser: 0\n"
                "            runAsGroup: 0\n"
            )
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(
                any("initContainer" in v.message and "'setup'" in v.message for v in violations)
            )

    def test_init_container_compliant_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = (
                self.HARDENED_POD
                + "      initContainers:\n"
                "        - name: setup\n"
                "          image: example/setup:1\n"
                "          securityContext:\n"
                "            allowPrivilegeEscalation: false\n"
                "            capabilities:\n"
                "              drop: [\"ALL\"]\n"
                "            readOnlyRootFilesystem: true\n"
                "            runAsNonRoot: true\n"
                "            runAsUser: 1000\n"
                "            runAsGroup: 1000\n"
            )
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            self.assertEqual(self._run(repo_root), [])

    def test_boolean_run_as_user_is_rejected(self) -> None:
        """`runAsUser: true` must NOT pass even though bool is a subclass of int."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace("runAsUser: 1000", "runAsUser: true")
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("runAsUser" in v.message for v in violations))

    def test_boolean_run_as_group_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace("runAsGroup: 1000", "runAsGroup: false")
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("runAsGroup" in v.message for v in violations))


class K8sNetworkPolicyCoverageTests(unittest.TestCase):
    """Tests for the k8s-network-policy-coverage ADR-006-R3 check."""

    NAMESPACES = (
        "apiVersion: v1\n"
        "kind: Namespace\n"
        "metadata:\n"
        "  name: shifter-platform\n"
        "---\n"
        "apiVersion: v1\n"
        "kind: Namespace\n"
        "metadata:\n"
        "  name: shifter-jobs\n"
    )

    DEFAULT_DENY_PLATFORM = (
        "apiVersion: networking.k8s.io/v1\n"
        "kind: NetworkPolicy\n"
        "metadata:\n"
        "  name: default-deny\n"
        "  namespace: shifter-platform\n"
        "spec:\n"
        "  podSelector: {}\n"
        "  policyTypes:\n"
        "    - Ingress\n"
        "    - Egress\n"
        "  ingress: []\n"
        "  egress: []\n"
    )

    DEFAULT_DENY_JOBS = DEFAULT_DENY_PLATFORM.replace(
        "namespace: shifter-platform", "namespace: shifter-jobs"
    )

    def _write(self, repo_root: Path, rel: str, body: str) -> None:
        path = repo_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def _run(self, repo_root: Path, files: list[str] | None = None) -> list:
        if files is None:
            base = repo_root / ADR_GUARD.K8S_BASE_DEPLOYMENT_DIR
            files = sorted(
                ADR_GUARD._repo_relative(p, repo_root)
                for p in list(base.rglob("*.yaml")) + list(base.rglob("*.yml"))
            )
        return ADR_GUARD.check_k8s_network_policy_coverage(repo_root, files)

    def test_each_namespace_requires_default_deny_network_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/namespaces.yaml", self.NAMESPACES)
            self._write(
                repo_root,
                "platform/k8s/gcp/base/networkpolicies.yaml",
                self.DEFAULT_DENY_PLATFORM,
            )

            violations = self._run(repo_root)

            self.assertTrue(any("shifter-jobs" in v.message for v in violations))
            self.assertTrue(all(v.rule_id == "ADR-006-R3" for v in violations))

    def test_default_deny_network_policy_coverage_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/namespaces.yaml", self.NAMESPACES)
            self._write(
                repo_root,
                "platform/k8s/gcp/base/networkpolicies.yaml",
                self.DEFAULT_DENY_PLATFORM + "---\n" + self.DEFAULT_DENY_JOBS,
            )

            self.assertEqual(self._run(repo_root), [])

    def test_broad_egress_ip_block_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            broad_allow = (
                self.DEFAULT_DENY_PLATFORM
                + "---\n"
                + "apiVersion: networking.k8s.io/v1\n"
                + "kind: NetworkPolicy\n"
                + "metadata:\n"
                + "  name: broad-egress\n"
                + "  namespace: shifter-platform\n"
                + "spec:\n"
                + "  podSelector: {}\n"
                + "  policyTypes: [Egress]\n"
                + "  egress:\n"
                + "    - to:\n"
                + "        - ipBlock:\n"
                + "            cidr: 0.0.0.0/0\n"
            )
            self._write(repo_root, "platform/k8s/gcp/base/namespaces.yaml", self.NAMESPACES)
            self._write(
                repo_root,
                "platform/k8s/gcp/base/networkpolicies.yaml",
                broad_allow + "---\n" + self.DEFAULT_DENY_JOBS,
            )

            violations = self._run(repo_root)

            self.assertTrue(any("0.0.0.0/0" in v.message for v in violations))


class K8sDeploymentSecurityContextRobustnessTests(unittest.TestCase):
    """Cycle-3 robustness coverage: PyYAML-backed parsing, kind-based filtering,
    pod-level inheritance, multi-document files, and unsupported shapes."""

    HARDENED_POD = K8sDeploymentSecurityContextTests.HARDENED_POD

    def _write(self, repo_root: Path, rel: str, body: str) -> None:
        path = repo_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def _run(self, repo_root: Path, files: list[str] | None = None) -> list:
        if files is None:
            base = repo_root / ADR_GUARD.K8S_BASE_DEPLOYMENT_DIR
            files = sorted(
                ADR_GUARD._repo_relative(p, repo_root)
                for p in list(base.rglob("*.yaml")) + list(base.rglob("*.yml"))
            )
        return ADR_GUARD.check_k8s_deployment_security_context(repo_root, files)

    def test_leading_document_separator_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "platform/k8s/gcp/base/web-deployment.yaml",
                "---\n" + self.HARDENED_POD,
            )
            self.assertEqual(self._run(repo_root), [])

    def test_indentless_sequence_passes(self) -> None:
        body = (
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: web\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      securityContext:\n"
            "        seccompProfile:\n"
            "          type: RuntimeDefault\n"
            "      containers:\n"
            "      - name: web\n"
            "        image: example/web:1\n"
            "        securityContext:\n"
            "          allowPrivilegeEscalation: false\n"
            "          capabilities:\n"
            "            drop: [\"ALL\"]\n"
            "          readOnlyRootFilesystem: true\n"
            "          runAsNonRoot: true\n"
            "          runAsUser: 1000\n"
            "          runAsGroup: 1000\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            self.assertEqual(self._run(repo_root), [])

    def test_empty_flow_security_context_fails_cleanly(self) -> None:
        """`securityContext: {}` parses as an empty mapping but exposes no fields,
        so the container-level checks must report violations rather than crash."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace(
                "          securityContext:\n"
                "            allowPrivilegeEscalation: false\n"
                "            capabilities:\n"
                "              drop: [\"ALL\"]\n"
                "            readOnlyRootFilesystem: true\n"
                "            runAsNonRoot: true\n"
                "            runAsUser: 1000\n"
                "            runAsGroup: 1000\n",
                "          securityContext: {}\n",
            )
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(len(violations) >= 4)
            self.assertTrue(all(v.rule_id == "ADR-006-R2" for v in violations))

    def test_non_mapping_security_context_reports_violation(self) -> None:
        """A non-mapping `securityContext:` value (e.g., a YAML alias resolved to a
        string) must produce a clear violation, not crash with AttributeError."""
        body = (
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: web\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      securityContext: scalar-not-a-mapping\n"
            "      containers:\n"
            "        - name: web\n"
            "          image: example/web:1\n"
            "          securityContext: scalar-not-a-mapping\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(
                any("must be a mapping" in v.message for v in violations)
            )

    def test_pod_level_run_as_user_inheritance_passes(self) -> None:
        body = (
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: web\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      securityContext:\n"
            "        seccompProfile:\n"
            "          type: RuntimeDefault\n"
            "        runAsNonRoot: true\n"
            "        runAsUser: 1000\n"
            "        runAsGroup: 1000\n"
            "      containers:\n"
            "        - name: web\n"
            "          image: example/web:1\n"
            "          securityContext:\n"
            "            allowPrivilegeEscalation: false\n"
            "            capabilities:\n"
            "              drop: [\"ALL\"]\n"
            "            readOnlyRootFilesystem: true\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            self.assertEqual(self._run(repo_root), [])

    def test_container_override_beats_pod_level_default(self) -> None:
        """If pod sets runAsUser=1000 but a container overrides to 0, that container fails."""
        body = (
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: web\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      securityContext:\n"
            "        seccompProfile:\n"
            "          type: RuntimeDefault\n"
            "        runAsNonRoot: true\n"
            "        runAsUser: 1000\n"
            "        runAsGroup: 1000\n"
            "      containers:\n"
            "        - name: web\n"
            "          image: example/web:1\n"
            "          securityContext:\n"
            "            allowPrivilegeEscalation: false\n"
            "            capabilities:\n"
            "              drop: [\"ALL\"]\n"
            "            readOnlyRootFilesystem: true\n"
            "            runAsUser: 0\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("runAsUser" in v.message for v in violations))

    def test_kind_based_filtering_scans_unsuffixed_yaml(self) -> None:
        """A Deployment placed in a file without the '-deployment.yaml' suffix
        must still be scanned. Filename is not authoritative; `kind:` is."""
        body = self.HARDENED_POD.replace("allowPrivilegeEscalation: false", "allowPrivilegeEscalation: true")
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/worker.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("allowPrivilegeEscalation" in v.message for v in violations))

    def test_non_deployment_kind_is_skipped(self) -> None:
        """A non-Deployment YAML in the base dir must be parsed but not flagged."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(
                repo_root,
                "platform/k8s/gcp/base/configmap.yaml",
                "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: foo\n",
            )
            self.assertEqual(self._run(repo_root), [])

    def test_empty_capabilities_add_is_rejected(self) -> None:
        """`capabilities.add: []` is forbidden by key presence; the rule says
        'no capabilities.add', not 'no non-empty capabilities.add'."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            body = self.HARDENED_POD.replace(
                "            capabilities:\n              drop: [\"ALL\"]\n",
                "            capabilities:\n              drop: [\"ALL\"]\n              add: []\n",
            )
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(
                any("capabilities.add" in v.message for v in violations)
            )

    def test_non_mapping_spec_fails_cleanly(self) -> None:
        """A `spec:` value that is a non-mapping scalar must produce a violation,
        not crash the entire ADR guard with an AttributeError."""
        body = (
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: web\n"
            "spec: scalar-not-a-mapping\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("spec must be a mapping" in v.message for v in violations))

    def test_non_mapping_template_fails_cleanly(self) -> None:
        body = (
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: web\n"
            "spec:\n"
            "  template: scalar-not-a-mapping\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(
                any("spec.template must be a mapping" in v.message for v in violations)
            )

    def test_yml_extension_is_scanned(self) -> None:
        """A Deployment in a `.yml`-extension file under base/ must be scanned."""
        body = self.HARDENED_POD.replace("allowPrivilegeEscalation: false", "allowPrivilegeEscalation: true")
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/worker.yml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("allowPrivilegeEscalation" in v.message for v in violations))

    def test_missing_chart_directory_is_a_violation(self) -> None:
        """Deleting the entire chart directory must produce a violation,
        not a silent skip — the chart is the authoritative deployment
        contract per ADR-007."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            # No chart/ directory created.
            rendered, violations = ADR_GUARD._render_chart_for_validation(
                repo_root, ADR_GUARD.HELM_VALUES_FILES
            )
            self.assertEqual(rendered, [])
            self.assertTrue(
                any(
                    v.path == ADR_GUARD.HELM_CHART_DIR
                    and "chart directory is missing" in v.message
                    for v in violations
                )
            )

    def test_chart_violation_path_is_repo_relative(self) -> None:
        """Rendered-chart violations must use the values-file repo-relative
        path so existing exception globs in docs/adr/exceptions.yaml can
        match (the path field, not a synthetic 'helm template -f X' label)."""
        import os
        import stat

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            chart_dir = repo_root / "platform/charts/shifter"
            chart_dir.mkdir(parents=True)
            for vf in ADR_GUARD.HELM_VALUES_FILES:
                (repo_root / vf).write_text("dummy: true\n", encoding="utf-8")

            unsafe_deployment = (
                "apiVersion: apps/v1\n"
                "kind: Deployment\n"
                "metadata:\n"
                "  name: rendered\n"
                "spec:\n"
                "  template:\n"
                "    spec:\n"
                "      containers:\n"
                "        - name: rendered\n"
                "          image: example/x:1\n"
                "          securityContext:\n"
                "            allowPrivilegeEscalation: true\n"
            )
            shim_dir = repo_root / "_shim"
            shim_dir.mkdir()
            shim_path = shim_dir / "helm"
            shim_path.write_text(
                "#!/usr/bin/env bash\n"
                f"cat <<'YAML'\n{unsafe_deployment}YAML\n",
                encoding="utf-8",
            )
            shim_path.chmod(shim_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

            old_path = os.environ.get("PATH", "")
            try:
                os.environ["PATH"] = f"{shim_dir}:{old_path}"
                violations = ADR_GUARD.check_k8s_deployment_security_context(
                    repo_root,
                    ["platform/charts/shifter/values-gcp-dev.yaml"],
                )
            finally:
                os.environ["PATH"] = old_path

            chart_violations = [
                v for v in violations if "allowPrivilegeEscalation" in v.message
            ]
            self.assertTrue(chart_violations)
            for v in chart_violations:
                self.assertIn(v.path, ADR_GUARD.HELM_VALUES_FILES)

    def test_helm_not_installed_returns_actionable_violation(self) -> None:
        """When helm is absent, the chart branch returns a clear violation
        (not a silent skip), so CI surfaces the missing prerequisite."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            (repo_root / "platform/charts/shifter").mkdir(parents=True)
            # Override PATH so helm cannot be found.
            import os
            old_path = os.environ.get("PATH", "")
            try:
                os.environ["PATH"] = ""
                rendered, violations = ADR_GUARD._render_chart_for_validation(
                    repo_root, ADR_GUARD.HELM_VALUES_FILES
                )
            finally:
                os.environ["PATH"] = old_path
            self.assertEqual(rendered, [])
            self.assertTrue(any("helm CLI is required" in v.message for v in violations))

    def test_chart_render_via_fake_helm(self) -> None:
        """End-to-end exercise of the chart-rendering branch using a fake
        helm shim that emits a multi-document YAML payload. Validates
        that rendered Deployments are checked and violations are surfaced
        with a `helm template -f <values>` source label. Both configured
        values files exist so the missing-file path doesn't fire."""
        import os
        import stat

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            chart_dir = repo_root / "platform/charts/shifter"
            chart_dir.mkdir(parents=True)
            for vf in ADR_GUARD.HELM_VALUES_FILES:
                (repo_root / vf).write_text("dummy: true\n", encoding="utf-8")

            # Fake helm shim. Emits a Deployment that violates ADR-006-R2.
            unsafe_deployment = (
                "apiVersion: apps/v1\n"
                "kind: Deployment\n"
                "metadata:\n"
                "  name: rendered\n"
                "spec:\n"
                "  template:\n"
                "    spec:\n"
                "      containers:\n"
                "        - name: rendered\n"
                "          image: example/x:1\n"
                "          securityContext:\n"
                "            allowPrivilegeEscalation: true\n"
            )
            shim_dir = repo_root / "_shim"
            shim_dir.mkdir()
            shim_path = shim_dir / "helm"
            shim_path.write_text(
                "#!/usr/bin/env bash\n"
                f"cat <<'YAML'\n{unsafe_deployment}YAML\n",
                encoding="utf-8",
            )
            shim_path.chmod(shim_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

            old_path = os.environ.get("PATH", "")
            try:
                os.environ["PATH"] = f"{shim_dir}:{old_path}"
                violations = ADR_GUARD.check_k8s_deployment_security_context(
                    repo_root,
                    ["platform/charts/shifter/values-gcp-dev.yaml"],
                )
            finally:
                os.environ["PATH"] = old_path

            self.assertTrue(
                any("allowPrivilegeEscalation" in v.message for v in violations)
            )
            # Violation path is the repo-relative values file (so existing
            # exception globs in docs/adr/exceptions.yaml can match), not a
            # synthetic 'helm template -f X' label.
            self.assertTrue(
                any(v.path in ADR_GUARD.HELM_VALUES_FILES for v in violations)
            )

    def test_missing_helm_values_file_is_a_violation(self) -> None:
        """Deleting / renaming a configured values file must produce a violation,
        not a silent skip — the file is part of the enforcement contract."""
        import os
        import stat

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            chart_dir = repo_root / "platform/charts/shifter"
            chart_dir.mkdir(parents=True)
            # Create only ONE of the configured values files.
            (repo_root / ADR_GUARD.HELM_VALUES_FILES[0]).write_text(
                "dummy: true\n", encoding="utf-8"
            )

            # Compliant deployment from the shim so the existing one passes.
            compliant_deployment = self.HARDENED_POD
            shim_dir = repo_root / "_shim"
            shim_dir.mkdir()
            shim_path = shim_dir / "helm"
            shim_path.write_text(
                "#!/usr/bin/env bash\n"
                f"cat <<'YAML'\n{compliant_deployment}YAML\n",
                encoding="utf-8",
            )
            shim_path.chmod(shim_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

            old_path = os.environ.get("PATH", "")
            try:
                os.environ["PATH"] = f"{shim_dir}:{old_path}"
                rendered, violations = ADR_GUARD._render_chart_for_validation(
                    repo_root, ADR_GUARD.HELM_VALUES_FILES
                )
            finally:
                os.environ["PATH"] = old_path

            missing_file = ADR_GUARD.HELM_VALUES_FILES[1]
            self.assertTrue(
                any(missing_file in v.path and "missing" in v.message for v in violations),
                msg=f"expected violation for missing {missing_file}; got {violations}",
            )

    def test_empty_containers_list_is_a_violation(self) -> None:
        body = (
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: web\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      securityContext:\n"
            "        seccompProfile:\n"
            "          type: RuntimeDefault\n"
            "      containers: []\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(
                any("containers must be a non-empty list" in v.message for v in violations)
            )

    def test_missing_containers_key_is_a_violation(self) -> None:
        body = (
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: web\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      securityContext:\n"
            "        seccompProfile:\n"
            "          type: RuntimeDefault\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/web-deployment.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(
                any("containers must be a non-empty list" in v.message for v in violations)
            )

    def test_multi_document_file_scans_only_deployments(self) -> None:
        """A multi-document YAML file with a ConfigMap and a Deployment must only
        flag violations in the Deployment document."""
        body = (
            "apiVersion: v1\n"
            "kind: ConfigMap\n"
            "metadata:\n"
            "  name: cfg\n"
            "---\n"
            + self.HARDENED_POD.replace("allowPrivilegeEscalation: false", "allowPrivilegeEscalation: true")
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write(repo_root, "platform/k8s/gcp/base/bundle.yaml", body)
            violations = self._run(repo_root)
            self.assertTrue(any("allowPrivilegeEscalation" in v.message for v in violations))


class PythonComplexityGateTests(unittest.TestCase):
    """Tests for the python-complexity-gate adr_guard check (ADR-012-R1)."""

    PYPROJECT_OK = (
        "[project]\n"
        'name = "pkg-a"\n'
        "\n"
        "[tool.ruff.lint]\n"
        'select = ["E", "F", "C901"]\n'
        "\n"
        "[tool.ruff.lint.mccabe]\n"
        "max-complexity = 15\n"
    )

    PYPROJECT_MISSING_C901 = (
        "[project]\n"
        'name = "pkg-a"\n'
        "\n"
        "[tool.ruff.lint]\n"
        'select = ["E", "F"]\n'
        "\n"
        "[tool.ruff.lint.mccabe]\n"
        "max-complexity = 15\n"
    )

    PYPROJECT_MISSING_MCCABE = (
        "[project]\n"
        'name = "pkg-a"\n'
        "\n"
        "[tool.ruff.lint]\n"
        'select = ["E", "F", "C901"]\n'
    )

    PYPROJECT_WRONG_THRESHOLD = (
        "[project]\n"
        'name = "pkg-a"\n'
        "\n"
        "[tool.ruff.lint]\n"
        'select = ["E", "F", "C901"]\n'
        "\n"
        "[tool.ruff.lint.mccabe]\n"
        "max-complexity = 20\n"
    )

    def _write_packages(self, repo_root: Path, packages: dict[str, str]) -> None:
        """Create a temp repo's pyproject.toml files + empty backlog doc.

        The backlog doc is a precondition for the reconciliation pass; writing
        an empty one keeps older synthetic fixtures focused on config-shape
        violations without tripping the missing-backlog check. Tests that
        specifically exercise the missing-backlog path override this.
        """
        for package_path, body in packages.items():
            target = repo_root / package_path / "pyproject.toml"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
        backlog = repo_root / "docs" / "adr" / "complexity-backlog.md"
        if not backlog.exists():
            backlog.parent.mkdir(parents=True, exist_ok=True)
            backlog.write_text(
                "# Python Complexity Backlog\n\n"
                "| Package | File | Function | Complexity |\n"
                "|---|---|---|---|\n",
                encoding="utf-8",
            )

    def test_clean_pyprojects_pass(self) -> None:
        """All canonical pyprojects with C901 + max-complexity=15 produce no violations."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            packages = {pkg: self.PYPROJECT_OK for pkg in ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS}
            self._write_packages(repo_root, packages)

            violations = ADR_GUARD.check_python_complexity_gate(repo_root, None)

            self.assertEqual(violations, [])

    def test_missing_c901_in_select_violates(self) -> None:
        """A canonical pyproject without C901 in select fails ADR-012-R1."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            target_pkg = ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS[0]
            packages = {pkg: self.PYPROJECT_OK for pkg in ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS}
            packages[target_pkg] = self.PYPROJECT_MISSING_C901
            self._write_packages(repo_root, packages)

            violations = ADR_GUARD.check_python_complexity_gate(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].check, "python-complexity-gate")
            self.assertEqual(violations[0].rule_id, "ADR-012-R1")
            self.assertIn("C901", violations[0].message)
            self.assertEqual(violations[0].path, f"{target_pkg}/pyproject.toml")

    def test_missing_mccabe_block_violates(self) -> None:
        """A canonical pyproject without [tool.ruff.lint.mccabe] fails ADR-012-R1."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            target_pkg = ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS[0]
            packages = {pkg: self.PYPROJECT_OK for pkg in ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS}
            packages[target_pkg] = self.PYPROJECT_MISSING_MCCABE
            self._write_packages(repo_root, packages)

            violations = ADR_GUARD.check_python_complexity_gate(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-012-R1")
            self.assertIn("max-complexity", violations[0].message)

    def test_wrong_threshold_violates(self) -> None:
        """A threshold value that does not match the repo target fails ADR-012-R1."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            target_pkg = ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS[0]
            packages = {pkg: self.PYPROJECT_OK for pkg in ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS}
            packages[target_pkg] = self.PYPROJECT_WRONG_THRESHOLD
            self._write_packages(repo_root, packages)

            violations = ADR_GUARD.check_python_complexity_gate(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-012-R1")
            self.assertIn("max-complexity", violations[0].message)
            self.assertIn(str(ADR_GUARD.PYTHON_COMPLEXITY_THRESHOLD), violations[0].message)

    def test_missing_pyproject_violates(self) -> None:
        """A canonical package missing its pyproject.toml fails ADR-012-R1."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            # Skip the first canonical package entirely.
            packages = {pkg: self.PYPROJECT_OK for pkg in ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS[1:]}
            self._write_packages(repo_root, packages)

            violations = ADR_GUARD.check_python_complexity_gate(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-012-R1")
            self.assertIn("missing", violations[0].message.lower())

    def test_files_filter_skips_when_no_canonical_pyproject_touched(self) -> None:
        """When `files` is given but no canonical pyproject is touched, the check is a no-op."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            target_pkg = ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS[0]
            packages = {pkg: self.PYPROJECT_OK for pkg in ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS}
            # Even with a bad pyproject, the file filter should skip the check.
            packages[target_pkg] = self.PYPROJECT_MISSING_C901
            self._write_packages(repo_root, packages)

            violations = ADR_GUARD.check_python_complexity_gate(
                repo_root, ["docs/unrelated.md"]
            )

            self.assertEqual(violations, [])

    def test_files_filter_runs_when_canonical_pyproject_touched(self) -> None:
        """When `files` includes a canonical pyproject, the check runs and reports violations."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            target_pkg = ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS[0]
            packages = {pkg: self.PYPROJECT_OK for pkg in ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS}
            packages[target_pkg] = self.PYPROJECT_MISSING_C901
            self._write_packages(repo_root, packages)

            violations = ADR_GUARD.check_python_complexity_gate(
                repo_root, [f"{target_pkg}/pyproject.toml"]
            )

            self.assertEqual(len(violations), 1)
            self.assertIn("C901", violations[0].message)

    def test_real_repo_passes(self) -> None:
        """Run against the real repo: every canonical pyproject must satisfy ADR-012-R1."""
        violations = ADR_GUARD.check_python_complexity_gate(ADR_GUARD.REPO_ROOT, None)
        self.assertEqual(
            violations,
            [],
            msg="Real repo has python-complexity-gate violations: " + str(violations),
        )

    def test_check_registered_in_check_levels(self) -> None:
        """The new check is wired into the `fast`, `ci`, and `all` profiles."""
        for level in ("fast", "ci", "all"):
            self.assertIn(
                "python-complexity-gate",
                ADR_GUARD.CHECK_LEVELS[level],
                msg=f"python-complexity-gate missing from level={level}",
            )

    def test_check_registered_in_checks_registry(self) -> None:
        """The new check has a CHECKS entry pointing at the implementation."""
        self.assertIn("python-complexity-gate", ADR_GUARD.CHECKS)
        self.assertIs(
            ADR_GUARD.CHECKS["python-complexity-gate"], ADR_GUARD.check_python_complexity_gate
        )

    # ----- Findings 1: silent gate bypass through ignore / per-file-ignores -----

    @staticmethod
    def _pyproject_with_lint_keys(extra_lint_lines: str = "", extra_sections: str = "") -> str:
        """Build a synthetic pyproject with extra `[tool.ruff.lint]` lines or sections.

        Used by the silent-bypass + prefix-selector tests so each case only
        declares what differs from the OK baseline.
        """
        lint = "[tool.ruff.lint]\nselect = [\"E\", \"F\", \"C901\"]\n"
        if extra_lint_lines:
            lint += extra_lint_lines if extra_lint_lines.endswith("\n") else extra_lint_lines + "\n"
        return (
            "[project]\n"
            'name = "pkg-a"\n'
            "\n"
            + lint
            + "\n[tool.ruff.lint.mccabe]\nmax-complexity = 15\n"
            + (("\n" + extra_sections) if extra_sections else "")
        )

    def _assert_single_bypass_violation(
        self, pyproject_body: str, must_contain: tuple[str, ...]
    ) -> None:
        """Helper: synthetic repo with one bad pyproject; assert one violation matching all strings."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            target_pkg = ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS[0]
            packages = {pkg: self.PYPROJECT_OK for pkg in ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS}
            packages[target_pkg] = pyproject_body
            self._write_packages(repo_root, packages)

            violations = ADR_GUARD.check_python_complexity_gate(repo_root, None)

            self.assertEqual(len(violations), 1, msg=str(violations))
            self.assertEqual(violations[0].rule_id, "ADR-012-R1")
            for needle in must_contain:
                self.assertIn(needle, violations[0].message)

    def test_silent_bypass_variants_violate(self) -> None:
        """Each silent-bypass shape (ignore / extend-ignore / per-file-ignores with C901) fails."""
        cases = (
            (
                "ignore_C901",
                self._pyproject_with_lint_keys(extra_lint_lines='ignore = ["C901"]'),
                ("ignore", "C901"),
            ),
            (
                "extend-ignore_C901",
                self._pyproject_with_lint_keys(extra_lint_lines='extend-ignore = ["C901"]'),
                ("extend-ignore", "C901"),
            ),
            (
                "per-file-ignores_C901",
                self._pyproject_with_lint_keys(
                    extra_sections='[tool.ruff.lint.per-file-ignores]\n"**/*.py" = ["C901"]\n'
                ),
                ("per-file-ignores", "C901"),
            ),
        )
        for label, body, expected_substrings in cases:
            with self.subTest(case=label):
                self._assert_single_bypass_violation(body, expected_substrings)

    # ----- Finding 2: package inventory must match pre-commit ruff hooks -----

    def _write_precommit(self, repo_root: Path, hook_paths: list[str]) -> None:
        """Write a minimal .pre-commit-config.yaml whose ruff hooks target the given paths."""
        lines = ["repos:", "  - repo: https://github.com/astral-sh/ruff-pre-commit", "    rev: v0.14.10", "    hooks:"]
        for path in hook_paths:
            lines.extend(
                [
                    "      - id: ruff",
                    f"        name: ruff ({path})",
                    "        args: [--fix]",
                    f"        files: ^{path}/",
                    "      - id: ruff-format",
                    f"        name: ruff-format ({path})",
                    f"        files: ^{path}/",
                ]
            )
        (repo_root / ".pre-commit-config.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_precommit_ruff_hook_without_constant_entry_violates(self) -> None:
        """A ruff hook for a package missing from PYTHON_COMPLEXITY_GATE_PYPROJECTS must fail."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            packages = {pkg: self.PYPROJECT_OK for pkg in ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS}
            self._write_packages(repo_root, packages)
            # Pre-commit has a hook for a new package not in the constant.
            extra_pkg = "scripts/new_uncovered_pkg"
            (repo_root / extra_pkg).mkdir(parents=True, exist_ok=True)
            self._write_precommit(
                repo_root,
                list(ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS) + [extra_pkg],
            )

            violations = ADR_GUARD.check_python_complexity_gate(repo_root, None)

            self.assertTrue(
                any(extra_pkg in v.message for v in violations),
                msg=f"Expected violation mentioning {extra_pkg}: {violations}",
            )

    def test_constant_entry_without_precommit_ruff_hook_violates(self) -> None:
        """A constant entry not backed by a ruff hook indicates stale config; must fail."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            packages = {pkg: self.PYPROJECT_OK for pkg in ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS}
            self._write_packages(repo_root, packages)
            # Pre-commit covers only the first N-1 packages; the last constant entry is stale.
            covered = list(ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS)[:-1]
            stale = ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS[-1]
            self._write_precommit(repo_root, covered)

            violations = ADR_GUARD.check_python_complexity_gate(repo_root, None)

            self.assertTrue(
                any(stale in v.message for v in violations),
                msg=f"Expected violation mentioning {stale}: {violations}",
            )

    def test_precommit_consistency_clean(self) -> None:
        """Constant + ruff hooks in agreement → no consistency violation."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            packages = {pkg: self.PYPROJECT_OK for pkg in ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS}
            self._write_packages(repo_root, packages)
            self._write_precommit(repo_root, list(ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS))

            violations = ADR_GUARD.check_python_complexity_gate(repo_root, None)

            self.assertEqual(violations, [])

    # ----- Reconciliation: in-source `# noqa: C901` ↔ backlog rows -----

    def _write_backlog(self, repo_root: Path, rows: list[tuple[str, str, str, int]]) -> None:
        """Write a synthetic docs/adr/complexity-backlog.md with the given rows.

        Each row is (package, file, function, complexity).
        """
        lines = [
            "# Python Complexity Backlog",
            "",
            "| Package | File | Function | Complexity |",
            "|---|---|---|---|",
        ]
        for pkg, file_, func, complexity in rows:
            lines.append(f"| {pkg} | `{file_}` | `{func}` | {complexity} |")
        target = repo_root / "docs" / "adr" / "complexity-backlog.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_source(self, repo_root: Path, relpath: str, body: str) -> None:
        target = repo_root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")

    def _full_synthetic_repo(self, repo_root: Path) -> None:
        """Build a minimal repo with all canonical pyprojects + precommit + empty backlog."""
        packages = {pkg: self.PYPROJECT_OK for pkg in ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS}
        self._write_packages(repo_root, packages)
        self._write_precommit(repo_root, list(ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS))
        self._write_backlog(repo_root, [])

    def test_noqa_with_matching_backlog_row_passes(self) -> None:
        """A noqa whose file+function appear in the backlog is approved exemption."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._full_synthetic_repo(repo_root)
            pkg = ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS[0]
            source_rel = f"{pkg}/svc.py"
            self._write_source(
                repo_root,
                source_rel,
                "def foo(x):  # noqa: C901\n    pass\n",
            )
            self._write_backlog(repo_root, [("pkg", source_rel, "foo", 17)])

            violations = ADR_GUARD.check_python_complexity_gate(repo_root, None)

            self.assertEqual(violations, [])

    def test_noqa_without_backlog_row_violates(self) -> None:
        """A `# noqa: C901` with no matching backlog row is an unauthorized exemption."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._full_synthetic_repo(repo_root)
            pkg = ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS[0]
            source_rel = f"{pkg}/svc.py"
            self._write_source(
                repo_root,
                source_rel,
                "def foo(x):  # noqa: C901\n    pass\n",
            )
            # Backlog has no row for foo.

            violations = ADR_GUARD.check_python_complexity_gate(repo_root, None)

            self.assertTrue(
                any(
                    "foo" in v.message and v.path.startswith(source_rel)
                    for v in violations
                ),
                msg=f"Expected unauthorized-exemption violation: {violations}",
            )

    def test_backlog_row_without_noqa_violates(self) -> None:
        """A backlog row with no matching `# noqa: C901` in code is stale and must fail."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._full_synthetic_repo(repo_root)
            pkg = ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS[0]
            source_rel = f"{pkg}/svc.py"
            # No source file with a noqa.
            self._write_backlog(repo_root, [("pkg", source_rel, "ghost", 17)])

            violations = ADR_GUARD.check_python_complexity_gate(repo_root, None)

            self.assertTrue(
                any("ghost" in v.message for v in violations),
                msg=f"Expected stale-backlog-row violation: {violations}",
            )

    def test_backlog_doc_missing_violates(self) -> None:
        """If the backlog doc is absent, the reconciliation gate cannot operate; fail."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            packages = {pkg: self.PYPROJECT_OK for pkg in ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS}
            self._write_packages(repo_root, packages)
            self._write_precommit(repo_root, list(ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS))
            # `_write_packages` writes an empty backlog by default; delete it
            # to exercise the missing-backlog path.
            (repo_root / "docs" / "adr" / "complexity-backlog.md").unlink()

            violations = ADR_GUARD.check_python_complexity_gate(repo_root, None)

            self.assertTrue(
                any(
                    v.path == "docs/adr/complexity-backlog.md" and "missing" in v.message
                    for v in violations
                ),
                msg=f"Expected missing-backlog violation: {violations}",
            )

    def test_noqa_with_other_codes_alongside_c901_is_detected(self) -> None:
        """`# noqa: E501, C901` is still a C901 exemption and needs a backlog row."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._full_synthetic_repo(repo_root)
            pkg = ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS[0]
            source_rel = f"{pkg}/svc.py"
            self._write_source(
                repo_root,
                source_rel,
                "def foo(x):  # noqa: E501, C901\n    pass\n",
            )

            violations = ADR_GUARD.check_python_complexity_gate(repo_root, None)

            self.assertTrue(
                any("foo" in v.message for v in violations),
                msg=f"Expected multi-code noqa detected: {violations}",
            )

    # ----- Cycle-3 finding 1: bare `# noqa` on def line bypasses scanner -----

    def test_bare_noqa_on_def_line_violates(self) -> None:
        """`def foo(...):  # noqa` (no code list) suppresses C901 too; must fail."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._full_synthetic_repo(repo_root)
            pkg = ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS[0]
            source_rel = f"{pkg}/svc.py"
            self._write_source(
                repo_root,
                source_rel,
                "def foo(x):  # noqa\n    pass\n",
            )

            violations = ADR_GUARD.check_python_complexity_gate(repo_root, None)

            self.assertTrue(
                any(
                    "bare" in v.message.lower() and v.path.startswith(source_rel)
                    for v in violations
                ),
                msg=f"Expected bare-noqa violation: {violations}",
            )

    def test_bare_noqa_off_def_line_does_not_violate(self) -> None:
        """A bare `# noqa` inside a function body is unrelated to C901; do not flag."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._full_synthetic_repo(repo_root)
            pkg = ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS[0]
            source_rel = f"{pkg}/svc.py"
            self._write_source(
                repo_root,
                source_rel,
                "def foo(x):\n    return x  # noqa\n",
            )

            violations = ADR_GUARD.check_python_complexity_gate(repo_root, None)

            self.assertFalse(
                any("bare" in v.message.lower() for v in violations),
                msg=f"Did not expect bare-noqa violation on non-def line: {violations}",
            )

    # ----- Cycle-3 finding 2: prefix selectors that cover C901 -----

    def test_prefix_selectors_silently_disabling_c901_violate(self) -> None:
        """Prefix selectors that cover C901 (C, C9, C90, ALL) in suppress fields must fail."""
        cases = (
            (
                'ignore_C_prefix',
                self._pyproject_with_lint_keys(extra_lint_lines='ignore = ["C"]'),
                ("ignore", "C901"),
            ),
            (
                'extend-ignore_ALL',
                self._pyproject_with_lint_keys(extra_lint_lines='extend-ignore = ["ALL"]'),
                ("extend-ignore", "C901"),
            ),
            (
                'per-file-ignores_C90_prefix',
                self._pyproject_with_lint_keys(
                    extra_sections='[tool.ruff.lint.per-file-ignores]\n"**/*.py" = ["C90"]\n'
                ),
                ("per-file-ignores", "C901"),
            ),
        )
        for label, body, expected_substrings in cases:
            with self.subTest(case=label):
                with tempfile.TemporaryDirectory() as tmp:
                    repo_root = Path(tmp)
                    target_pkg = ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS[0]
                    packages = {pkg: self.PYPROJECT_OK for pkg in ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS}
                    packages[target_pkg] = body
                    self._write_packages(repo_root, packages)

                    violations = ADR_GUARD.check_python_complexity_gate(repo_root, None)

                    self.assertTrue(
                        any(all(s in v.message for s in expected_substrings) for v in violations),
                        msg=f"{label}: expected violation containing {expected_substrings}; got {violations}",
                    )

    def test_select_with_c_prefix_satisfies_gate(self) -> None:
        """`select = ["C"]` enables C901 by prefix; the gate accepts it."""
        body = (
            "[project]\n"
            'name = "pkg-a"\n'
            "\n"
            "[tool.ruff.lint]\n"
            'select = ["E", "F", "C"]\n'
            "\n"
            "[tool.ruff.lint.mccabe]\n"
            "max-complexity = 15\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            target_pkg = ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS[0]
            packages = {pkg: self.PYPROJECT_OK for pkg in ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS}
            packages[target_pkg] = body
            self._write_packages(repo_root, packages)

            violations = ADR_GUARD.check_python_complexity_gate(repo_root, None)

            self.assertFalse(
                any("select" in v.message and "C901" in v.message for v in violations),
                msg=f"Did not expect select violation when prefix covers C901: {violations}",
            )

    # ----- Cycle-3 finding 3: targeted mode must consider adr_guard.py relevant -----

    def test_targeted_files_include_adr_guard_py_runs_check(self) -> None:
        """Changes to `scripts/adr_guard/adr_guard.py` (where the constants live) trigger the check."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            target_pkg = ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS[0]
            packages = {pkg: self.PYPROJECT_OK for pkg in ADR_GUARD.PYTHON_COMPLEXITY_GATE_PYPROJECTS}
            # Introduce a config-shape problem so the check has something to report.
            packages[target_pkg] = self.PYPROJECT_MISSING_C901
            self._write_packages(repo_root, packages)

            # Pass only adr_guard.py in --files mode.
            violations = ADR_GUARD.check_python_complexity_gate(
                repo_root, ["scripts/adr_guard/adr_guard.py"]
            )

            self.assertTrue(
                any("C901" in v.message for v in violations),
                msg=f"Expected check to run on adr_guard.py change: {violations}",
            )


class McpOpsTlsStrictTests(unittest.TestCase):
    """Tests for ADR-014-R7: mcp/ops must keep Postgres TLS verification on.

    The check is a defense-in-depth backstop for
    `mcp/ops/lib.js::buildPoolConfig`, which is the single source of
    truth for the pool TLS config. Any other file under `mcp/ops/`
    that re-introduces `rejectUnauthorized: false` (or `0`/`null`)
    must trip this check.
    """

    def _write_mcp_ops_file(self, repo_root: Path, rel: str, contents: str) -> None:
        path = repo_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    def test_flags_rejectunauthorized_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_mcp_ops_file(
                repo_root,
                "mcp/ops/legacy.js",
                "export const cfg = { ssl: { rejectUnauthorized: false } };",
            )

            violations = ADR_GUARD.check_mcp_ops_tls_strict(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-014-R7")
            self.assertEqual(violations[0].path, "mcp/ops/legacy.js")

    def test_flags_rejectunauthorized_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_mcp_ops_file(
                repo_root,
                "mcp/ops/other.js",
                "const tls = { rejectUnauthorized: 0 };",
            )

            violations = ADR_GUARD.check_mcp_ops_tls_strict(repo_root, None)
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-014-R7")

    def test_ignores_comments_about_the_pattern(self) -> None:
        """Doc comments mentioning the pattern must NOT trip the check.

        Both `//` and `/* */` comment forms are stripped before the
        regex runs (codex review #1180 cycle 1 finding 7's selected
        fix). String literals are NOT stripped — see the next test —
        because that erases quoted property keys.
        """
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_mcp_ops_file(
                repo_root,
                "mcp/ops/doc.js",
                "/* previously rejectUnauthorized: false */\n"
                "// rejectUnauthorized: false was the old behavior\n"
                "export const cfg = { ssl: { rejectUnauthorized: true } };",
            )

            violations = ADR_GUARD.check_mcp_ops_tls_strict(repo_root, None)
            self.assertEqual(violations, [])

    def test_flags_quoted_property_key_form(self) -> None:
        """`{ "rejectUnauthorized": false }` and the single-quoted form
        must trip the check (codex review #1180 cycle 1 finding 7)."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_mcp_ops_file(
                repo_root,
                "mcp/ops/dq.js",
                'export const cfg = { ssl: { "rejectUnauthorized": false } };',
            )
            self._write_mcp_ops_file(
                repo_root,
                "mcp/ops/sq.js",
                "export const cfg = { ssl: { 'rejectUnauthorized': false } };",
            )

            violations = ADR_GUARD.check_mcp_ops_tls_strict(repo_root, None)
            flagged = {v.path for v in violations}
            self.assertIn("mcp/ops/dq.js", flagged)
            self.assertIn("mcp/ops/sq.js", flagged)

    def test_real_repo_passes(self) -> None:
        """The shipped mcp/ops tree must not contain a rejectUnauthorized: false anywhere."""
        violations = ADR_GUARD.check_mcp_ops_tls_strict(ADR_GUARD.REPO_ROOT, None)
        self.assertEqual(violations, [], msg=f"Unexpected mcp-ops-tls-strict violations: {violations}")

    def test_files_arg_narrows_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_mcp_ops_file(
                repo_root,
                "mcp/ops/a.js",
                "const cfg = { rejectUnauthorized: false };",
            )
            # files arg lists an unrelated file: no violation surfaced.
            violations = ADR_GUARD.check_mcp_ops_tls_strict(repo_root, ["mcp/ops/b.js"])
            self.assertEqual(violations, [])

    def test_check_registered_at_ci_and_fast_levels(self) -> None:
        self.assertIn("mcp-ops-tls-strict", ADR_GUARD.CHECKS)
        self.assertIn("mcp-ops-tls-strict", ADR_GUARD.CHECK_LEVELS["ci"])
        self.assertIn("mcp-ops-tls-strict", ADR_GUARD.CHECK_LEVELS["fast"])


class BoundaryMockPolicyTests(unittest.TestCase):
    """Tests for ADR-019-R1: new tests mock boundaries, not internal topology."""

    BASELINE_REL = "scripts/adr_guard/boundary_mock_baseline.json"

    def _write_file(self, repo_root: Path, rel: str, text: str = "") -> None:
        path = repo_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _write_first_party_module(self, repo_root: Path) -> None:
        self._write_file(repo_root, "cms/__init__.py")
        self._write_file(repo_root, "cms/services.py", "def create_range():\n    return None\n")

    def _write_baseline(self, repo_root: Path, records: list[dict]) -> None:
        self._write_file(
            repo_root,
            self.BASELINE_REL,
            json.dumps(
                {
                    "version": 1,
                    "allowed_internal_patch_counts": records,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )

    def test_flags_first_party_internal_patch_not_in_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_first_party_module(repo_root)
            self._write_baseline(repo_root, [])
            self._write_file(
                repo_root,
                "tests/test_ranges.py",
                "from unittest.mock import patch\n\n"
                "def test_range_creation():\n"
                "    with patch('cms.services.create_range'):\n"
                "        pass\n",
            )

            violations = ADR_GUARD.check_boundary_mock_policy(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-019-R1")
            self.assertIn("cms.services.create_range", violations[0].message)

    def test_allows_existing_internal_patch_count_from_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_first_party_module(repo_root)
            self._write_baseline(
                repo_root,
                [
                    {
                        "path": "tests/test_ranges.py",
                        "target": "cms.services.create_range",
                        "count": 1,
                    }
                ],
            )
            self._write_file(
                repo_root,
                "tests/test_ranges.py",
                "from unittest.mock import patch\n\n"
                "def test_range_creation():\n"
                "    with patch('cms.services.create_range'):\n"
                "        pass\n",
            )

            violations = ADR_GUARD.check_boundary_mock_policy(repo_root, None)

            self.assertEqual(violations, [])

    def test_flags_internal_patch_count_growth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_first_party_module(repo_root)
            self._write_baseline(
                repo_root,
                [
                    {
                        "path": "tests/test_ranges.py",
                        "target": "cms.services.create_range",
                        "count": 1,
                    }
                ],
            )
            self._write_file(
                repo_root,
                "tests/test_ranges.py",
                "from unittest.mock import patch\n\n"
                "def test_one():\n"
                "    with patch('cms.services.create_range'):\n"
                "        pass\n\n"
                "def test_two():\n"
                "    with patch('cms.services.create_range'):\n"
                "        pass\n",
            )

            violations = ADR_GUARD.check_boundary_mock_policy(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertIn("allowed 1", violations[0].message)
            self.assertIn("found 2", violations[0].message)

    def test_flags_baseline_count_growth_against_git_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_first_party_module(repo_root)
            self._write_baseline(
                repo_root,
                [
                    {
                        "path": "tests/test_ranges.py",
                        "target": "cms.services.create_range",
                        "count": 1,
                    }
                ],
            )
            self._write_file(
                repo_root,
                "tests/test_ranges.py",
                "from unittest.mock import patch\n\n"
                "def test_range_creation():\n"
                "    with patch('cms.services.create_range'):\n"
                "        pass\n",
            )
            self._write_baseline(
                repo_root,
                [
                    {
                        "path": "tests/test_ranges.py",
                        "target": "cms.services.create_range",
                        "count": 2,
                    }
                ],
            )

            reference_baseline = Counter(
                {("tests/test_ranges.py", "cms.services.create_range"): 1}
            )
            with patch.object(
                ADR_GUARD,
                "_load_boundary_mock_reference_baseline",
                return_value=(reference_baseline, None),
            ):
                violations = ADR_GUARD.check_boundary_mock_policy(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].path, self.BASELINE_REL)
            self.assertIn("grew from 1 to 2", violations[0].message)

    def test_flags_new_baseline_entry_against_git_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_first_party_module(repo_root)
            self._write_file(repo_root, "tests/test_ranges.py", "def test_range_creation():\n    pass\n")
            self._write_baseline(
                repo_root,
                [
                    {
                        "path": "tests/test_ranges.py",
                        "target": "cms.services.create_range",
                        "count": 1,
                    }
                ],
            )

            with patch.object(
                ADR_GUARD,
                "_load_boundary_mock_reference_baseline",
                return_value=(Counter(), None),
            ):
                violations = ADR_GUARD.check_boundary_mock_policy(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].path, self.BASELINE_REL)
            self.assertIn("grew from 0 to 1", violations[0].message)

    def test_allows_process_and_cloud_boundary_patches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_first_party_module(repo_root)
            self._write_file(repo_root, "deploy.py", "import subprocess\n")
            self._write_baseline(repo_root, [])
            self._write_file(
                repo_root,
                "tests/test_boundaries.py",
                "from unittest.mock import patch\n\n"
                "def test_boundaries(mocker):\n"
                "    with patch('subprocess.Popen'):\n"
                "        pass\n"
                "    mocker.patch('boto3.Session')\n"
                "    mocker.patch('deploy.subprocess.run')\n",
            )

            violations = ADR_GUARD.check_boundary_mock_policy(repo_root, None)

            self.assertEqual(violations, [])

    def test_flags_resolvable_patch_object_internal_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_first_party_module(repo_root)
            self._write_baseline(repo_root, [])
            self._write_file(
                repo_root,
                "tests/test_ranges.py",
                "from cms import services\n"
                "from unittest.mock import patch\n\n"
                "def test_range_creation():\n"
                "    with patch.object(services, 'create_range'):\n"
                "        pass\n",
            )

            violations = ADR_GUARD.check_boundary_mock_policy(repo_root, None)

            self.assertEqual(len(violations), 1)
            self.assertIn("cms.services.create_range", violations[0].message)

    def test_targeted_mode_skips_unrelated_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_first_party_module(repo_root)
            self._write_baseline(repo_root, [])
            self._write_file(
                repo_root,
                "tests/test_ranges.py",
                "from unittest.mock import patch\n\n"
                "def test_range_creation():\n"
                "    with patch('cms.services.create_range'):\n"
                "        pass\n",
            )

            violations = ADR_GUARD.check_boundary_mock_policy(repo_root, ["docs/unrelated.md"])

            self.assertEqual(violations, [])

    def test_targeted_mode_baseline_change_triggers_full_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_first_party_module(repo_root)
            self._write_baseline(repo_root, [])
            self._write_file(
                repo_root,
                "tests/test_ranges.py",
                "from unittest.mock import patch\n\n"
                "def test_range_creation():\n"
                "    with patch('cms.services.create_range'):\n"
                "        pass\n",
            )

            violations = ADR_GUARD.check_boundary_mock_policy(repo_root, [self.BASELINE_REL])

            self.assertEqual(len(violations), 1)
            self.assertIn("cms.services.create_range", violations[0].message)

    def test_targeted_mode_guard_change_triggers_full_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_first_party_module(repo_root)
            self._write_baseline(repo_root, [])
            self._write_file(
                repo_root,
                "tests/test_ranges.py",
                "from unittest.mock import patch\n\n"
                "def test_range_creation():\n"
                "    with patch('cms.services.create_range'):\n"
                "        pass\n",
            )

            violations = ADR_GUARD.check_boundary_mock_policy(repo_root, ["scripts/adr_guard/adr_guard.py"])

            self.assertEqual(len(violations), 1)
            self.assertIn("cms.services.create_range", violations[0].message)

    def test_real_repo_passes(self) -> None:
        violations = ADR_GUARD.check_boundary_mock_policy(ADR_GUARD.REPO_ROOT, None)
        self.assertEqual(violations, [], msg=f"Unexpected boundary-mock-policy violations: {violations}")

    def test_check_registered_at_ci_and_fast_levels(self) -> None:
        self.assertIn("boundary-mock-policy", ADR_GUARD.CHECKS)
        self.assertIn("boundary-mock-policy", ADR_GUARD.CHECK_LEVELS["ci"])
        self.assertIn("boundary-mock-policy", ADR_GUARD.CHECK_LEVELS["fast"])


class NoTrackedGeneratedArtifactsTests(unittest.TestCase):
    """Tests for ADR-004-R8: forbid tracked generated/sensitive artifacts.

    Covers Terraform plan outputs under terraform environment trees and
    bootstrap license / authcode material under temp/bootstrap/. The
    blocked path/name set is centralized in the check.
    """

    def _make_terraform_env(self, repo_root: Path, rel: str) -> Path:
        env_dir = repo_root / rel
        env_dir.mkdir(parents=True)
        return env_dir

    def test_flags_tracked_tfplan_under_aws_environments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            env_dir = self._make_terraform_env(repo_root, "platform/terraform/environments/dev/portal")
            (env_dir / "tfplan").write_bytes(b"\x00binary plan output")
            (env_dir / "plan.out").write_text("plan output", encoding="utf-8")
            # A clearly-unrelated file in the same tree must NOT be flagged.
            (env_dir / "main.tf").write_text("# terraform", encoding="utf-8")

            violations = ADR_GUARD.check_no_tracked_generated_artifacts(repo_root, None)

            flagged_paths = {v.path for v in violations}
            self.assertIn("platform/terraform/environments/dev/portal/tfplan", flagged_paths)
            self.assertIn("platform/terraform/environments/dev/portal/plan.out", flagged_paths)
            self.assertNotIn("platform/terraform/environments/dev/portal/main.tf", flagged_paths)
            for v in violations:
                self.assertEqual(v.rule_id, "ADR-004-R8")
                # Per preflight: messages must NOT echo file content,
                # only the repo-relative path + remediation.
                self.assertNotIn("binary plan output", v.message)

    def test_flags_tracked_tfplan_under_gcp_environments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            env_dir = self._make_terraform_env(repo_root, "platform/terraform/gcp/environments/dev")
            (env_dir / "tfplan.binary").write_text("binary", encoding="utf-8")
            (env_dir / "my.tfplan").write_text("text", encoding="utf-8")

            violations = ADR_GUARD.check_no_tracked_generated_artifacts(repo_root, None)

            flagged_paths = {v.path for v in violations}
            self.assertIn("platform/terraform/gcp/environments/dev/tfplan.binary", flagged_paths)
            self.assertIn("platform/terraform/gcp/environments/dev/my.tfplan", flagged_paths)

    def test_flags_bootstrap_license_and_authcode_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            license_dir = repo_root / "temp" / "bootstrap" / "license"
            license_dir.mkdir(parents=True)
            (license_dir / "authcodes").write_text("XYZ-123", encoding="utf-8")

            violations = ADR_GUARD.check_no_tracked_generated_artifacts(repo_root, None)

            flagged_paths = {v.path for v in violations}
            self.assertIn("temp/bootstrap/license/authcodes", flagged_paths)
            for v in violations:
                self.assertEqual(v.rule_id, "ADR-004-R8")
                self.assertNotIn("XYZ-123", v.message)

    def test_clean_tree_emits_no_violations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            env_dir = self._make_terraform_env(repo_root, "platform/terraform/environments/dev")
            (env_dir / "main.tf").write_text("# terraform", encoding="utf-8")
            (env_dir / "terraform.tfvars").write_text("# vars", encoding="utf-8")

            violations = ADR_GUARD.check_no_tracked_generated_artifacts(repo_root, None)

            self.assertEqual(violations, [])

    def test_files_arg_narrows_scope(self) -> None:
        """When the --files arg is given, only those paths are inspected."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            env_dir = self._make_terraform_env(repo_root, "platform/terraform/environments/dev")
            (env_dir / "tfplan").write_text("plan", encoding="utf-8")
            license_dir = repo_root / "temp" / "bootstrap" / "license"
            license_dir.mkdir(parents=True)
            (license_dir / "authcodes").write_text("X", encoding="utf-8")

            # files arg lists only the terraform file
            files_violations = ADR_GUARD.check_no_tracked_generated_artifacts(
                repo_root, ["platform/terraform/environments/dev/tfplan"]
            )
            self.assertEqual(
                {v.path for v in files_violations},
                {"platform/terraform/environments/dev/tfplan"},
            )

            # files arg lists an unrelated path: no violations even though
            # blocked artifacts exist on disk
            unrelated = ADR_GUARD.check_no_tracked_generated_artifacts(
                repo_root, ["platform/terraform/environments/dev/main.tf"]
            )
            self.assertEqual(unrelated, [])

    def test_check_registered_at_ci_and_fast_levels(self) -> None:
        """The new check is part of the CI level so adr_guard --all --level ci catches it."""
        self.assertIn("no-tracked-generated-artifacts", ADR_GUARD.CHECKS)
        self.assertIn("no-tracked-generated-artifacts", ADR_GUARD.CHECK_LEVELS["ci"])
        self.assertIn("no-tracked-generated-artifacts", ADR_GUARD.CHECK_LEVELS["fast"])


class NoPopulatedSecretEnvFilesTests(unittest.TestCase):
    """Tests for ADR-004-R9: forbid populated tracked ``*-secrets.env`` files.

    The check guards against re-introducing the failure mode resolved by
    PR #1207, where ``platform-runtime-secrets.env`` carried plaintext
    runtime credentials. Synthetic placeholders are allowed so the
    Kustomize overlay still renders for static validation, but real
    values must be supplied at deploy time (GCP Secret Manager,
    deploy-time Kubernetes Secret, or a gitignored local env file).

    Violation messages must name only the path and variable name,
    never the rejected value.
    """

    SECRETS_ENV_REL = (
        "platform/k8s/gcp/overlays/gcp-dev/platform-runtime-secrets.env"
    )

    def _make_overlay(self, repo_root: Path, rel: str) -> Path:
        d = repo_root / rel
        d.mkdir(parents=True)
        return d

    def test_passes_when_file_is_comments_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            overlay = self._make_overlay(
                repo_root, "platform/k8s/gcp/overlays/gcp-dev"
            )
            (overlay / "platform-runtime-secrets.env").write_text(
                "# header comment\n#\n# another comment line\n\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_populated_secret_env_files(
                repo_root, None
            )

            self.assertEqual(violations, [])

    def test_passes_with_empty_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            overlay = self._make_overlay(
                repo_root, "platform/k8s/gcp/overlays/gcp-dev"
            )
            (overlay / "platform-runtime-secrets.env").write_text(
                "DB_PASSWORD=\nAPP_TOKEN=\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_populated_secret_env_files(
                repo_root, None
            )

            self.assertEqual(violations, [])

    def test_passes_with_synthetic_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            overlay = self._make_overlay(
                repo_root, "platform/k8s/gcp/overlays/gcp-dev"
            )
            (overlay / "platform-runtime-secrets.env").write_text(
                "DB_PASSWORD=REPLACE_AT_DEPLOY\n"
                "API_TOKEN=CHANGE_ME\n"
                "SHARED_KEY=PLACEHOLDER\n"
                "DEMO_VALUE=EXAMPLE\n"
                "BRACKETED=<replace-at-deploy>\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_populated_secret_env_files(
                repo_root, None
            )

            self.assertEqual(violations, [])

    def test_flags_populated_assignment_without_echoing_value(self) -> None:
        # Use a distinctive value so the assertion that violation
        # messages do NOT contain the value is unambiguous.
        sentinel_value = "ActualSensitiveValue123XYZ"
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            overlay = self._make_overlay(
                repo_root, "platform/k8s/gcp/overlays/gcp-dev"
            )
            (overlay / "platform-runtime-secrets.env").write_text(
                f"DB_PASSWORD={sentinel_value}\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_populated_secret_env_files(
                repo_root, None
            )

            self.assertEqual(len(violations), 1)
            v = violations[0]
            self.assertEqual(v.rule_id, "ADR-004-R9")
            self.assertEqual(v.path, self.SECRETS_ENV_REL)
            self.assertIn("DB_PASSWORD", v.message)
            self.assertNotIn(sentinel_value, v.message)

    def test_skips_files_outside_path_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            other = repo_root / "tests" / "fixtures"
            other.mkdir(parents=True)
            (other / "platform-runtime-secrets.env").write_text(
                "DB_PASSWORD=SomeRealValue\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_populated_secret_env_files(
                repo_root, None
            )

            self.assertEqual(violations, [])

    def test_only_scans_secrets_env_basename_pattern(self) -> None:
        # Non-secrets env files in the same overlay must NOT be scanned.
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            overlay = self._make_overlay(
                repo_root, "platform/k8s/gcp/overlays/gcp-dev"
            )
            (overlay / "platform-runtime.env").write_text(
                "DB_HOST=postgresql.example.com\nDB_PORT=5432\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_populated_secret_env_files(
                repo_root, None
            )

            self.assertEqual(violations, [])

    def test_files_arg_narrows_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            dev = self._make_overlay(
                repo_root, "platform/k8s/gcp/overlays/gcp-dev"
            )
            (dev / "platform-runtime-secrets.env").write_text(
                "DB_PASSWORD=DevRealVal\n",
                encoding="utf-8",
            )
            prod = self._make_overlay(
                repo_root, "platform/k8s/gcp/overlays/gcp-prod"
            )
            (prod / "platform-runtime-secrets.env").write_text(
                "DB_PASSWORD=ProdRealVal\n",
                encoding="utf-8",
            )

            scoped = ADR_GUARD.check_no_populated_secret_env_files(
                repo_root,
                [
                    "platform/k8s/gcp/overlays/gcp-dev/"
                    "platform-runtime-secrets.env"
                ],
            )

            self.assertEqual(len(scoped), 1)
            self.assertEqual(
                scoped[0].path,
                "platform/k8s/gcp/overlays/gcp-dev/"
                "platform-runtime-secrets.env",
            )

    def test_flags_only_violating_lines_not_placeholder_siblings(self) -> None:
        # Mixed-content file: placeholders are OK, populated lines flag.
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            overlay = self._make_overlay(
                repo_root, "platform/k8s/gcp/overlays/gcp-dev"
            )
            (overlay / "platform-runtime-secrets.env").write_text(
                "# header\n"
                "DB_PASSWORD=REPLACE_AT_DEPLOY\n"
                "API_TOKEN=NotASynthetic\n"
                "APP_KEY=\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_populated_secret_env_files(
                repo_root, None
            )

            flagged_vars = [v.message for v in violations]
            self.assertEqual(len(violations), 1)
            self.assertIn("API_TOKEN", flagged_vars[0])

    def test_flags_value_starting_with_hash(self) -> None:
        # Bypass regression: `KEY=#actualsecret` must NOT be treated as
        # an empty/commented assignment. Kustomize's env_file loader
        # (Docker-compat) only honors `#` as a comment when it is the
        # first non-whitespace character on a line; mid-line `#` is
        # part of the value. Treating it otherwise would let a
        # committer hide plaintext credentials behind an inline-
        # comment shape. Codex review cycle 1 caught this.
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            overlay = self._make_overlay(
                repo_root, "platform/k8s/gcp/overlays/gcp-dev"
            )
            (overlay / "platform-runtime-secrets.env").write_text(
                "DB_PASSWORD=#actualsecret\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_populated_secret_env_files(
                repo_root, None
            )

            self.assertEqual(len(violations), 1)
            v = violations[0]
            self.assertEqual(v.rule_id, "ADR-004-R9")
            self.assertIn("DB_PASSWORD", v.message)
            self.assertNotIn("actualsecret", v.message)

    def test_flags_value_with_inline_hash_after_placeholder(self) -> None:
        # Bypass regression: `KEY=REPLACE_AT_DEPLOY#real` must be
        # flagged. Inline `#` is part of the value, so the RHS is not
        # exactly one of the approved placeholders.
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            overlay = self._make_overlay(
                repo_root, "platform/k8s/gcp/overlays/gcp-dev"
            )
            (overlay / "platform-runtime-secrets.env").write_text(
                "API_TOKEN=REPLACE_AT_DEPLOY#realtoken\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_populated_secret_env_files(
                repo_root, None
            )

            self.assertEqual(len(violations), 1)
            v = violations[0]
            self.assertIn("API_TOKEN", v.message)
            self.assertNotIn("realtoken", v.message)

    def test_flags_value_with_inline_hash_and_whitespace(self) -> None:
        # Bypass regression: `KEY=actual # note` is also flagged.
        # Treating ` # note` as a comment would allow committed values
        # of the form `KEY=actual # note` to slip through.
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            overlay = self._make_overlay(
                repo_root, "platform/k8s/gcp/overlays/gcp-dev"
            )
            (overlay / "platform-runtime-secrets.env").write_text(
                "SHARED_KEY=actualvalue # not a comment\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_populated_secret_env_files(
                repo_root, None
            )

            self.assertEqual(len(violations), 1)
            self.assertIn("SHARED_KEY", violations[0].message)
            self.assertNotIn("actualvalue", violations[0].message)

    def test_flags_non_identifier_key_with_real_value(self) -> None:
        # Bypass regression (codex review cycle 2): a key with a dot
        # (`db.password=...`) is a valid Kubernetes Secret data key
        # shape. The earlier strict-identifier regex silently skipped
        # such lines; the parser now splits on the first `=` and
        # validates the RHS regardless of key shape.
        sentinel = "DotKeyRealValueZ9"
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            overlay = self._make_overlay(
                repo_root, "platform/k8s/gcp/overlays/gcp-dev"
            )
            (overlay / "platform-runtime-secrets.env").write_text(
                f"db.password={sentinel}\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_populated_secret_env_files(
                repo_root, None
            )

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-004-R9")
            self.assertIn("db.password", violations[0].message)
            self.assertNotIn(sentinel, violations[0].message)

    def test_flags_hyphenated_key_with_real_value(self) -> None:
        # Hyphenated keys are also valid Kubernetes Secret data keys.
        sentinel = "HyphenKeyRealValueQ7"
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            overlay = self._make_overlay(
                repo_root, "platform/k8s/gcp/overlays/gcp-dev"
            )
            (overlay / "platform-runtime-secrets.env").write_text(
                f"api-token={sentinel}\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_populated_secret_env_files(
                repo_root, None
            )

            self.assertEqual(len(violations), 1)
            self.assertIn("api-token", violations[0].message)
            self.assertNotIn(sentinel, violations[0].message)

    def test_flags_export_prefixed_assignment(self) -> None:
        # `export KEY=value` is a shell-style assignment that the
        # strict-identifier regex would skip. The parser now reports
        # the full LHS (`export KEY`) so the bypass is closed.
        sentinel = "ExportShellValueK3"
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            overlay = self._make_overlay(
                repo_root, "platform/k8s/gcp/overlays/gcp-dev"
            )
            (overlay / "platform-runtime-secrets.env").write_text(
                f"export DB_PASSWORD={sentinel}\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_populated_secret_env_files(
                repo_root, None
            )

            self.assertEqual(len(violations), 1)
            self.assertIn("export DB_PASSWORD", violations[0].message)
            self.assertNotIn(sentinel, violations[0].message)

    def test_flags_non_assignment_line(self) -> None:
        # A non-comment, non-blank line that does not contain `=` is a
        # malformed shape. Flag it so a real value smuggled in as YAML
        # / free text cannot slip past the value check.
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            overlay = self._make_overlay(
                repo_root, "platform/k8s/gcp/overlays/gcp-dev"
            )
            (overlay / "platform-runtime-secrets.env").write_text(
                "some random secret-bearing text without an equals sign\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_populated_secret_env_files(
                repo_root, None
            )

            self.assertEqual(len(violations), 1)
            self.assertIn("not a comment", violations[0].message)
            self.assertNotIn("secret-bearing", violations[0].message)

    def test_passes_non_identifier_key_with_placeholder(self) -> None:
        # The placeholder check applies regardless of key shape, so a
        # valid Kubernetes Secret data key with a placeholder value
        # still passes (consistency: the rule is about values, not
        # key shapes).
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            overlay = self._make_overlay(
                repo_root, "platform/k8s/gcp/overlays/gcp-dev"
            )
            (overlay / "platform-runtime-secrets.env").write_text(
                "db.password=REPLACE_AT_DEPLOY\n"
                "api-token=<replace-at-deploy>\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_populated_secret_env_files(
                repo_root, None
            )

            self.assertEqual(violations, [])

    def test_flags_arbitrary_bracketed_value(self) -> None:
        # Bypass regression (codex review cycle 3 security finding):
        # the placeholder allowlist must be a fixed set, NOT a `<...>`
        # pattern. A pattern would accept a real credential wrapped in
        # angle brackets (e.g. `DB_PASSWORD=<attacker-known-password>`)
        # and the deployment would consume those bracketed bytes as
        # the literal Secret value.
        sentinel = "AttackerKnownValueB7"
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            overlay = self._make_overlay(
                repo_root, "platform/k8s/gcp/overlays/gcp-dev"
            )
            (overlay / "platform-runtime-secrets.env").write_text(
                f"DB_PASSWORD=<{sentinel}>\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_populated_secret_env_files(
                repo_root, None
            )

            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule_id, "ADR-004-R9")
            self.assertIn("DB_PASSWORD", violations[0].message)
            self.assertNotIn(sentinel, violations[0].message)

    def test_passes_only_explicit_bracketed_allowlist_entries(self) -> None:
        # The explicit bracketed forms in the allowlist still pass
        # (consistency: the allowlist is fixed but it does include the
        # common bracketed example tokens).
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            overlay = self._make_overlay(
                repo_root, "platform/k8s/gcp/overlays/gcp-dev"
            )
            (overlay / "platform-runtime-secrets.env").write_text(
                "A=<replace-at-deploy>\n"
                "B=<placeholder>\n"
                "C=<PLACEHOLDER>\n"
                "D=<example>\n"
                "E=<change-me>\n",
                encoding="utf-8",
            )

            violations = ADR_GUARD.check_no_populated_secret_env_files(
                repo_root, None
            )

            self.assertEqual(violations, [])

    def test_check_registered_at_ci_and_fast_levels(self) -> None:
        self.assertIn("no-populated-secret-env-files", ADR_GUARD.CHECKS)
        self.assertIn(
            "no-populated-secret-env-files",
            ADR_GUARD.CHECK_LEVELS["ci"],
        )
        self.assertIn(
            "no-populated-secret-env-files",
            ADR_GUARD.CHECK_LEVELS["fast"],
        )


class DeployVerificationFailLoudTests(unittest.TestCase):
    """Tests for the deploy-verification fail-loud guardrail (ADR-003-R3).

    The Guacamole stabilization timeout in `_shifter-platform.yml` and the
    engine ECS task-family check in `_shifter-engine.yml` must fail the deploy
    when verification fails, instead of warning and exiting 0. The engine skip
    is allowed only behind the explicit `first_deploy` bootstrap input.
    """

    _PLATFORM_PROLOGUE = (
        "name: Platform\n"
        "jobs:\n"
        "  apply:\n"
        "    runs-on: self-hosted\n"
        "    steps:\n"
        "      - run: terraform apply -auto-approve\n"
        "      - name: Wait for Guacamole ECS services to stabilize\n"
        "        run: |\n"
        "          CLUSTER_NAME=\"${ENV}-portal-guacamole\"\n"
        "          for SVC in a b; do\n"
        "            echo \"$SVC\"\n"
        "          done\n"
        "          ATTEMPTS=0\n"
        "          while [ $ATTEMPTS -lt 40 ]; do\n"
        "            if [ \"$S\" = \"COMPLETED\" ]; then exit 0; fi\n"
        "            ATTEMPTS=$((ATTEMPTS + 1))\n"
        "            sleep 30\n"
        "          done\n"
    )
    _PLATFORM_EPILOGUE = "      - name: Build\n        run: echo build\n"

    _ENGINE_PROLOGUE = (
        "name: Shifter Engine\n"
        "on:\n"
        "  workflow_call:\n"
        "    inputs:\n"
        "      first_deploy:\n"
        "        type: boolean\n"
        "        default: false\n"
        "jobs:\n"
        "  deploy:\n"
        "    runs-on: self-hosted\n"
        "    env:\n"
        "      TASK_FAMILY: dev-portal-pulumi-provisioner\n"
        "    steps:\n"
        "      - name: Update ECS task definition\n"
        "        env:\n"
        "          FIRST_DEPLOY: ${{ inputs.first_deploy }}\n"
        "        run: |\n"
        "          TASK_DEF=$(aws ecs describe-task-definition "
        "--task-definition \"${TASK_FAMILY}\" --query 'taskDefinition' 2>/dev/null) || {\n"
    )

    def _write_platform(self, repo_root: Path, timeout_tail: str) -> None:
        workflow_dir = repo_root / ".github" / "workflows"
        workflow_dir.mkdir(parents=True, exist_ok=True)
        (workflow_dir / "_shifter-platform.yml").write_text(
            self._PLATFORM_PROLOGUE + timeout_tail + self._PLATFORM_EPILOGUE,
            encoding="utf-8",
        )

    def _write_engine(self, repo_root: Path, failure_branch: str) -> None:
        workflow_dir = repo_root / ".github" / "workflows"
        workflow_dir.mkdir(parents=True, exist_ok=True)
        (workflow_dir / "_shifter-engine.yml").write_text(
            self._ENGINE_PROLOGUE + failure_branch,
            encoding="utf-8",
        )

    def test_platform_timeout_warning_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_platform(
                repo_root,
                '          echo "::warning::Guacamole services did not stabilize'
                ' — continuing (services may still be starting)"\n',
            )
            self._write_engine(
                repo_root,
                '            if [ "${FIRST_DEPLOY}" = "true" ]; then echo skip; exit 0; fi\n'
                '            echo "::error::missing"; exit 1\n'
                "          }\n",
            )

            violations = ADR_GUARD.check_deploy_verification_fail_loud(repo_root, None)

            self.assertTrue(violations)
            self.assertEqual(violations[0].rule_id, "ADR-003-R3")
            self.assertTrue(
                any(".github/workflows/_shifter-platform.yml" in v.path for v in violations)
            )

    def test_platform_timeout_exit_1_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_platform(
                repo_root,
                '          echo "::error::Guacamole services did not stabilize"\n'
                "          exit 1\n",
            )
            self._write_engine(
                repo_root,
                '            if [ "${FIRST_DEPLOY}" = "true" ]; then echo skip; exit 0; fi\n'
                '            echo "::error::missing"; exit 1\n'
                "          }\n",
            )

            violations = ADR_GUARD.check_deploy_verification_fail_loud(repo_root, None)

            self.assertEqual(violations, [], msg=f"Unexpected violations: {violations}")

    def test_engine_unconditional_skip_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_platform(
                repo_root,
                '          echo "::error::timeout"\n          exit 1\n',
            )
            # Unconditional warn + exit 0, no first_deploy gate, no exit 1.
            engine = (
                "name: Shifter Engine\n"
                "jobs:\n"
                "  deploy:\n"
                "    runs-on: self-hosted\n"
                "    env:\n"
                "      TASK_FAMILY: dev-portal-pulumi-provisioner\n"
                "    steps:\n"
                "      - name: Update ECS task definition\n"
                "        run: |\n"
                "          TASK_DEF=$(aws ecs describe-task-definition "
                "--task-definition \"${TASK_FAMILY}\" 2>/dev/null) || {\n"
                '            echo "::warning::does not exist yet. Skipping deploy."\n'
                "            exit 0\n"
                "          }\n"
            )
            (repo_root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
            (repo_root / ".github" / "workflows" / "_shifter-engine.yml").write_text(
                engine, encoding="utf-8"
            )

            violations = ADR_GUARD.check_deploy_verification_fail_loud(repo_root, None)

            self.assertTrue(violations)
            self.assertTrue(
                any(".github/workflows/_shifter-engine.yml" in v.path for v in violations)
            )

    def test_engine_gated_fail_closed_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_platform(
                repo_root,
                '          echo "::error::timeout"\n          exit 1\n',
            )
            self._write_engine(
                repo_root,
                '            if [ "${FIRST_DEPLOY}" = "true" ]; then\n'
                '              echo "::warning::bootstrap skip"; exit 0\n'
                "            fi\n"
                '            echo "::error::task family ${TASK_FAMILY} does not exist"\n'
                "            exit 1\n"
                "          }\n",
            )

            violations = ADR_GUARD.check_deploy_verification_fail_loud(repo_root, None)

            self.assertEqual(violations, [], msg=f"Unexpected violations: {violations}")

    def test_missing_workflow_files_are_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            (repo_root / ".github" / "workflows").mkdir(parents=True)

            violations = ADR_GUARD.check_deploy_verification_fail_loud(repo_root, None)

            flagged = {v.path for v in violations}
            self.assertIn(".github/workflows/_shifter-platform.yml", flagged)
            self.assertIn(".github/workflows/_shifter-engine.yml", flagged)

    def _write_noncompliant_pair(self, repo_root: Path) -> None:
        """Write workflows that both violate the rule (warn-and-continue +
        unconditional skip), so any run of the check yields violations."""
        self._write_platform(
            repo_root,
            '          echo "::warning::Guacamole services did not stabilize'
            ' — continuing (services may still be starting)"\n',
        )
        engine = (
            "name: Shifter Engine\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: self-hosted\n"
            "    env:\n"
            "      TASK_FAMILY: dev-portal-pulumi-provisioner\n"
            "    steps:\n"
            "      - name: Update ECS task definition\n"
            "        run: |\n"
            "          TASK_DEF=$(aws ecs describe-task-definition "
            "--task-definition \"${TASK_FAMILY}\" 2>/dev/null) || {\n"
            '            echo "::warning::does not exist yet. Skipping deploy."\n'
            "            exit 0\n"
            "          }\n"
        )
        (repo_root / ".github" / "workflows" / "_shifter-engine.yml").write_text(
            engine, encoding="utf-8"
        )

    def test_targeted_mode_skips_unrelated_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_noncompliant_pair(repo_root)

            # Even with non-compliant workflows on disk, a changed-file set that
            # touches none of the relevant paths must skip the check entirely.
            violations = ADR_GUARD.check_deploy_verification_fail_loud(
                repo_root, ["shifter/shifter_platform/config/settings.py"]
            )

            self.assertEqual(violations, [], msg=f"Unexpected violations: {violations}")

    def test_targeted_mode_runs_for_relevant_workflow_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            self._write_noncompliant_pair(repo_root)

            # A changed-file set that includes a relevant workflow must run the
            # check and surface the non-compliant workflows' violations.
            violations = ADR_GUARD.check_deploy_verification_fail_loud(
                repo_root, [".github/workflows/_shifter-engine.yml"]
            )

            self.assertTrue(violations)
            self.assertTrue(all(v.rule_id == "ADR-003-R3" for v in violations))

    def test_clean_real_repo_passes(self) -> None:
        violations = ADR_GUARD.check_deploy_verification_fail_loud(ADR_GUARD.REPO_ROOT, None)
        self.assertEqual(violations, [], msg=f"Unexpected violations: {violations}")

    def test_check_registered_at_ci_and_fast_levels(self) -> None:
        self.assertIn("deploy-verification-fail-loud", ADR_GUARD.CHECKS)
        self.assertIn("deploy-verification-fail-loud", ADR_GUARD.CHECK_LEVELS["ci"])
        self.assertIn("deploy-verification-fail-loud", ADR_GUARD.CHECK_LEVELS["fast"])


if __name__ == "__main__":
    unittest.main()
