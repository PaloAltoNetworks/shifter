# VM Guest Credential Preflight

Issue: GitHub #762, "Shared hardcoded VM passwords are baked into range
images and reused in portal access flows".

This note records the architecture boundary for replacing shared Kali,
Ubuntu, Windows victim, and Windows DC guest passwords. It is intentionally
not an implementation plan. The goal is to keep the fix inside existing
secret, provisioning, access-brokering, and layer-boundary contracts.

## Decision

Guest access passwords are runtime range data, not image defaults, portal
configuration, scenario schema, or CTF workflow data.

The durable contract is:

- Generate a unique guest credential at provisioning time, scoped at least to
  a range and preferably to an instance where the guest OS supports it.
- Persist only a secret reference in range state. Do not persist the password
  value in `Range.provisioned_instances`, `engine_instance.state`, scenario
  specs, Terraform variables, events, logs, generated ConfigMaps, or CTF data.
- Broker RDP by resolving the secret reference at the engine service boundary
  immediately before building the Guacamole payload.
- Keep usernames and credential references separate. Usernames may remain
  deterministic by OS/role; passwords must not.
- Treat the DC domain Administrator credential separately from local desktop
  credentials. Do not use deployment-scoped `DC_DOMAIN_PASSWORD` as the
  blanket answer for per-range or per-instance guest RDP access.

The existing deployment-scoped DC secret was a useful bridge away from a
literal source password, but this issue requires tighter blast-radius
containment. A single environment-level password still fails the issue's
cross-range containment objective.

## Canonical Incumbents

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Portal secret reads | `shifter/shifter_platform/shared/cloud.get_secrets_store`, `shared.cloud.*.secrets`, and `engine.secrets.get_ssh_key` | Reuse the provider-neutral secret read path. Do not add direct `boto3` or Google Secret Manager calls in mission_control, CTF, or Django views. |
| Provisioner secret reads | `shifter/engine/provisioner/cloud.get_secrets_store` and provider adapters | Keep provisioner cloud access behind the existing standalone cloud adapter set unless creating provider resources already requires provider-specific code. |
| Per-instance secret precedent | AWS range Terraform SSH-key secrets in `shifter/engine/provisioner/terraform/modules/range/main.tf`; GDC VM Runtime `_ensure_ssh_secret` in `gdc_vmruntime_assets.py` | Model guest password storage like per-instance SSH keys: generated per runtime asset, encrypted in the provider secret store, and referenced from persisted state. |
| Range state contract | `write_provisioned_state`, `_build_instance_state`, `_build_provisioned_instance_payload`, `Range.provisioned_instances` | Add credential references to the existing state payload once, close to the provisioner write boundary. Do not create parallel RDP schemas in portal or CTF code. |
| Portal access service | `engine.services.get_rdp_connection_info`, `_resolve_instance_host`, `_resolve_instance_connection_name`, `_resolve_instance_ssh_key_secret_ref` | Keep connection lookup and ownership checks in engine services. Views should not know how to resolve guest credentials. |
| Guacamole payload | `mission_control.guacamole.create_guacamole_rdp_url` and `create_rdp_connection_params` | Keep this module as a payload builder only. It should receive a password value from the engine service and never fetch or infer credentials. |
| HTTP error envelope | `mission_control.views.guacamole_rdp_url` | Preserve current `ValueError` to 400 and unexpected error to generic 500 behavior; do not leak secret IDs or values to users. |
| CTF boundary | `ctf.views.api_range_access` and `ctf.bridges` | CTF must not import engine or mission_control directly. It should continue delegating to the standard Mission Control RDP endpoint or CTF bridge seams. |
| Secret documentation | `shifter/shifter_platform/documentation/docs/technical/dev/secrets.md`, ADR-004-R7, `.gitleaks.toml` | Secret material belongs in provider secret stores or runtime Kubernetes Secrets, never committed files or tfvars literals. |
| Runtime env binding | `entrypoint.sh`, `engine/ecs.py`, `scripts/gcp/render_runtime_env.py`, Helm/Kustomize `secretRef` wiring | Pass secret references or runtime secret bundles, not guest password values, through app/provisioner env contracts. |
| Remote setup execution | `SetupOrchestrator`, `SSMExecutor`, setup plan masking | If a credential must touch remote setup, avoid echoing it and use existing masking. Prefer passing references over rendered plaintext scripts. |

