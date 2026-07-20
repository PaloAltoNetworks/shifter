# Settings Fail-Fast Preflight

Issue: GitHub #558, "Architecture review: align settings with fail-fast
configuration policy and remove duplicate encryption-key initialization".

This note records the architecture boundary for tightening Django runtime
settings. It is not an implementation plan.

## Decision Boundary

Production-significant Django settings must have one owner and one initialization
path. Missing production runtime config should fail during settings import or
runtime env rendering, not later as a provider error, silent fallback, or local
default.

Local development, pytest, and image-build conveniences are allowed only when
they are explicit, isolated, and named by posture (`TESTING=1`, `ENVIRONMENT=build`
or `DJANGO_DEBUG=true`). A fallback that could be reached by production without
an explicit dev/test/build posture is not acceptable.

No new ADR is needed for this issue. The governing policy already exists in the
engineering principles, ADR-008 production security posture, ADR-009 identity
boundary, ADR-011 backend-bundle/runtime config model, and ADR-018 fail-closed
runtime-config precedent.

## Canonical Incumbents

| Concern | Canonical incumbent | Guardrail for #558 |
| --- | --- | --- |
| Django settings surface | `shifter/shifter_platform/config/settings.py` plus star-reexported `config/_*.py` modules | Preserve `config.settings` as the public Django settings module. Do not create alternate settings modules or a second runtime config schema. |
| Runtime posture detection | `config/_runtime_env.py::IS_TEST_RUN`, `AUTH_PROVIDER`, `require_environment()` | Reuse this posture vocabulary for dev/test/build exceptions. Do not infer production solely from one variable when `ENVIRONMENT`, `TESTING`, `DJANGO_DEBUG`, and `AUTH_PROVIDER` already exist. |
| Database settings | `config/_database_settings.py::_build_databases()` and `config.db_backends.rds_iam` | Make DB requiredness and test SQLite exception live here. Do not duplicate DB host/name/user/password parsing in `settings.py`, entrypoint probes, or deployment scripts. |
| Auth/OIDC settings | `config/_oidc_settings.py`, `config.oidc`, `config.identity_platform` | OIDC requiredness belongs to the selected auth provider. Do not make GCP Identity Platform depend on AWS Cognito/OIDC vars, and do not leave production OIDC endpoint gaps as warnings. |
| Email settings | `config/_email.py`, `scripts/gcp/render_runtime_env.py`, AWS SES IAM path | Email is optional only if the deployment has intentionally selected console/no delivery. A configured ESP backend must fail closed when its required non-secret config or secret reference is incomplete. |
| Field encryption | `FIELD_ENCRYPTION_KEY`, `entrypoint.sh` app secret hydration, `cms.credential_encryption`, `docs/dev/secrets-rotation-runbook.md` | There must be one settings initialization path. The value is a secret, not a generated default. Test/build keys must stay synthetic and isolated. |
| Runtime env inventory | `config/_env_manifest.py`, `config/env-manifest.json`, `generate_env_manifest` | Every changed env binding must be represented in the manifest. Do not hand-edit the JSON except by regenerating it. |
| Provider runtime renderers | AWS `scripts/portal-deploy/deploy_portal.sh` / SSM and GCP `scripts/gcp/render_runtime_env.py` / Helm values | Required production config should be supplied or rejected at these existing seams; do not add app-side fallbacks to compensate for missing renderer outputs. |
| Secret hydration | `shifter/shifter_platform/entrypoint.sh` and `entrypoint-lib.sh` | Keep provider secret values in secret managers and process memory. Do not move secret values into ConfigMaps, generated env files, Docker argv, workflow logs, or checked-in examples. |
| Logging and errors | `django.core.exceptions.ImproperlyConfigured`, `shared.log_sanitize`, `config._logging_config` | Use existing Django config errors and sanitized non-secret diagnostics. Do not add a custom exception hierarchy or log full env dumps. |

## Cross-Cutting Layers

- Auth surface: AWS `AUTH_PROVIDER=oidc` must require OIDC client ID/secret,
  auth domain, issuer, and derived endpoints in production. GCP
  `AUTH_PROVIDER=identity_platform` must keep its own Identity Platform
  requiredness and must not be blocked by absent Cognito values.
- Secret-handling surface: `DJANGO_SECRET_KEY`, `FIELD_ENCRYPTION_KEY`,
  `DB_PASSWORD`, `OIDC_RP_CLIENT_SECRET`, Redis AUTH, Guacamole secrets, and ESP
  API keys are hydrated by `entrypoint.sh` or supplied as explicit local/test
  inputs. Error messages may name missing variable names but must not include
  values, bundle payloads, or DSNs.
- Env-binding shape: settings values flow through `os.environ`, the generated
  env manifest, AWS SSM/deploy env assembly, GCP renderer output, Helm runtime
  values, and pytest/build setup. A change to requiredness is incomplete if any
  of those surfaces still relies on the old fallback.
