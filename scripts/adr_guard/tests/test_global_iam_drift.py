"""ADR-004-R26: the out-of-band global/iam stack has a CI drift-check workflow.

``platform/terraform/global/iam`` is applied out-of-band (not by the deploy
pipeline), so a merged ``github-oidc.tf`` change can go un-applied and the live
deploy role falls behind - the recurring "new resource -> next deploy 403s"
churn (issue #247). The ``global-iam-drift-check`` guard pins the drift-check
workflow's *contract*, not disconnected tokens, so it cannot be silently
weakened. These tests prove every bypass the pre-push review named produces a
violation: PR-capable or extra events, a missing/wrong branch allowlist, a
missing global/iam path filter, an echoed/commented plan, a swallowed exit
status, continue-on-error, and a cross-job scope match. One positive test
asserts the real committed workflow satisfies the guard.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "adr_guard.py"
SPEC = importlib.util.spec_from_file_location("adr_guard", MODULE_PATH)
ADR_GUARD = importlib.util.module_from_spec(SPEC)
sys.modules["adr_guard"] = ADR_GUARD
SPEC.loader.exec_module(ADR_GUARD)

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_REL = ".github/workflows/iam-drift-check.yml"

_ON_VALID = """\
on:
  push:
    branches: [dev, main]
    paths:
      - 'platform/terraform/global/iam/**'
"""

_JOBS_VALID = """\
jobs:
  drift:
    runs-on: self-hosted
    defaults:
      run:
        working-directory: platform/terraform/global/iam
    steps:
      - run: terraform init -backend-config="$SHIFTER_BACKEND_CONFIG_PATH"
      - name: Terraform plan
        run: terraform plan -detailed-exitcode -no-color -lock-timeout=5m -refresh=false -var-file=dev.tfvars
