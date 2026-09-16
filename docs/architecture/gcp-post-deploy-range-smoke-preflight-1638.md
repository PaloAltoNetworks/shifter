# GCP Post-Deploy Range Smoke Preflight (#1638)

Status: pre-implementation guidance

Date: 2026-07-27

Issue: GitHub #1638, "Add GCP post-deploy range smoke (parity with AWS #1422)".

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is intentionally not an
implementation plan.

## Scope Boundary

The implementation adds GCP parity for the existing advisory post-deploy range
smoke. It does not redefine what the smoke proves.

Keep these concerns separate:

1. GCP deploy verification: `_gcp-dev.yml`'s existing Terraform, provenance,
   rollout, ingress, and certificate checks.
2. Post-deploy range smoke: advisory proof that the deployed platform can
   provision a minimal range, observe `READY`, reach a guest over SSH/RDP, and
   tear it down.
3. Provider transport: how the workflow invokes `manage.py run_post_deploy_smoke`
   inside the deployed portal. AWS uses SSM via `portal_deploy.py`; GCP will
   need its own transport into the deployed portal runtime.
4. Smoke domain logic: `run_post_deploy_smoke`, `cms.post_deploy_smoke.*`, the
   `smoke_linux` / `smoke_windows` fixtures, and the CMS/Engine service-layer
   range lifecycle they already use.
5. Participant-journey QA/QAT: terminal, Guacamole, browser-session, or
   scenario-content validation. That is a different proof surface and remains
   outside this issue.

Do not treat #1638 as permission to create a second smoke implementation, a
provider-specific smoke scenario schema, or a new deploy gate.

## Architecture Decisions

- Reuse the existing smoke command as the single source of truth for smoke
  behavior. `shifter/shifter_platform/cms/management/commands/run_post_deploy_smoke.py`
  already drives `cms.services.create_range`, readiness polling, connection-info
  resolution, connectivity probes, and teardown through the platform service
  layer.
- Reuse the existing smoke fixtures and variant model unless GCP proves a real
  backend incompatibility. The canonical fixtures are
  `cms/scenarios/templates/smoke_linux.yaml`,
  `cms/scenarios/templates/smoke_windows.yaml`, and
  `cms/post_deploy_smoke/variants.py`.
- Keep the smoke advisory and dev-only. The current AWS contract in ADR-003-R6
  is the right deploy-safety posture: smoke failure opens an issue and marks the
  smoke job failed, but must not block deploy success.
- Extend the workflow contract, not the smoke semantics. GCP parity belongs in
  `_gcp-dev.yml`, its tests, and the deploy-secret/workflow docs; it does not
  justify forking `run_post_deploy_smoke` by provider or adding GCP-only range
  lifecycle logic in CMS.
- Keep provider-specific execution transport outside CMS/Engine domain code. The
  cloud-specific concern is how CI executes the existing manage command in the
  deployed portal. AWS already keeps that in workflow + deploy helper code. GCP
  should do the same.
- Do not add an AWS-shaped assumption to GCP and do not erase the transport
  seam. SSM polling is an AWS transport detail, not part of the smoke's domain
  contract.
- Treat any GCP guest-readiness race as backend/runtime behavior, not as a
  reason to widen the smoke definition. If GCP needs a readiness fix analogous
  to #1632, pin it to the GCE/GDC backend or guest bootstrap path, not to the
  provider-neutral smoke runner.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1638 |
