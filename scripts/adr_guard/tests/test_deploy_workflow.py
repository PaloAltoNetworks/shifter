"""Deploy control-plane verification suite (GitHub #921 + #935, consolidated).

Reads deploy.yml and the reusable deploy workflows as data via the single
workflow-as-data model in ``adr_guard.py`` (the ``_dw_*`` helpers) and asserts
the gating invariants that ``actionlint`` (syntax only) and the narrow ADR
checks cannot infer:

* ADR-003-R5 runner exposure - no pull_request event reaches a self-hosted
  deploy job (also enforced as the hard ``deploy-workflow-runner-exposure``
  adr_guard check; here proven semantically against every self-hosted job).
* #781 - every deploy job fails closed when an upstream is failure/cancelled.
* #892 - branch/event routing: only workflow_dispatch on main is a prod-apply
  path; no pull_request routes a provider deploy; dev/main never deploy.
* #913 / R-A2 - the portal_image (app image) vs shifter_platform (Terraform)
  change-filter split is preserved.
* Mutating deploy jobs bind a GitHub Environment (#935); the engine deploy
  pins an immutable ECR digest instead of a mutable tag lookup (#935).

This replaces the substring-based ``test_deploy_workflow_security.py`` and the
standalone ``scripts/workflow_gating/`` suite, which proved the same
runner-exposure/PR-routing invariants by string matching; the model here
evaluates the if-expression, so a guard broadened with ``|| always()`` is
caught. See ``docs/architecture/workflow-gating-test-suite-preflight-921.md``.
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
REUSABLE_PATHS = ADR_GUARD._DW_REUSABLE_WORKFLOW_PATHS

# Deploy jobs in deploy.yml that fan out into the reusable deploy workflows.
DEPLOY_JOBS = ("gcp-dev", "core", "range", "shifter-engine", "shifter_platform")


def _load(name: str) -> dict:
    return ADR_GUARD._dw_load_workflow(REPO_ROOT, f".github/workflows/{name}")


class TestRunnerExposure(unittest.TestCase):
    """ADR-003-R5: no pull_request event reaches a self-hosted deploy job."""

    def test_runner_exposure_check_passes_on_real_workflows(self):
        self.assertEqual(ADR_GUARD.check_deploy_runner_exposure(REPO_ROOT, None), [])

    def test_every_self_hosted_job_fails_closed_on_pull_request(self):
        checked = 0
        for rel in REUSABLE_PATHS:
            wf = ADR_GUARD._dw_load_workflow(REPO_ROOT, rel)
            for jid, job in ADR_GUARD._dw_jobs(wf, rel).items():
                if not ADR_GUARD._dw_is_self_hosted(job):
                    continue
                checked += 1
                expr = ADR_GUARD._dw_job_if(job)
                self.assertTrue(
                    ADR_GUARD._dw_job_denied_on_pull_request(expr),
                    f"{rel}:{jid} runs on self-hosted but is reachable from a "
                    f"pull_request event (ADR-003-R5). if: {expr}",
                )
                self.assertTrue(
                    ADR_GUARD._dw_evaluate_if(expr, event_name="push"),
                    f"{rel}:{jid} never runs on push; its PR-denial assertion "
                    f"would be vacuous. if: {expr}",
                )
        self.assertGreater(checked, 0, "no self-hosted deploy jobs were found")

    def test_check_fails_closed_when_workflows_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            violations = ADR_GUARD.check_deploy_runner_exposure(Path(tmp), None)
            self.assertTrue(violations)
            self.assertTrue(all(v.rule_id == "ADR-003-R5" for v in violations))

    def test_semantic_eval_beats_substring(self):
        # A guard broadened with `|| always()` still contains the substring but
        # is fail-open; the model catches it where a substring check would not.
        broadened = "github.event_name != 'pull_request' || always()"
        self.assertFalse(ADR_GUARD._dw_job_denied_on_pull_request(broadened))
        guarded = "inputs.apply_changes && github.event_name != 'pull_request'"
        self.assertTrue(ADR_GUARD._dw_job_denied_on_pull_request(guarded))
        # A guard living only in a YAML comment never reaches the `if:` value,
        # so an empty / unguarded expression is reachable (the #935 intent).
        self.assertFalse(
            ADR_GUARD._dw_job_denied_on_pull_request("inputs.apply_changes")
        )


class TestUpstreamGating(unittest.TestCase):
    """#781: a failed/cancelled upstream must block every deploy job."""

    @classmethod
    def setUpClass(cls):
        cls.deploy = _load("deploy.yml")

    def test_known_deploy_jobs_exist(self):
        present = ADR_GUARD._dw_jobs(self.deploy, "deploy.yml")
        for jid in DEPLOY_JOBS:
            self.assertIn(jid, present, f"deploy.yml lost deploy job '{jid}'")

    def test_failed_or_cancelled_upstream_blocks_every_deploy_job(self):
        for jid, job in ADR_GUARD._dw_jobs(self.deploy, "deploy.yml").items():
            expr = ADR_GUARD._dw_job_if(job)
            upstreams = sorted(ADR_GUARD._dw_result_guarded_upstreams(expr))
            if not upstreams:
                continue
            self.assertTrue(
                ADR_GUARD._dw_job_runs_when_eligible(expr),
                f"deploy.yml job '{jid}' never runs even when eligible; the "
                f"denied-case assertions would be vacuous. if: {expr}",
            )
            for upstream in upstreams:
                for bad in ("failure", "cancelled"):
                    self.assertTrue(
                        ADR_GUARD._dw_job_denied_when_upstream(expr, upstream, bad),
                        f"deploy.yml job '{jid}' still runs when upstream "
                        f"'{upstream}' is '{bad}' - fail-open gating (#781). "
                        f"if: {expr}",
                    )

    def test_negative_fixture_cancelled_form_is_rejected(self):
        # `!= 'cancelled'` is fail-open on `failure`; the model flags it. (#781
        # is already fixed at dev HEAD - commit 801f114d - so this fixture
        # preserves the acceptance criterion's regression intent.)
        buggy_if = (
            "always() && needs.changes.outputs.run_aws == 'true' && "
            "(needs.shifter-engine.result != 'cancelled') && "
            "(needs.quality.result == 'success' || needs.quality.result == 'skipped')"
        )
        self.assertIn(
            "shifter-engine", ADR_GUARD._dw_result_guarded_upstreams(buggy_if)
        )
        self.assertFalse(
            ADR_GUARD._dw_job_denied_when_upstream(
                buggy_if, "shifter-engine", "failure"
            ),
            "`!= 'cancelled'` must be caught as fail-open on a `failure` result",
        )
        fake_wf = {
            "jobs": {"shifter_platform": {"if": buggy_if, "needs": ["shifter-engine"]}}
        }
        self.assertEqual(
            ADR_GUARD._dw_upstream_gating_violations(fake_wf, ["shifter_platform"]),
            [("shifter_platform", "shifter-engine", "failure")],
            "the buggy deploy.yml must be flagged by the model",
        )

    def test_negative_fixture_failure_form_is_rejected(self):
        # `!= 'failure'` blocks `failure` but is fail-open on `cancelled`.
        buggy_if = "always() && (needs.core.result != 'failure')"
        self.assertTrue(
            ADR_GUARD._dw_job_denied_when_upstream(buggy_if, "core", "failure")
        )
        self.assertFalse(
            ADR_GUARD._dw_job_denied_when_upstream(buggy_if, "core", "cancelled"),
            "`!= 'failure'` must be caught as fail-open on a `cancelled` result",
        )


