# Installation Config

`shifter.yaml` is the root installation config. It lives at the repository root,
selects one backend bundle, and provides deployment-level settings.

The authoritative parser is `shifter/installation`.

## Validate

Run from the repository root:

```bash
uv run --project shifter/installation shifter-config validate shifter.yaml
```

The command exits `0` when the file is valid. It exits `1` and prints all
detected issues when validation fails.

## Doctor

`validate` checks only the shape of `shifter.yaml`. To validate the selected
backend before applying infrastructure (required tools, secret references,
generated env, owned repository paths, and the backend bundle's credential-free
validation checks, plus opt-in read-only health probes), run `doctor`:

```bash
uv run --project shifter/installation shifter-config doctor shifter.yaml
```

Every check is labelled local-only, cloud-read-only, or deployment-mutating, and
`doctor` is non-mutating by default. See [Setup](setup) for the full setup and
validation flow.

## Start From An Example

Scaffold a starting `shifter.yaml` for a backend, or copy an example directly:

```bash
# Scaffold ./shifter.yaml from the checked example (omit --backend to list backends).
uv run --project shifter/installation shifter-config init --backend aws
# Or copy the example directly:
cp shifter/installation/examples/aws.yaml shifter.yaml
```

Use `--backend gcp` (or `examples/gcp.yaml`) for GCP, then run `validate` and `doctor`.

## Supported Backends

| Backend | Profiles | Required secrets |
| --- | --- | --- |
| `aws` | `prod`, `dev` | `django_secret_key`, `db_password` |
| `gcp` | `prod`, `dev` | `django_secret_key` |

Both backends currently accept any `settings` mapping at root-config validation
time. Deployment tooling still validates the values it consumes.

## Fields

| Key | Required | Notes |
| --- | --- | --- |
| `version` | no | Defaults to `1`. Only `1` is accepted. |
| `backend` | yes | Must be `aws` or `gcp`. |
| `deployment.name` | yes | Lowercase letters, digits, and internal hyphens. Length: 1-40 characters. |
| `deployment.domain` | yes | Lowercase DNS hostname with at least two labels. IP literals, schemes, trailing dots, and bare hostnames are rejected. |
| `deployment.profile` | no | Defaults to `prod`. Must be supported by the selected backend. |
| `secrets` | no | Mapping of logical secret name to a reference. Values must be references, not secret values. |
| `settings` | no | Backend-specific mapping. The root schema only checks that this is a mapping. |

Secret names must match `^[a-z][a-z0-9_]*$`.

The literal secret reference `prompt` is valid for every required secret. It
records that the value must be supplied during deployment.

## Validation Rules

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

Validation messages identify paths and do not echo rejected input values.

## Secret Handling

`shifter.yaml` stores secret references only.

Do not put passwords, tokens, private keys, service-account JSON, or certificate
material in `shifter.yaml`.

The root schema rejects recognizable raw secret material, including PEM blocks,
multi-line values, and implausibly long values. Short raw values can look like
references, so `gitleaks` is still required.
