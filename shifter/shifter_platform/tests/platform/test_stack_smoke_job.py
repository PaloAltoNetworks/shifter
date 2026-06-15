"""Built-image stack-smoke CI contract invariants (issue #922).

CI can pass while the production portal *image* cannot boot under its real
``entrypoint.sh`` with the dependencies it needs at runtime: the entire June-7
hotfix wave (portal home-directory, worker container healthchecks) was
container-runtime failures invisible to the pytest estate, which runs against
the source tree with test settings rather than the built image.

These tests pin the structural contract of the stack-smoke job and its reusable
harness so the gate itself is regression-protected:

* ``_quality.yml`` carries a ``run_stack_smoke`` input and a ``stack-smoke`` job
  that is gated on it, requests no cloud identity, and runs the harness.
* ``deploy.yml`` drives that input from the existing ``portal_image`` /
  ``shifter_platform`` path filters (no duplicate changed-file parsing).
* the harness builds the *production* image (context ``./shifter``), boots it
  through the real ``entrypoint.sh``, runs migrations exactly once and boots the
  long-running containers with ``SKIP_MIGRATIONS=1``, and asserts the existing
  ``/health`` readiness probe, an authenticated websocket handshake, and the
  worker / scheduler heartbeat files — never merely "the container is running".

They are text-substring invariants (same style as ``test_portal_dockerfile.py``)
so they fire on a real regression without coupling to YAML formatting.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
QUALITY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "_quality.yml"
DEPLOY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
SMOKE_DIR = REPO_ROOT / "scripts" / "stack-smoke"
SMOKE_SCRIPT = SMOKE_DIR / "stack_smoke.sh"
WS_HELPER = SMOKE_DIR / "ws_handshake.py"
ELASTICMQ_CONF = SMOKE_DIR / "elasticmq.conf"


@pytest.fixture(scope="module")
def quality_yml() -> str:
    return QUALITY_WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def deploy_yml() -> str:
    return DEPLOY_WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def smoke_script() -> str:
    return SMOKE_SCRIPT.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Workflow wiring
# ---------------------------------------------------------------------------


def test_quality_workflow_declares_run_stack_smoke_input(quality_yml: str) -> None:
    assert "run_stack_smoke:" in quality_yml
    # The job must be gated on the input, not run unconditionally on every PR.
    assert "inputs.run_stack_smoke" in quality_yml


def test_quality_workflow_has_stack_smoke_job_running_the_harness(quality_yml: str) -> None:
    assert "stack-smoke:" in quality_yml
    assert "scripts/stack-smoke/stack_smoke.sh" in quality_yml


def test_stack_smoke_job_requests_no_cloud_identity(quality_yml: str) -> None:
    # Hosted-runner smoke: no OIDC, no cloud role, no write scopes. The whole
    # workflow must stay free of id-token escalation.
    assert "id-token: write" not in quality_yml


def test_deploy_drives_smoke_from_portal_image_and_platform_filters(deploy_yml: str) -> None:
    assert "run_stack_smoke:" in deploy_yml
    # Reuse the existing path signals rather than recomputing changed files.
    assert "needs.changes.outputs.portal_image" in deploy_yml
    assert "needs.changes.outputs.shifter_platform" in deploy_yml


def test_deploy_reruns_smoke_when_its_own_implementation_changes(deploy_yml: str) -> None:
    # A CI guardrail must run when its own implementation changes; otherwise the
    # harness can be edited and merged without ever booting the built image.
    assert "stack_smoke:" in deploy_yml
    assert "scripts/stack-smoke/**" in deploy_yml
    assert "needs.changes.outputs.stack_smoke" in deploy_yml


# ---------------------------------------------------------------------------
# Harness contract
# ---------------------------------------------------------------------------


def test_harness_files_exist() -> None:
    assert SMOKE_SCRIPT.is_file()
    assert WS_HELPER.is_file()
    assert ELASTICMQ_CONF.is_file()


def test_harness_builds_production_image_context(smoke_script: str) -> None:
    # Same image shape as deploy: context ./shifter, file shifter_platform/Dockerfile.
    assert "shifter_platform/Dockerfile" in smoke_script
    assert "docker build" in smoke_script


def test_harness_boots_real_entrypoint_not_a_bypass(smoke_script: str) -> None:
    # The web container must run the image's own ENTRYPOINT (gunicorn/uvicorn),
    # never a runserver/daphne/direct-gunicorn override that skips entrypoint.sh.
    assert "runserver" not in smoke_script
    assert "daphne" not in smoke_script


def test_harness_runs_migrations_exactly_once(smoke_script: str) -> None:
    # One explicit migrate; long-running containers skip their entrypoint migrate.
    assert "manage.py migrate" in smoke_script
    assert "SKIP_MIGRATIONS=1" in smoke_script


def test_harness_skip_migrations_assertion_is_retry_bounded(smoke_script: str) -> None:
    # A single-shot `docker logs | grep "Skipping migrations"` raced docker
    # log-delivery behind the readiness probe and flaked (#922). The assertion
    # must poll with a bounded deadline (like wait_for) so a genuine
    # SKIP_MIGRATIONS contract break still fails (the entrypoint logs "Running
    # migrations" instead) while a pure delivery race is absorbed.
    assert "SMOKE_LOG_ASSERT_TIMEOUT" in smoke_script
    start = smoke_script.index("assert_skipped_migrations()")
    body = smoke_script[start : smoke_script.index("\n}", start)]
    assert "while" in body, "skip-migrations assertion must poll, not check exactly once"
    assert "SMOKE_LOG_ASSERT_TIMEOUT" in body
    assert "SKIP_MIGRATIONS contract broken" in body


def test_harness_uses_production_posture_not_test_settings(smoke_script: str) -> None:
    # The validators that historically failed only in the built artifact must run:
    # no TESTING=1, no DJANGO_DEBUG=true, no /dev-login bypass.
    assert "TESTING=1" not in smoke_script
    assert "DJANGO_DEBUG=true" not in smoke_script
    assert "ENVIRONMENT=development" not in smoke_script


def test_harness_uses_local_doubles_no_cloud_credentials(smoke_script: str) -> None:
    # Worker heartbeat is proven against a local SQS double, not real SQS.
    assert "AWS_ENDPOINT_URL" in smoke_script


def test_harness_asserts_health_ws_and_worker_heartbeats(smoke_script: str) -> None:
    assert "/health" in smoke_script
    assert "ws_handshake.py" in smoke_script
    assert "worker-cms-heartbeat" in smoke_script
    assert "ctf-scheduler-heartbeat" in smoke_script


def test_harness_asserts_authenticated_page_renders(smoke_script: str) -> None:
    # The range-independent half of the post-deploy functional gate (#923 TEST-3):
    # render real authenticated pages off the built image and assert their static
    # assets resolve, catching the missing-terminal-sourcemaps / static class.
    assert "page_smoke.py" in smoke_script
    assert "/mission-control/terminal/" in smoke_script
    assert "$session_key" in smoke_script  # reuses the authenticated WS session


def test_page_smoke_helper_checks_static_and_sourcemaps() -> None:
    helper = WS_HELPER.parent.joinpath("page_smoke.py").read_text(encoding="utf-8")
    assert "/static/" in helper
    assert "sourceMappingURL" in helper
    # Mirrors the production ALB so the DEBUG=False image serves instead of
    # issuing its HTTPS redirect.
    assert "X-Forwarded-Proto" in helper


def test_harness_does_not_override_image_user(smoke_script: str) -> None:
    # The /home/appuser HOME regression is only caught when the container runs as
    # the image's non-root user; the harness must not pass --user/-u to escape it.
    assert "--user" not in smoke_script
    assert "-u 0" not in smoke_script


def test_harness_asserts_home_directory_writable(smoke_script: str) -> None:
    # Acceptance criterion #1: reverting the June-7 home-directory fix must fail
    # the job. The boot/health path does not exercise HOME, so the harness has an
    # explicit writability check against the running container's real user,
    # covering HOME and the terraform/pulumi cache dirs the Dockerfile creates.
    # Match the call site, not the bare function name: asserting the function is
    # merely *defined* would stay green if the enforcing call were deleted.
    assert 'assert_home_writable "$WEB"' in smoke_script
    assert ".terraform.d/plugin-cache" in smoke_script
    assert ".pulumi" in smoke_script


def test_ws_helper_targets_authenticated_notifications_route() -> None:
    helper = WS_HELPER.read_text(encoding="utf-8")
    # Real routed consumer through AllowedHostsOriginValidator + AuthMiddlewareStack.
    assert "sessionid" in helper
    assert "Origin" in helper
