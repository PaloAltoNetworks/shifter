# installation — root installation config + backend bundle contract

A Shifter OSS deployment is configured by **one** root file, `shifter.yaml`, at the
repository root, and that file selects a **backend bundle**. This package owns both
contracts: the typed root schema, a loader that fails fast with aggregated errors, the
`shifter-config` CLI, the machine-readable backend bundle contract every backend
exposes, and the registry of known backends. It is the single authoritative parser —
setup, doctor, CI, and (later) runtime derivation validate against it rather than
re-parsing the YAML by hand or maintaining a parallel backend table. Constrained by
[ADR-011](../../docs/adr/index.yaml) and the
[Root-Configured Backend Bundles](../../docs/architecture/root-configured-backend-bundles.md)
architecture note.

This package is Django-free (pydantic v2 + PyYAML only) so scripts, CI, and the
Django app can all use it.

## `shifter.yaml`

```yaml
version: 1                       # optional, default 1; only schema version 1 is supported
backend: aws                     # required; one of the known backends (currently: aws, gcp)
deployment:                      # required
  name: shifter                  # required; DNS-label-safe (lowercase letters, digits, internal hyphens, 1-40 chars)
  domain: shifter.example.com    # required; a real public DNS hostname (>= 2 labels, not an IP, not bare localhost)
  profile: prod                  # optional, default prod; one of {prod, dev}; must be allowed by the selected backend
secrets:                         # logical name -> reference; the selected backend requires an entry for each
  django_secret_key: shifter/prod/django-secret-key   #   secret it declares (value may be `prompt` to collect at
  db_password: prompt                                 #   deploy time); typo'd / unknown keys are rejected
settings:                        # optional; backend-specific settings, validated by the selected backend bundle
  region: us-east-2
```

### Field reference

