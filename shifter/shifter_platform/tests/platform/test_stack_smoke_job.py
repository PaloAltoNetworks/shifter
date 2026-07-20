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
PAGE_HELPER = SMOKE_DIR / "page_smoke.py"
STUB_IDP = SMOKE_DIR / "stub_idp.py"
LOGIN_PROBE = SMOKE_DIR / "oidc_login.py"
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
    assert PAGE_HELPER.is_file()
    assert STUB_IDP.is_file()
    assert LOGIN_PROBE.is_file()
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
    # Reuses the callback-established session via a mode-0600 file handoff (#988),
    # not a second directly minted session.
    assert "--session-file" in smoke_script


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


# ---------------------------------------------------------------------------
# Real OIDC login contract (issue #988)
# ---------------------------------------------------------------------------


def test_harness_drives_real_oidc_login(smoke_script: str) -> None:
    # The session must be obtained through the real authorization-code flow
    # against the local provider double, not minted directly (#988).
    assert "oidc_login.py" in smoke_script
    assert "stub_idp.py" in smoke_script
    assert "OIDC_AUTH_DOMAIN" in smoke_script
    assert "OIDC_ISSUER_URL" in smoke_script


def test_harness_has_no_direct_session_shortcut(smoke_script: str) -> None:
    # Acceptance criterion (#988): the #922 direct-session shortcut must not
    # return - no SessionStore mint, no force_login, no /dev-login bypass.
    assert "SessionStore" not in smoke_script
    assert "_auth_user_id" not in smoke_script
    assert "force_login" not in smoke_script
    assert "/dev-login" not in smoke_script
    # The session value is handed off by file path, never on argv.
    assert "--session-file" in smoke_script
    assert "--session " not in smoke_script


def test_harness_proves_first_login_provisioning(smoke_script: str) -> None:
    # Acceptance criterion (#988): prove the account is absent before the flow,
    # then created + identity-bound by the callback (not a directly written row).
    # Match the definition AND the enforcing call (count >= 2): a bare-name check
    # stays green if the invocation is deleted while the function body remains
    # (the #922 "defined but never called" lesson; cf. assert_home_writable).
    assert smoke_script.count("assert_oidc_user_absent") >= 2
    assert smoke_script.count("assert_oidc_user_provisioned") >= 2
    assert "UserProfile" in smoke_script
    assert "cognito_sub" in smoke_script
    assert "issuer" in smoke_script


def test_harness_redacts_secrets_in_failure_logs(smoke_script: str) -> None:
    # gunicorn / IdP request lines can carry the auth code, state, nonce, tokens,
    # and session key; the bounded failure log tail must redact them (#988).
    # Assert the redaction expression covers each secret-bearing field by name,
    # not merely that the word REDACTED appears somewhere (a narrowed field list
    # would keep this green while leaking a real session key / client secret).
    redaction = "\n".join(ln for ln in smoke_script.splitlines() if "REDACTED" in ln)
    assert redaction, "no redaction expression found in the failure-log tail"
    for field in ("code", "state", "nonce", "access_token", "id_token", "sessionid", "client_secret"):
        assert field in redaction, f"redaction expression does not cover {field}"


def test_stub_idp_is_cognito_shaped_and_fail_closed() -> None:
    stub = STUB_IDP.read_text(encoding="utf-8")
    # Exact Cognito endpoint shapes config._oidc_settings derives - not a generic
    # mock's paths (which would force weakening production endpoint construction).
    assert "/oauth2/authorize" in stub
    assert "/oauth2/token" in stub
    assert "/oauth2/userInfo" in stub
    assert "/.well-known/jwks.json" in stub
    # RS256 signing with a published JWKS; the signing call must never use a
    # symmetric HS* or "none" algorithm (docstring prose may still mention them).
    assert 'algorithm="RS256"' in stub
    assert 'algorithm="HS256"' not in stub
    assert 'algorithm="none"' not in stub
    # Literal-boolean email_verified true (a truthy string must not pass).
    assert '"email_verified": True' in stub
    # Fail-closed: rejects wrong client, reused/invalid grant, and bad tokens.
    assert "invalid_client" in stub
    assert "invalid_grant" in stub
    assert "invalid_token" in stub


def test_login_probe_runs_real_flow_and_is_redaction_safe() -> None:
    probe = LOGIN_PROBE.read_text(encoding="utf-8")
    # Starts at the public /login router and traverses the real callback.
    assert "/login" in probe
    assert "callback" in probe
    # Preserves the logical-HTTPS production posture across portal hops.
    assert "X-Forwarded-Proto" in probe
    # Never logs secret-bearing full URLs / query strings. Match the definition
    # AND at least one call (count >= 2), so removing the redaction call fails.
    assert probe.count("_redact") >= 2


def test_probes_read_session_from_file_not_argv() -> None:
    # The session value must never appear on a probe's argv (#988): its path,
    # not its value, is the argument.
    for helper in (WS_HELPER, PAGE_HELPER):
        text = helper.read_text(encoding="utf-8")
        assert "--session-file" in text
        assert '"--session"' not in text
