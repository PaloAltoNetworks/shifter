# Post-Deploy Smoke Test Preflight (#218)

Status: pre-implementation guidance

Date: 2026-06-24

Issue: GitHub #218, "Add post-deploy smoke test with auto-issue creation on
failure".

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is intentionally not an
implementation plan.

## Scope Boundary

Treat this as a live dev-environment verification problem, not a new range
provisioning subsystem, deployment gate, public API, auth model, health
framework, or observability platform.

Keep these concepts separate:

1. Built-image stack smoke: `scripts/stack-smoke/stack_smoke.sh` proves the
   production image boots locally with doubles and no cloud credentials.
2. Post-deploy health verification: `_shifter-platform.yml` and
   `scripts/portal_deploy/portal_deploy.py verify-post-deploy` fail loud when
   the deployed portal/Guacamole health contract is broken.
3. Live range smoke: this issue provisions and tears down a real dev range, then
   checks guest connectivity through existing range/terminal/Guacamole
   contracts.
4. Event/load validation: `uat/event-load-harness` and the native CTF smoke
   protocol cover event-scale behavior; this issue should stay a small
   operational readiness check.

The smoke may be non-blocking for deployment success, but it still consumes
runner time, cloud quota, and range capacity. `continue-on-error` only changes
the job conclusion; it does not detach the work from the workflow run or make
the duration free.

## Architecture Decisions

- Keep the operator-facing local entrypoint named `scripts/smoke-test.sh`, as
  requested by the issue. If the logic grows beyond simple orchestration, the
  shell script should delegate to a typed script module with `argparse`,
  bounded polling, structured output, and fixed-argv subprocess calls.
- Run only after trusted dev deploys. Pull requests must not reach deploy
  runners, cloud roles, smoke credentials, or issue creation. Reuse the
  branch/event/environment gates already encoded in `.github/workflows/deploy.yml`,
  `_shifter-platform.yml`, and `_gcp-dev.yml`.
- The smoke is advisory. A failure must create or update a GitHub issue, but it
  must not turn a successful dev deploy red unless a later ADR explicitly
  changes deploy policy.
- Use existing range lifecycle contracts. Provision through the CTF/CMS/engine
  service boundary or the existing HTTP API boundary once authenticated; do not
  create Terraform directly, write range rows by hand, or invent a separate
  range schema for smoke state.
- Use existing scenario templates. Parameterize the Linux and Windows variants
  by scenario/victim OS instead of creating a special smoke-only scenario
  format. The implementation must verify that the selected template hydrates to
  the expected guest OS/protocol set; if no current template fits, add a normal
  schema-valid scenario through `cms.scenarios` rather than a smoke-private
  schema.
- Verify connectivity through the product access boundary wherever possible:
  `engine.services.get_ssh_connection_info`, `get_rdp_connection_info`,
  `connect_terminal`, and the Guacamole URL builders already own readiness,
  ownership, secret resolution, and error handling. A raw port probe may be a
  secondary signal, not a replacement for those checks.
- Always tear down the range using the request-id / `RangeInstance` ownership
  paths, even when provisioning, reachability, or issue creation fails. The
  script must be safe to interrupt and must leave a bounded diagnostic trail.
- Failed-smoke issue creation should use the default `GITHUB_TOKEN` with
  minimal `issues: write` permission, bounded sanitized logs, and a dedupe key
  that includes environment, provider, variant, and commit SHA. Do not use a PAT
  or create a new GitHub integration.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #218 |