class TestBranchEventMatrix(unittest.TestCase):
    """#892: branch/event routing produces the intended deploy outputs."""

    @classmethod
    def setUpClass(cls):
        cls.script = ADR_GUARD._dw_extract_set_environment_script(_load("deploy.yml"))

    def env(self, event_name, ref="", base_ref=""):
        return ADR_GUARD._dw_evaluate_env(
            self.script, event_name, ref=ref, base_ref=base_ref
        )

    def test_push_to_dev_and_main_produce_no_deploy(self):
        for ref in ("refs/heads/dev", "refs/heads/main"):
            out = self.env("push", ref=ref)
            self.assertEqual(out["run_aws"], "false", ref)
            self.assertEqual(out["run_gcp"], "false", ref)
            self.assertEqual(out["apply_aws"], "false", ref)
            self.assertEqual(out["deploy_gcp"], "false", ref)

    def test_no_pull_request_routes_a_provider_deploy(self):
        for base in ("dev", "main", "aws-dev", "gcp-dev"):
            out = self.env("pull_request", base_ref=base)
            self.assertEqual(out["run_aws"], "false", base)
            self.assertEqual(out["run_gcp"], "false", base)
            self.assertEqual(out["apply_aws"], "false", base)
            self.assertEqual(out["deploy_gcp"], "false", base)

    def test_push_to_aws_dev_plans_and_applies(self):
        out = self.env("push", ref="refs/heads/aws-dev")
        self.assertEqual(out["run_aws"], "true")
        self.assertEqual(out["apply_aws"], "true")
        self.assertEqual(out["aws_environment"], "dev")
        self.assertEqual(out["aws_is_dev"], "true")

    def test_push_to_gcp_dev_plans_and_applies(self):
        out = self.env("push", ref="refs/heads/gcp-dev")
        self.assertEqual(out["run_gcp"], "true")
        self.assertEqual(out["deploy_gcp"], "true")
        self.assertEqual(out["fast_gcp_deploy"], "true")

    def test_workflow_dispatch_main_is_the_only_prod_apply_path(self):
        prod = self.env("workflow_dispatch", ref="refs/heads/main")
        self.assertEqual(prod["aws_environment"], "prod")
        self.assertEqual(prod["aws_is_dev"], "false")
        self.assertEqual(prod["run_aws"], "true")
        self.assertEqual(prod["apply_aws"], "true")
        others = [
            ("push", "refs/heads/dev", ""),
            ("push", "refs/heads/main", ""),
            ("push", "refs/heads/aws-dev", ""),
            ("push", "refs/heads/gcp-dev", ""),
            ("pull_request", "", "dev"),
            ("pull_request", "", "aws-dev"),
            ("workflow_dispatch", "refs/heads/dev", ""),
            ("workflow_dispatch", "refs/heads/aws-dev", ""),
            ("workflow_dispatch", "refs/heads/gcp-dev", ""),
        ]
        for event, ref, base in others:
            out = self.env(event, ref=ref, base_ref=base)
            self.assertNotEqual(
                out.get("aws_environment"),
                "prod",
                f"{event}/{ref or base} must not target prod",
            )

    def test_workflow_dispatch_dev_runs_both_clouds_without_apply(self):
        out = self.env("workflow_dispatch", ref="refs/heads/dev")
        self.assertEqual(out["run_aws"], "true")
        self.assertEqual(out["run_gcp"], "true")
        self.assertEqual(out["apply_aws"], "false")
        self.assertEqual(out["aws_environment"], "dev")


