# Frontend brace-expansion advisory preflight (#1880)

Status: pre-implementation guidance

Date: 2026-07-28

Issue: GitHub #1880, "fix(frontend): clear remaining brace-expansion advisory
once eslint-plugin-jsx-a11y supports minimatch 10"

This is a requirement-free maintenance change. The issue title, body, and
acceptance criteria are the shipping contract. This note does not implement the
dependency update and is not an implementation plan.

## Decision and boundary

Close the advisory through a published, upstream-compatible lint dependency
line. Preserve the existing ESLint 9 and `jsx-a11y` behavior unless the complete
React lint stack has published and verified ESLint 10 support. Do not trade an
audit finding for disabled, unloaded, or silently ineffective accessibility
rules.

`shifter/shifter_platform/frontend/package.json` and its lockfile remain the
only dependency-resolution contract for the SPA. Parent-scoped npm overrides
are acceptable only where the parent actually supports the replacement
package's API. A global `brace-expansion` or `minimatch` override, a vendored
compatibility package, a nested `file:` dependency, `patch-package`, or an
install-time rewrite is not an acceptable resolution.

No application schema, DTO, controller, service, repository, persistence model,
exception hierarchy, runtime setting, or ADR is needed. This is build/lint
tooling. An ADR update is required only if implementation changes the broader
dependency trust model or weakens an existing quality/security control.

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Dependency declaration and resolution | `frontend/package.json` and lockfile-version-3 `frontend/package-lock.json` | Update the direct lint dependency and regenerated lock together. Keep resolved registry artifacts integrity-pinned. Do not hand-edit transitive lock entries. |
| Existing safe overrides | Parent-scoped `overrides` in `frontend/package.json` | Keep overrides narrow and API-compatible. Remove an override only when the selected upstream graph makes it redundant; do not collapse the current parent scopes into a global override. |
| Lint policy | `frontend/eslint.config.js` and the `lint` package script | Retain `jsxA11y.flatConfigs.recommended.rules` and the existing React/TypeScript flat-config composition. Do not duplicate the rules in another config. |
| Accessibility evidence | Existing Vitest setup and the ESLint API/config | A durable canary belongs in the existing frontend test suite: lint deliberate invalid JSX and assert the exact `jsx-a11y/alt-text` rule, not merely a nonzero process exit. This proves the plugin loaded and remained effective without committing invalid application code or adding a second lint runner. |
| Clean install and functional CI | `_quality.yml` `shifter-platform-spa` job with Node 20.19, `npm ci`, lint, typecheck, Vitest/axe, and Vite build | Extend this package lane for a blocking full-tree npm audit; do not create a detached scanner workflow that can disagree with the installed lockfile. |
| Production build consumer | `shifter/shifter_platform/Dockerfile` frontend stage (`node:20-slim`, `npm ci --ignore-scripts`, `npm run build`) | The selected graph must also install and build with lifecycle scripts disabled. Node and lint dependencies remain build-time-only; the production image receives only the built static bundle. |
| Dependency update cadence | `.github/dependabot.yml`; `docs/adr/README.md` dependency-root convention | Register `/shifter/shifter_platform/frontend` as its own npm package root. The current config comment and ADR guidance require every root, but this root is presently missing. Because Dependabot config is a guardrail file, update ADR enforcement documentation in the same change. |
| Clean-checkout convention | `docs/dev/testing.md` and `docs/architecture/rev1-testing-quality-preflight-1529.md` | Treat `npm ci` from the committed lock as evidence. An existing local `node_modules` tree or `npm install` result is not reproducibility evidence. |
| Repository advisory scanners | `_quality.yml` Trivy and OSV jobs | Do not claim these close #1880: they are explicitly advisory, and OSV currently scans only the repository-root lockfile, not the SPA lockfile. |

The package-local audit command should cover production and development
dependencies and use an explicit low severity floor so "green" means zero npm
vulnerabilities, matching the issue contract. CI should invoke that package
command after `npm ci`; do not duplicate its flags in workflow YAML.

## Cross-cutting layers

- **Package and lock validation:** npm's package/lock consistency check and
  lockfile integrity fields are the schema and supply-chain gate. `npm ci` must
  succeed from a clean tree, `npm ls --all` must report a valid graph, and the
  installed tree must contain no broken symlink or local `file:`/`link:`
  resolution. Audit the full graph including `devDependencies`; omitting dev
  dependencies would hide the exact advisory in scope.
