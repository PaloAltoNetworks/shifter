# Backend-Aware Setup And Doctor Preflight (#727)

Status: pre-implementation architecture guidance

Date: 2026-07-14

Issue: GitHub #727, "Add backend-aware setup and doctor validation UX"

This is a requirement-free run. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is intentionally not an
implementation plan.

## Scope Boundary

#727 gives OSS users a concrete path to prepare and validate a selected backend
before infrastructure is applied. It must surface the same prerequisite truth the
repo already enforces in code, but in a backend-aware operator UX.

The implementation may add `init`, `configure`, `doctor`, or repo-native
equivalent commands. Regardless of naming, the boundaries are:

- `init` is local-only. It may select or create a starting `shifter.yaml` from
  checked examples and point at existing docs. It does not authenticate to cloud
  APIs, write GitHub secrets, create provider secrets, or apply infrastructure.
- `configure` records references and operator-owned local files through existing
  config surfaces. Any write to GitHub secrets, provider secret stores, Terraform
  state, Kubernetes, DNS, or cloud resources is a separate explicit mutating
  operation, not an implicit side effect of "validation".
- `doctor` validates the selected backend from `shifter.yaml`, reports every
  blocking prerequisite it can determine, and tells the user which checks are
  local-only, cloud-read-only, or deployment-mutating. The default posture should
  be non-mutating.

No new ADR is needed for #727 if implementation stays within ADR-011
root-configured backend bundles and ADR-035 shared deployment preflight. A new
ADR or ADR-011 update is warranted only if doctor becomes a new authoritative
workflow engine, changes the backend contract shape incompatibly, or introduces
an enforceable rule not already covered by ADR-011/ADR-035.

## Architecture Decisions

- Use `shifter/installation` as the user-facing backend-selection authority.
  `load_root_config()` is the one parser for `shifter.yaml`; doctor must not
  parse YAML, settings, or secrets through a second path.
- Use the selected `BackendBundle` as the backend-specific contract surface.
  Required tools, required logical secrets, generated outputs, validation
  checks, health checks, owned files, capabilities, and docs come from
  `installation.registry`, not from branch names or workflow conditionals.
- Reuse `scripts/bootstrap/preflight.py` for deploy prerequisite semantics.
  Where #727 expands prerequisites, extend the declarative preflight spec and
  its docs parity tests instead of adding workflow-only or CLI-only checks.
- Keep validation check execution structured. `CommandSpec.argv` is the safe
  command format; do not store shell strings, pipes, `sh -c`, absolute host
  paths, path traversal, or secret-bearing argv.
- Keep setup/doctor reports sanitized. Reports may name backend, profile,
  logical secret names, check names, missing tools, missing files, repo-relative
  docs, and remediation actions. They must not print root config bodies, env
  dumps, secret reference values, secret payloads, Terraform outputs/plans,
  provider SDK responses, or local absolute paths unless already operator-owned
  and non-sensitive.
- Keep branch logic out of user remediation. Doctor output should explain the
  selected backend's required local files, config, tools, and cloud-read
  prerequisites directly. It should not require users to understand
  `deploy.yml` path filters or branch-to-provider routing.
- Keep backend-specific checks with the backend bundle contract. A new backend
  should add its own bundle metadata/check records and reuse the same doctor
  executor rather than editing a central `if backend == ...` command list.

## Check Classification

Doctor must classify checks by side-effect level before running them.

| Class | Allowed by default | Examples | Guardrail |
| --- | --- | --- | --- |
| Local-only | yes | `load_root_config`, required tool lookup/version checks, checked example validation, runtime inventory, generated-output classification, backend-owned repository path existence, backendless Terraform/Kubernetes render checks that do not contact providers | Must not read secret values, cloud credentials, `.secrets`, Terraform state, or write outside normal generated output targets. |
| Cloud-read-only | opt-in or clearly labeled | `aws sts get-caller-identity`, `gcloud auth list`/project lookup, state bucket existence/access metadata, GCP API enablement, AWS SSM AMI parameter existence, Secret Manager/Secrets Manager reference existence metadata, DNS record observation | Must never call payload APIs such as `GetSecretValue` or `gcloud secrets versions access`; must not create, update, delete, apply, register, or rotate anything. |
| Deployment-mutating | never part of doctor default | bootstrap state/OIDC/roles, runner provisioning, GitHub secret writes, provider secret writes, Terraform apply/destroy, Helm/Kubernetes apply, Packer/image promotion, DNS changes, account recovery sweep | Requires explicit command/flag and the existing mutating owner. Doctor may report that the step is required; it must not perform it. |