| --- | --- | --- |
| Advisory smoke behavior | `shifter/shifter_platform/cms/management/commands/run_post_deploy_smoke.py` | Reuse the existing command; do not create a GCP-only smoke command or duplicate range lifecycle logic in shell/Python workflow snippets. |
| Variant and fixture contract | `cms/post_deploy_smoke/variants.py`, `cms/post_deploy_smoke/smoke_runner.py`, `cms/scenarios/templates/smoke_linux.yaml`, `cms/scenarios/templates/smoke_windows.yaml` | Keep the existing `linux` / `windows` variant seam. If a future provider-specific fixture is required, it belongs behind the variant map rather than a second workflow-only scenario selector. |
| Range lifecycle | `cms.services.create_range`, `find_range_instance_id_by_request`, `get_range_status_by_id`, `get_range_by_request_id`, `destroy_range_by_request_id` | Reuse the CMS service layer end to end. No direct model mutation, Terraform calls, or provider SDK orchestration from the smoke path. |
| Connection info and ownership checks | `engine.services.get_ssh_connection_info`, `get_rdp_connection_info` | Reuse the existing ownership, `READY`, credential-resolution, and participant-channel checks. Do not probe guessed IPs or secret refs directly. |
| Smoke issue/report contract | `cms/post_deploy_smoke/github_issue.py` | Reuse the structured smoke issue shape, labels, and title/body contract instead of duplicating inline issue text in a second workflow. |
| AWS transport precedent | `scripts/smoke-test.sh`, `scripts/portal_deploy/portal_deploy.py`, `_shifter-platform.yml` | Preserve the separation between cloud-specific exec transport and shared smoke semantics. |
| GCP deploy trust boundary | `.github/workflows/_gcp-dev.yml`, `deploy.yml`, ADR-003-R5, ADR-037-R6 | Keep trusted-event routing, `gcp-dev` runner binding, OIDC auth, digest verification, and exact deploy-byte identity intact. |
| GCP runtime config | `scripts/gcp/render_runtime_env.py`, `shared/range_instantiation_policy.py`, `shared/remote_access.py` | Reuse the existing GCP range-backend selector, remote-access contracts, and rendered runtime env. Do not add a workflow-local backend selector or second readiness schema. |
| Existing smoke design docs | `docs/architecture/smoke-test-qat-design-983.md`, `docs/dev/deploy-secrets.md` | Keep the smoke proof level clear: range lifecycle + guest-port reachability, not participant-journey QA. |

## Cross-Cutting Layers The Intended Design Must Pass

Security layers:

- GitHub workflow trust boundary: the new GCP smoke job must remain inside the
  existing trusted deploy path only (`github.event_name != 'pull_request'`,
  `gcp-dev` Environment binding, self-hosted-class runner posture per
  ADR-003-R5). No PR path may reach the smoke transport or cloud credentials.
- Cloud credential surface: reuse GCP OIDC and the existing `google-github-actions/auth`
  posture. Do not add long-lived cloud keys, kubeconfigs in repo, or ad hoc
  secret files committed or uploaded as artifacts.
- Secret-handling surface: `SMOKE_TEST_USER_EMAIL` is the only smoke-specific
  secret today. Keep it written through environment, not echoed, not embedded in
  issue bodies, and not passed in argv where avoidable. If the GCP exec path
  needs temporary files or manifests, they must contain references/non-secret
  values only, be ephemeral, and be cleaned up.
- Env-binding and config-shape surface: reuse the existing GCP runtime env and
  backend selector (`GCP_RANGE_BACKEND`, rendered by
  `scripts/gcp/render_runtime_env.py`, validated by
  `shared.range_instantiation_policy`). Do not invent a second workflow-local
  backend or readiness knob.
- Authorization / access surface: the smoke must continue to resolve connection
  details through `engine.services.get_ssh_connection_info` /
  `get_rdp_connection_info`, which enforce range ownership, `READY`, declared
  participant-access channels where present, and secret-resolution boundaries.
- Error-envelope leakage surface: smoke failures may surface stable failure text
  (`CommandError`, structured issue summary, sanitized logs). Do not expose raw
  provider payloads, secret refs, kubeconfig content, or generated runtime-env
  contents in workflow logs or issue bodies.
- OS/process exposure: avoid passing sensitive values through shell tracing or
  process argv. The existing repo standard is temp files or env, never `set -x`,
  never echoing secrets, and argv arrays where subprocesses are needed.

Maintainability layers:

- Reuse `_gcp-dev.yml` as the only GCP deploy workflow. Do not add a second GCP
  deploy workflow or a post-deploy sidecar workflow just to run smoke.
- Reuse the workflow/test pattern already used for AWS smoke:
  workflow-as-data invariants under `shifter/shifter_platform/tests/platform/`
  and the repo-wide `actionlint` / ADR guard.
- Reuse the smoke issue/report helpers and docs rather than reauthoring labels,
  titles, bodies, or secret guidance inline.
