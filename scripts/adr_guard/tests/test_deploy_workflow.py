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
import re
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

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
                    f"{rel}:{jid} never runs on push; its PR-denial assertion would be vacuous. if: {expr}",
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
        self.assertFalse(ADR_GUARD._dw_job_denied_on_pull_request("inputs.apply_changes"))


class TestSelfHostedClassLabels(unittest.TestCase):
    """ADR-003-R5 exposure recognizes custom self-hosted-class labels (#1546).

    A GCP-native runner registers with ``--no-default-labels`` + a custom label,
    so a job selecting it never carries the literal ``self-hosted`` label. The
    exposure check must still treat such a job as self-hosted-class, or the
    pull_request-reachability gate develops a blind spot when GCP-dev CI is cut
    over to its own runner.
    """

    def test_literal_self_hosted_is_recognized(self):
        self.assertTrue(ADR_GUARD._dw_is_self_hosted({"runs-on": "self-hosted"}))

    def test_custom_gcp_label_is_recognized_as_self_hosted_class(self):
        self.assertTrue(ADR_GUARD._dw_is_self_hosted({"runs-on": "gcp-dev"}))
        self.assertTrue(ADR_GUARD._dw_is_self_hosted({"runs-on": ["gcp-dev"]}))

    def test_github_hosted_label_is_not_self_hosted(self):
        self.assertFalse(ADR_GUARD._dw_is_self_hosted({"runs-on": "ubuntu-latest"}))
        self.assertFalse(ADR_GUARD._dw_is_self_hosted({"runs-on": ["ubuntu-latest"]}))


class TestExpressionOperandCoverage(unittest.TestCase):
    """#1874: the evaluator resolves the operands `_quality.yml` conditions use.

    That workflow writes its conditions in the wrapped ``${{ }}`` form, and the
    Sonar scan gate is an exact comparison against ``github.repository`` that
    must stay independent of whether ``vars.SONAR_*`` are set. Without unwrap,
    repository, and ``vars`` support the gate could only be substring-matched -
    the failure mode this whole suite exists to avoid.
    """

    def test_wrapped_expressions_are_unwrapped_before_evaluation(self):
        self.assertTrue(ADR_GUARD._dw_evaluate_if("${{ always() }}"))
        self.assertFalse(ADR_GUARD._dw_evaluate_if("${{ github.event_name == 'pull_request' }}", event_name="push"))

    def test_repository_identity_is_resolvable(self):
        expr = "github.repository == 'Brad-Edwards/shifter'"
        # The permissive default is the canonical repository, so only the
        # scenario under test flips the outcome.
        self.assertTrue(ADR_GUARD._dw_evaluate_if(expr))
        self.assertFalse(ADR_GUARD._dw_evaluate_if(expr, repository="a-fork/shifter"))

    def test_repository_variables_are_resolvable_and_can_be_unset(self):
        expr = "vars.SONAR_PROJECT_KEY != ''"
        self.assertTrue(ADR_GUARD._dw_evaluate_if(expr))
        self.assertFalse(ADR_GUARD._dw_evaluate_if(expr, vars_set=False))


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
        self.assertIn("shifter-engine", ADR_GUARD._dw_result_guarded_upstreams(buggy_if))
        self.assertFalse(
            ADR_GUARD._dw_job_denied_when_upstream(buggy_if, "shifter-engine", "failure"),
            "`!= 'cancelled'` must be caught as fail-open on a `failure` result",
        )
        fake_wf = {"jobs": {"shifter_platform": {"if": buggy_if, "needs": ["shifter-engine"]}}}
        self.assertEqual(
            ADR_GUARD._dw_upstream_gating_violations(fake_wf, ["shifter_platform"]),
            [("shifter_platform", "shifter-engine", "failure")],
            "the buggy deploy.yml must be flagged by the model",
        )

    def test_negative_fixture_failure_form_is_rejected(self):
        # `!= 'failure'` blocks `failure` but is fail-open on `cancelled`.
        buggy_if = "always() && (needs.core.result != 'failure')"
        self.assertTrue(ADR_GUARD._dw_job_denied_when_upstream(buggy_if, "core", "failure"))
        self.assertFalse(
            ADR_GUARD._dw_job_denied_when_upstream(buggy_if, "core", "cancelled"),
            "`!= 'failure'` must be caught as fail-open on a `cancelled` result",
        )


class TestManualDeployDispatch(unittest.TestCase):
    """#730: environment deploys are manual (a workflow_dispatch names the
    environment). push and pull_request run validation only, and no branch name
    selects a deployment target."""

    ENV_OPTIONS = {"aws-dev", "aws-proof", "gcp-dev"}

    @classmethod
    def setUpClass(cls):
        cls.deploy = _load("deploy.yml")
        cls.script = ADR_GUARD._dw_extract_set_environment_script(cls.deploy)

    def env(self, event_name, ref="", base_ref=""):
        return ADR_GUARD._dw_evaluate_env(self.script, event_name, ref=ref, base_ref=base_ref)

    def test_push_never_deploys(self):
        for ref in ("refs/heads/dev", "refs/heads/main"):
            out = self.env("push", ref=ref)
            for key in ("run_aws", "run_gcp", "apply_aws", "deploy_gcp"):
                self.assertEqual(out[key], "false", f"{ref}:{key}")

    def test_pull_request_never_deploys(self):
        for base in ("dev", "main", "aws-dev", "gcp-dev"):
            out = self.env("pull_request", base_ref=base)
            for key in ("run_aws", "run_gcp", "apply_aws", "deploy_gcp"):
                self.assertEqual(out[key], "false", f"{base}:{key}")

    def test_deploy_is_selected_by_the_environment_input_not_the_branch(self):
        # The Set environment step keys on the workflow_dispatch `environment`
        # input; the old branch-name `case` router (and prod path) are gone.
        self.assertIn('case "$ENVIRONMENT"', self.script)

    def test_aws_platform_uses_the_explicit_eks_bundle_entrypoint(self):
        platform = _load("_shifter-platform.yml")
        job = platform["jobs"]["eks-deploy"]
        rendered = str(job)

        self.assertIn("scripts/bootstrap/deploy.py eks-deploy", rendered)
        self.assertIn("SHIFTER_CONFIG_", rendered)
        self.assertIn("needs.build.outputs.image_digest", rendered)
        self.assertIn("inputs.engine_image_digest", rendered)
        self.assertIn("provisioner:$provisioner", rendered)
        self.assertNotIn("github.ref", rendered)
        self.assertIn("__legacy-disabled__", platform["jobs"]["plan"]["if"])
        self.assertIn("__legacy-disabled__", platform["jobs"]["deploy"]["if"])
        self.assertNotIn("GITHUB_REF#refs/heads/", self.script)
        self.assertNotIn("aws-prod", self.script)

    def test_environment_input_is_a_closed_choice_allowlist(self):
        env_input = self.deploy["on"]["workflow_dispatch"]["inputs"]["environment"]
        self.assertEqual(env_input["type"], "choice")
        self.assertEqual(set(env_input["options"]), self.ENV_OPTIONS)

    def test_deploy_jobs_stay_pull_request_denied(self):
        # Unchanged trust invariant: no deploy job runs on a pull_request event.
        jobs = ADR_GUARD._dw_jobs(self.deploy, "deploy.yml")
        for jid in DEPLOY_JOBS:
            expr = ADR_GUARD._dw_job_if(jobs[jid])
            self.assertTrue(
                ADR_GUARD._dw_job_denied_on_pull_request(expr),
                f"{jid} must be denied on pull_request",
            )