If the existing `ValidationCheck` contract is extended to carry this
classification, that is a published-contract change and must follow
`shifter/installation/published_contract/MIGRATIONS.md`.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Root config parsing and error aggregation | `shifter/installation/loader.py`, `schema.py`, `errors.py` | Use `load_root_config()` / `validate_root_config_file()` and render `ConfigIssue`s. Do not reparse YAML or echo rejected input values. |
| Backend-specific settings and secret references | `BackendBundle.validate_settings`, `secret_reference_issues`, `AwsSettings`, `GcpBackendSettings`, `installation.range_egress` | Keep backend settings closed and range egress cross-backend. Do not create another settings model in doctor, workflows, Terraform, or docs. |
| Backend contract metadata | `installation.contract`, `installation.registry`, published contract artifacts | Read selected bundle data. If the contract shape changes, regenerate/check the published artifact and migration note. |
| CLI entrypoint | `shifter/installation/cli.py` | Prefer extending `shifter-config` for root-config/backend UX. Keep output small, deterministic, and sanitized. |
| Deploy prerequisite preflight | `scripts/bootstrap/preflight.py`, `scripts/bootstrap/tests/test_preflight.py`, `docs/dev/deploy-secrets.md` | Extend the shared declarative preflight and docs parity test. Do not add divergent checks inside GitHub Actions or a doctor-only list. |
| Command execution hygiene | `scripts/bootstrap/bootstrap_core.py` | Reuse argv validation, redacted logging, `AWS_PAGER=""`, and stdin/temp-file secret handoff patterns. Never put secret payloads in argv. |
| Terraform backend config | `scripts/bootstrap/terraform_backend.py`, `scripts/terraform/render_aws_backend_configs.py` | Reuse instance-dir/backend config rendering and validation. Do not rewrite S3 backend layout or hardcode state paths in doctor. |
| Runtime env ownership | `installation.runtime_inventory`, `installation.render`, `scripts/gcp/render_runtime_env.py`, `config/env-manifest.json` | Validate key ownership and generated outputs through existing inventories/renderers. Do not invent a second runtime env schema. |
| Workflow/deploy conventions | `.github/workflows/deploy.yml`, `_core.yml`, `_range.yml`, `_shifter-platform.yml`, `_gcp-dev.yml`, `docs/technical/dev/ci-cd.md` | Use workflows as compatibility/current-state evidence only. User-facing doctor remediation must be backend/profile based, not branch-filter based. |
| Architecture guardrails | ADR-011, ADR-035, ADR-004, `scripts/adr_guard/adr_guard.py` | Preserve root-configured backend bundles, shared preflight, secret/identifier scanning, no generated sensitive artifacts, and ADR guard behavior. |

## Cross-Cutting Security Path

The intended design must pass these layers:

1. **Root YAML and shape gate.** `installation.loader` rejects missing,
   unreadable, duplicate-key, merge-key, non-mapping, unknown-field,
   unsupported-profile, malformed-domain/name, malformed-secret, and
   raw-looking-secret cases before any check executor runs.
2. **Backend settings and reference gate.** The selected `BackendBundle` validates
   backend-owned settings and logical secret references. `range_egress` stays in
   `installation.range_egress` and must not be copied into backend models.
3. **Published contract gate.** `RequiredTool`, `RequiredSecret`,
   `GeneratedOutput`, `ValidationCheck`, `HealthCheck`, `OwnedFiles`, and
   `CommandSpec` remain closed validated data. Any contract-field addition
   follows the publication drift and compatibility gates.
4. **Secret-handling gate.** Root config holds references only. Doctor may check
   reference presence and, in cloud-read-only mode, reference metadata existence.
   It must not fetch, print, compare, or persist secret payloads.
5. **Environment binding gate.** Runtime keys stay classified by
   `runtime_inventory`, generated-output metadata, `config/env-manifest.json`,
   and the existing provider renderers. New generated keys update all inventory,
   manifest, admission, and parity tests.
6. **OS/process exposure gate.** Commands run as argv arrays through existing
   validation/redaction helpers. Secret payloads and config bodies travel by
   stdin, provider secret store, or protected generated files owned by existing
   renderers - never process argv or shell fragments.
7. **Cloud access gate.** Read-only probes use least authority and fail closed
   on ambiguous identity/account/project results. Mutating provider calls remain
   in bootstrap/deploy owners and require explicit user intent.
8. **Error-envelope gate.** CLI output uses `ConfigIssue` and `CheckResult`-style
   path/check diagnostics. Future HTTP, WebSocket, health, or event surfaces must
   not expose provider exception text, secret references, local paths, or
   capability internals.