## Cross-Cutting Layers

Security layers the design must satisfy:

- Auth surface: RDP access continues through `@login_required`,
  `Range.get_active_for_user`, `Range.get_instance_by_uuid`, and engine service
  ownership checks. CTF participant access continues through CTF role
  decorators and then the standard Mission Control RDP endpoint.
- Secret-handling surface: secret values live in AWS Secrets Manager, AWS SSM
  SecureString, GCP Secret Manager, or Kubernetes Secrets only as runtime
  deployment plumbing. Portal code retrieves them through `shared.cloud`
  adapters or a small engine helper that wraps those adapters. Provisioner code
  uses its own `cloud` adapters or the established provider-specific creation
  helper where no write protocol exists yet.
- State and schema shape: `engine_instance.state` and
  `Range.provisioned_instances` may contain username, OS, role, provider, and
  secret reference fields. They must not contain `rdp_password`,
  `guest_password`, or any equivalent plaintext value.
- Config validators: `adr_guard`, `.gitleaks.toml`, ADR-004-R7, Terraform
  variable validation, and GCP runtime render tests must continue catching
  committed credentials and ConfigMap-bound secret values. Moving literals into
  `platform-runtime-secrets.env` is not sufficient when that file is committed.
- Provider env binding: `_GCP_PROVISIONER_ENV_KEYS`, ECS task definitions,
  Helm values, Kustomize overlays, and EC2 `docker run -e` startup should carry
  secret IDs or bundle IDs. They should not grow new
  `*_PASSWORD=<generated value>` contracts for guest access.
- OS/runtime exposure: do not bake passwords in Packer scripts. Avoid putting
  passwords in Terraform `user_data`, EC2 user data, process argv, Docker
  command lines, Kubernetes ConfigMaps, or long-lived SSM command history. If a
  setup path must briefly materialize a password on a guest, the script must
  not echo it, and failure logging must be masked by existing setup
  orchestrator sensitive-output handling.
- Error envelopes: a missing credential reference or failed secret fetch should
  fail closed with a non-sensitive operational error. User-facing JSON may say
  that credentials are unavailable; logs may include range ID, instance UUID,
  provider, and secret reference type, but not the value.
- Guacamole token surface: generated Guacamole URLs/tokens are sensitive
  because the encrypted connection payload contains credentials. Keep the
  current posture of not logging generated URLs and do not add analytics or
  audit payloads that include them.

Maintainability incumbents the implementation must build on:

- `shared.cloud` and `engine/provisioner/cloud` provider adapter families.
- `engine.services` connection resolvers and access checks.
- `mission_control.guacamole` payload builders.
- `write_provisioned_state` as the state persistence boundary.
- AWS range Terraform secret naming and CMK input (`secrets_kms_key_arn`) for
  runtime range secrets.
- GDC VM Runtime Secret Manager helpers and runtime metadata shape.
- `entrypoint.sh` and GCP runtime renderer conventions for secret ID hydration.
- ADR guardrails, import-linter, gitleaks, tflint, actionlint, kube-linter, and
  kubeconform for the surfaces they already own.

Extensibility seam:

Keep a single provider-neutral guest access credential reference on the
provisioned instance state, parameterized by protocol/purpose, username, scope
(`range` or `instance`), provider, and secret reference. That seam allows the
next reasonable change, such as per-protocol credentials, password rotation,
Windows local-admin renaming, or key-only Linux desktop access, without
rewiring CTF, Mission Control views, or Guacamole payload code.

## Whole-Repo Scope

In scope for the future implementation:

- Portal access flow:
  `shifter/shifter_platform/engine/services.py`,
  `mission_control/views.py`, `mission_control/guacamole.py`, and CTF access
  delegation.
