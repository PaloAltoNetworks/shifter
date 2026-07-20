# Backend Bundle Contract Publication Preflight

Status: pre-implementation architecture guidance

Date: 2026-07-13

Issue: GitHub #1323, "Publish the backend-bundle contract as a versioned
artifact with CI drift and breaking-change gates"

This is a requirement-free run. The GitHub issue title, body, scope, and
acceptance criteria are the shipping contract. This note is intentionally not an
implementation plan.

## Scope Boundary

#1323 publishes the existing backend-bundle contract as a versioned, committed
artifact so downstream backend-bundle authors can build against it without
reading Shifter internals. The artifact is a public contract publication, not a
new backend selector, settings parser, runtime config surface, provider adapter,
deployment workflow, or registry.

The canonical producer remains `shifter/installation/contract.py` plus the
registry entries in `shifter/installation/registry.py`. The committed artifact
must be generated from those closed Pydantic models and deterministic registry
data, then checked for drift in CI. Do not hand-maintain a second schema whose
meaning can diverge from the Python contract.

The contract version is independent of `RootConfig.version` in
`shifter/installation/schema.py` and independent of the `installation` Python
package version. A backend-bundle contract version describes the public
interface consumed by bundle authors and downstream tooling.

## Architecture Decisions

- Keep `BackendBundle` and its nested contract models as the source of truth for
  contract shape and invariants. The committed artifact is a publication output
  generated from that source.
- Make the artifact deterministic, stable, and reviewable. Ordering,
  serialization, and examples must not depend on Python object identity, set
  iteration order, local paths, timestamps, hostnames, or live environment.
- Keep the version bump explicit. A breaking contract change requires changing
  the public contract version, adding a migration note/changelog entry, and
  preserving a compatibility check against the prior committed artifact.
- Treat drift and breaking-change checks as quality/contract gates. They must
  run in the existing `shifter/installation` lint/test/CI lane or a small
  package-local CLI/test invoked from that lane; workflow-only logic must not be
  the source of compatibility semantics.
- Validate the AWS and GCP registry entries against the published version using
  the same public artifact and the same `BackendBundle` validators. Do not add
  provider-specific schema copies or backend-name special cases.
- Keep diagnostics sanitized. Artifact and compatibility failures may name
  fields, enum values, backend names, contract versions, artifact paths, and
  changelog/migration-note paths. They must not print secret references, raw
  settings values, env dumps, Terraform output, provider credentials, or local
  absolute paths.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Contract source | `shifter/installation/contract.py` | Generate the public artifact from `BackendBundle` and nested models; do not author a parallel schema by hand. |
| Supported bundles | `shifter/installation/registry.py` | Validate AWS and GCP through `BACKEND_BUNDLES`; do not maintain a second backend list in CI, docs, or workflows. |
| Root config boundary | `shifter/installation/schema.py`, `loader.py` | Keep `RootConfig.version`, root-field validation, backend-settings dispatch, and contract publication separate. |
| Error model | `shifter/installation/errors.py` | Report `ConfigIssue`-style path/message diagnostics without echoing rejected input. Avoid a new exception hierarchy. |
| CLI/test lane | `shifter/installation/cli.py`, `pyproject.toml`, `tests/` | Add publication/drift/compatibility checks beside the package's existing CLI and pytest coverage. |
| Example validation | `shifter/installation/tests/test_examples.py` | Keep examples tied to `load_root_config`; new contract examples should not become a second parser. |
| Runtime config inventory | `shifter/installation/runtime_inventory.py` | Do not include runtime env values or generated deployment config in the contract artifact. |
| Architecture control | ADR-011, `docs/architecture/root-configured-backend-bundles.md` | Extend the root-configured backend-bundle doctrine; create a new ADR only if implementation changes enforceable policy beyond ADR-011. |
| CI routing | `.github/workflows/_quality.yml`, `.pre-commit-config.yaml` | Reuse the existing `installation-lint`, `installation-tests`, and local pre-commit patterns; new workflow checks stay additive. |
| Repo guardrails | `scripts/adr_guard/adr_guard.py`, `docs/adr/index.yaml`, `docs/adr/exceptions.yaml` | Update ADR guard/docs only if the implementation adds an enforceable architecture rule or exception. |

## Cross-Cutting Layers The Design Must Pass

- Contract-shape validation: `BackendBundle` and nested Pydantic models remain
  closed (`extra="forbid"`), frozen, version-gated, and invariant-checking. The
  artifact generator must read this shape, not duplicate field validators.
- Registry validation: `BACKEND_BUNDLES`, `KNOWN_BACKENDS`, `KNOWN_PROFILES`,
  and `ALLOWED_PROFILES` remain derived from the registry. AWS and GCP must
  validate against the published contract version through registry data, not
  through backend-name fixtures that drift from production.