- **Runtime/auth surface:** no HTTP route, Django authentication, authorization,
  CSRF, API-token scope, serializer, or frontend API client changes. Adding a
  runtime endpoint or feature flag to control lint dependencies is concept
  conflation.
- **Secret and registry surface:** public npm metadata and artifacts require no
  application, cloud, or deployment secret. Do not add a committed `.npmrc`,
  registry token, GitHub token, environment dump, or lifecycle hook. CI remains
  `contents: read`; dependency versions and advisory identifiers are safe
  diagnostics, credentials are not.
- **Environment/config shape:** preserve the SPA's `node >=20.19.0` engine, CI's
  Node 20.19 selection, and the Docker `node:20-slim` build posture. This change
  adds no Django environment binding or Vite-exposed setting. A candidate whose
  engine or module format fails any of these consumers is incompatible.
- **OS/process exposure:** npm, ESLint, Vitest, and Vite receive only paths,
  package/version selectors, and source fixtures in argv. Do not pass tokens,
  registry credentials, or arbitrary package content through argv or echoed
  shell interpolation. Package lifecycle scripts stay disabled in the Docker
  build.
- **Error envelope:** there is no application error envelope. Preserve ordinary
  nonzero CLI exits and bounded CI diagnostics. Do not add a custom exception
  hierarchy, swallow an ESLint load error, or treat any lint failure as proof
  that the a11y rule fired.
- **Logging/observability:** npm audit output, the exact ESLint canary rule id,
  and existing CI job results are the evidence surface. Do not add runtime
  application logs, audit rows, metrics, or persistence for build-tool state.
- **Browser/static exposure:** `eslint`, its plugins, `minimatch`, and
  `brace-expansion` stay development/build dependencies and must not enter the
  Vite browser bundle or final Python image. The Docker stage boundary is the
  incumbent enforcement point.
- **Workflow policy:** changes to `_quality.yml` or `.github/dependabot.yml`
  remain guardrail work and must pass `actionlint` where applicable plus the
  full CI-level ADR guard. They must not soften unrelated jobs, path routing,
  permissions, or scanner status.

## Extensibility seam

The seam is the package root, not a repository-wide dependency abstraction.
Keep the audit policy as a named frontend package script with the severity floor
as its explicit parameter; CI calls the script, and Dependabot watches the same
package root. The next npm root can adopt its own package-native audit command
and Dependabot entry without copying a custom parser or sharing SPA overrides.

Within the dependency graph, the only version seam is the direct upstream lint
dependency (and, if eventually necessary, a parent-scoped override whose parent
has adopted the new API). This lets a later ESLint 10 migration replace the
whole verified React lint stack without preserving a compatibility shim created
for this advisory.

## Gotchas and anti-patterns

- Do not override `minimatch@10` under a caller that still invokes its removed
  callable default export.
- Do not override `brace-expansion@5` under `minimatch@3`, whose call site
  expects the old callable module export.
- Do not use `audit fix --force`, broad major upgrades, or lockfile-only success
  as a substitute for compatibility tests.
- Do not disable `jsx-a11y`, remove its recommended rules, ignore lint load
  errors, or rely only on axe runtime tests. ESLint and axe are complementary.
- Do not commit a known-bad JSX file that makes the normal lint lane fail. The
  canary must invoke ESLint deliberately and assert the exact expected finding.
- Do not accept a canary that passes on any exception or exit code; a plugin
  import crash is failure, not evidence of rule enforcement.
- Do not validate against a pre-existing `node_modules`. Use `npm ci`; inspect
  the resulting graph and symlinks after the clean install.
- Do not add a local package, dangling symlink, postinstall rewrite, patched
  copy, or second lockfile to bridge CommonJS/ESM export differences.
- Do not broaden #1880 into general SPA dependency modernization or make the
  repository's advisory OSV/Trivy jobs blocking under this issue.

## Non-goals

- No application behavior, browser UI, API, authentication, authorization,
  schema, validation, persistence, logging, or deployment configuration change.
- No removal or redesign of the existing accessibility rules, Vitest/axe
  coverage, TypeScript policy, or Vite build.
- No repository-wide npm workspace, shared dependency resolver, custom advisory
  database, exception allowlist, vendoring framework, or general ESLint 10
  migration.
- No remediation of unrelated package roots or advisories outside
  `shifter/shifter_platform/frontend`.