- Config validators: settings import must fail deterministically for missing
  production-required values; `require_environment()`, `_build_databases()`,
  `_oidc_settings.py`, `_email.py`, `_channels.py`, and renderer tests are the
  places to pin behavior. Invalid typed env should fail loud, not coerce to a
  safe-looking default.
- OS/process exposure: deployment and smoke paths may pass secret references in
  argv, but not secret values. Existing hydration uses stdin-fed JSON parsing and
  exported env values inside the process; preserve that shape.
- Error-envelope surface: this is startup/configuration behavior, not a public
  API. Do not surface raw provider exceptions, secret payloads, stack traces, or
  internal hostnames through `/health`, auth redirects, or DRF responses.
- Persistence surface: no model, migration, repository, DTO, or stored schema is
  needed for this issue. `FIELD_ENCRYPTION_KEY` rotation remains out of scope
  because existing encrypted fields would need a separate re-encryption workflow.

## Extensibility Seam

The useful seam is a small settings-owned "required runtime env under posture"
helper or equivalent pure function, not a new config framework. If the
implementation needs shared logic, keep it in the existing `config` settings
family and parameterize it by variable name, selected posture/provider, and the
allowed dev/test/build exception. The next obvious extension is adding another
required provider setting without re-editing deployment scripts and tests in
multiple inconsistent ways.

## Whole-Repo Scope

Likely implementation touchpoints:

- `shifter/shifter_platform/config/settings.py`
- `shifter/shifter_platform/config/_runtime_env.py`
- `shifter/shifter_platform/config/_database_settings.py`
- `shifter/shifter_platform/config/_oidc_settings.py`
- `shifter/shifter_platform/config/_email.py`
- `shifter/shifter_platform/config/_env_manifest.py`
- `shifter/shifter_platform/config/env-manifest.json`
- `shifter/shifter_platform/entrypoint.sh` only if a secret hydration contract
  changes
- `scripts/portal-deploy/deploy_portal.sh`, `platform/terraform/modules/portal/ssm/`,
  and AWS deploy/user-data tests if AWS runtime env assembly changes
- `scripts/gcp/render_runtime_env.py`, Helm/Kubernetes runtime values, and GCP
  renderer tests if GCP runtime env assembly changes
- `shifter/shifter_platform/Dockerfile` only for build-time synthetic settings
  used by `compilemessages` and `collectstatic`
- Config tests under `shifter/shifter_platform/tests/config/`
- `docs/dev/deploy-secrets.md` or operator docs only if the required runtime
  contract changes for operators

## Gotchas And Anti-Patterns

- Do not collapse duplicate `FIELD_ENCRYPTION_KEY` code by keeping whichever
  default happens to make tests pass. Pick one owner and one explicit dev/test or
  build exception.
- Do not use `DJANGO_DEBUG` as the only production detector. Debug is a security
  mode, not a complete deployment identity.
- Do not make `ALLOWED_HOSTS = ["*"]` or broaden host admission. Load-balancer
  health accommodation is already path-scoped in `HealthCheckMiddleware`, and
  AWS/GCP renderers already include `localhost` / `127.0.0.1` intentionally.
- Do not conflate optional email delivery with incomplete configured email
  delivery. Console fallback is acceptable only for an explicitly unconfigured
  sender path, not for a half-rendered ESP backend.
- Do not treat missing OIDC endpoints as warnings in production OIDC mode.
  Warnings are too late and too easy to miss during deploy.
- Do not create duplicate env parsers, Pydantic settings, new exception classes,
  or provider-local copies of the same validation.
- Do not print secret values while improving diagnostics. Name the missing key
  and the owning surface instead.
- Do not weaken Docker build, pytest, stack smoke, Redis TLS, health readiness,
  or ADR guard behavior to make fail-fast settings easier to import.

## Non-Goals

- No redesign of Cognito/OIDC, Identity Platform, dev login, Django sessions,
  CTF magic links, or DRF authentication.
- No rotation of `FIELD_ENCRYPTION_KEY`, `DJANGO_SECRET_KEY`, DB credentials, OIDC
  client secrets, Redis AUTH, or ESP API keys.
- No new runtime configuration schema, settings package, cloud secret manager
  abstraction, database model, migration, API endpoint, or operator UI.
- No change to range provisioning, cloud adapter protocols, health endpoint
  semantics, or worker/process management except where required config import
  behavior is directly exercised.
- No implementation of fallback values for production-significant settings merely
  to preserve legacy local behavior. Local/test/build behavior must be explicit.

## Validation

At minimum, a future implementation on this path must run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
cd shifter/shifter_platform && uv run pytest tests/config
```

Then add targeted checks for touched outer surfaces: env manifest freshness,
Dockerfile build-setting tests, AWS deploy script tests, GCP runtime renderer
tests, actionlint for workflow edits, and Terraform/Kubernetes linters for
provider runtime-contract changes.
