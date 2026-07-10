# installation

This package validates the root Shifter installation config, `shifter.yaml`.

`shifter.yaml` is a user-authored file at the repository root. It selects one
backend bundle and provides deployment-level settings. The installation package
is the authoritative parser for that file.

## Supported Backends

| Backend | Profiles | Required secrets |
| --- | --- | --- |
| `aws` | `prod`, `dev` | `django_secret_key`, `db_password` |
| `gcp` | `prod`, `dev` | `django_secret_key` |

Both backend entries currently accept any `settings` mapping. Backend-specific
setting keys are still enforced by the deployment path that consumes them.

## Config File

Start from one of the checked examples:

```bash
cp shifter/installation/examples/aws.yaml shifter.yaml
uv run --project shifter/installation shifter-config validate shifter.yaml
```

Use `examples/gcp.yaml` for GCP.

## Root Fields

| Key | Required | Notes |
| --- | --- | --- |
| `version` | no | Defaults to `1`. Only `1` is accepted. |
| `backend` | yes | Must be `aws` or `gcp`. |
| `deployment.name` | yes | Lowercase letters, digits, and internal hyphens. Length: 1-40 characters. |
| `deployment.domain` | yes | Lowercase DNS hostname with at least two labels. IP literals, schemes, trailing dots, and bare hostnames are rejected. |
| `deployment.profile` | no | Defaults to `prod`. Must be allowed by the selected backend. |
| `secrets` | no | Mapping of logical secret name to a reference. Values must be references, not secret values. |
| `settings` | no | Backend-specific mapping. The root schema only checks that this is a mapping. |

Secret names must match `^[a-z][a-z0-9_]*$`.

Secret references must be single-line strings with no surrounding whitespace.
The root schema rejects recognizable raw secret material, including PEM blocks,
multi-line values, and implausibly long values. It cannot distinguish every short
secret value from a reference; `gitleaks` remains part of the enforcement path.

The literal value `prompt` is accepted for any required secret. It records that
the value must be supplied during deployment.

## Validation

Run validation from the repository root:

```bash
uv run --project shifter/installation shifter-config validate shifter.yaml
```

The command exits `0` when the config is valid. It exits `1` and prints all
detected issues when validation fails.

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

Validation messages are path-based and do not echo rejected input values.

## Render

`shifter-config render` turns the validated `settings.range_egress` policy into
the provider-specific Terraform bridge variables for the config's backend, so
the deployed firewall rules are generated from `shifter.yaml` rather than
hand-copied into a second allowlist (ADR-017-R4, issue #958).

```bash
# AWS: emits `victim_allowed_cidrs = [...]`
uv run --project shifter/installation shifter-config render shifter.yaml \
  --output platform/terraform/environments/<env>/range/victim_allowed_cidrs.auto.tfvars

# GCP: emits `range_egress_mode` + `range_egress_allowed_cidrs`
uv run --project shifter/installation shifter-config render shifter.yaml \
  --output platform/terraform/gcp/environments/gcp-dev/range_egress.auto.tfvars
```

The backend is read from `shifter.yaml`; the renderer emits the matching bridge
variables. Without `--output` the rendered tfvars is written to stdout. The
command exits `1` and prints the same sanitized issues as `validate` when the
config is invalid. See
[`docs/architecture/range-egress-ip-allowlist.md`](../../docs/architecture/range-egress-ip-allowlist.md)
for the full operator workflow.

## Runtime Inventory

Check the checked-in runtime-env inventory from the repository root:

```bash
uv run --project shifter/installation shifter-config runtime-inventory --check
```

The runtime-inventory check compares file paths and env-key names only. It
does not print values. Today it guards the GCP static runtime env, keeps the
tracked generated runtime stub assignment-free, records the generated renderer
key contract, and documents the boundary between the public `shifter.yaml`
installation config, the checked-in `.shifter.yaml` MCP ops policy, and
gitignored local `.env` files.

## Backend Bundle Contract

`contract.py` defines the machine-readable backend bundle contract.
`registry.py` contains the backend entries consumed by the schema and loader.

A backend bundle declares:

- backend identity and supported profiles
- required command-line tools
- required logical secrets and accepted reference grammar
- generated outputs, including destination and sensitivity
- validation checks and health checks
- cloud-neutral capabilities
- owned repository paths and docs

Generated outputs are classified as `public`, `secret-reference`, or
`secret-value`. A `secret-value` output may only be placed in a Kubernetes Secret
or provider secret store.

Validation commands are stored as argv arrays, not shell strings. Command specs
reject shell metacharacters, absolute paths, path traversal, and tokens with
internal whitespace.

## Package Layout

| File | Purpose |
| --- | --- |
| `schema.py` | Root config model and root-field validators. |
| `loader.py` | YAML loading, duplicate-key checks, root validation, and backend validation dispatch. |
| `contract.py` | Backend bundle contract types and invariants. |
| `registry.py` | Supported backend bundle registry. |
| `runtime_inventory.py` | Runtime config surface inventory and env-key drift checker. |
| `cli.py` | `shifter-config validate`, `render`, and `runtime-inventory`. |
| `render.py` | Render `settings.range_egress` into provider Terraform bridge tfvars. |
| `errors.py` | Sanitized validation issue model. |
| `examples/` | Valid AWS and GCP example configs. |
