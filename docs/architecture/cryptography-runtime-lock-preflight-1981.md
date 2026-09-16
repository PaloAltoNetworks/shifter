# Cryptography Runtime Lock Preflight

Status: binding implementation guidance for issue
[#1981](https://github.com/Brad-Edwards/shifter/issues/1981)

This security change is a dependency-resolution change, not a new application
cryptography design. The repository does not call `pkcs7_decrypt_*`, but it
ships affected `cryptography` resolutions through application, authentication,
SSH, encrypted-field, and Google client dependency paths. Remediation must
therefore reach the deployed installation artifacts, not only the three
Dependabot alert manifests.

## Boundary Decision

Keep each package root's existing dependency declarations intact and use its
own `uv` resolution. Do not add a repository-wide Python workspace, a second
constraints schema, or a `cryptography`-specific update script.

The three alert manifests are:

- `shifter/engine/provisioner/uv.lock`;
- `shifter/shifter_platform/uv.lock`; and
- `uat/range-functional-smoke/uv.lock`.

Three additional hash-pinned runtime artifacts are in the security boundary:

| Runtime artifact | Current vulnerable pin | Why it is in scope |
| --- | --- | --- |
| `shifter/engine/provisioner/requirements.lock` | `cryptography==49.0.0` | The provisioner image installs this file rather than `uv.lock`. |
| `shifter/engine/provisioner/requirements-gcp.lock` | `cryptography==49.0.0` | The same image installs this GCP supplement after the main lock. |
| `shifter/shifter_platform/requirements-gcp.lock` | `cryptography==47.0.0` | The platform image installs this supplement after exporting `uv.lock`; leaving it stale can downgrade the fixed main resolution. |

ADR-037-R4 and
`docs/architecture/rev1-build-deployment-provenance.md` already require these
runtime files to be generated from the frozen package-root resolution and
installed with hash enforcement. Regenerate them through that incumbent flow;
never hand-edit versions or hashes. A resolver-required companion move such as
the platform lock's `pyOpenSSL` 26.3.0 to 26.4.0 is acceptable, but unrelated
package churn is not.

## Canonical Incumbents

- Dependency declarations and resolution boundaries remain the three
  package-local `pyproject.toml` / `uv.lock` pairs. The provisioner declares
  `cryptography` directly; the platform constrains it under
  `[tool.uv].constraint-dependencies`; the functional smoke reaches it only
  through its optional GCP dependency graph.
- `.github/dependabot.yml` remains the dependency update cadence. Its existing
  one-entry-per-package-root model must not be replaced or duplicated.
- `shifter/engine/provisioner/Dockerfile` and
  `shifter/shifter_platform/Dockerfile` remain the production install
  contracts. Preserve frozen exports, `--require-hashes`, and the existing
  binary-only policy.
- `.github/quality-path-filters.yaml` and `.github/workflows/_quality.yml`
  already route each package root to its lint, SAST, and test owners. Do not add
  an advisory-specific workflow.
- Runtime crypto call sites retain their existing boundaries:
  `shifter/engine/provisioner/config/_crypto.py` (`FieldDecryptError` and
  fail-closed Fernet handling), `shifter/engine/provisioner/utils/crypto.py`
  (SSH key generation), `shifter/engine/provisioner/vpn_access.py` (OpenVPN
  identity generation), `shifter/shifter_platform/shared/field_encryption.py`
  (the `enc:v1:` persistence contract), and
  `shifter/shifter_platform/mission_control/guacamole.py` (validated Guacamole
  signing/encryption input).

No controller, DTO, service, repository, schema, migration, or exception
hierarchy is needed for a lock refresh.

## Cross-Cutting Security Layers

| Layer | Required treatment |
| --- | --- |
| Resolver and integrity gate | Resolve the targeted package through `uv`, retain generated sdist/wheel hashes, and prove every changed lock is fresh. Do not paste advisory hashes or package metadata by hand. |
| Production image install | Keep ADR-037-R4's frozen, hash-enforced install. Both supplemental GCP locks must agree with the fixed main graph so the second install cannot downgrade `cryptography`. |
| Authentication surface | OIDC/PyJWT, Firebase/Google auth, SSH, and Guacamole continue through their existing libraries and application admission paths. This issue adds no endpoint, bypass, token shape, or policy decision. |
| Secret and environment binding | Preserve `FIELD_ENCRYPTION_KEY` hydration/validation, `shared.cloud.sensitive_env` classification, provisioner fail-closed decryption, and the functional smoke's 0600 session-file/GCP Secret Manager handling. No secret belongs in package-manager argv, logs, reports, or generated metadata. |
| Persistence and schema | Preserve existing Fernet ciphertext and `enc:v1:` compatibility. There is no data rewrite or migration. Existing encrypted values must remain readable after the library upgrade. |
| Error envelope | Keep `FieldDecryptError`, `ImproperlyConfigured`, existing cloud exceptions, and current CLI errors. Do not expose raw ciphertext, keys, tokens, upstream exception payloads, or a new crypto-specific exception family. |
| Logging and observability | A dependency refresh needs no new runtime log. Existing `shared.log_sanitize` / provisioner `log_redact` rules remain authoritative if any touched test or diagnostic emits identifiers. |
| Host and OS exposure | The change introduces no executable, environment variable, port, file permission, or process argument. Distribution selection stays constrained by the existing wheel-only container policy and non-root runtime images. |

Completion evidence must cover both resolution and consumption: the three
package-local locks are fresh; all six in-scope artifacts resolve
`cryptography` 50.0.0 or newer; hash-enforced image inputs remain installable;
and the existing package-owned quality jobs pass. Unit tests executed only from
`uv.lock` are not evidence that the separately installed runtime exports are
safe.

## Extensibility Seam

The seam is the package root plus its derived runtime export, with the target
package name supplied to the package manager. The next dependency advisory can
reuse the same root-local resolver and export path without editing a global pin.
If export-freshness enforcement is automated later, make it a generic mapping
of package root to derived install artifact; do not encode `cryptography`, this
CVE, or a fixed list of transitive parents in policy code.

## Gotchas And Anti-Patterns

- Do not stop after the three Dependabot-visible `uv.lock` files. The deployed
  provisioner would retain 49.0.0, and the platform's second install could
  replace 50.0.0 with 47.0.0.
- Do not describe `cryptography` as transitive in every root: it is a direct
  provisioner dependency, a platform constraint/transitive dependency, and a
  functional-smoke optional-GCP transitive dependency.
- Do not change the existing direct or constraint declarations solely to make
  the lock diff look explicit; issue #1981 requires the current declarations to
  remain intact.
- Do not revert a minimal resolver-required `pyOpenSSL` companion update, and
  do not turn the targeted operation into a broad dependency refresh.
- Do not add PKCS#7 wrappers, oracle-specific application handling, duplicate
  encryption helpers, or tests that call the vulnerable primitive. The safe
  resolution is the control.
- Do not hand-edit generated lock hashes, weaken `--require-hashes` /
  binary-only installation, add an index override, or suppress a resolver
  conflict.
- Do not add a changelog fragment or edit `CHANGELOG.md`; release-please owns
  release notes under the repository workflow policy.

## Non-Goals

- No redesign of application encryption, OIDC, SSH, VPN, Guacamole, Google
  Secret Manager, secret hydration, or persistence formats.
- No new API, schema, migration, service, repository, exception hierarchy,
  logging event, dependency scanner, or CI workflow.
- No upgrade of unrelated dependencies and no remediation claim for package
  roots or container/OS packages outside the issue's Python runtime graph.
