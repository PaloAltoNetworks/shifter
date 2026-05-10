# ADR Enforcement

Architecture rules in this repo are enforced by tooling, not just prose.

## What Exists

The current enforcement stack has six parts:

1. `docs/adr/index.yaml`
   Machine-readable ADR registry. Each accepted ADR lists the rules and the checks that enforce them.

2. `docs/adr/exceptions.yaml`
   Explicit exceptions. If a rule needs a temporary waiver, record it here with an owner and expiry instead of leaving the exception implicit.

3. `scripts/adr_guard/adr_guard.py`
   Repo-native policy runner. This is the entrypoint for ADR conformance checks.

4. `.pre-commit-config.yaml`
   Fast local enforcement. The ADR guard runs before commit so architectural drift is caught locally.

5. `.github/workflows/_quality.yml`
   CI enforcement. ADR conformance runs as its own architecture gate.

6. Existing ecosystem tooling
   - `import-linter` for Python package contracts
   - `actionlint` for GitHub Actions workflows
   - `TFLint` for Terraform linting (including the `tflint-ruleset-google` plugin for GCP resources)
   - `gitleaks` for new secret leakage detection
   - `helm lint` for Helm chart validation where files are templates rather than plain YAML
   - `kubeconform` for Kubernetes manifest schema validation
   - `kube-linter` for Kubernetes security and best-practice enforcement
   - `Checkov` for IaC security scanning (Terraform and Kubernetes)

There is also agent-specific wiring:

- `.claude/hooks/adr_guard_hook.py` runs the ADR guard after Claude edits files.
- `.claude/skills/adr-check/SKILL.md` provides a default workflow for ADR conformance work.
- `.claude/skills/architecture-review/SKILL.md` provides a repo-specific architecture review checklist.
- `AGENTS.md` gives Codex a repo-local policy file, including Ground Control project context for the `/implement` workflow. The GC project pointer (and matching `.ground-control.yaml` `project:` field) names the `shifter` project (id `df4e718f-1f67-46f8-a375-3ba53fabc9c4`) with `CTF-*`, `PLAT-*`, `GEN-*` UID prefixes by subsystem; an earlier draft incorrectly pointed both at `aphelion` (a separate, unrelated project).

Review controls:

- `.github/CODEOWNERS` requires review on guardrail files and shared/public architecture seams.
- `.github/pull_request_template.md` requires an ADR impact section on PRs.
- `.github/copilot-instructions.md` now points GitHub Copilot toward the same ADR enforcement model.

## Current Checks

The first slice intentionally stays small:

- `adr-registry`
  Validates the ADR registry and exception files.

- `layer-imports`
  Enforces the existing cross-layer import policy from `scripts/check_layer_imports/layer_imports.yaml`.

- `guardrail-docs`
  Requires guardrail changes to update ADR or developer docs in the same change.
  This is a changeset-level check (needs to see multiple files) so it runs in
  pre-commit and `--level fast`, but NOT in the per-edit Claude hook.

- `cross-layer-model-imports`
  Fails on direct cross-layer model imports inside service layers. The current tree already satisfies this rule, so it is part of the default guard.

- `import-linter`
  Adds package-level forbidden-import contracts across the main Django app layers.

- `actionlint`
  Lints GitHub Actions workflows beyond plain YAML validation.

- `TFLint`
  Adds Terraform linting on top of `terraform fmt` and `terraform validate`.
  The initial profile is intentionally narrow: it leaves existing repo-wide
  debt rules disabled so the new gate enforces signal instead of legacy noise.

- `gitleaks`
  Scans newly introduced commits for likely secrets, with a small repo config for approved false positives.

- `cloud-factory-seam`
  Enforces ADR-005-R1: every cloud adapter module in `cloud/aws/` must have a
  counterpart in `cloud/gcp/` and vice versa. Catches provider parity drift
  when one side adds a new adapter without the other. Runs in both fast and ci
  levels.

