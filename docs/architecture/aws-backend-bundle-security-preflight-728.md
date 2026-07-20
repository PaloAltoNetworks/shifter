# AWS Backend Bundle Security Preservation Preflight (#728 / PLAT-2006)

Status: pre-implementation guidance

Date: 2026-07-13

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/728>

## Decision Boundary

Moving AWS support behind the root-selected backend bundle means describing and
validating the existing AWS deployment/runtime contract through
`shifter/installation`; it does not replace the AWS Terraform modules, Cognito/OIDC
flow, cloud adapters, provisioner, or deploy safety machinery. Any intentional
reduction or change in those controls requires an ADR plus matching enforcement.

No new ADR is needed for this migration. ADR-011-R5 already requires AWS/GCP
security preservation; ADR-009 owns identity, ADR-003/004/035/037 own deploy and
validation safety, ADR-017/020/021/026 own AWS range posture, and ADR-039 owns the
range-substrate boundary.

The bundle registry remains declarative metadata and selection. It must not become a
workflow DSL, import provider SDKs, or execute Terraform. Existing bootstrap scripts
and reusable workflows remain execution owners until their separately tracked routing
migration changes that boundary.

## Architecture Decisions And Canonical Incumbents

| Concern | Canonical incumbent | Migration guardrail |
| --- | --- | --- |
| Root installation shape | `shifter/installation/schema.py`, `loader.py`, `errors.py` | Parse once with `load_root_config`; retain duplicate/merge-key rejection, closed root fields, and value-free `InstallationConfigError` diagnostics. |
| AWS bundle metadata | `installation/contract.py`, `registry.py`, `publication.py` | Replace provisional AWS metadata with one closed `settings_model`, precise secret-reference grammars, classified outputs, actual owned paths/checks, and publication evidence. Do not add a second registry or hand-edit the published JSON. |
| Shared egress intent | `installation/range_egress.py`, `render.py` | Reuse normalized `settings.range_egress`; AWS Terraform variables are derived bridge values, not another operator schema. |
| Deployment prerequisites | `scripts/bootstrap/preflight.py`, `docs/dev/deploy-secrets.md` | Extend the shared declarative preflight and its parity tests when AWS requirements change. Do not add workflow-only prerequisite logic that can drift from local bootstrap. |
| AWS execution paths | `scripts/bootstrap/deploy.py`, `.github/workflows/deploy.yml`, `_core.yml`, `_range.yml`, `_shifter-engine.yml`, `_shifter-platform.yml` | Keep execution in existing owners. Bundle checks may invoke canonical commands but must not duplicate their orchestration or safety logic. |
| Terraform roots and state | `platform/terraform/validation-inventory.yaml`, `platform/terraform/environments/{dev,proof,prod}`, `platform/terraform/modules`, `scripts/terraform/render_aws_backend_configs.py` | Preserve root ownership, lockfiles/toolchains, S3 backend rendering, state locks, saved-plan apply, moved blocks, and existing state keys. Metadata movement is not state migration. |
| Runtime binding | `GeneratedOutput`, `ProcessRole`, `config/env-manifest.json`, `config/_runtime_env.py`, `config/_cloud.py` | Derive public/runtime bindings from validated config and validated Terraform outputs. Every portal, worker, and provisioner role receives the same backend identity and fails closed when it is absent/unsupported. |
| Runtime secret hydration | `entrypoint.sh`, `entrypoint-lib.sh`, portal Secrets Manager CMK, ECS task-definition `secrets` | Carry references only through config/Terraform/SSM/task definitions; fetch values at startup, parse through stdin, and abort on fetch/shape failure. Preserve the execution-role versus task/instance-role distinction. |
| Django cloud operations | `shared/cloud/types.py`, `shared/cloud/__init__.py`, `shared/cloud/aws/*` | Reuse storage, queue consumer/publisher, task-runner, secrets, and event-bus protocols. Domain services do not import `boto3` or branch on AWS. |
| Provisioner cloud operations | `shifter/engine/provisioner/cloud/types.py`, `cloud/__init__.py`, `cloud/aws/*` | Keep this Django-free adapter family for event bus, config store, DB auth, secrets, storage, and network inventory. Do not merge it with the Django adapter package. |
| Task and range execution | `engine/ecs.py`, `engine/launch_intents.py`, provisioner CLI, ADR-039 | Preserve canonical structured commands, launch authorization/idempotency, private ECS placement, and the separate bundle-selected range-substrate adapter. Task submission is not range convergence. |
| Identity | ADR-009, `config/_oidc_settings.py`, `config/oidc.py`, `config/views.py`, `shared/verified_identity.py`, `management/services.py`, Cognito Terraform | AWS keeps Cognito/OIDC and the existing verified-email, issuer/subject binding, MFA/provider, bootstrap, session, and authorization gates. Backend selection is not proof of identity. |
| Persistence and events | Engine range/request state, `ProvisionerLaunchIntent`, range-event outbox/reconciler | The selected installation backend is process configuration. Existing persisted provider/resource metadata remains historical ownership and cleanup evidence; do not add a backend table, request field, DTO, or event selector. |
| Errors and observability | `installation.errors`, both cloud exception modules, `shared.errors`, `shared.api.errors`, `shared.log_sanitize`, provisioner `log_redact`, `config._posture` | Keep config, cloud-operation, and substrate failure contracts separate. Public envelopes remain fixed/sanitized; logs carry bounded non-secret posture and correlation only. |