9. **Logging/observability gate.** Logs can carry normalized non-secret posture:
   backend, profile/environment, check class, check name, and capability names.
   They must not dump env mappings, root config, Terraform output/state, provider
   responses, account identifiers beyond existing masked/fingerprinted patterns,
   or token material.

## Extensibility Seam

The extension seam is the selected `BackendBundle` plus a check-classification
parameter. A future backend or profile should add:

- closed settings model and logical secret reference grammar,
- required tools and owned docs/paths,
- generated outputs with destination and sensitivity,
- validation/health checks classified as local-only, cloud-read-only, or
  mutating,
- adapter/capability declarations only for capabilities it actually supports.

The doctor executor should be generic over bundle, profile, check class, and
report format. It should not require provider branches in domain services,
runtime adapters, public DTOs, persistence, workflows, or ADR-039 range
substrate code.

## Whole-Repository Scope

Future implementation must evaluate changes against:

- `docs/architecture/root-configured-backend-bundles.md`
- `docs/adr/index.yaml` ADR-011 and ADR-035 if enforceable policy changes
- `shifter/installation/schema.py`
- `shifter/installation/loader.py`
- `shifter/installation/errors.py`
- `shifter/installation/contract.py`
- `shifter/installation/registry.py`
- `shifter/installation/publication.py`
- `shifter/installation/runtime_inventory.py`
- `shifter/installation/render.py`
- `shifter/installation/cli.py`
- `shifter/installation/README.md`
- `shifter/installation/examples/*.yaml`
- `shifter/installation/tests/`
- `scripts/bootstrap/preflight.py`
- `scripts/bootstrap/bootstrap_core.py`
- `scripts/bootstrap/terraform_backend.py`
- `scripts/bootstrap/tests/`
- `scripts/terraform/render_aws_backend_configs.py`
- `scripts/gcp/render_runtime_env.py`
- `docs/dev/deploy-secrets.md`
- `docs/technical/dev/setup.md`
- `docs/technical/dev/installation-config.md`
- `docs/technical/dev/ci-cd.md`
- `.github/workflows/deploy.yml` and reusable deploy workflows only when
  explicit deployment invocation or CI validation changes
- `platform/terraform/validation-inventory.yaml`
- `platform/terraform/**`, `platform/k8s/gcp/**`, and `platform/charts/shifter/**`
  only for checks tied to those owned backend paths

Current gotcha: some backend metadata and architecture notes still reference old
documentation paths under `shifter/shifter_platform/documentation/docs/...`.
The live docs are under `docs/technical/dev/...`. Do not add new doctor
remediation text that points users at stale paths.

## Gotchas And Anti-Patterns

- Do not derive backend from branch name, workflow ref, Terraform directory,
  Helm values file, or legacy compatibility names.
- Do not conflate installation backend, deployment profile/environment,
  `CLOUD_PROVIDER`, `AUTH_PROVIDER`, `GCP_RANGE_BACKEND` / `GCP_RANGE_PLANE`,
  persisted resource provider, or range-substrate adapter.
- Do not add a second backend registry, settings schema, secret-reference
  validator, exception hierarchy, command runner, or preflight list.
- Do not turn `ValidationCheck` into a deployment workflow language. It is a
  validated pointer to canonical checks, not a generic orchestrator.
- Do not run `terraform apply`, `terraform destroy`, `helm install/upgrade`,
  `kubectl apply`, `gh secret set`, provider secret writes, account recovery
  sweeps, or runner provisioning from doctor.
- Do not fetch secret payloads to prove secrets exist. Check metadata only, or
  report that payload validation is deferred to the existing runtime/startup
  owner.
- Do not put token, password, service-account JSON, private key, rendered
  `shifter.yaml`, or `local.auto.tfvars` content in command argv, logs, GitHub
  annotations, plan comments, or error reports.
- Do not weaken existing Terraform, Kubernetes, import, workflow, secret, or ADR
  guardrails to make the UX pass.
- Do not read or depend on user-local secret files such as `~/.secrets`.
- Do not make doctor success equivalent to deploy success. Doctor is a
  pre-mutation readiness signal; Terraform, workflow, runtime startup, health,
  and smoke gates remain authoritative for their own layers.

## Non-Goals

- No issue implementation in this preflight note.
- No new backend, local backend completion, provider adapter, Terraform module,
  Helm value, Kubernetes manifest, workflow route, database model, API DTO,
  event field, or runtime selection mechanism.
- No branch-routing replacement beyond making doctor output independent of
  branch logic.
- No credential collection, secret rotation, provider secret-store writes, or
  GitHub secret synchronization as part of doctor.
- No live cloud mutation in validation mode.
- No redesign of identity, runtime secret hydration, range substrate,
  persistence, outbox/reconciler, task dispatch, logging, or public error
  envelopes.
