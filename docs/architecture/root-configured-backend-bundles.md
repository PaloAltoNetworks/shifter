# Root-Configured Backend Bundles

Status: current architecture, constrained by ADR-011

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1109>

## Summary

Shifter uses one root installation config, `shifter.yaml`, to select the
deployment backend and deployment profile.

The implementation lives in `shifter/installation/`:

- `schema.py` validates root fields.
- `loader.py` reads YAML, rejects duplicate keys and merge keys, and dispatches
  backend checks.
- `contract.py` defines the backend bundle contract.
- `registry.py` contains the supported backend bundles.
- `cli.py` exposes `shifter-config validate`.
- `examples/` contains validated AWS and GCP examples.

Published operator docs:

- `shifter/installation/README.md`
- `shifter/shifter_platform/documentation/docs/technical/dev/installation-config.md`

## Root Config Boundary

`shifter.yaml` is user-authored installation intent. It is not a Terraform
output file, Helm values file, generated runtime environment file, Kubernetes
manifest, or CI branch selector.

The root config owns:

- schema version
- selected backend
- deployment name
- deployment domain
- deployment profile
- logical secret references
- backend-specific settings mapping

The root schema validates root shape. Backend bundles validate backend-owned
settings and secret reference grammar when they declare those validators.

## Supported Backends

| Backend | Profiles | Required secrets | Settings validation |
| --- | --- | --- | --- |
| `aws` | `prod`, `dev` | `django_secret_key`, `db_password` | Any mapping accepted by root-config validation. Deployment tooling validates consumed values. |
| `gcp` | `prod`, `dev` | `django_secret_key` | Any mapping accepted by root-config validation. Deployment tooling validates consumed values. |

## Validation

Run from the repository root:

```bash
uv run --project shifter/installation shifter-config validate shifter.yaml
```

Validation rejects:

- missing config files
- invalid YAML
- duplicate YAML mapping keys
- YAML merge keys (`<<`)
- non-mapping top-level YAML
- unknown top-level fields
- unknown `deployment` fields
- missing required fields
- unknown backend names
- unsupported profile/backend combinations
- malformed deployment names or domains
- malformed secret names or references
- missing required backend secrets
- secret names not used by the selected backend

Validation errors are path-based and do not echo rejected input values.

## Secret Handling

`shifter.yaml` stores references, not secret values.

Accepted reference forms are backend-described strings such as provider secret
names, GitHub Actions secret names, environment variable names, or the literal
`prompt`.

The schema rejects recognizable raw secret material, including PEM blocks,
multi-line values, and implausibly long values. Short raw values can look like
references, so `gitleaks` remains part of enforcement.

Generated backend outputs classify sensitive data as:

- `public`
- `secret-reference`
- `secret-value`

`secret-value` outputs may only be placed in a Kubernetes Secret or provider
secret store.

## Runtime Binding

Backend metadata declares generated outputs consumed by runtime processes. The
current registry declares `CLOUD_PROVIDER` for portal, worker, and provisioner
roles. Django and provisioner code still select cloud adapters from
`CLOUD_PROVIDER` at runtime through the existing cloud factory seams.

Backend selection is not derived from branch names.

## Backend Bundle Contract

A backend bundle declares:

- backend identity and supported profiles
- required command-line tools
- required logical secrets and accepted reference grammar
- generated outputs, destination, sensitivity, and consuming process roles
- validation checks
- health checks
- cloud-neutral capabilities
- backend-owned repository paths and docs

Validation command specs are argv arrays, not shell strings. The contract rejects
shell metacharacters, absolute host paths, path traversal, and tokens with
internal whitespace.

## Source Of Truth

Do not create a second root-config parser in scripts, Django settings,
Terraform, Helm, or examples. Import or execute the `shifter/installation`
package instead.

Do not treat CI branch names, Terraform environment directories, Helm values, or
generated env files as additional authoritative backend selectors.