- `kubeconform`
  Validates Kubernetes manifests against official schemas. Catches misspelled
  fields, invalid resource types, and schema violations before they reach a
  cluster. Pinned to the target GKE Kubernetes version.

- `helm lint`
  Validates the Helm-packaged GCP control plane. This is the correct validation
  boundary for raw chart templates, which are not parseable by generic YAML
  tooling before render time.

- `kube-linter`
  Enforces Kubernetes security and best practices: non-root containers,
  read-only root filesystems, resource limits, privilege escalation prevention,
  and more. Configured via `.kube-linter.yaml`.

- `checkov-k8s`
  CIS Kubernetes benchmark and container security checks on manifests in
  `platform/k8s/`. Currently soft-fail while existing manifests are being
  hardened.

- `k8s-image-registry`
  Verifies that the staged GCP Kubernetes deployment assets still point at
  Artifact Registry (`pkg.dev`), preventing accidental use of public or
  untrusted registries while the GCP workflow and generated assets are being
  reconciled around the Helm cutover.

- `k8s-pss-labels`
  Architecture check ensuring namespace manifests carry Pod Security Standards
  `pod-security.kubernetes.io/enforce` labels. Enforces ADR-006-R1.

- `k8s-deployment-security-context`
  Enforces ADR-006-R2 against two enforcement sources: (1) every YAML
  document under `platform/k8s/gcp/base/` (recursive) whose `kind` is
  `Deployment`, and (2) the rendered output of
  `helm template platform/charts/shifter -f <values>` for each entry
  in `HELM_VALUES_FILES` (`values-gcp-dev.yaml`, `values-gcp-prod.yaml`).
  Per ADR-007 the chart is the authoritative deployment contract;
  base manifests are supporting snapshots. Validating both sources
  catches regressions where a chart template or values file removes
  a required securityContext field even when the base snapshots
  remain compliant. Kind-based filtering, not filename-based — a
  Deployment shipped under any filename or extension is scanned.
  Multi-document files (`---` separator) and indentless YAML
  sequences are supported.
  Per pod template: `securityContext.seccompProfile.type` must be
  `RuntimeDefault`. Per container AND init container: the *effective*
  context (after pod-level inheritance for `runAsNonRoot`,
  `runAsUser`, `runAsGroup`) must satisfy
  `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]` with
  no `capabilities.add`, `readOnlyRootFilesystem: true`,
  `runAsNonRoot: true`, `securityContext.privileged` not `true`, an
  optional container-level `seccompProfile.type` (when set) equal to
  `RuntimeDefault`, and `runAsUser`/`runAsGroup` set to positive
  integers (booleans are rejected since Python treats `bool` as a
  subclass of `int`). Runs in the `ci` level (`--all --level ci`,
  including CI) and in a dedicated pre-commit hook `adr-guard-k8s`
  (separate from `adr-guard-fast`) that triggers on
  `platform/k8s/gcp/base/*.{yaml,yml}` and
  `platform/charts/shifter/` changes. Not in the `fast` level, so
  unrelated `--level fast` invocations and the system-Python
  `adr-guard-fast` hook do not pull in the YAML or helm dependencies.
  **Runtime dependencies:** PyYAML (`pyyaml>=6.0`) and Helm
  (`v3.15.4`). The `adr-conformance` job in
  `.github/workflows/_quality.yml` bootstraps pip via the stdlib
  `ensurepip` module (the self-hosted Amazon Linux runner's system
  Python ships without pip; `actions/setup-python` cannot fetch
  Python 3.12 for the runner's architecture), then installs PyYAML
  via `python3 -m pip install --no-deps --target
  ${RUNNER_TEMP}/py-deps` with `PYTHONPATH=${RUNNER_TEMP}/py-deps`
  on the run step, and Helm via the official `get.helm.sh` release
  tarball extracted to `${RUNNER_TEMP}/helm-bin/` and added to
  `$GITHUB_PATH`. The `--user` site PyPI install of pip itself is
  job-scoped on the self-hosted runner; PyYAML lands under
  `${RUNNER_TEMP}/py-deps` which is ephemeral. The `adr-guard-tests`
  job uses the same ensurepip + PyYAML pattern; the chart-rendering
  test uses a fake helm shim, so CI tests don't need real helm. The `adr-guard-k8s` pre-commit hook
  uses `language: python` with `additional_dependencies:
  pyyaml>=6.0` so PyYAML is provisioned in an isolated pre-commit
  virtualenv; helm is a developer prerequisite shared with the
  existing `helm-lint-shifter-chart` hook. Complements existing
  kube-linter checks (`run-as-non-root`, `no-read-only-root-fs`,
  `privilege-escalation-container`) which cover the subset
  PSS-restricted enforces directly; this check fills the gaps for
  `seccompProfile`, `capabilities.drop`/`add`, container-level
  seccomp overrides, `privileged: true`, pod-level inheritance, and
  initContainer coverage. Implementation note: the validator is
  decomposed into focused helpers (`_check_container_basic_fields`,
  `_check_container_capabilities`, `_check_container_seccomp`,
  `_check_container_identity`, `_resolve_pod_spec`,
  `_resolve_pod_sc`, `_validate_containers_list`, `_scan_targets`,
  `_validate_base_files`, `_validate_chart_renders`) so each piece
  stays under SonarCloud's cognitive-complexity threshold and tests
  can target each clause independently.

- `rds-pending-modifications`
  Post-`terraform apply` gate in `_shifter-platform.yml`. Reads the portal
  Terraform outputs, then calls `aws rds describe-db-instances` for each
  `*_db_instance_id` output and fails the deploy job if any RDS instance
  still has non-empty `PendingModifiedValues` or non-`in-sync`/`applying`
  `DBParameterGroups[].ParameterApplyStatus`. Catches the failure mode
  documented in `dev/terraform.md` ("RDS Change Application") where a
  successful apply silently queues class/parameter changes for the
  maintenance window. Implementation: `scripts/check_rds_pending_modifications/`,
  with its own uv-managed dev environment, dedicated CI lint+test jobs
  (`check-rds-pending-modifications-lint` / `-tests` in `_quality.yml`),
  and matching pre-commit hooks (ruff + pytest). Same pattern as
  `scripts/check_layer_imports/`.

## Local Usage

Run the fast profile on the full repo:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level fast
```

Run the CI profile:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Useful ecosystem checks:

```bash
cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
actionlint
helm lint platform/charts/shifter -f platform/charts/shifter/values-gcp-dev.yaml
kube-linter lint --config .kube-linter.yaml platform/k8s/
kubeconform -strict -summary -ignore-missing-schemas -kubernetes-version 1.31.0 platform/k8s/gcp/base/*.yaml
```

Run on specific files:

```bash
python3 scripts/adr_guard/adr_guard.py --files .github/workflows/_quality.yml --level fast
```

Run on staged or modified files:

```bash
python3 scripts/adr_guard/adr_guard.py --changed --level fast
```

## How To Add A Rule

1. Add or update the ADR entry in `docs/adr/index.yaml`.
2. Implement the check in `scripts/adr_guard/adr_guard.py`.
3. Decide where it belongs:
   - fast local gate
   - CI gate
   - Claude post-edit hook
   - agent policy docs
4. If the rule cannot be enforced immediately, add a dated exception to `docs/adr/exceptions.yaml`.

## Exceptions

Use exceptions sparingly. They are for temporary, explicit waivers only.

Required fields:

- `rule_id`
- `owner`
- `reason`
- `expires_on`

Optional narrowing fields:

- `checks`
- `paths`

Expired exceptions fail `adr_guard`, so they cannot linger unnoticed.

## Design Constraints

- Keep the default local gate fast.
- Do not rely on external dependencies for the core ADR guard.
- Prefer explicit exceptions over hidden tolerances.
- Do not make CI architecture checks skippable through the normal test-skip path.
- Keep review friction focused on guardrail files, not on ordinary feature code.
