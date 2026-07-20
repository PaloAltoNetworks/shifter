# Guacamole Helm Secret Boundary Preflight (#1180)

Status: pre-implementation guidance

Date: 2026-07-07

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1180>

Canonical finding: `csf_afa7479c33666959a2a8ed84`

## Scope Boundary

The issue contract is to stop duplicating Guacamole runtime credentials into
Helm input and Helm release state. `POSTGRESQL_PASSWORD` and `JSON_SECRET_KEY`
must not appear in chart values, generated values files, Helm `--set` args,
Helm release history, logs, committed manifests, or long-lived local artifacts.

The acceptable runtime destinations are the provider secret store and the
Kubernetes Secret consumed by `guacamole-client`. For the current GCP path, GCP
Secret Manager remains the source of truth and bootstrap may sync the
`guacamole-runtime` Kubernetes Secret out of band with `kubectl apply -f -`.
Helm owns the workload reference to that Secret, not the Secret payload.

This note is not an implementation plan. It records the repository-wide
boundaries the implementation must preserve.

## Architecture Decisions

- GCP Secret Manager and Terraform `runtime_secret_ids` remain the canonical
  source of Guacamole secret references. Do not introduce a parallel vault,
  schema registry, or secret DTO for this issue.
- `scripts/bootstrap/gcp_control_plane.py` is the owner of the GCP control-plane
  sync path. `scripts/bootstrap/deploy.py` is only the compatibility facade.
  Reuse the existing secret-fetch and `sync_gcp_guacamole_runtime_secret`
  boundary instead of adding another deployment script path.
- The Helm chart must model `guacamoleRuntimeSecret` as a non-secret reference,
  preferably just the existing Secret name. Raw `stringData` values are not a
  chart contract. If a future controller owns the object, Helm values should
  pass controller references, not payloads.
- The `guacamole-client` pod should continue consuming non-secret connection
  shape from `platform-runtime` and secret values from `envFrom.secretRef`.
  Splitting those shapes prevents the ConfigMap from becoming a secret store.
- Portal signing and Guacamole JSON auth must stay single-sourced: the Portal
  reads `GUACAMOLE_SECRET_ID` and exports `GUACAMOLE_JSON_AUTH_SECRET`, while
  guacamole-client receives the same Secret Manager value as `JSON_SECRET_KEY`.
- Updating an externally managed Kubernetes Secret does not automatically roll
  pods. Preserve the existing post-sync restart/rollout seam or replace it only
  with a non-secret rollout trigger. Do not hash secret values into Helm
  annotations.
- AWS is the comparison incumbent, not a target for this issue: the ECS task
  definition already uses `secrets.valueFrom` for `POSTGRESQL_PASSWORD` and
  `JSON_SECRET_KEY`.

## Cross-Cutting Layers

| Layer | Required posture |
| --- | --- |
| Auth surface | Do not change Identity Platform, Django session auth, Mission Control authorization, or Guacamole JSON-auth semantics. The signed launch path still fails closed with a non-sensitive `503` when `GUACAMOLE_JSON_AUTH_SECRET` is absent. |
| Secret handling | Raw Guacamole DB and JSON-auth values may exist in GCP Secret Manager payloads, the transient stdin payload to `kubectl apply -f -`, and the Kubernetes Secret data. They must not exist in Helm values or Helm release config. |
| Env binding | Keep `GUACAMOLE_SECRET_ID` and other Secret Manager IDs as config references. Keep `POSTGRESQL_HOSTNAME`, port, and database in ConfigMap-backed env. Keep `POSTGRESQL_USER`, `POSTGRESQL_PASSWORD`, and `JSON_SECRET_KEY` in the Secret-backed env surface. |
| Config validators | Preserve `render_gcp_helm_values`, `scripts/gcp/render_runtime_env.py`, image-tag/public-host validators, Helm template rendering, kube-linter/kubeconform for manifest changes, and ADR guard. Add focused negative assertions rather than ad hoc runtime string checks. |
| OS/process exposure | Commands must remain argv lists. Secret payloads must not be passed through argv, shell strings, `helm --set`, `--values`, or diagnostic command output. The one-shot Kubernetes apply path must use stdin or an equivalent non-persistent transport. |
| Error envelope | Bootstrap errors should name missing Terraform outputs, Secret Manager resource IDs, Kubernetes object names, or field names only. Do not print rejected payloads, rendered Secret manifests, or fetched `gcloud secrets versions access` stdout. |
| Persistence | Generated `shifter.values.generated.json` and Helm release history may contain secret names and references only. The only persisted secret value copies in scope are Secret Manager versions and Kubernetes Secret data. |
| Observability | Status logs may say the Secret was created/configured and that guacamole-client restarted. They must not include manifest bodies or secret values. |

## Canonical Incumbents