## Cross-Cutting Layers The Design Must Pass

### Security and configuration path

1. **Root YAML gate.** `installation.loader` must reject missing/unreadable YAML,
   duplicate or merge keys, unknown root fields, invalid backend/profile/domain values,
   and raw-looking secret material before rendering or mutation. Renderers consume the
   normalized `RootConfig`; they do not parse YAML or revalidate a parallel dict.
2. **AWS settings and secret-reference gate.** The AWS `settings_model` must be closed
   (`extra="forbid"`) and hold stable operator intent, not Terraform output payloads,
   workflow secret names, or provider SDK objects. `RequiredSecret` patterns validate
   references only. The existing `settings_model=None` and unset reference patterns are
   migration debt and cannot remain the production acceptance rule.
3. **Published-contract gate.** Registry/contract changes regenerate
   `published_contract/backend-bundle-contract.json`; incompatible public shape changes
   require a contract version bump, migration note, and new immutable snapshot. Reuse
   `validate_published_bundle`; do not create a looser AWS-only validator.
4. **Deployment preflight gate.** Required AWS role, state, tfvars, root-config, tool,
   and component prerequisites belong in `scripts/bootstrap/preflight.py` and its docs
   parity test. Missing requirements fail before Terraform mutation. Bundle validation
   metadata points at the canonical checks; it does not reimplement them.
5. **Workflow trust gate.** Preserve GitHub OIDC role assumption, least permissions,
   protected GitHub Environments, PR denial for self-hosted/credentialed jobs, pinned
   action SHAs, queued applies, upstream failure/cancellation gating, explicit manual
   production invocation, and immutable attested image digests. Backend selection comes
   from validated config/invocation, never a ref name; branch-routing removal remains
   separate work.
6. **Terraform and state gate.** Preserve the registered root/toolchain inventory,
   backend encryption/access/locking, `-lock-timeout`, saved plan applied exactly once,
   service-discovery drain/restore behavior, fail-loud verification, and moved/state
   compatibility blocks. Do not relocate or rename roots/resources merely to match a
   bundle layout.
7. **IAM, KMS, database, and secret gate.** Preserve scoped GitHub OIDC policies,
   execution/task/instance role separation, Secrets Manager CMK namespace and
   `kms:ViaService` conditions, range SSM/EC2/ELB/Bedrock scope, RDS IAM auth and CA
   selection, secret rotation, and runtime password removal after RDS IAM handoff.
   Config artifacts contain IDs/ARNs only; values remain in Secrets Manager or process
   memory after hydration.
