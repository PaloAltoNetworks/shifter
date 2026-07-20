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
        return ADR_GUARD._dw_evaluate_env(
            self.script, event_name, ref=ref, base_ref=base_ref
        )

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
        framework_path = (
            "shifter/shifter_platform/shared/scenario_verification/__init__.py"
        )
        self.assertTrue(
            ADR_GUARD._dw_path_matches_any(
                framework_path, self.filters["shifter_platform"]
            )
        )
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
        self.assertTrue(
            ADR_GUARD._dw_path_matches_any(
                polaris_test_path, self.filters["polaris_tests"]
            )
        )
        path_outputs = self.jobs["paths"].get("outputs", {})
        self.assertIn("polaris_tests", path_outputs)
        job = self.jobs["polaris-tests"]
        self.assertIn(
            "needs.paths.outputs.polaris_tests", ADR_GUARD._dw_job_if(job)
        )
        run_steps = "\n".join(
            str(step.get("run", "")) for step in job.get("steps", [])
        )
        self.assertIn("python3 -m compileall", run_steps)
        self.assertIn('bash -n "$script"', run_steps)

    def test_adapter_specific_quality_route_is_removed(self):
        self.assertNotIn("scenario_smoketest", self.filters)
        path_outputs = self.jobs["paths"].get("outputs", {})
        self.assertNotIn("scenario_smoketest", path_outputs)
        self.assertNotIn("scenario-smoketest-tests", self.jobs)


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
            matching_steps = [
                step for step in steps if command in str(step.get("run", ""))
            ]
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
            f"`validate` is self-hosted and must fail closed on pull_request "
            f"(ADR-003-R5). if: {expr}",
        )
        self.assertTrue(
            ADR_GUARD._dw_evaluate_if(expr, event_name="push"),
            f"`validate` must still run on push or its PR-denial is vacuous. "
            f"if: {expr}",
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
        self.assertEqual(
            ADR_GUARD.check_workflow_action_sha_pinning(REPO_ROOT, None), []
        )

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
            self.assertTrue(
                any("actions/checkout" in v.message for v in violations)
            )

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
            self.assertEqual(
                ADR_GUARD.check_workflow_action_sha_pinning(root, None), []
            )

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
            self.assertEqual(
                ADR_GUARD.check_workflow_action_sha_pinning(root, None), []
            )

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
            self.assertEqual(
                ADR_GUARD.check_workflow_action_sha_pinning(root, None), []
            )

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
            self.assertEqual(
                ADR_GUARD.check_workflow_action_sha_pinning(root, None), []
            )

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
            ADR_GUARD.check_workflow_action_sha_pinning(
                REPO_ROOT, ["shifter/shifter_platform/README.md"]
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