| Concern | Canonical incumbent | Reuse requirement |
| --- | --- | --- |
| GCP secret inventory | `platform/terraform/gcp/modules/portal/secrets/main.tf`, `platform/terraform/gcp/modules/platform-core/outputs.tf` | Keep using `runtime_secret_ids["guacamole-db"]` and `runtime_secret_ids["guacamole-json-auth"]`. |
| GCP runtime env | `scripts/gcp/render_runtime_env.py`, `shifter/shifter_platform/entrypoint.sh`, `shifter/shifter_platform/config/_guacamole_settings.py` | Preserve `GUACAMOLE_SECRET_ID` -> `GUACAMOLE_JSON_AUTH_SECRET` hydration. |
| Bootstrap sync | `scripts/bootstrap/gcp_control_plane.py`, `scripts/bootstrap/tests/test_gcp_control_plane.py`, `scripts/bootstrap/tests/test_gdc_cluster.py` | Build on the existing sync-before-Helm sequence and stdin apply tests. |
| Chart workload binding | `platform/charts/shifter/templates/guacamole-client-deployment.yaml` | Keep `envFrom.secretRef` as the workload contract; remove raw payload ownership from chart values/templates. |
| AWS comparison | `platform/terraform/modules/guacamole/ecs.tf` | Use ECS `secrets.valueFrom` as the established reference-only pattern. |
| Guardrails | `scripts/adr_guard/adr_guard.py`, `.gitleaks.toml`, Helm template tests, kube validators | Use existing validators as backstops; add narrow tests for this regression instead of a new scanner framework. |
| Operator docs | `shifter/shifter_platform/documentation/docs/technical/dev/secrets.md`, `shifter/shifter_platform/documentation/docs/technical/platform_infrastructure/guacamole.md` | Keep docs clear that Secret Manager is source of truth and Kubernetes Secret is runtime binding, not Helm configuration. |

## Extensibility Seam

The extension point is a non-secret secret-binding reference, not a payload
schema. Keep the current name parameter (`guacamoleRuntimeSecret.name`) or a
similarly small `existingSecretName` shape in Helm values. If the next variation
uses External Secrets, CSI Secret Store, or a per-environment Secret name, add
that as a reference/source-kind field and keep the raw payload resolution
server-side or in bootstrap.

The bootstrap seam should remain environment-owned: `gcp-dev`, future
`gcp-prod`, and local/operator-driven deploys can choose how the Kubernetes
Secret is created without changing the `guacamole-client` container contract.

## Whole-Repo Scope

In scope for the future implementation:

- `scripts/bootstrap/gcp_control_plane.py`
- `scripts/bootstrap/tests/test_gcp_control_plane.py`
- `scripts/bootstrap/tests/test_gdc_cluster.py`
- `platform/charts/shifter/values.yaml`
- `platform/charts/shifter/templates/secret-guacamole-runtime.yaml`
- `platform/charts/shifter/templates/guacamole-client-deployment.yaml`
- `platform/charts/shifter/templates/_helpers.tpl`
- `shifter/shifter_platform/documentation/docs/technical/dev/secrets.md`
- `shifter/shifter_platform/documentation/docs/technical/platform_infrastructure/guacamole.md`

Usually out of scope unless the implementation deliberately changes the
contract:

- AWS Terraform under `platform/terraform/modules/guacamole/`
- GCP Terraform secret resource definitions
- `scripts/gcp/render_runtime_env.py`
- `shifter/shifter_platform/entrypoint.sh`
- application controllers, DTOs, repositories, exception hierarchies, and
  Mission Control request handling

## Gotchas And Anti-Patterns

- Do not move raw values from `stringData` to base64 `data`; base64 is still
  plaintext for this threat model and is still persisted in Helm release state.
- Do not use `helm --set`, generated values files, workflow env vars, or command
  examples to carry `POSTGRESQL_PASSWORD` or `JSON_SECRET_KEY`.
- Do not leave a chart checksum that hashes `.Values.guacamoleRuntimeSecret`
  payloads. A checksum over a reference is acceptable; a checksum over a secret
  value is not.
- Do not conflate "Helm should not create the Secret" with "the pod should not
  consume a Kubernetes Secret". The workload still needs the runtime Secret.
- Do not duplicate Secret Manager payload schemas in a second validator. Validate
  required fields at the existing bootstrap boundary and keep errors
  non-sensitive.
- Do not broaden Workload Identity, Secret Manager IAM, NetworkPolicy, pod
  security, or service-account token mounting to compensate for secret delivery.
- Do not break the existing Helm cutover order: legacy cleanup, namespace
  ensure, runtime Secret sync, Helm release, then restart if the external Secret
  changed.
- Do not change the single `guacamole-client` replica invariant from issue #928.
  Secret remediation and token/task affinity are separate concerns.

## Non-Goals

- No implementation in this preflight.
- No secret rotation, incident response, or git-history rewrite.
- No new formal Ground Control requirement.
- No generic secret-management abstraction, controller, DTO, service,
  repository, exception hierarchy, or logging framework.
- No redesign of Identity Platform, Django auth, Guacamole JSON auth, Redis
  AUTH/TLS, GDC access secrets, or per-instance guest credentials.
- No Terraform state migration, cloud-resource topology change, workflow
  permissions expansion, or AWS deployment behavior change.

## Validation Expectations

At minimum for implementation on this path:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Add focused bootstrap/chart tests proving generated Helm values never contain
`POSTGRESQL_PASSWORD` or `JSON_SECRET_KEY`, rendered chart output does not create
a raw `Secret` from values, and the out-of-band sync path does not place secret
values in process argv.
