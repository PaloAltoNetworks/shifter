# installation — root installation config contract

A Shifter OSS deployment is configured by **one** root file, `shifter.yaml`, at the
repository root. This package owns that contract: the typed schema, a loader that
fails fast with aggregated errors, and the `shifter-config` CLI. It is the single
authoritative parser — setup, doctor, CI, and (later) runtime derivation validate
against it rather than re-parsing the YAML by hand. Constrained by
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
secrets:                         # optional; mapping of logical name -> reference identifier
  django_secret_key: shifter/prod/django-secret-key
settings:                        # optional; backend-specific settings, validated by the selected backend bundle
  region: us-east-2
```

### Field reference

| Key | Required | Type | Notes |
| --- | --- | --- | --- |
| `version` | no (default `1`) | int | Schema version. Only `1` is supported today. |
| `backend` | yes | string | The backend bundle to use. Must be one of the known backends (`aws`, `gcp`). The backend bundle registry in #1113 supersedes this set; the `local` backend is #1119. |
| `deployment.name` | yes | string | DNS-label-safe identifier for this installation: lowercase letters, digits, and internal hyphens; 1-40 characters. |
| `deployment.domain` | yes | string | Public hostname users reach this deployment at. Must be a fully-qualified DNS name (at least two labels), lowercase, with no scheme, no IP literal, and no trailing dot. |
| `deployment.profile` | no (default `prod`) | string | Deployment tier: `prod` or `dev`. Must also be a profile the selected backend supports. |
| `secrets` | no (default `{}`) | mapping | Logical secret name → reference identifier. Keys match `^[a-z][a-z0-9_]*$`. Values are *references* — a provider secret name, a GitHub Actions secret name, an environment variable, or the literal `prompt` — never the secret value itself. |
| `settings` | no (default `{}`) | mapping | Backend-specific settings. Opaque to the root parser; the selected backend bundle validates the contents (#1113). |

`validate` checks the *shape* of the root config — the backend selector, deployment
identity, secret references, and that `settings` is a mapping. Unknown top-level keys,
unknown keys under `deployment`, missing required keys, an unknown backend, an
unsupported profile/backend combination, a malformed name or domain, and a `secrets`
value that is clearly raw key material (multi-line, PEM-headered, or implausibly long)
are all rejected — and all problems are reported together — *before* Terraform, Helm,
Django, workers, or deployment scripts run. The *contents* of `settings` (and which
settings a backend requires) are validated by the selected backend bundle's
contract (#1113), not by this command.

> The root config holds references, not secret values. Storing a raw password,
> token, private key, or service-account JSON in `shifter.yaml` is rejected by the
> schema where it is recognizable and caught independently by `gitleaks`. The schema
> cannot tell a short secret value from a secret *name*, so the precise per-provider
> reference format is the backend bundle's responsibility (#1113).

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
| `schema.py` | Pydantic v2 models for the root config (`RootConfig`, `DeploymentConfig`). |
| `backends.py` | Provisional registry of known backends and the profiles each allows (superseded by the backend bundle registry in #1113). |
| `loader.py` | `load_root_config` / `validate_root_config_file` — read YAML, validate, aggregate errors. |
| `errors.py` | `ConfigIssue` and `InstallationConfigError` — the error model (never carries the rejected input, so it cannot leak a mistyped secret). |
| `cli.py` / `__main__.py` | The `shifter-config` CLI. |
| `examples/` | Worked example configs, validated by the test suite. |
