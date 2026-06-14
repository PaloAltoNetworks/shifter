"""Workflow-gating test suite for the deploy control plane (GitHub #921).

Reads ``.github/workflows/deploy.yml`` and the reusable deploy workflows as
data (no cloud calls, no Actions execution) and asserts the gating invariants
that ``actionlint`` (syntax only) and ``adr_guard`` (narrow ADR checks) cannot
infer. Each test names the finding/issue it guards so a regression is
self-documenting:

* #781 / TEST-1  - deploy jobs gate upstream deploy dependencies on
  ``success || skipped`` (never ``!= 'cancelled'``).
* #892           - branch/event routing: only ``workflow_dispatch`` on ``main``
  is a prod-apply path; ``dev``/``main`` never deploy; deploy-branch PRs are
  plan-only.
* #913 / R-A2    - the ``shifter_platform`` (Terraform) vs ``portal_image``
  (app image) change-filter split is preserved.
* runner-exposure / DP-2 - no ``pull_request`` event reaches a self-hosted
  apply/deploy job.

See ``docs/architecture/workflow-gating-test-suite-preflight-921.md``.
"""

from __future__ import annotations

import unittest

from .workflow_gating import (
    REUSABLE_DEPLOY_WORKFLOWS,
    WorkflowShapeError,
    evaluate_env,
    evaluate_if,
    extract_set_environment_script,
    is_self_hosted,
    job_denied_on_pull_request,
    job_denied_when_upstream,
    job_if,
    job_runs_when_eligible,
    jobs,
    load_workflow,
    parse_paths_filter,
    path_matches_any,
    result_guarded_upstreams,
    upstream_gating_violations,
)

# Deploy jobs in deploy.yml that fan out into the reusable deploy workflows.
# Existence is asserted below; the upstream-gating test discovers result-gated
# jobs dynamically so a new deploy job is covered without editing this list.
DEPLOY_JOBS = ("gcp-dev", "core", "range", "shifter-engine", "shifter_platform")


class TestUpstreamGating(unittest.TestCase):
    """#781 / TEST-1: upstream deploy dependencies must fail closed."""

    @classmethod
    def setUpClass(cls):
        cls.deploy = load_workflow("deploy.yml")

    def test_known_deploy_jobs_exist(self):
        present = jobs(self.deploy, "deploy.yml")
        for jid in DEPLOY_JOBS:
            self.assertIn(jid, present, f"deploy.yml lost deploy job '{jid}'")

    def test_failed_or_cancelled_upstream_blocks_every_deploy_job(self):
        # Semantic proof (not substring): for each job whose `if:` gates an
        # upstream's result, evaluate the expression with that upstream set to
        # `failure` / `cancelled` (every other condition permissive) and assert
        # the job does NOT run. Catches #781 (the pre-fix `shifter_platform`
        # gate used `needs.shifter-engine.result != 'cancelled'`, which a
        # `failure` satisfied).
        for jid, job in jobs(self.deploy, "deploy.yml").items():
            expr = job_if(job)
            upstreams = sorted(result_guarded_upstreams(expr))
            if not upstreams:
                continue
            self.assertTrue(
                job_runs_when_eligible(expr),
                f"deploy.yml job '{jid}' never runs even when eligible; the "
                f"denied-case assertions below would be vacuous. if: {expr}",
            )
            for upstream in upstreams:
                for bad in ("failure", "cancelled"):
                    self.assertTrue(
                        job_denied_when_upstream(expr, upstream, bad),
                        f"deploy.yml job '{jid}' still runs when upstream "
                        f"'{upstream}' is '{bad}' - fail-open gating (#781). "
                        f"if: {expr}",
                    )

    def test_negative_fixture_cancelled_form_is_rejected(self):
        # Regression intent of the acceptance criteria: prove the suite WOULD
        # fail against the pre-#781 `deploy.yml`. #781 is already fixed at dev
        # HEAD (commit 801f114d), so we evaluate the buggy form instead of
        # leaving CI red. `!= 'cancelled'` is fail-open on `failure`: the job
        # still runs, so the semantic checker flags it.
        buggy_if = (
            "always() && needs.changes.outputs.run_aws == 'true' && "
            "(needs.shifter-engine.result != 'cancelled') && "
            "(needs.quality.result == 'success' || needs.quality.result == 'skipped')"
        )
        self.assertIn("shifter-engine", result_guarded_upstreams(buggy_if))
        self.assertFalse(
            job_denied_when_upstream(buggy_if, "shifter-engine", "failure"),
            "`!= 'cancelled'` must be caught as fail-open on a `failure` result",
        )
        fake_wf = {
            "jobs": {"shifter_platform": {"if": buggy_if, "needs": ["shifter-engine"]}}
        }
        self.assertEqual(
            upstream_gating_violations(fake_wf, ["shifter_platform"]),
            [("shifter_platform", "shifter-engine", "failure")],
            "the buggy deploy.yml must be flagged by the suite",
        )

    def test_negative_fixture_failure_form_is_rejected(self):
        # `failure` and `cancelled` must BOTH block downstream deploys.
        # `!= 'failure'` blocks `failure` but is fail-open on `cancelled`.
        buggy_if = "always() && (needs.core.result != 'failure')"
        self.assertTrue(job_denied_when_upstream(buggy_if, "core", "failure"))
        self.assertFalse(
            job_denied_when_upstream(buggy_if, "core", "cancelled"),
            "`!= 'failure'` must be caught as fail-open on a `cancelled` result",
        )