8. **Identity gate.** An AWS renderer may select `AUTH_PROVIDER=oidc`, but all issuer,
   token, exact-boolean `email_verified`, immutable issuer/subject binding, bootstrap
   elevation, role synchronization, and session checks stay in the existing auth seam.
   Do not model identity as a generic `shared.cloud` capability or infer authorization
   from `backend=aws`.
9. **Network gate.** Preserve private ECS provisioner placement with public IP disabled,
   portal target SG segmentation, runner VPC isolation, portal inspection enablement and
   live assertion, AWS service endpoints, range single-AZ placement, and ADR-020's
   route-table plus Network Firewall default-deny. `settings.range_egress` may select the
   documented policy; absence, an empty endpoint, or a disabled firewall must not be
   reinterpreted as a safe fallback.
10. **Runtime/env gate.** `CLOUD_PROVIDER` is a public generated binding, not an
    operator-authored second selector. `config.resolve_cloud_provider` and the
    provisioner counterpart remain the startup validators. Extend the existing runtime
    inventory/env-manifest tests for AWS outputs and roles; do not create an AWS env
    schema beside them or copy the parent environment wholesale.
11. **Process/OS gate.** Contract commands and provisioner commands remain argv arrays.
    Root-config payloads, tfvars bodies, credentials, secret values/references, provider
    responses, and Terraform output blobs must not appear in argv or echoed shell text.
    Temporary config/tfvars/plan material stays in bounded ignored/runner workspaces with
    restrictive permissions and cleanup. Provisioner argv remains an operation plus
    validated identifiers; do not add request-controlled `--backend` or config blobs.
12. **Error-envelope gate.** Use `InstallationConfigError` for installation problems,
    the existing portal/provisioner `CloudError` families for adapter failures, and
    ADR-039's classified substrate failure for range convergence. Provider exception
    text, rejected Pydantic input, config/reference paths, and health-check details must
    not cross HTTP, WebSocket, status-event, or public health envelopes.
13. **Logging/health gate.** Log backend/profile/check/capability posture only through
    the existing structured pipeline and sanitizers. Never log the root config, env
    mappings, secret ARNs when unnecessary, Terraform outputs/plans, task definitions,
    Cognito tokens, or SDK responses. Reuse existing portal/Guacamole/worker/post-deploy
    health and smoke paths; a registry health claim does not replace their behavior.

### Executable guardrails that remain authoritative

The AWS bundle must reuse or invoke these incumbents rather than duplicate their policy:

- Terraform `fmt`/`validate`, `.tflint.hcl`, blocking Checkov via
  `platform/terraform/.checkov.yaml`, and `scripts/check_tf_roots` plus
  `platform/terraform/validation-inventory.yaml`.
- `scripts/check_tf_iam_ec2_scope`, `check_tf_iam_elb_scope`,
  `check_tf_iam_ssm_scope`, `check_tf_iam_ssm_range_scope`,
  `check_tf_iam_role_naming`, `check_tf_iam_bedrock_agent_scope`,
  `check_tf_sg_cidrs`, `check_tf_kms_secrets_grant`, `check_tf_rds_security`,
  `check_tf_runner_network`, and `check_portal_target_sg_sources`, including each
  checker's unit tests and CI wiring.
- `scripts/assert_portal_inspection`, range firewall/DNS and zero-egress tests, RDS
  pending-modification checks, deploy verification, and portal/worker/post-deploy smoke
  tests for the paths the bundle claims.
- `scripts/adr_guard/adr_guard.py`, `actionlint`, gitleaks, import-linter, Bandit,
  contract publication drift/compatibility tests, and workflow semantic tests. Do not
  weaken path filters, soft-fail a gate, or add an exception without the existing
  owner/reason/expiry process.

`BackendBundle.validation_checks` is an inventory of canonical blocking checks, not a
replacement implementation. Every command executable must also be declared in
`required_tools`, as the existing contract enforces.

## Extensibility Seam

The extension parameters are the selected `BackendBundle`, its closed settings model,
`deployment.profile`, `ProcessRole`, and declared `BackendCapability`. Existing deploy
tooling may additionally use its established component name (`core`, `range`, `portal`,
or engine image/runtime) to select the owned root without branching in domain code.