- Root config parsing: `load_root_config()` and `RootConfig` keep owning
  operator-authored `shifter.yaml`. Contract publication must not parse
  `shifter.yaml`, read `.env`, infer backend from branch names, or change
  `RootConfig.version`.
- Secret-handling surface: the contract may publish logical secret names,
  reference grammars, regex patterns, destinations, and sensitivity labels. It
  must never publish secret values, provider credentials, generated env values,
  Terraform variables/output, GitHub secret values, or local operator config.
- Command/OS exposure: command specs remain structured argv arrays validated by
  `CommandSpec`; new checker invocations must use structured argv with
  repo-relative paths. Do not route artifact JSON, secrets, settings payloads, or
  compatibility baselines through shell strings or process argv.
- Error envelope: failures should use package-local sanitized diagnostics or
  pytest assertion messages that include field paths and expected remediation.
  Do not surface raw Pydantic `input`, full YAML/env bodies, tracebacks with
  values, or provider exception text.
- Workflow layer: `.github/workflows/_quality.yml` and `.pre-commit-config.yaml`
  already run `shifter/installation` lint/tests. Any CI gate added for drift or
  breaking changes must be additive, use `contents: read`, avoid secrets/cloud
  permissions, and keep `actionlint`/ADR guard behavior intact.
- Import/security tooling: ruff, Bandit, pytest coverage, `adr_guard`, and
  gitleaks remain in force. Do not suppress checks to publish generated JSON or
  changelog text.
- Artifact persistence: the committed artifact is source-controlled public
  metadata. It must not be placed under generated-sensitive locations blocked by
  ADR-004, must not include host-specific material, and should carry a generated
  header/comment only if the chosen file format supports it without breaking
  consumers.

## Extensibility Seam

The seam is a small contract-publication API over:

- contract version
- artifact format/path
- selected backend bundle records
- compatibility baseline path
- migration-note/changelog path

The first version covers AWS and GCP at `contract_version=1`. The next
reasonable variation is another backend, another artifact format, or a v2
contract with additive fields. That should require changing the versioned
artifact metadata and compatibility baseline, not copying validators into
workflows, Terraform, Helm, Django settings, or provider scripts.

## Whole-Repo Scope

Future implementation must evaluate changes against:

- `docs/architecture/root-configured-backend-bundles.md`
- `docs/adr/index.yaml` ADR-011 if enforceable rules change
- `shifter/installation/contract.py`
- `shifter/installation/registry.py`
- `shifter/installation/schema.py`
- `shifter/installation/loader.py`
- `shifter/installation/errors.py`
- `shifter/installation/cli.py`
- `shifter/installation/README.md`
- `shifter/installation/examples/aws.yaml`
- `shifter/installation/examples/gcp.yaml`
- `shifter/installation/tests/`
- `shifter/installation/pyproject.toml`
- `.github/workflows/_quality.yml`
- `.github/workflows/deploy.yml` path routing only if installation paths or
  guardrail docs routing change
- `.pre-commit-config.yaml`
- `scripts/adr_guard/**` only if the publication gate becomes an ADR-level
  guardrail

Out of scope for #1323 unless the implementation changes the relevant surface:
`shifter/shifter_platform` runtime adapter code, Terraform modules, Helm values,
Kubernetes manifests, provider bootstrap scripts, Django API views, persistence
models, and live cloud verification.

## Gotchas And Anti-Patterns

- Do not hand-write JSON Schema, Markdown tables, or examples as the source of
  truth. Generate from the Python contract and check drift.
- Do not conflate `RootConfig.version`, backend `contract_version`, artifact
  schema version, and package version.
- Do not add a second backend registry, second settings schema, second
  validation dispatcher, second error hierarchy, or second secret-reference
  validator.
- Do not make CI compatibility semantics live only in YAML or shell. The
  workflow may invoke a checker; the checker owns semantics.
- Do not classify all enum additions as automatically supported by all
  backends. `registry.py` currently enumerates capabilities explicitly to avoid
  that bug.
- Do not compare artifacts using nondeterministic raw file text if canonical
  serialization is available. Normalize ordering and formatting before drift
  checks.
- Do not print raw contract instances with settings values, raw config bodies,
  environment variables, or secret references in failure output.
- Do not treat the published artifact as runtime authority for provider adapter
  selection. Runtime selection still flows from validated backend configuration
  through existing service boundaries.

## Non-Goals

- No implementation in this preflight note.
- No new backend bundle, provider adapter, Terraform module, Helm value,
  Kubernetes manifest, Django setting, database model, or runtime API.
- No change to `RootConfig.version` or root `shifter.yaml` shape unless a later
  issue explicitly changes root config.
- No live cloud, Terraform, Kubernetes, Docker, GitHub API, or secret-store
  calls in the publication/drift/breaking-change gates.
- No public package publishing requirement beyond a committed repository
  artifact unless a separate issue asks for external distribution.
- No Ground Control requirement UID for this requirement-free issue.