- Provisioner state and setup flow:
  `shifter/engine/provisioner/main.py`,
  `gdc_vmruntime_assets.py`, `plans/*`, `orchestrators/setup_orchestrator.py`,
  `executors/ssm_executor.py`, and provider cloud adapters.
- AWS range Terraform:
  `shifter/engine/provisioner/terraform/modules/range/**` and the platform
  engine-provisioner secret/KMS/IAM wiring under `platform/terraform/**` if new
  runtime secret permissions are needed.
- GCP/GDC runtime:
  `scripts/gcp/render_runtime_env.py`, `platform/k8s/gcp/**`,
  `platform/charts/shifter/**`, `platform/terraform/gcp/**`, and
  `_GCP_PROVISIONER_ENV_KEYS`.
- Image builds:
  `shifter/packer/scripts/kali/base.sh`,
  `shifter/packer/scripts/ubuntu/desktop.sh`, Windows/DC Packer templates, and
  any AMI promotion notes.
- Architecture enforcement:
  `.gitleaks.toml`, `.importlinter`, `.tflint.hcl`, `.kube-linter.yaml`,
  `scripts/adr_guard/**`, and `docs/adr/**` if a new enforced rule or
  exception is introduced.

## Gotchas And Anti-Patterns

- Do not replace hardcoded source passwords with hardcoded Kubernetes Secret
  generator files, tfvars, Terraform locals, or committed generated env files.
- Do not leave fallback branches such as `kali`, `ubuntu`,
  `CortexSavesTheDay!`, `GDC_*_PASSWORD`, or `DC_DOMAIN_PASSWORD` as silent
  defaults for normal RDP brokering.
- Do not conflate RDP desktop credentials, SSH private keys, DC domain admin
  credentials, Guacamole JSON-auth signing keys, and app/database secrets.
  They have different rotation scopes and consumers.
- Do not add credential fetching in `mission_control.guacamole`; it is a
  Guacamole JSON-auth builder, not a repository or secret service.
- Do not add CTF-specific RDP credential code. CTF should use the standard
  portal access flow.
- Do not store secret values in Django model fields or JSON state because they
  are convenient to query. Store references and fetch at use time.
- Do not add a second cloud secret abstraction unless the existing `SecretsStore`
  read-only protocol is intentionally extended for both AWS and GCP, with tests.
- Do not log full SSM scripts, cloud-init user data, Terraform variable JSON,
  Guacamole payloads, or generated URLs.
- Do not rely on Packer bake-time password changes for ephemeral containment.
  Image builds should install/configure access services, not define the live
  credential for every future range.
- Do not treat tests that assert static values as compatibility requirements.
  They should become regression tests for per-range/per-instance uniqueness,
  fail-closed missing references, and absence of literal fallbacks.

## Non-Goals

- This preflight does not implement credential generation, rotation, or
  migration.
- Do not redesign Guacamole authentication, replace JSON auth, or change the
  Mission Control RDP endpoint contract beyond the credential source.
- Do not redesign CTF participant access, scoring, range lifecycle, NGFW
  attachment, subnet allocation, or scenario authoring.
- Do not introduce a general credential vault feature or user-managed password
  UI for this issue.
- Do not weaken SSH/RDP network controls, IAM least privilege, GCP default-deny
  network policy, or existing ADR checks while changing credentials.
- Live rotation of already-provisioned ranges and already-built images is an
  operations rollout item after the code path changes. The implementation
  should make the required rotation/rebuild path explicit, but this preflight
  does not execute it.

## Validation

At minimum, changes on this path must run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Then add the stack-native checks for the touched surfaces:

- `cd shifter/shifter_platform && uv run ruff check . && uv run ruff format --check .`
- `cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter` when Python imports change.
- `TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"` when Terraform changes.
- `actionlint` when workflows change.
- `kube-linter lint --config .kube-linter.yaml platform/k8s/` and
  `kubeconform -strict -summary -ignore-missing-schemas -kubernetes-version 1.31.0 platform/k8s/gcp/base/*.yaml`
  when Kubernetes manifests change.
- Targeted provisioner, engine service, Guacamole, GDC runtime, Packer, and GCP
  runtime-renderer tests covering the changed paths.