The next likely AWS variation is another installation profile/region or an added
capability—not an `aws-proof` backend and not a new provider enum. The repository already
has `proof` AWS roots/workflow inputs while the public AWS bundle currently accepts only
`dev` and `prod`; implementation must explicitly either admit/map `proof` through the
registry and publication contract or document it as a compatibility-only unsupported
path. It must not silently strand it or infer support from a Terraform directory.

A future backend adds a bundle/settings model, classified role outputs, adapter
constructors only for capabilities it claims, and conformance evidence. It must not
require changes to domain services, public DTOs/events, auth policy, or ADR-039's
four-operation substrate port.

## Gotchas And Anti-Patterns

- Do not conflate `backend=aws`, `CLOUD_PROVIDER=aws`, `AUTH_PROVIDER=oidc`,
  deployment profile/environment, persisted resource provider, or range-substrate
  adapter. They align at composition boundaries but have different owners and trust
  meanings.
- Do not conflate logical secret seed inputs (`django_secret_key`, `db_password`),
  runtime bundle references (`APP_SECRET_ARN`, `DB_SECRET_ARN`, OIDC/Redis/Guacamole
  references), and hydrated secret values. The existing AWS `*_ARN` names are read-side
  compatibility aliases normalized by `entrypoint.sh`, not new authoring keys.
- `entrypoint-lib.sh` still has a legacy AWS fallback when its provider variable is
  absent/unknown. A bundle-rendered deployed path must never rely on that fallback; it
  must supply the validated binding before secret access, with regression coverage that
  omission cannot select AWS accidentally.
- Do not turn `validation_checks` into setup/deploy/teardown commands or stuff executable
  import paths into registry data. The current contract has no generic deployment
  workflow language.
- Do not copy Terraform variables or outputs wholesale into `settings`. Root settings
  are operator intent; provider outputs are validated derived state and generated
  runtime bindings.
- Do not add provider branches to CMS, Engine services, CTF, Mission Control, shared
  schemas, repositories, event handlers, or public error/status contracts.
- Do not merge the two cloud exception packages merely because their classes have
  similar names; the provisioner intentionally has no Django dependency.
- Do not remove Pulumi-era task/container/state aliases or Terraform moved blocks in
  this migration. They require an explicit compatibility/state migration.
- Do not replace existing `dev`/`proof`/`prod` tfvars and state mapping with one generic
  directory, rename deployment secrets, or remove branch routing under #728; those are
  separate migration decisions.
- Do not claim a capability, stable maturity, health check, or security posture solely
  because metadata says so. Claims require the unchanged protocol tests, guardrails,
  smoke tests, and, for range substrate, ADR-039 conformance evidence.

## Non-Goals And Implementation Boundaries

- No requirement implementation, Terraform move, state migration, resource rename,
  workflow-routing replacement, or production deployment in this preflight.
- No redesign of Cognito/OIDC, Django sessions, participant auth, bootstrap privilege,
  RDS/Redis/Guacamole secret formats, or credential rotation.
- No new cloud SDK wrapper, dependency-injection container, workflow engine, config
  registry, exception hierarchy, logging stack, persistence model, repository, DTO,
  event family, or scenario/range schema.
- No redesign of shared cloud protocols, task dispatch, launch-intent persistence,
  range lifecycle/status, ADR-039 substrate semantics, network isolation, or AWS
  infrastructure modules beyond the minimum binding needed by the bundle migration.
- GCP/local bundle completion, Azure, branch-targeted documentation/CI replacement, and
  compatibility-name cleanup remain separate work.

## Validation Expectations For The Following Implementation

Run the repository-required architecture gate and every stack-native check for touched
surfaces. At minimum for architecture/workflow/platform changes:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
(cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter)
(TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG")
actionlint
```

Also run installation package tests/publication checks, the affected Terraform root
matrix and custom security checker tests, platform/provisioner adapter tests, workflow
semantic tests, and the AWS smoke/verification paths represented by the completed
bundle metadata.
