# GCP Runtime Secret Env Preflight

Issue: GitHub #1195, "Security: remove tracked plaintext GCP runtime secret
env files".

This note records the architecture boundary for removing the committed
`platform-runtime-secrets.env` values from the GCP Kustomize overlay. It is not
an implementation plan.

## Decision Boundary

`platform-runtime-secrets.env` is deployment secret material, not source
configuration. The repository may keep a structural example only if every
assignment is synthetic and fail-loud; real values must be supplied through the
existing deployment secret paths at render/apply time.

The implementation must not solve this by moving plaintext into another
committed env file, Terraform variable file, workflow literal, generated
ConfigMap, or command line. The desired end state is a source tree that can run
static Kustomize validation without carrying usable runtime secret values, plus
a deployment path that documents where real values come from.

## Canonical Incumbents

| Concern | Canonical incumbent | Guardrail for #1195 |
| --- | --- | --- |
| GCP runtime generation | `scripts/gcp/render_runtime_env.py`, `scripts/gcp/tests/test_render_runtime_env.py` | Generated runtime files carry non-secret configuration and secret references only. Do not add secret values to `platform-runtime.generated.env`. |
| Bootstrap deployment | `.github/workflows/_gcp-dev.yml`, `scripts/bootstrap/deploy.py`, `platform/k8s/gcp/README.md` | CI/bootstrap should hydrate or create Kubernetes Secrets from GitHub Secrets, Terraform outputs, or GCP Secret Manager payloads before `kubectl apply -k`; keep the contract documented. |
| Runtime secret store | `platform/terraform/gcp/modules/platform-core/*`, `runtime_secret_ids`, `shifter/shifter_platform/entrypoint.sh`, `shifter/shifter_platform/documentation/docs/technical/dev/secrets.md` | Prefer GCP Secret Manager bundle IDs and existing entrypoint hydration for app/database/cache secrets. Kubernetes Secrets are a runtime binding layer, not a source-of-truth vault. |
| Kustomize overlay shape | `platform/k8s/gcp/overlays/gcp-dev/kustomization.yaml`, `patch-runtime-secretref.patch` | If the overlay keeps `secretGenerator`, its input must be local/gitignored or synthetic-only. Preserve `envFrom.secretRef` shape for workloads unless the Helm/bootstrap path intentionally supersedes it. |
| Secret scanning | `.gitleaks.toml`, `.pre-commit-config.yaml`, `scripts/adr_guard/adr_guard.py`, `docs/adr/index.yaml` | Add the repo-specific low-entropy guardrail to `adr_guard`; do not rely on entropy scanning alone for `*-secrets.env` files. Guardrail-file changes must update ADR docs. |
| Kubernetes validation | ADR-004-R5, ADR-006, `.kube-linter.yaml`, kubeconform, `_quality.yml` rendered-kustomize checks | Placeholder/example secret inputs must still let `kustomize build`, kube-linter, and kubeconform validate the rendered deployment shape. |
| Deploy secret inventory | `docs/dev/deploy-secrets.md` | Document any new GitHub secret, local generated file, or Secret Manager bootstrap prerequisite there instead of scattering setup instructions. |

## Cross-Cutting Layers

Security layers the design must satisfy:

- Auth surface: this issue should not alter Identity Platform, Django session
  creation, bootstrap-operator elevation, or Mission Control authorization.
  Any runtime secrets consumed by auth must still be sourced through the
  existing GCP Secret Manager / entrypoint path.
- Secret-handling surface: real values belong in GitHub Actions secrets for CI
  inputs, GCP Secret Manager for runtime bundles, or a Kubernetes Secret created
  at deploy time from those sources. Committed files may contain only
  placeholders such as `REPLACE_AT_DEPLOY` or non-sensitive structural keys.
- Env-binding shape: workloads currently consume `platform-runtime` plus
  `platform-runtime-secrets` via `envFrom`. Preserve that shape unless the
  implementation migrates the overlay to the chart/bootstrap runtime contract in
  one reviewed change. ConfigMap-bound files remain non-secret; Secret-bound
  files must not be committed with real assignments.
- Config validators: `gitleaks` is necessary but insufficient because lab
  defaults and short placeholders can be low entropy. Add a deterministic
  `adr_guard` check that fails on tracked `*-secrets.env` files containing
  populated assignments outside approved synthetic example paths. Tests should
  cover comments, blank values, placeholders, and real-looking assignments.
- OS/process exposure: deployment scripts must avoid passing secret values in
  process argv, shell-expanded command strings, workflow logs, or generated
  files that survive checkout. Prefer stdin, `--from-env-file` with a
  gitignored local file, Secret Manager access, or Kubernetes Secret manifests
  applied without echoing values.
- Error envelopes and logging: validation failures should report file paths and
  variable names only. Do not print rejected secret values in `adr_guard`,
  workflow preflights, bootstrap errors, or Kustomize helper output.