| --- | --- | --- |
| Deploy routing | `.github/workflows/deploy.yml` change/env matrix | Derive dev smoke eligibility from existing trusted deploy outputs and branch gates; do not duplicate ad hoc branch parsing. |
| AWS post-deploy verification | `.github/workflows/_shifter-platform.yml`, `scripts/portal_deploy/portal_deploy.py verify-post-deploy` | Run the range smoke after existing portal/Guacamole health succeeds; do not weaken fail-loud deploy verification. |
| GCP deploy verification | `.github/workflows/_gcp-dev.yml`, GKE rollout/certificate gates | Preserve GCP OIDC, rollout, runtime-render, and certificate gates before any live range smoke. |
| Built-image smoke | `scripts/stack-smoke/stack_smoke.sh`, `scripts/stack-smoke/README.md` | Reuse one-command script discipline, bounded diagnostics, and cleanup posture, but keep this live-cloud smoke separate. |
| Native CTF smoke protocol | `shifter/shifter_platform/documentation/docs/qa/native-ctf-smoketest.md` | Use the documented participant range lifecycle as product context; keep event-scale/manual browser checks out of this issue. |
| Scenario contracts | `cms.scenarios.registry`, `cms.scenarios.schema`, YAML templates under `cms/scenarios/templates/` | Load and validate existing scenarios; no duplicate smoke schema. |
| Range lifecycle | `ctf.services.range`, `cms.services.create_range`, `destroy_range_by_request_id`, pause/resume lifecycle helpers | Preserve active-range checks, request-id ownership, status transitions, retries, audit logs, and cleanup behavior. |
| Connection brokers | `engine.services._terminal`, `engine.ssh.SSHConnection`, `mission_control.guacamole`, `mission_control.guacamole_bootstrap` | Keep SSH/RDP/Guacamole credential resolution inside existing service boundaries. |
| Programmatic auth | `shared.api_tokens`, `REST_FRAMEWORK`, `ctf.views._access` | Do not invent a second token/cookie mechanism. If HTTP automation needs tokens on function views, extend the existing scope/decorator path. |
| Secrets and config | `docs/dev/deploy-secrets.md`, `entrypoint.sh`, `scripts/gcp/render_runtime_env.py`, workflow secret render steps | New smoke credentials or config must be documented and environment-owned; no committed deployment values. |
| Logging and errors | `shared.log_sanitize`, `shared.errors.classify_user_message`, GitHub Actions annotations | Issue bodies and logs must be bounded and sanitized; no raw tracebacks, env dumps, private keys, RDP passwords, cookies, or Guacamole URLs. |
| Workflow issue comments/API use | Existing `actions/github-script` patterns in reusable workflows | Prefer GitHub API calls with exact permissions and body strings/files over shelling token-bearing values through argv. |
| Enforcement | `actionlint`, `scripts/adr_guard/adr_guard.py`, `.importlinter`, TFLint, kube-linter, kubeconform | Workflow/architecture/platform changes must keep the repo guardrails intact. |

## Cross-Cutting Layers

- Auth surface: browser/session flows still use Django auth, provider auth,
  CSRF, `@login_required`, and CTF organizer/participant decorators. Token
  flows must use `shared.api_tokens` and exact scopes; bad bearer input must
  fail closed. Do not use `ENVIRONMENT=development`, `/dev-login/`, hard-coded
  cookies, or CSRF exemptions as a shortcut for deployed dev.
- GitHub runner and trust surface: smoke jobs must be unreachable from
  `pull_request`. Any job that touches cloud credentials, self-hosted runners,
  deployed clusters, or issue creation must bind the dev environment and use
  least-privilege permissions.
- Secret-handling surface: cloud credentials, session cookies, CSRF tokens,
  API tokens, SSH private keys, RDP passwords, WinRM passwords, Guacamole URLs,
  and secret references are secret-bearing. Keep them out of argv, workflow
  logs, issue bodies, artifacts, screenshots, shell traces, and temp files
  unless the file is gitignored, short-lived, and permissioned.
- Env-binding shape: smoke config should be explicit non-secret inputs such as
  target URL, provider, environment, variant, scenario id, timeouts, and output
  path. Do not add smoke-only Django settings, Terraform variables, or
  Kubernetes values unless the runtime truly needs them.
- Config validators: workflow changes must pass `actionlint` and ADR guard.
  Python under `shifter/shifter_platform` must satisfy import-linter. Terraform
  or Kubernetes changes, if any, must pass the repo-native TFLint,
  kube-linter, and kubeconform checks.
- Network and OS exposure: the smoke must not open security groups,
  NetworkPolicies, firewall rules, or ingress just to make a runner-origin port
  probe work. If a raw SSH/RDP/WinRM probe is used, name the vantage point
  explicitly and do not confuse it with portal-mediated access.
- Error-envelope surface: return fixed/sanitized failure classes in automation
  output, with bounded log tails and links to the workflow run. Public GitHub
  issues may contain commit SHA, variant, provider, timeout stage, and
  sanitized summaries, not raw provider payloads or credential-bearing URLs.