class TestChangeFilterCoverage(unittest.TestCase):
    """#913 / R-A2: change filters route the right paths to the right gates."""

    @classmethod
    def setUpClass(cls):
        cls.filters = ADR_GUARD._dw_parse_paths_filter(
            _load("deploy.yml"), "changes", "filter"
        )

    def assertPathInFilter(self, path, filter_name):
        self.assertIn(filter_name, self.filters, f"filter '{filter_name}' missing")
        self.assertTrue(
            ADR_GUARD._dw_path_matches_any(path, self.filters[filter_name]),
            f"'{path}' should match filter '{filter_name}'",
        )

    def assertPathNotInFilter(self, path, filter_name):
        self.assertFalse(
            ADR_GUARD._dw_path_matches_any(path, self.filters[filter_name]),
            f"'{path}' should NOT match filter '{filter_name}'",
        )

    def test_app_code_triggers_portal_image(self):
        for path in (
            "shifter/shifter_platform/views.py",
            "shifter/cyberscript/index.ts",
            "shifter/installation/setup.sh",
            "shifter/.dockerignore",
        ):
            self.assertPathInFilter(path, "portal_image")

    def test_portal_app_code_does_not_trigger_terraform_filter(self):
        # #913 deliberately split app-image routing from the Terraform-only
        # `shifter_platform` filter; do not collapse them.
        self.assertPathNotInFilter(
            "shifter/shifter_platform/views.py", "shifter_platform"
        )
        self.assertPathNotInFilter("shifter/cyberscript/index.ts", "shifter_platform")

    def test_terraform_paths_trigger_their_plan_filters(self):
        self.assertPathInFilter(
            "platform/terraform/modules/portal/ec2/main.tf", "shifter_platform"
        )
        self.assertPathInFilter("platform/terraform/modules/range/main.tf", "range")
        self.assertPathInFilter("platform/terraform/modules/ecr/main.tf", "core")
        self.assertPathInFilter(
            "platform/terraform/modules/engine-provisioner/iam.tf", "shifter_engine"
        )
        self.assertPathInFilter("platform/terraform/environments/dev/main.tf", "core")

    def test_guardrail_scripts_route_to_quality_only(self):
        for path in (
            "scripts/check_tf_iam_ec2_scope/check_tf_iam_ec2_scope.py",
            "scripts/adr_guard/adr_guard.py",
            "docs/adr/index.yaml",
            ".pre-commit-config.yaml",
        ):
            self.assertPathInFilter(path, "quality_only")
            self.assertPathNotInFilter(path, "core")
            self.assertPathNotInFilter(path, "shifter_platform")

    def test_gcp_paths_trigger_gcp_filter(self):
        self.assertPathInFilter("platform/terraform/gcp/main.tf", "gcp")
        self.assertPathInFilter("platform/k8s/gcp/base/deployment.yaml", "gcp")