| Key | Required | Type | Notes |
| --- | --- | --- | --- |
| `version` | no (default `1`) | int | Schema version. Only `1` is supported today. |
| `backend` | yes | string | The backend bundle to use. Must be a name in the [backend bundle registry](#backend-bundle-contract) (`aws`, `gcp`); the `local` backend is #1119. |
| `deployment.name` | yes | string | DNS-label-safe identifier for this installation: lowercase letters, digits, and internal hyphens; 1-40 characters. |
| `deployment.domain` | yes | string | Public hostname users reach this deployment at. Must be a fully-qualified DNS name (at least two labels), lowercase, with no scheme, no IP literal, and no trailing dot. |
| `deployment.profile` | no (default `prod`) | string | Deployment tier: `prod` or `dev`. Must also be a profile the selected backend supports. |
| `secrets` | no (default `{}`) | mapping | Logical secret name → reference identifier. Keys match `^[a-z][a-z0-9_]*$`. Values are *references* — a provider secret name, a GitHub Actions secret name, an environment variable, or the literal `prompt` (collect at deploy time) — never the secret value itself. The selected backend bundle requires an entry here for each secret *it* declares (value may be `prompt`) and rejects entries for secrets it does not use, so a missing or typo'd secret key fails before deploy. |
| `settings` | no (default `{}`) | mapping | Backend-specific settings. The root schema only checks it is a mapping; the selected backend bundle's `settings_model` validates the contents. |

`validate` checks the *shape* of the root config — the backend selector, deployment
identity, secret references, and that `settings` is a mapping — then runs the selected
backend bundle's checks: its `settings_model` validates the `settings` contents, and
its `RequiredSecret.reference_pattern`s validate the supplied secret references. Unknown
top-level keys, unknown keys under `deployment`, missing required keys, an unknown
backend, an unsupported profile/backend combination, a malformed name or domain, a
`secrets` value that is clearly raw key material (multi-line, PEM-headered, or
implausibly long), and any backend-specific `settings` or secret-reference problem the
bundle reports are all rejected — and all problems are reported together — *before*
Terraform, Helm, Django, workers, or deployment scripts run. The shipped `aws`/`gcp`
bundles accept any `settings` mapping and reference format today (`settings_model` and
`reference_pattern` unset); the full per-backend validation lands with the AWS/GCP
migration issues (#1116/#1117).

> The root config holds references, not secret values. Storing a raw password,
> token, private key, or service-account JSON in `shifter.yaml` is rejected by the
> schema where it is recognizable and caught independently by `gitleaks`. The schema
> cannot tell a short secret value from a secret *name*, so the precise per-provider
> reference grammar is the backend bundle's responsibility
> (`RequiredSecret.reference_grammar` for humans, `reference_pattern` for machines).

## Backend bundle contract

A **backend bundle** is the public OSS unit of backend selection: a deployment picks
one bundle (`aws`, `gcp`, `local`, ...) and that bundle owns everything the backend
needs. [`contract.py`](contract.py) defines the typed, machine-readable contract every
bundle exposes; [`registry.py`](registry.py) is the single registry of known bundles
that the root schema, setup, doctor, CI, and docs generation all consume.

A `BackendBundle` carries:

| Field | What it is |
| --- | --- |
| `contract_version` | The contract-shape version (independent of `shifter.yaml`'s `version`); an unknown version fails closed. |
| `name`, `title`, `maturity`, `description` | Stable backend identity for selection and documentation. |
| `supported_profiles` | The deployment profiles this backend supports (replaces the old hard-coded `ALLOWED_PROFILES` data). |
| `settings_model` | A Pydantic model (which must set `extra="forbid"`) validating this backend's `RootConfig.settings`; `None` means "any mapping" until the backend supplies one. |
| `required_tools` | Command-line tools the backend's setup/deploy/doctor flow needs (bare executable names; every `validation_checks` executable must appear here). |
| `required_secrets` | Logical secret names, the human-readable reference grammar each accepts, and an optional `reference_pattern` (anchored regex) for machine validation (the root config holds references, never values). |
| `generated_outputs` | The runtime/infra/CI values the backend renders, each tagged with owner, source, an `OutputDestination` (where it lands — `runtime-env`, `kubernetes-secret`, `provider-secret-store`, `terraform-variables`, `helm-values`, `generated-file`), sensitivity (`public` / `secret-reference` / `secret-value`), and the process roles that consume it. A `secret-value` output may only be placed in a Kubernetes Secret or a provider secret store — the contract rejects, e.g., a secret value destined for a ConfigMap. |
| `validation_checks` | Checks the backend runs (or front-runs) before mutating infrastructure — each an argv command spec (PATH-resolved executable name, repo-relative path args, no internal whitespace or shell metacharacters), never a shell string. |
| `health_checks` | Read-only post-render / post-deploy probes. |
| `capabilities` | Which cloud-neutral protocols (storage, queue, task runner, secrets, ...) the backend satisfies through the existing `shared.cloud` / `engine/provisioner/cloud` seams. |
| `owned_files`, `docs` | Repository-relative path roots the backend owns, so validation and docs generation can find them without a branch router. |

Within a bundle, the `name` / `logical_name` of every `RequiredTool`, `RequiredSecret`,
`GeneratedOutput`, `ValidationCheck`, and `HealthCheck` must be unique (consumers build
maps keyed by them).

```python
from installation import BACKEND_BUNDLES, get_backend_bundle

bundle = get_backend_bundle("aws")               # -> BackendBundle | None
list(BACKEND_BUNDLES)                            # -> ["aws", "gcp"]
bundle.supports_profile("dev")                   # -> True
bundle.validate_settings({"region": "us-east-2"})    # -> normalized dict; raises InstallationConfigError on failure
bundle.settings_issues({"region": "us-east-2"})      # -> [ConfigIssue, ...] anchored under "settings"; [] if valid
bundle.secret_reference_issues({"django_secret_key": "..."})  # -> [ConfigIssue, ...] anchored under "secrets.<name>"
```

Adding a backend is a new entry in `BACKEND_BUNDLES` (plus its worked example under
`examples/`) — not a schema change and not a branch router.

## Usage

This package is its own [uv](https://docs.astral.sh/uv/) project, so run the CLI
through `uv run --project shifter/installation` from the repo root (paths are
relative to the directory you run from):

```bash
# After copying an example to ./shifter.yaml at the repo root:
uv run --project shifter/installation shifter-config validate            # validates ./shifter.yaml
uv run --project shifter/installation shifter-config validate path/to/shifter.yaml
# equivalently:  uv run --project shifter/installation python -m installation validate [PATH]
```

`validate` prints `OK — root config shape is valid (backend=…, profile=…)` and exits
`0` when the config is valid, or prints each problem to stderr and exits `1`.

```python
from installation import load_root_config, validate_root_config_file, InstallationConfigError

config = load_root_config("shifter.yaml")   # raises InstallationConfigError with aggregated .issues
issues = validate_root_config_file("shifter.yaml")  # returns a list of ConfigIssue; never raises
```

## Examples

Worked, machine-validated configs for the supported backends live in
[`examples/`](examples/) (`aws.yaml`, `gcp.yaml`). The package test suite loads
every file in that directory through the same parser, so an example can never drift
from the schema. Copy one to `./shifter.yaml` at the repo root and edit it for your
deployment.

## Layout

| File | Purpose |
| --- | --- |
| `schema.py` | Pydantic v2 models for the root config (`RootConfig`, `DeploymentConfig`) — the root-key *shape*, including that `settings` is a mapping; the contents of `settings` and the secret reference grammar belong to the selected backend bundle. |
| `contract.py` | The machine-readable backend bundle contract: `BackendBundle` and its `GeneratedOutput` / `ValidationCheck` / `HealthCheck` / `RequiredTool` / `RequiredSecret` / `OwnedFiles` / `CommandSpec` parts, plus the `BackendMaturity` / `OutputSensitivity` / `ProcessRole` / `BackendCapability` / `OutputKind` enums. |
| `registry.py` | The single registry of known backend bundles (`BACKEND_BUNDLES`, `get_backend_bundle`) and the derived `KNOWN_BACKENDS` / `KNOWN_PROFILES` / `ALLOWED_PROFILES` the root schema uses. |
| `loader.py` | `load_root_config` / `validate_root_config_file` — read YAML, validate the root shape, then run the selected backend bundle's `settings` and secret-reference checks; aggregate every problem. |
| `errors.py` | `ConfigIssue` and `InstallationConfigError` — the error model (never carries the rejected input, so it cannot leak a mistyped secret). |
| `cli.py` / `__main__.py` | The `shifter-config` CLI. |
| `examples/` | Worked example configs, validated by the test suite. |