- Reuse provider-neutral service contracts. The smoke should continue to prove
  that the current backend behind the CMS/Engine boundary works; it should not
  know whether the backend underneath is AWS, GCE, or GDC.

Extensibility seam:

- The seam that must remain explicit is provider-specific portal-exec transport.
  The smoke behavior is shared; the exec mechanism is not. If a future provider
  adds parity, it should plug in another transport that runs the same manage
  command and returns the same success/failure contract, without editing the
  smoke domain logic again.
- The variant seam stays in `VARIANTS`. If GCP eventually needs a different
  canonical fixture for one variant, add it as a parameterized variant-level
  choice, not as a workflow-only hardcoded scenario id.

## Whole-Repo Scope

In scope for implementation:

- `.github/workflows/_gcp-dev.yml`
- `.github/workflows/deploy.yml` only if reusable-workflow inputs/secrets need
  forwarding changes
- `shifter/shifter_platform/tests/platform/test_post_deploy_smoke_job.py` or a
  sibling GCP workflow invariant test
- `docs/dev/deploy-secrets.md`
- `docs/adr/index.yaml`
- `scripts/adr_guard/tests/test_deploy_workflow.py` or other workflow semantic
  guard tests only if a new reusable-workflow invariant is codified
- Any minimal GCP deploy-helper script needed to exec the existing manage
  command inside the deployed portal runtime

Out of scope unless the implementation uncovers a real bug that separately needs
fixing:

- Rewriting `run_post_deploy_smoke` into a provider-aware orchestration layer
- New scenario schemas, new DTOs, new exception hierarchies, or new persistence
  models for smoke
- Terminal, Guacamole, browser-session, or QAT participant-journey validation
- Changes to range-instantiation policy, backend selection policy, or scenario
  catalog semantics unrelated to this smoke path
- Changes to AWS smoke behavior other than keeping the shared contract aligned

## Gotchas And Anti-Patterns

- Do not duplicate the smoke's readiness, connectivity, or teardown logic in
  `_gcp-dev.yml` shell.
- Do not fork smoke behavior by cloud provider inside CMS unless the domain
  semantics genuinely differ. Transport differences alone do not justify that.
- Do not hardcode a GCP-only scenario id in workflow YAML when the variant map
  already owns fixture selection.
- Do not treat Terraform apply, rollout success, managed certificate readiness,
  or provenance verification as proof that a range can actually provision.
- Do not treat a guest TCP port check as proof of participant-journey QA. The
  smoke remains narrower than QAT by design.
- Do not smuggle AWS-only concepts into the shared smoke contract: no SSM
  assumptions, no ASG/instance-tag topology logic, no AmazonProvidedDNS logic
  in provider-neutral code.
- Do not add a workflow-local fallback that silently downgrades `smoke_windows`
  or skips it on GCP. If GCP cannot satisfy a variant, fail loud and capture the
  real backend limitation.
- Do not fix a GCP guest-readiness race by padding workflow sleeps around the
  smoke job. The fix belongs in backend/bootstrap readiness semantics, with the
  smoke continuing to observe the canonical contract.
- Do not weaken ADR-003-R5 trusted-runner gating, ADR-037 digest/provenance
  verification, or the existing `continue-on-error` advisory posture to make the
  smoke easier to wire.

## Non-Goals

- No implementation in this preflight note.
- No new deploy gate; the smoke remains advisory.
- No provider-specific duplicate smoke command, duplicate issue schema, or
  duplicate readiness/validation hierarchy.
- No redesign of the GCP deploy/runtime architecture, range backend policy, or
  QAT system.
- No direct cloud-SDK orchestration of range lifecycle from workflow code.
- No Ground Control requirement or traceability object is created for this
  requirement-free issue; #1638 is the authoritative contract.

## Validation

Any implementation that changes workflows, architecture docs, or
`shifter/shifter_platform` must run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

And then the relevant stack-native checks for touched surfaces:

- `actionlint` for workflow changes
- `cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter`
  for platform/service changes
- `kube-linter lint --config .kube-linter.yaml platform/k8s/` and
  `kubeconform -strict -summary -ignore-missing-schemas -kubernetes-version 1.31.0 platform/k8s/gcp/base/*.yaml`
  if Kubernetes/GCP workload manifests change