class TestChangeFilterCoverage(unittest.TestCase):
    """#913 / R-A2: change filters route the right paths to the right gates."""

    @classmethod
    def setUpClass(cls):
        cls.filters = ADR_GUARD._dw_parse_paths_filter(_load("deploy.yml"), "changes", "filter")

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
            "shifter/installation/setup.sh",
            "shifter/.dockerignore",
        ):
            self.assertPathInFilter(path, "portal_image")

    def test_portal_app_code_does_not_trigger_terraform_filter(self):
        # #913 deliberately split app-image routing from the Terraform-only
        # `shifter_platform` filter; do not collapse them.
        self.assertPathNotInFilter("shifter/shifter_platform/views.py", "shifter_platform")

    def test_terraform_paths_trigger_their_plan_filters(self):
        self.assertPathInFilter("platform/terraform/modules/portal/ec2/main.tf", "shifter_platform")
        self.assertPathInFilter("platform/terraform/modules/range/main.tf", "range")
        self.assertPathInFilter("platform/terraform/modules/ecr/main.tf", "core")
        self.assertPathInFilter("platform/terraform/modules/engine-provisioner/iam.tf", "shifter_engine")
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


class TestScenarioVerificationQualityRouting(unittest.TestCase):
    """#1293: neutral verification uses platform CI, not a scenario adapter job."""

    @classmethod
    def setUpClass(cls):
        cls.quality = _load("_quality.yml")
        cls.jobs = ADR_GUARD._dw_jobs(cls.quality, "_quality.yml")
        filter_path = REPO_ROOT / ".github" / "quality-path-filters.yaml"
        raw = yaml.safe_load(filter_path.read_text(encoding="utf-8"))
        # #1530 evolved this file from a flat category->globs map into a
        # versioned quality-ownership contract. Derive the category->paths map
        # these routing assertions expect from the quality_units.
        cls.filters = {unit["id"]: unit["paths"] for unit in raw["quality_units"]}

    def test_shared_framework_path_uses_normal_platform_quality_jobs(self):
        framework_path = "shifter/shifter_platform/shared/scenario_verification/__init__.py"
        self.assertTrue(ADR_GUARD._dw_path_matches_any(framework_path, self.filters["shifter_platform"]))
        for job_id in (
            "shifter-platform-lint",
            "shifter-platform-sast",
            "shifter-platform-tests",
        ):
            self.assertIn(job_id, self.jobs)
            self.assertIn(
                "needs.paths.outputs.shifter_platform",
                ADR_GUARD._dw_job_if(self.jobs[job_id]),
                f"{job_id} must remain on normal shifter-platform routing",
            )

    def test_surviving_polaris_tests_keep_neutral_quality_route(self):
        polaris_test_path = "scenario-dev/polaris/tests/isolation-smoketest.sh"
        self.assertTrue(ADR_GUARD._dw_path_matches_any(polaris_test_path, self.filters["polaris_tests"]))
        path_outputs = self.jobs["paths"].get("outputs", {})
        self.assertIn("polaris_tests", path_outputs)
        job = self.jobs["polaris-tests"]
        self.assertIn("needs.paths.outputs.polaris_tests", ADR_GUARD._dw_job_if(job))
        run_steps = "\n".join(str(step.get("run", "")) for step in job.get("steps", []))
        self.assertIn("python3 -m compileall", run_steps)
        self.assertIn('bash -n "$script"', run_steps)

    def test_adapter_specific_quality_route_is_removed(self):
        self.assertNotIn("scenario_smoketest", self.filters)
        path_outputs = self.jobs["paths"].get("outputs", {})
        self.assertNotIn("scenario_smoketest", path_outputs)
        self.assertNotIn("scenario-smoketest-tests", self.jobs)


class TestTflintPluginAuthentication(unittest.TestCase):
    """#1850: TFLint plugin downloads use the job-scoped GitHub token."""

    def test_tflint_init_avoids_unauthenticated_api_rate_limit(self):
        quality = _load("_quality.yml")
        jobs = ADR_GUARD._dw_jobs(quality, "_quality.yml")
        terraform_lint = jobs["terraform-lint"]
        init_step = next(step for step in terraform_lint.get("steps", []) if step.get("name") == "Init TFLint")
        self.assertEqual(
            init_step.get("env", {}).get("GITHUB_TOKEN"),
            "${{ github.token }}",
        )