- Persistence surface: use existing CMS/engine request and range records,
  existing audit logging, and cleanup transitions. Do not add Django models,
  migrations, repositories, Redis keys, or durable smoke state for this issue.

## Extensibility Seam

The durable seam is a variant/config contract:

- environment and provider: `aws-dev` / `gcp-dev` and the deployed portal URL;
- actor: smoke-owned user/session/token or management-command actor;
- range variant: scenario id, expected victim OS, and expected protocols;
- readiness policy: provisioning timeout, poll interval, SSH/RDP/WinRM/Guacamole
  checks, and bounded log collection;
- cleanup policy: request id, RangeInstance id, retry/timeout, and orphan
  warning;
- issue policy: labels, dedupe key, maximum log bytes, and update-vs-create
  behavior.

The next reasonable changes are adding a GCP-specific range variant, changing
the Windows scenario, adding WinRM after RDP, or running the same smoke on a
manual dispatch. Those should be parameter/config changes, not copies of the
workflow block or new app services.

## Whole-Repo Scope

Likely in scope for implementation:

- `scripts/smoke-test.sh` and, if needed, a small script-local helper package
  under `scripts/`.
- `.github/workflows/deploy.yml`, `_shifter-platform.yml`, and `_gcp-dev.yml`,
  or a separate trusted post-deploy workflow if strict non-duration blocking is
  required.
- `docs/dev/deploy-secrets.md` if the smoke needs new GitHub secrets,
  environment variables, smoke actors, or operator setup.
- Existing CTF/CMS/range/connection code only as contracts or bug-fix targets:
  `ctf.services.range`, `cms.services`, `engine.services`, `mission_control`
  Guacamole and terminal surfaces.
- Tests for script parsing/deduping/cleanup and workflow structure, plus
  existing platform tests if implementation exposes a real bug.

Usually out of scope:

- New Terraform modules, new Kubernetes workloads, new deploy roles, new auth
  system, new health endpoint, new range schema, new exception hierarchy, new
  logging format, new telemetry store, or event/load harness behavior.
- Production smoke tests. This issue is dev operational readiness.

## Gotchas And Anti-Patterns

- Do not equate `continue-on-error` with "pipeline duration not increased." If
  the acceptance criterion means the deploy workflow must finish immediately,
  use a detached trusted follow-up workflow or dispatch pattern instead of a
  normal in-run job.
- Do not let smoke run after skipped, failed, cancelled, or PR deploy jobs.
  `always()` guards must still fail closed on bad upstream results.
- Do not create an issue for every retry or every matrix leg without dedupe.
  One failed commit/provider/variant should map to one open issue update.
- Do not upload or paste full logs. Provisioner logs can contain account
  metadata, secret refs, generated URLs, guest credentials, or operator config.
- Do not key lifecycle operations on legacy `RangeInstance.range_id`; recent
  range lifecycle fixes use request id / instance PK to avoid orphaning live
  ranges.
- Do not treat "port open from runner" as equivalent to "participant can access
  SSH/RDP through the portal." The source network matters.
- Do not add direct `boto3`, `gcloud`, `kubectl`, or Terraform calls inside
  Django app code for this. Provider operations belong in scripts/workflows or
  existing cloud adapters.
- Do not use one long-lived real user with an existing active range. The smoke
  must own its actor/range and clean it up deterministically.
- Do not use unbounded waits. Windows boot, domain join, RDP, and WinRM need
  longer timeouts than Linux SSH, but they still need explicit caps.
- Do not weaken deploy verification, ADR guard, import-linter, secret scanning,
  security group policy, NetworkPolicy, TLS verification, CSRF, or websocket
  origin validation to make smoke automation pass.

## Non-Goals

- No implementation is performed by this preflight.
- No implementation plan is encoded here.
- No formal Ground Control requirement or traceability work is attached.
- No change to production deployment policy, branch protection, range
  architecture, auth provider, API-token migration plan, CTF event model,
  Guacamole JSON-auth design, terminal websocket protocol, or cloud networking
  unless the future smoke uncovers a separate accepted defect.

## Validation Expectations

At minimum, workflow or platform implementation follow-ups should run the repo
architecture gate:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Run `actionlint` for workflow edits. Run import-linter, TFLint, kube-linter, and
kubeconform only for the touched stack surfaces named in `AGENTS.md`.