"""


def _wf(on_block: str = _ON_VALID, jobs_block: str = _JOBS_VALID) -> str:
    return (
        "name: IAM Drift Check\n"
        f"{on_block}"
        "permissions:\n"
        "  id-token: write\n"
        "  contents: read\n"
        f"{jobs_block}"
    )


def _drift_jobs(plan_run: str, working_directory: str = "platform/terraform/global/iam",
                continue_on_error: bool = False, scope_via_defaults: bool = True) -> str:
    defaults = (
        f"    defaults:\n      run:\n        working-directory: {working_directory}\n"
        if scope_via_defaults
        else ""
    )
    coe = "        continue-on-error: true\n" if continue_on_error else ""
    # plan_run may be a single line or a block scalar body.
    if "\n" in plan_run.strip():
        run_block = "        run: |\n" + "".join(
            f"          {line}\n" for line in plan_run.strip().splitlines()
        )
    else:
        run_block = f"        run: {plan_run.strip()}\n"
    return (
        "jobs:\n"
        "  drift:\n"
        "    runs-on: self-hosted\n"
        f"{defaults}"
        "    steps:\n"
        "      - name: Terraform plan\n"
        f"{coe}"
        f"{run_block}"
    )


def _write(root: Path, text: str) -> None:
    path = root / WORKFLOW_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _violations(text: str) -> list:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, text)
        return ADR_GUARD.check_global_iam_drift_check(root, None)


class TestGlobalIamDriftGuard(unittest.TestCase):
    """ADR-004-R26 global-iam-drift-check guard."""

    # --- positive paths ---------------------------------------------------- #
    def test_real_committed_workflow_satisfies_guard(self):
        self.assertEqual(ADR_GUARD.check_global_iam_drift_check(REPO_ROOT, None), [])

    def test_valid_synthetic_workflow_passes(self):
        self.assertEqual(_violations(_wf()), [])

    def test_workflow_dispatch_alongside_push_passes(self):
        on_block = _ON_VALID + "  workflow_dispatch:\n"
        self.assertEqual(_violations(_wf(on_block=on_block)), [])

    def test_scope_via_step_working_directory_passes(self):
        jobs = (
            "jobs:\n"
            "  drift:\n"
            "    runs-on: self-hosted\n"
            "    steps:\n"
            "      - name: Terraform plan\n"
            "        working-directory: platform/terraform/global/iam\n"
            "        run: terraform plan -detailed-exitcode -refresh=false\n"
        )
        self.assertEqual(_violations(_wf(jobs_block=jobs)), [])

    # --- missing / unparseable -------------------------------------------- #
    def test_missing_workflow_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            violations = ADR_GUARD.check_global_iam_drift_check(Path(tmp), None)
            self.assertTrue(violations)
            self.assertTrue(all(v.rule_id == "ADR-004-R26" for v in violations))

    # --- trigger allowlist ------------------------------------------------- #
    def test_pull_request_trigger_is_flagged(self):
        on_block = _ON_VALID + "  pull_request:\n    branches: [dev]\n"
        violations = _violations(_wf(on_block=on_block))
        self.assertTrue(any("pull_request" in v.message for v in violations))

    def test_pull_request_target_trigger_is_flagged(self):
        on_block = _ON_VALID + "  pull_request_target:\n    branches: [dev]\n"
        violations = _violations(_wf(on_block=on_block))
        self.assertTrue(any("pull_request_target" in v.message for v in violations))

    def test_schedule_trigger_is_flagged(self):
        on_block = _ON_VALID + "  schedule:\n    - cron: '0 6 * * *'\n"
        violations = _violations(_wf(on_block=on_block))
        self.assertTrue(any("schedule" in v.message for v in violations))

    def test_missing_push_is_flagged(self):
        on_block = "on:\n  workflow_dispatch:\n"
        violations = _violations(_wf(on_block=on_block))
        self.assertTrue(any("push" in v.message for v in violations))

    # --- branch / path filters -------------------------------------------- #
    def test_missing_branch_filter_is_flagged(self):
        on_block = "on:\n  push:\n    paths:\n      - 'platform/terraform/global/iam/**'\n"
        violations = _violations(_wf(on_block=on_block))
        self.assertTrue(any("branches" in v.message for v in violations))

    def test_wrong_branch_is_flagged(self):
        on_block = (
            "on:\n  push:\n    branches: [dev, feature-x]\n"
            "    paths:\n      - 'platform/terraform/global/iam/**'\n"
        )
        violations = _violations(_wf(on_block=on_block))
        self.assertTrue(any("dev, main" in v.message for v in violations))

    def test_missing_global_iam_path_filter_is_flagged(self):
        on_block = (
            "on:\n  push:\n    branches: [dev, main]\n"
            "    paths:\n      - 'platform/terraform/environments/**'\n"
        )
        violations = _violations(_wf(on_block=on_block))
        self.assertTrue(any("path" in v.message for v in violations))

    # --- designated plan step contract ------------------------------------ #
    def test_plan_without_detailed_exitcode_is_flagged(self):
        jobs = _drift_jobs("terraform plan -refresh=false")
        violations = _violations(_wf(jobs_block=jobs))
        self.assertTrue(any("detailed-exitcode" in v.message for v in violations))

    def test_echoed_plan_is_flagged(self):
        jobs = _drift_jobs("echo terraform plan -detailed-exitcode")
        violations = _violations(_wf(jobs_block=jobs))
        self.assertTrue(any("terraform plan -detailed-exitcode" in v.message for v in violations))

    def test_commented_plan_is_flagged(self):
        jobs = _drift_jobs("# terraform plan -detailed-exitcode\ntrue")
        self.assertTrue(_violations(_wf(jobs_block=jobs)))

    def test_swallowed_plan_or_true_is_flagged(self):
        jobs = _drift_jobs("terraform plan -detailed-exitcode -refresh=false || true")
        self.assertTrue(_violations(_wf(jobs_block=jobs)))

    def test_swallowed_plan_exit_zero_is_flagged(self):
        jobs = _drift_jobs("terraform plan -detailed-exitcode -refresh=false\nexit 0")
        self.assertTrue(_violations(_wf(jobs_block=jobs)))

    def test_continue_on_error_is_flagged(self):
        jobs = _drift_jobs(
            "terraform plan -detailed-exitcode -refresh=false", continue_on_error=True
        )
        self.assertTrue(_violations(_wf(jobs_block=jobs)))

    def test_job_level_continue_on_error_is_flagged(self):
        # A job-level continue-on-error: true (sibling to runs-on, not the step)
        # makes GitHub Actions mark the job successful even when the plan step
        # exits non-zero on drift - so _has_designated_drift_plan must skip the
        # whole job, not only step-level continue-on-error.
        jobs = (
            "jobs:\n"
            "  drift:\n"
            "    runs-on: self-hosted\n"
            "    continue-on-error: true\n"
            "    defaults:\n      run:\n        working-directory: platform/terraform/global/iam\n"
            "    steps:\n"
            "      - name: Terraform plan\n"
            "        run: terraform plan -detailed-exitcode -refresh=false\n"
        )
        self.assertTrue(_violations(_wf(jobs_block=jobs)))

    def test_plan_outside_global_iam_is_flagged(self):
        jobs = _drift_jobs(
            "terraform plan -detailed-exitcode -refresh=false",
            working_directory="platform/terraform/environments/dev",
        )
        violations = _violations(_wf(jobs_block=jobs))
        self.assertTrue(any("global/iam" in v.message for v in violations))

    def test_cross_job_scope_match_is_flagged(self):
        # global/iam appears only in an unrelated job; the plan job is unscoped.
        jobs = (
            "jobs:\n"
            "  unrelated:\n"
            "    runs-on: self-hosted\n"
            "    steps:\n"
            "      - run: echo platform/terraform/global/iam\n"
            "  drift:\n"
            "    runs-on: self-hosted\n"
            "    defaults:\n      run:\n        working-directory: platform/terraform/environments/dev\n"
            "    steps:\n"
            "      - name: Terraform plan\n"
            "        run: terraform plan -detailed-exitcode -refresh=false\n"
        )
        violations = _violations(_wf(jobs_block=jobs))
        self.assertTrue(any("global/iam" in v.message for v in violations))

    # --- relevance --------------------------------------------------------- #
    def test_irrelevant_file_subset_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                ADR_GUARD.check_global_iam_drift_check(Path(tmp), ["README.md"]), []
            )

    def test_relevant_file_subset_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(
                ADR_GUARD.check_global_iam_drift_check(Path(tmp), [WORKFLOW_REL])
            )


if __name__ == "__main__":
    unittest.main()