class TestSonarScannerIdentity(unittest.TestCase):
    """#1874 / ADR-003-R7: Sonar project identity is repository configuration.

    The project key and organization come from non-secret repository variables
    instead of the committed properties file, and the scan attempt is gated on
    the canonical repository rather than on those variables being set. The
    gating half is the security-relevant one: `if: vars.SONAR_PROJECT_KEY != ''`
    would make a renamed or deleted variable delete the SonarCloud quality gate
    from `PR Gate` with a green check and no failure anywhere. Evaluating the
    condition (rather than matching its text) is what proves a presence guard
    has not crept back in.
    """

    CANONICAL_REPOSITORY = "Brad-Edwards/shifter"
    IDENTITY_PROPERTIES = (
        "sonar.projectKey",
        "sonar.organization",
        "sonar.projectName",
    )
    # Shared analysis configuration that must stay committed - the guard against
    # over-deleting while removing identity.
    SHARED_PROPERTIES = (
        "sonar.projectVersion",
        "sonar.sources",
        "sonar.tests",
        "sonar.exclusions",
        "sonar.security.exclusions",
        "sonar.coverage.exclusions",
        "sonar.python.coverage.reportPaths",
        "sonar.javascript.lcov.reportPaths",
        "sonar.sourceEncoding",
        "sonar.issue.ignore.multicriteria",
        "sonar.html.fileHeader",
    )

    @classmethod
    def setUpClass(cls):
        jobs = ADR_GUARD._dw_jobs(_load("_quality.yml"), "_quality.yml")
        cls.scan_step = next(
            step for step in ADR_GUARD._dw_job_steps(jobs["sonarcloud"]) if step.get("name") == "SonarQube Cloud scan"
        )
        cls.scan_if = cls.scan_step.get("if", "")
        cls.args = str(cls.scan_step.get("with", {}).get("args", ""))
        cls.property_keys = {
            line.split("=", 1)[0].strip()
            for line in (REPO_ROOT / "sonar-project.properties").read_text(encoding="utf-8").splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        }

    def test_identity_properties_are_not_committed(self):
        for prop in self.IDENTITY_PROPERTIES:
            self.assertNotIn(
                prop,
                self.property_keys,
                f"{prop} must not travel with the source (ADR-003-R7)",
            )

    def test_shared_analysis_configuration_stays_committed(self):
        for prop in self.SHARED_PROPERTIES:
            self.assertIn(
                prop,
                self.property_keys,
                f"{prop} is shared analysis configuration and belongs in the repo",
            )

    def test_scan_reads_identity_from_repository_variables(self):
        self.assertIn("-Dsonar.projectKey=${{ vars.SONAR_PROJECT_KEY }}", self.args)
        self.assertIn("-Dsonar.organization=${{ vars.SONAR_ORGANIZATION }}", self.args)

    def test_canonical_repository_always_attempts_the_scan(self):
        self.assertTrue(
            ADR_GUARD._dw_evaluate_if(self.scan_if, repository=self.CANONICAL_REPOSITORY),
            "the canonical repository must always attempt the Sonar scan",
        )

    def test_unset_variables_do_not_skip_the_scan(self):
        # The regression this test exists for: a presence guard makes the
        # scanner no-op and the quality gate vanish silently. With the identity
        # gate the scanner receives an empty key and fails loudly instead.
        self.assertTrue(
            ADR_GUARD._dw_evaluate_if(
                self.scan_if,
                repository=self.CANONICAL_REPOSITORY,
                vars_set=False,
            ),
            "the scan must not be gated on SONAR_PROJECT_KEY / SONAR_ORGANIZATION "
            "being set - an unset variable has to fail the scanner, not skip it",
        )

    def test_other_repositories_skip_the_scan(self):
        self.assertFalse(
            ADR_GUARD._dw_evaluate_if(self.scan_if, repository="someone/shifter"),
            "SonarCloud is this project's tooling choice, not a dependency "
            "imposed on anyone who cloned the repo — their runs must skip it",
        )

    def test_fork_origin_pull_requests_skip_the_scan(self):
        # A fork PR runs in the base repository's context, so the identity test
        # passes, but GitHub withholds secrets from it. Without this the scan
        # fails on an empty SONAR_TOKEN and an outside contributor gets a red
        # check they cannot fix.
        self.assertFalse(
            ADR_GUARD._dw_evaluate_if(
                self.scan_if,
                repository=self.CANONICAL_REPOSITORY,
                event_name="pull_request",
                fork_pr=True,
            ),
            "a fork-origin pull request must skip the scan, not fail on a secret it can never be given",
        )

    def test_same_repository_pull_requests_still_scan(self):
        self.assertTrue(
            ADR_GUARD._dw_evaluate_if(
                self.scan_if,
                repository=self.CANONICAL_REPOSITORY,
                event_name="pull_request",
                fork_pr=False,
            ),
            "a branch PR inside the canonical repository must still be analyzed",
        )

    def test_token_stays_out_of_scanner_argv(self):
        self.assertEqual(
            self.scan_step.get("env", {}).get("SONAR_TOKEN"),
            "${{ secrets.SONAR_TOKEN }}",
        )
        self.assertNotIn(
            "SONAR_TOKEN",
            self.args,
            "the analysis token must never reach the scanner's argv",
        )

    def test_every_analysis_waits_for_the_quality_gate(self):
        self.assertIn("-Dsonar.qualitygate.wait=true", self.args)
        self.assertNotIn(
            "github.event_name == 'pull_request'",
            self.args,
            "push and manually dispatched release analysis must wait for the quality-gate verdict too (#2084)",
        )