class TestGithubEnvironmentBinding(unittest.TestCase):
    """#935 / ADR-003-R5: mutating deploy jobs bind a GitHub Environment."""

    EXPECTED = {
        "_core.yml": ("apply",),
        "_range.yml": ("apply",),
        "_shifter-engine.yml": ("build", "deploy"),
        "_shifter-platform.yml": ("push-guacamole-images", "apply", "build", "deploy"),
        "_gcp-dev.yml": ("deploy",),
    }

    def test_mutating_jobs_bind_github_environment(self):
        for name, job_ids in self.EXPECTED.items():
            wf = _load(name)
            jobs = ADR_GUARD._dw_jobs(wf, name)
            for jid in job_ids:
                self.assertIn(jid, jobs, f"{name}:{jid} missing")
                self.assertEqual(
                    jobs[jid].get("environment"),
                    "${{ inputs.github_environment }}",
                    f"{name}:{jid} must bind the github_environment input (ADR-003-R5)",
                )


class TestEngineImageDigest(unittest.TestCase):
    """#935: the engine deploy pins an immutable ECR digest, not a tag lookup."""

    def _read(self, rel):
        return (REPO_ROOT / rel).read_text(encoding="utf-8")

    def _active_text(self, rel):
        return "\n".join(
            stripped
            for line in self._read(rel).splitlines()
            if (stripped := line.strip()) and not stripped.startswith("#")
        )

    def test_engine_terraform_uses_explicit_digest_without_ecr_tag_lookup(self):
        engine_main = self._read(
            "platform/terraform/modules/engine-provisioner/main.tf"
        )
        engine_task = self._read(
            "platform/terraform/modules/engine-provisioner/task_definition.tf"
        )
        engine_vars = self._read(
            "platform/terraform/modules/engine-provisioner/variables.tf"
        )
        platform_wf = self._active_text(".github/workflows/_shifter-platform.yml")
        deploy_wf = self._active_text(".github/workflows/deploy.yml")

        self.assertNotIn('data "aws_ecr_image"', engine_main)
        self.assertIn('variable "container_image_digest"', engine_vars)
        self.assertIn(
            "${var.ecr_repository_url}@${var.container_image_digest}", engine_task
        )
        self.assertIn("engine_image_digest:", platform_wf)
        self.assertIn('engine_container_image_digest = "%s"', platform_wf)
        self.assertIn(
            "engine_image_digest: ${{ needs.shifter-engine.outputs.image_digest }}",
            deploy_wf,
        )


class TestWorkflowShapeContract(unittest.TestCase):
    """Config-shape layer: the model fails closed on malformed workflows."""

    def test_on_key_is_normalized(self):
        wf = _load("deploy.yml")
        self.assertIn("on", wf, "bare `on:` must be normalized from YAML True")
        self.assertNotIn(True, wf)

    def test_missing_workflow_raises(self):
        with self.assertRaises(ADR_GUARD._DwShapeError):
            ADR_GUARD._dw_load_workflow(
                REPO_ROOT, ".github/workflows/does-not-exist.yml"
            )

    def test_missing_jobs_raises(self):
        with self.assertRaises(ADR_GUARD._DwShapeError):
            ADR_GUARD._dw_jobs({"name": "x"}, "fixture")

    def test_missing_paths_filter_step_raises(self):
        with self.assertRaises(ADR_GUARD._DwShapeError):
            ADR_GUARD._dw_parse_paths_filter(
                {"jobs": {"changes": {"steps": []}}}, "changes", "filter"
            )


if __name__ == "__main__":
    unittest.main()