- Kubernetes runtime surface: `Secret` objects generated by Kustomize are
  acceptable only as deployment-time artifacts. Do not treat a committed
  Kustomize `secretGenerator` input as an acceptable secret store.

Maintainability incumbents the implementation must build on:

- `scripts/adr_guard/adr_guard.py` and its tests for repo-specific policy.
- ADR-004 / ADR-002 in `docs/adr/index.yaml` for documenting guardrail changes.
- Existing GCP Secret Manager bundles and `runtime_secret_ids` outputs.
- Existing entrypoint hydration for app, DB, Guacamole, and Redis secret
  payloads.
- Existing GCP runtime renderer tests for negative assertions that generated env
  files do not carry secret values.
- Existing docs: `docs/dev/deploy-secrets.md`, `platform/k8s/gcp/README.md`,
  and `shifter/shifter_platform/documentation/docs/technical/dev/secrets.md`.

## Extensibility Seam

Parameterize the guardrail around path patterns and allowed synthetic tokens,
not around today’s single file. The next reasonable variation is another
overlay or environment adding `*-secrets.env`; it should be covered without
editing the checker. The deployment seam should be environment-owned
(`gcp-dev`, future `gcp-prod`, local) and should accept a secret source choice
such as generated local env file, Secret Manager bundle, or Kubernetes Secret
name without changing workload manifests.

## Whole-Repo Scope

In scope for the future implementation:

- `platform/k8s/gcp/overlays/gcp-dev/platform-runtime-secrets.env` and any
  replacement example or gitignored local filename.
- `platform/k8s/gcp/overlays/gcp-dev/kustomization.yaml` and
  `patch-runtime-secretref.patch` if the secret binding changes.
- `.gitignore` if a generated local secret env file is introduced.
- `scripts/adr_guard/adr_guard.py`, `scripts/adr_guard/tests/test_adr_guard.py`,
  `docs/adr/index.yaml`, and ADR enforcement docs if adding the required
  guardrail.
- `.gitleaks.toml` only for entropy-scanner tuning; do not use broad allowlists
  as the primary control.
- `docs/dev/deploy-secrets.md`, `platform/k8s/gcp/README.md`, and developer
  secrets docs for operator-facing bootstrap instructions.
- `.github/workflows/_gcp-dev.yml` and `scripts/bootstrap/deploy.py` only if the
  CI/bootstrap flow needs to create or hydrate the runtime Kubernetes Secret.

## Gotchas And Anti-Patterns

- Do not rename the file while keeping assignments in source.
- Do not replace one committed secret env file with a committed Kubernetes
  Secret manifest containing base64-encoded values. Base64 is not encryption.
- Do not move values into `platform-runtime.env`,
  `platform-runtime.generated.env`, Terraform `*.tfvars`, workflow YAML, or
  README command examples.
- Do not add a gitleaks allowlist that hides `platform/k8s/gcp/**` secrets.
- Do not conflate secret values with secret references. `DB_SECRET_ID`,
  `APP_SECRET_ID`, and similar provider resource IDs may be config; passwords,
  tokens, JSON-auth keys, private keys, and Redis AUTH strings are values.
- Do not weaken Kustomize, kube-linter, kubeconform, ADR guard, or workflow
  checks to make a placeholder file pass.
- Do not introduce a new secret manager abstraction for this issue. Existing
  GCP Secret Manager, entrypoint, bootstrap, and Kubernetes Secret seams cover
  the need.
- Do not log generated env file contents or `kubectl create secret` literals in
  workflow output.

## Non-Goals

- Do not redesign Identity Platform auth, Guacamole JSON auth, Redis AUTH/TLS,
  per-instance guest credentials, or cloud adapter protocols.
- Do not migrate the whole GCP deployment from Kustomize to Helm or vice versa
  as part of this remediation.
- Do not rotate production secrets or rewrite git history in this code change;
  that is an operational incident-response task if real secrets were exposed.
- Do not add user-managed secret UI, a generic vault service, or a new
  exception hierarchy.
- Do not broaden Workload Identity, Secret Manager IAM, network policy, or pod
  security to compensate for secret bootstrap friction.

## Validation

At minimum, changes on this path must run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Then add the stack-native checks for touched surfaces:

- `kube-linter lint --config .kube-linter.yaml platform/k8s/` and
  `kubeconform -strict -summary -ignore-missing-schemas -kubernetes-version 1.31.0 platform/k8s/gcp/base/*.yaml`
  when Kubernetes manifests or overlay inputs change.
- `actionlint` when workflows change.
- `python3 -m unittest scripts/adr_guard/tests/test_adr_guard.py` when ADR
  guard logic changes.
- Targeted GCP renderer/bootstrap tests if the deployment hydration path
  changes.