class TestGcpReleaseSecurityClosure(unittest.TestCase):
    """#2084: release security checks fail closed and preserve exact evidence."""

    def assert_hcl_assignment(self, text, name, value):
        """Compare exact assignment values without depending on terraform fmt spacing."""
        pattern = rf"(?m)^\s*{re.escape(name)}\s*=\s*{re.escape(value)}\s*(?:#.*)?$"
        self.assertTrue(re.search(pattern, text), f"Expected HCL assignment {name} = {value}")

    def test_codeql_analysis_is_not_advisory(self):
        workflow = _load("codeql-analysis.yml")
        jobs = ADR_GUARD._dw_jobs(workflow, "codeql-analysis.yml")
        analyze = jobs["analyze"]
        step = next(item for item in ADR_GUARD._dw_job_steps(analyze) if item.get("name") == "Perform CodeQL Analysis")
        self.assertNotIn("continue-on-error", step)

    def test_osv_scans_every_owned_lockfile_and_fails_on_findings(self):
        workflow = _load("_quality.yml")
        jobs = ADR_GUARD._dw_jobs(workflow, "_quality.yml")
        job = jobs["security-osv-advisory"]
        run = "\n".join(str(step.get("run", "")) for step in job["steps"])
        self.assertIn("find . -name package-lock.json", run)
        self.assertIn("find . -name uv.lock", run)
        self.assertNotIn("|| true", run)

    def test_dependabot_owns_every_python_package_root(self):
        config = yaml.safe_load((REPO_ROOT / ".github/dependabot.yml").read_text(encoding="utf-8"))
        configured = {
            update["directory"].lstrip("/") or "."
            for update in config["updates"]
            if update["package-ecosystem"] == "uv"
        }
        discovered = {
            path.parent.relative_to(REPO_ROOT).as_posix()
            for path in REPO_ROOT.rglob("pyproject.toml")
            if ".venv" not in path.parts
        }
        self.assertEqual(configured, discovered)

    def test_gcp_deploy_scans_each_exact_oci_digest(self):
        path = REPO_ROOT / ".github/workflows/_gcp-dev.yml"
        workflow = path.read_text(encoding="utf-8")
        jobs = ADR_GUARD._dw_jobs(yaml.safe_load(path.read_text()), "_gcp-dev.yml")
        scanner = jobs["release_scan"]
        deploy = jobs["deploy"]
        self.assertIn("Scan exact release image digests", workflow)
        for digest in (
            "PORTAL_IMAGE_DIGEST",
            "PROVISIONER_IMAGE_DIGEST",
            "GUACD_IMAGE_DIGEST",
            "GUACAMOLE_CLIENT_IMAGE_DIGEST",
        ):
            self.assertIn(digest, workflow)
        self.assertIn("--exit-code 1", workflow)
        self.assertIn("--severity HIGH,CRITICAL", workflow)
        self.assertEqual(scanner["environment"], "gcp-release-scan-dev")
        self.assertIn("release_scan", deploy["needs"])
        scan_env = "\n".join(str(step.get("env", "")) for step in scanner["steps"])
        self.assertNotIn("GCP_DEPLOY_SERVICE_ACCOUNT", scan_env)
        self.assertNotIn("GCP_BOOTSTRAP_ADMIN_PASSWORD", scan_env)
        self.assertIn("TRIVY_ARCHIVE_SHA256", workflow)

    def test_raw_release_evidence_is_not_uploaded_as_an_actions_artifact(self):
        for workflow_name in (
            "_gcp-dev.yml",
            "packer-gcp.yml",
            "packer-gcp-validate.yml",
        ):
            workflow = _load(workflow_name)
            jobs = ADR_GUARD._dw_jobs(workflow, workflow_name)
            upload_paths = [
                str(step.get("with", {}).get("path", ""))
                for job in jobs.values()
                for step in ADR_GUARD._dw_job_steps(job)
                if "actions/upload-artifact@" in str(step.get("uses", ""))
            ]
            joined = "\n".join(upload_paths)
            self.assertNotIn("gce-build-evidence.json", joined)
            self.assertNotIn("guest-sbom.spdx.json", joined)
            self.assertNotIn("running-image-ids.json", joined)
            self.assertNotIn("portal-trivy.json", joined)
        identity = (REPO_ROOT / "platform/terraform/gcp/modules/cicd-oidc-identity/main.tf").read_text()
        self.assertIn('resource "google_storage_bucket" "release_evidence"', identity)
        self.assert_hcl_assignment(identity, "role", '"roles/storage.objectCreator"')
        self.assert_hcl_assignment(identity, "role", '"roles/storage.objectViewer"')
        self.assert_hcl_assignment(identity, 'public_access_prevention', '"enforced"')
        self.assert_hcl_assignment(identity, 'uniform_bucket_level_access', 'true')
        self.assert_hcl_assignment(identity, 'retention_period', '7776000')
        self.assert_hcl_assignment(identity, 'is_locked', 'true')

    def test_gcp_guest_build_and_sbom_evidence_cross_trust_boundaries(self):
        build = (REPO_ROOT / ".github/workflows/packer-gcp.yml").read_text(encoding="utf-8")
        validate = (REPO_ROOT / ".github/workflows/packer-gcp-validate.yml").read_text(encoding="utf-8")
        verifier = (REPO_ROOT / "shifter/packer/gcp/scripts/validate/verify-build-evidence.sh").read_text(
            encoding="utf-8"
        )
        scanner = (REPO_ROOT / "shifter/packer/gcp/scripts/validate/scan-attached-disk.sh").read_text(encoding="utf-8")

        self.assertIn("PKR_VAR_source_revision=${GITHUB_SHA}", build)
        self.assertIn("Store immutable build-source evidence", build)
        self.assertIn("packer-builds/${BUILT_IMAGE_ID}/build-evidence.json", build)
        self.assertIn("packer-builds/${CANDIDATE_IMAGE_ID}/build-evidence.json", validate)
        self.assertIn('EXPECTED_SOURCE_REVISION="${GITHUB_SHA}"', validate)
        self.assertIn(".source_revision", verifier)
        self.assertIn("SYFT_ARCHIVE_SHA256", validate)
        self.assertNotIn("checksums.txt", validate)
        self.assertIn("--mode=ro", validate)
        self.assertIn("external-read-only-disk", validate)
        self.assertIn('blockdev --getro "${device}"', scanner)
        self.assertIn("ro,nosuid,nodev,noexec", scanner)
        self.assertNotIn("validator@${VALIDATION_VM}:/tmp/syft", validate)

    def test_release_evidence_iam_is_purpose_and_prefix_scoped(self):
        identity = (REPO_ROOT / "platform/terraform/gcp/modules/cicd-oidc-identity/main.tf").read_text(encoding="utf-8")
        expected_resources = {
            "packer_build_evidence_writer": ("objectCreator", "packer-builds"),
            "validate_build_evidence_reader": ("objectViewer", "packer-builds"),
            "validate_evidence_writer": ("objectCreator", "packer-validation"),
            "release_scan_evidence_writer": ("objectCreator", "release-scans"),
            "deploy_evidence_writer": ("objectCreator", "deployments"),
            "promotion_evidence_reader": ("objectViewer", "packer-validation"),
        }
        for resource_name, (role, prefix) in expected_resources.items():
            marker = f'resource "google_storage_bucket_iam_member" "{resource_name}"'
            start = identity.index(marker)
            end = identity.find('\nresource "google_storage_bucket_iam_member"', start + 1)
            block = identity[start : end if end != -1 else None]
            self.assert_hcl_assignment(block, "role", f'"roles/storage.{role}"')
            self.assertIn(f"/objects/{prefix}/", block)
            self.assertIn("resource.name.startsWith", block)

    def test_platform_lifecycle_roles_cannot_mutate_release_images_or_evidence(self):
        identity_dir = REPO_ROOT / "platform/terraform/gcp/modules/cicd-oidc-identity"
        variables = (identity_dir / "variables.tf").read_text(encoding="utf-8")
        identity = (identity_dir / "main.tf").read_text(encoding="utf-8")
        for marker in ('variable "deploy_roles"', 'variable "destroy_roles"'):
            start = variables.index(marker)
            end = variables.index("\n}", start) + 2
            block = variables[start:end]
            self.assertNotIn('"roles/compute.admin"', block)
            self.assertNotIn('"roles/compute.instanceAdmin.v1"', block)
            self.assertNotIn('"roles/storage.admin"', block)
            self.assertIn('"roles/compute.networkAdmin"', block)
            self.assertIn('"roles/compute.securityAdmin"', block)
        self.assertIn("platform_storage_bucket_names", identity)
        self.assertIn("platform_storage_condition", identity)
        self.assertIn('resource "google_project_iam_custom_role" "deploy_storage"', identity)
        self.assertIn('resource "google_project_iam_custom_role" "destroy_storage"', identity)
        self.assertIn('resource "google_storage_bucket_iam_member" "deploy_bucket_iam_admin"', identity)
        self.assertIn('resource "google_storage_bucket_iam_member" "destroy_bucket_iam_admin"', identity)
        self.assert_hcl_assignment(identity, "role", '"roles/storage.legacyBucketOwner"')
        self.assertIn("platform_external_bucket_names", identity)
        condition_start = identity.index("platform_storage_bucket_names")
        condition_end = identity.index("\n}", condition_start)
        self.assertNotIn("release-evidence", identity[condition_start:condition_end])

    def test_gcp_deploy_records_running_workload_image_ids(self):
        workflow = (REPO_ROOT / ".github/workflows/_gcp-dev.yml").read_text(encoding="utf-8")
        verifier = (REPO_ROOT / "scripts/gcp/verify_running_image_ids.py").read_text(encoding="utf-8")
        self.assertIn("Record running workload image IDs", workflow)
        self.assertIn("scripts/gcp/verify_running_image_ids.py", workflow)
        self.assertEqual(workflow.count("--expected-image"), 3)
        self.assertIn("_RELEASE_CONTAINERS", verifier)
        self.assertIn("_RELEASE_DEPLOYMENTS", verifier)
        self.assertIn("--list-deployments", workflow)
        self.assertIn('"initContainers"', verifier)
        self.assertIn("initContainerStatuses", verifier)
        self.assertIn('"containerStatuses",', verifier)
        self.assertIn('"ephemeralContainers"', verifier)
        self.assertIn("ephemeralContainerStatuses", verifier)
        self.assertIn('container.get("imageID", "")', verifier)
        self.assertIn("declared_image != exact_reference", verifier)
        self.assertIn("runtime_image != exact_reference", verifier)
        self.assertIn("unexpected Shifter workload component", verifier)
        self.assertIn("_require_closed_names", verifier)
        self.assertIn("unexpected {kind} containers", verifier)
        self.assertIn("${RUNNER_TEMP}/gcp-release-security/running-pods.json", workflow)
        self.assertIn("Remove ephemeral deployment evidence", workflow)

    def test_gcp_promotion_authenticates_redacted_verdict_before_private_evidence(self):
        validate = (REPO_ROOT / ".github/workflows/packer-gcp-validate.yml").read_text(encoding="utf-8")
        promote = (REPO_ROOT / ".github/workflows/packer-gcp-promote.yml").read_text(encoding="utf-8")
        verifier = (REPO_ROOT / "shifter/packer/gcp/scripts/validate/verify-promotion-evidence.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("candidate_binding_sha256", validate)
        self.assertIn("steps.upload_verdict.outputs.artifact-id", validate)
        self.assertIn("validated-verdict-id", validate)
        self.assertIn("actions/artifacts/${VALIDATED_VERDICT_ID}", promote)
        self.assertLess(
            promote.index("actions/artifacts/${VALIDATED_VERDICT_ID}"),
            promote.index("gcloud storage cp --quiet"),
        )
        for marker in (
            "VERDICT_FILE",
            "ARTIFACT_FILE",
            "candidate_binding_sha",
            "validation verdict artifact run",
            "verdict evidence digest",
        ):
            self.assertIn(marker, verifier)

    def test_gcp_workflows_keep_sensitive_tfvars_out_of_the_checkout(self):
        for name in ("_gcp-dev.yml", "gcp-dev-destroy.yml"):
            workflow = (REPO_ROOT / f".github/workflows/{name}").read_text(encoding="utf-8")
            self.assertNotIn("${TF_DIR}/local.auto.tfvars", workflow)
            self.assertNotIn("${TF_DIR}/range_egress.auto.tfvars", workflow)
            self.assertIn("${RUNNER_TEMP}", workflow)
            self.assertIn("os.O_EXCL", workflow)
            self.assertIn("umask 077", workflow)
            self.assertIn("chmod 600", workflow)
            self.assertIn("-var-file=", workflow)

        destroy = yaml.safe_load((REPO_ROOT / ".github/workflows/gcp-dev-destroy.yml").read_text(encoding="utf-8"))
        self.assertEqual(destroy["jobs"]["destroy"]["env"]["GCP_ENVIRONMENT"], "gcp-dev")

    def test_gcp_bootstrap_secrets_never_reach_process_argv(self):
        workflow = (REPO_ROOT / ".github/workflows/_gcp-dev.yml").read_text(encoding="utf-8")
        self.assertNotIn("--from-literal", workflow)
        self.assertIn("--from-env-file", workflow)

    def test_gcp_checkov_decisions_are_resource_scoped(self):
        config = (REPO_ROOT / "platform/terraform/.checkov.yaml").read_text(encoding="utf-8")
        self.assertNotIn("- CKV_GCP_", config)
        self.assertNotIn("- CKV2_GCP_", config)

        gcp_root = REPO_ROOT / "platform/terraform/gcp/modules/portal"
        sources = "\n".join(path.read_text(encoding="utf-8") for path in sorted(gcp_root.rglob("*.tf")))
        for finding in (
            "CKV_GCP_6",
            "CKV_GCP_12",
            "CKV_GCP_21",
            "CKV_GCP_62",
            "CKV_GCP_65",
            "CKV_GCP_79",
            "CKV_GCP_83",
            "CKV_GCP_107",
            "CKV_GCP_109",
            "CKV_GCP_111",
            "CKV_GCP_124",
            "CKV2_GCP_10",
        ):
            self.assertIn(f"checkov:skip={finding}", sources)

        self.assertIn("group:cloud-storage-analytics@google.com", sources)
        self.assertIn('role   = "roles/storage.objectCreator"', sources)


class TestGithubEnvironmentBinding(unittest.TestCase):
    """#935 / ADR-003-R5: mutating deploy jobs bind a GitHub Environment."""

    EXPECTED = {
        "_core.yml": ("apply",),
        "_range.yml": ("apply",),
        "_shifter-engine.yml": ("build", "deploy"),
        "_shifter-platform.yml": ("push-guacamole-images", "apply", "build", "deploy"),
        "_gcp-dev.yml": ("prepare", "deploy"),
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


class TestGcpPrivateControlPlaneAccess(unittest.TestCase):
    """#1850: every GCP deploy credential refresh stays on Connect Gateway."""

    def test_gcp_deploy_never_reverts_to_direct_endpoint_credentials(self):
        workflow = (REPO_ROOT / ".github/workflows/_gcp-dev.yml").read_text(encoding="utf-8")
        self.assertNotIn("google-github-actions/get-gke-credentials@", workflow)
        self.assertGreaterEqual(
            workflow.count("gcloud container fleet memberships get-credentials"),
            2,
            "GCP deploy must configure Connect Gateway before bootstrap work and refresh it before applying workloads",
        )


class TestGcpDeployPreflightInputs(unittest.TestCase):
    """#2083: the shared preflight receives every required deployment input."""

    def test_shifter_config_secret_reaches_the_preflight_step(self):
        workflow = _load("_gcp-dev.yml")
        jobs = ADR_GUARD._dw_jobs(workflow, "_gcp-dev.yml")
        step = next(
            item for item in jobs["prepare"]["steps"] if item.get("name") == "Preflight - validate deploy prerequisites"
        )
        self.assertEqual(
            step.get("env", {}).get("SHIFTER_CONFIG_GCP_DEV"),
            "${{ secrets.SHIFTER_CONFIG_GCP_DEV }}",
        )


class TestRangePlacementSingleSource(unittest.TestCase):
    """#2029: multi-region range placement and per-region NAT consume ONE input.

    ``RANGE_NETWORK_ZONES`` is the canonical operator setting. It reaches two
    consumers with different shapes: the runtime renderer as CSV (the provisioner
    reads back the per-range zone chosen at creation), and Terraform as a list
    (``range_network_zones``, which derives per-region range NAT). If those two
    drifted apart, a range could be placed in a region with no NAT and silently
    lose its egress path. Both must be projected from the same
    ``vars.RANGE_NETWORK_ZONES``.
    """

    def test_runtime_and_terraform_derive_from_the_same_variable(self):
        workflow = (REPO_ROOT / ".github/workflows/_gcp-dev.yml").read_text(encoding="utf-8")
        # Runtime CSV consumer (renderer -> ConfigMap -> platform placement).
        self.assertIn("RANGE_NETWORK_ZONES: ${{ vars.RANGE_NETWORK_ZONES }}", workflow)
        # Terraform list consumer (range_network_zones -> per-region NAT), derived
        # from the SAME variable, never a separate independent input.
        self.assertIn("TF_VAR_range_network_zones=", workflow)
        self.assertGreaterEqual(
            workflow.count("vars.RANGE_NETWORK_ZONES"),
            2,
            "RANGE_NETWORK_ZONES must feed both the runtime renderer and the "
            "Terraform range_network_zones tfvar from one canonical operator variable",
        )
        # The Terraform tfvar must be independent variables that could diverge; it is
        # derived from RANGE_NETWORK_ZONES, so a standalone range_nat_regions input
        # (the divergence hazard) must not reappear.
        self.assertNotIn("range_nat_regions", workflow)


class TestProvisionerDeployTestGate(unittest.TestCase):
    """#555: engine image build/deploy is gated by provisioner tests."""

    @classmethod
    def setUpClass(cls):
        cls.engine = _load("_shifter-engine.yml")
        cls.jobs = ADR_GUARD._dw_jobs(cls.engine, "_shifter-engine.yml")

    @staticmethod
    def _needs(job) -> set[str]:
        needs = job.get("needs", [])
        if isinstance(needs, str):
            return {needs}
        return set(needs)

    def test_engine_workflow_has_hosted_provisioner_test_gate(self):
        self.assertIn(
            "test",
            self.jobs,
            "_shifter-engine.yml lost the provisioner test gate (#555)",
        )
        test_job = self.jobs["test"]
        self.assertEqual(test_job.get("runs-on"), "ubuntu-latest")
        self.assertEqual(test_job.get("permissions"), {"contents": "read"})
        self.assertNotIn("environment", test_job)

        steps = test_job.get("steps", [])
        expected_commands = (
            "uv sync --group dev",
            "uv run --with pytest-cov pytest tests/ --cov=. --cov-report=xml:coverage.xml",
        )
        for command in expected_commands:
            matching_steps = [step for step in steps if command in str(step.get("run", ""))]
            self.assertTrue(matching_steps, f"test job missing `{command}`")
            for step in matching_steps:
                self.assertEqual(
                    step.get("working-directory"),
                    "shifter/engine/provisioner",
                    f"step running `{command}` must run from the provisioner directory",
                )

    def test_engine_build_and_deploy_depend_on_provisioner_tests(self):
        for job_id in ("validate", "build", "deploy"):
            self.assertIn(
                job_id,
                self.jobs,
                f"_shifter-engine.yml lost job '{job_id}'",
            )
            self.assertIn(
                "test",
                self._needs(self.jobs[job_id]),
                f"_shifter-engine.yml job '{job_id}' must depend on provisioner tests (#555)",
            )


class TestEngineValidateRunnerPlacement(unittest.TestCase):
    """#1474: the engine `validate` image-shape gate runs on the trusted
    self-hosted runner class so a GitHub-hosted runner-acquisition stall cannot
    cancel it before steps start (which skipped the whole Platform stage). It is
    hardened as defense in depth. Runner placement is pinned here as parsed
    workflow structure - runner class, PR reachability, permissions, needs, and
    timeout backstop - so the next placement change has one test surface to
    update. ``TestRunnerExposure`` already proves the generic PR-denial /
    push-reachability invariant for every self-hosted job.
    """

    @classmethod
    def setUpClass(cls):
        cls.engine = _load("_shifter-engine.yml")
        cls.jobs = ADR_GUARD._dw_jobs(cls.engine, "_shifter-engine.yml")
        cls.validate = cls.jobs["validate"]

    def test_validate_runs_on_self_hosted(self):
        self.assertTrue(
            ADR_GUARD._dw_is_self_hosted(self.validate),
            "_shifter-engine.yml `validate` must run on the self-hosted runner "
            "class (#1474); GitHub-hosted acquisition stalls cancelled the job "
            "and skipped Platform.",
        )

    def test_validate_denied_on_pull_request_but_runs_on_push(self):
        expr = ADR_GUARD._dw_job_if(self.validate)
        self.assertTrue(
            ADR_GUARD._dw_job_denied_on_pull_request(expr),
            f"`validate` is self-hosted and must fail closed on pull_request (ADR-003-R5). if: {expr}",
        )
        self.assertTrue(
            ADR_GUARD._dw_evaluate_if(expr, event_name="push"),
            f"`validate` must still run on push or its PR-denial is vacuous. if: {expr}",
        )

    def test_validate_depends_on_provisioner_test_gate(self):
        needs = self.validate.get("needs", [])
        needs = {needs} if isinstance(needs, str) else set(needs)
        self.assertIn(
            "test",
            needs,
            "`validate` must depend on the #555 provisioner test gate",
        )

    def test_validate_keeps_minimal_permissions(self):
        # Validate does a local image build only and takes no cloud credentials;
        # it must not request id-token / attestations or any write scope.
        self.assertEqual(
            self.validate.get("permissions"),
            {"contents": "read"},
            "`validate` must keep contents:read only (no OIDC / attestations)",
        )

    def test_validate_has_timeout_backstop(self):
        timeout = self.validate.get("timeout-minutes")
        self.assertIsInstance(
            timeout,
            int,
            "`validate` must set a timeout-minutes backstop (#1220 convention)",
        )
        self.assertGreater(timeout, 0)


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
        engine_main = self._read("platform/terraform/modules/engine-provisioner/main.tf")
        engine_task = self._read("platform/terraform/modules/engine-provisioner/task_definition.tf")
        engine_vars = self._read("platform/terraform/modules/engine-provisioner/variables.tf")
        platform_wf = self._active_text(".github/workflows/_shifter-platform.yml")
        deploy_wf = self._active_text(".github/workflows/deploy.yml")

        self.assertNotIn('data "aws_ecr_image"', engine_main)
        self.assertIn('variable "container_image_digest"', engine_vars)
        self.assertIn("${var.ecr_repository_url}@${var.container_image_digest}", engine_task)
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
            ADR_GUARD._dw_load_workflow(REPO_ROOT, ".github/workflows/does-not-exist.yml")

    def test_missing_jobs_raises(self):
        with self.assertRaises(ADR_GUARD._DwShapeError):
            ADR_GUARD._dw_jobs({"name": "x"}, "fixture")

    def test_missing_paths_filter_step_raises(self):
        with self.assertRaises(ADR_GUARD._DwShapeError):
            ADR_GUARD._dw_parse_paths_filter({"jobs": {"changes": {"steps": []}}}, "changes", "filter")


class TestWorkflowActionShaPinning(unittest.TestCase):
    """ADR-037-R1: every non-local ``uses:`` in a cloud-credentialed workflow
    must pin a full 40-hex commit SHA (``workflow-action-sha-pinning`` check).

    A cloud-credentialed workflow is one that requests ``id-token: write``, runs
    on a self-hosted runner, invokes a cloud-auth action
    (``aws-actions/configure-aws-credentials`` / ``google-github-actions/auth``),
    or passes a ``workload_identity_provider``. In such a workflow an unpinned
    action is an executable dependency that can move under a maintained tag and
    run with cloud credentials, so a mutable ref is a supply-chain exposure.
    """

    RULE = "ADR-037-R1"
    SHA = "df4cb1c069e1874edd31b4311f1884172cec0e10"  # a real 40-hex commit sha

    @staticmethod
    def _write_wf(root: Path, name: str, content: str) -> None:
        wf_dir = root / ".github" / "workflows"
        wf_dir.mkdir(parents=True, exist_ok=True)
        (wf_dir / name).write_text(content, encoding="utf-8")

    def test_check_passes_on_real_workflows(self):
        self.assertEqual(ADR_GUARD.check_workflow_action_sha_pinning(REPO_ROOT, None), [])

    def test_mutable_ref_in_credentialed_workflow_is_flagged(self):
        wf = (
            "name: cred\n"
            "on: [push]\n"
            "jobs:\n"
            "  build:\n"
            "    runs-on: ubuntu-latest\n"
            "    permissions:\n"
            "      id-token: write\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_wf(root, "cred.yml", wf)
            violations = ADR_GUARD.check_workflow_action_sha_pinning(root, None)
            self.assertTrue(violations)
            self.assertTrue(all(v.rule_id == self.RULE for v in violations))
            self.assertTrue(any("actions/checkout" in v.message for v in violations))

    def test_sha_pinned_ref_in_credentialed_workflow_passes(self):
        wf = (
            "name: cred\n"
            "on: [push]\n"
            "jobs:\n"
            "  build:\n"
            "    runs-on: [self-hosted]\n"
            "    steps:\n"
            f"      - uses: actions/checkout@{self.SHA} # v6.0.3\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_wf(root, "cred.yml", wf)
            self.assertEqual(ADR_GUARD.check_workflow_action_sha_pinning(root, None), [])

    def test_cloud_auth_action_marks_workflow_credentialed(self):
        wf = (
            "name: aws\n"
            "on: [push]\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - uses: aws-actions/configure-aws-credentials@v4\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_wf(root, "aws.yml", wf)
            violations = ADR_GUARD.check_workflow_action_sha_pinning(root, None)
            self.assertTrue(violations)
            self.assertTrue(all(v.rule_id == self.RULE for v in violations))

    def test_noncredentialed_workflow_is_out_of_scope(self):
        wf = (
            "name: lint\n"
            "on: [push]\n"
            "jobs:\n"
            "  lint:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_wf(root, "lint.yml", wf)
            self.assertEqual(ADR_GUARD.check_workflow_action_sha_pinning(root, None), [])

    def test_local_reusable_workflow_ref_is_allowed(self):
        wf = (
            "name: orch\n"
            "on: [push]\n"
            "permissions:\n"
            "  id-token: write\n"
            "jobs:\n"
            "  call:\n"
            "    uses: ./.github/workflows/_core.yml\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_wf(root, "orch.yml", wf)
            self.assertEqual(ADR_GUARD.check_workflow_action_sha_pinning(root, None), [])

    def test_mutable_docker_action_in_credentialed_workflow_is_flagged(self):
        wf = (
            "name: cred\n"
            "on: [push]\n"
            "jobs:\n"
            "  build:\n"
            "    runs-on: ubuntu-latest\n"
            "    permissions:\n"
            "      id-token: write\n"
            "    steps:\n"
            "      - uses: docker://registry.example/action:v1\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_wf(root, "cred.yml", wf)
            violations = ADR_GUARD.check_workflow_action_sha_pinning(root, None)
            self.assertTrue(violations)
            self.assertTrue(all(v.rule_id == self.RULE for v in violations))
            self.assertTrue(any("docker://" in v.message for v in violations))

    def test_digest_pinned_docker_action_passes(self):
        wf = (
            "name: cred\n"
            "on: [push]\n"
            "jobs:\n"
            "  build:\n"
            "    runs-on: ubuntu-latest\n"
            "    permissions:\n"
            "      id-token: write\n"
            f"    steps:\n"
            f"      - uses: docker://registry.example/action@sha256:{'a' * 64}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_wf(root, "cred.yml", wf)
            self.assertEqual(ADR_GUARD.check_workflow_action_sha_pinning(root, None), [])

    def test_unparseable_workflow_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_wf(root, "broken.yml", "this: [is: not: valid: yaml\n")
            violations = ADR_GUARD.check_workflow_action_sha_pinning(root, None)
            self.assertTrue(violations)
            self.assertTrue(all(v.rule_id == self.RULE for v in violations))

    def test_changed_scope_ignores_unrelated_files(self):
        # With an explicit changed-file set that touches no workflow and not the
        # adr_guard script, the check is a no-op (path-gated like its siblings).
        self.assertEqual(
            ADR_GUARD.check_workflow_action_sha_pinning(REPO_ROOT, ["shifter/shifter_platform/README.md"]),
            [],
        )


class CloudCredentialClassificationTests(unittest.TestCase):
    """Broadened ADR-037-R1 credential classification (#998 codex security finding).

    A job or workflow that holds a named secret - static ``env`` / step ``with``
    values, a ``secrets:`` mapping, ``secrets: inherit``, or a workflow-level
    ``env`` secret - is credential-bearing, so its remote actions must be
    SHA-pinned even without OIDC or a recognized auth action. GITHUB_TOKEN alone
    does not qualify (it is present by default and its elevated uses are already
    covered by the permission/OIDC markers).
    """

    DW = ADR_GUARD.deploy_workflow

    def test_static_env_secret_makes_job_credentialed(self):
        job = {
            "runs-on": "ubuntu-latest",
            "env": {"AWS_SECRET_ACCESS_KEY": "${{ secrets.AWS_SECRET }}"},
        }
        self.assertTrue(self.DW._dw_job_is_cloud_credentialed(job))

    def test_secret_passed_to_step_with_makes_job_credentialed(self):
        job = {
            "runs-on": "ubuntu-latest",
            "steps": [
                {
                    "uses": "some/action@v1",
                    "with": {"token": "${{ secrets.DEPLOY_TOKEN }}"},
                }
            ],
        }
        self.assertTrue(self.DW._dw_job_is_cloud_credentialed(job))

    def test_secrets_inherit_makes_job_credentialed(self):
        self.assertTrue(
            self.DW._dw_job_is_cloud_credentialed({"uses": "./.github/workflows/reusable.yml", "secrets": "inherit"})
        )

    def test_secrets_mapping_makes_job_credentialed(self):
        job = {
            "uses": "./.github/workflows/reusable.yml",
            "secrets": {"SONAR_TOKEN": "${{ secrets.SONAR_TOKEN }}"},
        }
        self.assertTrue(self.DW._dw_job_is_cloud_credentialed(job))

    def test_github_token_alone_is_not_credentialed(self):
        job = {"runs-on": "ubuntu-latest", "env": {"GH": "${{ secrets.GITHUB_TOKEN }}"}}
        self.assertFalse(self.DW._dw_job_is_cloud_credentialed(job))

    def test_workflow_level_env_secret_makes_workflow_credentialed(self):
        wf = {
            "env": {"TF_TOKEN": "${{ secrets.TF_API_TOKEN }}"},
            "jobs": {"a": {"runs-on": "ubuntu-latest", "steps": [{"uses": "x/y@v1"}]}},
        }
        self.assertTrue(self.DW._dw_workflow_is_cloud_credentialed(wf))

    def test_github_token_only_workflow_stays_uncredentialed(self):
        wf = {
            "jobs": {
                "a": {
                    "runs-on": "ubuntu-latest",
                    "env": {"GH": "${{ secrets.GITHUB_TOKEN }}"},
                    "steps": [{"uses": "x/y@v1"}],
                }
            }
        }
        self.assertFalse(self.DW._dw_workflow_is_cloud_credentialed(wf))

    def test_quality_workflow_is_credentialed_and_all_actions_pinned(self):
        # _quality.yml receives SONAR_TOKEN, so it must classify as credentialed;
        # ADR-037-R1 then requires every remote action across the repo's workflows
        # to be SHA-pinned. Regression for the #998 finding and its fix.
        wf = ADR_GUARD._dw_load_workflow(REPO_ROOT, ".github/workflows/_quality.yml")
        self.assertTrue(self.DW._dw_workflow_is_cloud_credentialed(wf))
        self.assertEqual(ADR_GUARD.check_workflow_action_sha_pinning(REPO_ROOT, None), [])


if __name__ == "__main__":
    unittest.main()