class TestBranchEventMatrix(unittest.TestCase):
    """#892: branch/event routing produces the intended deploy outputs."""

    @classmethod
    def setUpClass(cls):
        cls.script = extract_set_environment_script(load_workflow("deploy.yml"))

    def env(self, event_name, ref="", base_ref=""):
        return evaluate_env(self.script, event_name, ref=ref, base_ref=base_ref)

    def test_push_to_dev_and_main_produce_no_deploy(self):
        for ref in ("refs/heads/dev", "refs/heads/main"):
            out = self.env("push", ref=ref)
            self.assertEqual(out["run_aws"], "false", ref)
            self.assertEqual(out["run_gcp"], "false", ref)
            self.assertEqual(out["apply_aws"], "false", ref)
            self.assertEqual(out["deploy_gcp"], "false", ref)

    def test_no_pull_request_routes_a_provider_deploy(self):
        # PR-triggered deploy runs are hosted-only quality gates: no PR base
        # branch (dev/main OR the deploy branches) may route a provider deploy.
        # deploy.yml hardened this from the older "PR to a deploy branch plans"
        # behavior - PRs now never reach the self-hosted provider jobs at all.
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

        # Every other event/branch combination must NOT be a prod apply, i.e.
        # never (apply_aws == true AND aws_environment == prod).
        others = [
            ("push", "refs/heads/dev", ""),
            ("push", "refs/heads/main", ""),
            ("push", "refs/heads/aws-dev", ""),
            ("push", "refs/heads/gcp-dev", ""),
            ("pull_request", "", "dev"),
            ("pull_request", "", "main"),
            ("pull_request", "", "aws-dev"),
            ("pull_request", "", "gcp-dev"),
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
        cls.filters = parse_paths_filter(
            load_workflow("deploy.yml"), "changes", "filter"
        )

    def assertPathInFilter(self, path, filter_name):
        self.assertIn(filter_name, self.filters, f"filter '{filter_name}' missing")
        self.assertTrue(
            path_matches_any(path, self.filters[filter_name]),
            f"'{path}' should match filter '{filter_name}'",
        )

    def assertPathNotInFilter(self, path, filter_name):
        self.assertFalse(
            path_matches_any(path, self.filters[filter_name]),
            f"'{path}' should NOT match filter '{filter_name}'",
        )

    def test_app_code_triggers_portal_image(self):
        # #913: portal app code must drive the portal image build/deploy.
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
        # Guardrail script changes must re-run Quality but never deploy.
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


class TestRunnerExposure(unittest.TestCase):
    """runner-exposure / DP-2: no PR event reaches a self-hosted deploy job.

    deploy.yml routes no provider deploy on a pull_request, and the reusable
    workflows fail closed independently: every self-hosted job (plan, apply,
    build, deploy) must itself block pull_request events, so PR code can never
    reach a privileged self-hosted runner even if the caller gate regresses.
    This is verified semantically (the if-expression evaluator), which is
    stronger than a substring check: a guard broadened with `|| always()`
    would be caught here.
    """

    def test_every_self_hosted_job_fails_closed_on_pull_request(self):
        checked = 0
        for wf_name in REUSABLE_DEPLOY_WORKFLOWS:
            wf = load_workflow(wf_name)
            for jid, job in jobs(wf, wf_name).items():
                if not is_self_hosted(job):
                    continue
                checked += 1
                expr = job_if(job)
                self.assertTrue(
                    job_denied_on_pull_request(expr),
                    f"{wf_name}:{jid} runs on self-hosted but is reachable from "
                    f"a pull_request event (runner-exposure fix). if: {expr}",
                )
                self.assertTrue(
                    evaluate_if(expr, event_name="push"),
                    f"{wf_name}:{jid} never runs even on a push; its "
                    f"PR-denial assertion would be vacuous. if: {expr}",
                )
        # Fail closed if the inventory ever drops to nothing (e.g. a parsing
        # regression made every job look hosted): there must be self-hosted
        # deploy jobs to guard.
        self.assertGreater(checked, 0, "no self-hosted deploy jobs were found")

    def test_negative_fixture_unguarded_self_hosted_apply_is_flagged(self):
        # Without the PR guard the job still runs on a pull_request event.
        unguarded = "inputs.apply_changes && needs.plan.result == 'success'"
        self.assertFalse(job_denied_on_pull_request(unguarded))
        guarded = unguarded + " && github.event_name != 'pull_request'"
        self.assertTrue(job_denied_on_pull_request(guarded))


class TestWorkflowShapeContract(unittest.TestCase):
    """Config-shape layer: the loader fails closed on malformed workflows."""

    def test_on_key_is_normalized(self):
        wf = load_workflow("deploy.yml")
        self.assertIn("on", wf, "bare `on:` must be normalized from YAML True")
        self.assertNotIn(True, wf)

    def test_missing_workflow_raises(self):
        with self.assertRaises(WorkflowShapeError):
            load_workflow("does-not-exist.yml")

    def test_missing_jobs_raises(self):
        with self.assertRaises(WorkflowShapeError):
            jobs({"name": "x"}, "fixture")

    def test_missing_paths_filter_step_raises(self):
        with self.assertRaises(WorkflowShapeError):
            parse_paths_filter(
                {"jobs": {"changes": {"steps": []}}}, "changes", "filter"
            )


if __name__ == "__main__":
    unittest.main()
