# GEN-001 Documentation Deliverables Preflight (#670)

Status: pre-implementation guidance

Date: 2026-06-23

Requirement: GEN-001, Documentation Required for Major Features

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/670>

## Scope Boundary

GEN-001 is a repository-wide documentation deliverable requirement. It is not a
new product feature, a new documentation renderer, or a new workflow engine.

Future implementation may add missing user and technical documentation, improve
indexes, or add a narrow guard that prevents major features from landing without
their documentation deliverables. It must not bypass the existing in-app
documentation app, duplicate the ADR/traceability model, or turn documentation
coverage into a separate product schema.

"Major platform feature" should be treated as an issue and PR classification,
not a runtime domain model. The classification belongs in the Ground Control
requirement/issue context, PR scope, and review checklist. It should not create a
database table, Django app, or standalone feature registry unless a separate
accepted requirement asks for one.

## Architecture Decisions

- User-facing documentation belongs in the existing in-app docs tree under
  `shifter/shifter_platform/documentation/docs/`, normally in `features/`,
  `how-to/`, `scenarios/`, `getting-started/`, or `reference/`.
- Technical documentation belongs in
  `shifter/shifter_platform/documentation/docs/technical/` when it is intended
  for authenticated operators/developers inside the product, and under
  `docs/architecture/` only for preflight, architecture-review, or repo-level
  decision notes.
- Documentation discoverability is part of the deliverable. New user docs must
  be linked from the nearest section index and, when broadly useful, from the
  top-level in-app docs index. New technical docs must be linked from the
  technical index or the relevant technical subsection index.
- The existing Markdown renderer, navigation tree, slug mapping, path
  sanitization, and HTML sanitization are the documentation content boundary. Do
  not add another renderer, wiki adapter, or raw-file serving path.
- Ground Control traceability remains the requirement evidence surface. Link
  documentation artifacts to requirements/issues through the existing
  `DOCUMENTS` / `GITHUB_ISSUE` relationship, rather than creating a parallel
  traceability file.
- Release notes are not documentation. `changelog.d/` fragments explain what
  changed in a release; they do not satisfy GEN-001 user or technical docs.
- ADRs are for durable architecture decisions and enforceable guardrails. Do not
  create or edit ADR registry entries just to record that documentation exists.
  Use ADR files only when the implementation changes architecture policy or
  enforcement.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for GEN-001 |
| --- | --- | --- |
| In-app docs content | `shifter/shifter_platform/documentation/docs/` | Keep user and technical docs in the existing docs tree unless the content is repo-level architecture guidance. |
| User docs index | `shifter/shifter_platform/documentation/docs/features/index.md` and `shifter/shifter_platform/documentation/docs/index.md` | Link new feature docs from the closest index; do not rely on orphaned pages. |
| Technical docs index | `shifter/shifter_platform/documentation/docs/technical/index.md` and subsection indexes | Link operator/developer docs from the technical tree instead of scattering them in implementation directories. |
| Docs serving controller | `documentation.views.doc_index`, `doc_page`, `_doc_file_map`, `_sanitize_path`, `_render_markdown` | Reuse authenticated Markdown serving, trusted slug lookup, and Bleach sanitization. |
| Navigation/templates | `shifter/shifter_platform/templates/documentation/*.html`, `shifter/shifter_platform/templates/partials/icon_sidebar.html`, `shifter/shifter_platform/templates/mission_control/help.html` | Keep the existing docs navigation surface; do not add a second help center or unauthenticated route. |
| Access control | `@login_required`, `@require_GET`, sidebar `is_ctf_participant_only` visibility | Preserve authenticated access and the existing audience boundary. |
| Exception behavior | `django.http.Http404` from documentation views | Invalid, hidden, deprecated, or missing docs should keep returning 404 without exposing paths or filesystem details. |
| Docs tests | `shifter/shifter_platform/tests/documentation/test_helpers.py`, `test_views.py` | Reuse helper/view tests for renderer or navigation behavior. Avoid brittle content-specific tests. |
| Workflow routing | `.github/workflows/deploy.yml`, `.github/quality-path-filters.yaml`, `.gc/plan-rules.md` | Ordinary docs-only diffs may skip broad Quality; guardrail docs and enforcement changes must still run architecture gates. |
| Architecture enforcement | `scripts/adr_guard/adr_guard.py`, `docs/adr/index.yaml`, `docs/adr/exceptions.yaml` | Add enforcement here only if GEN-001 becomes a real guardrail, and document the rule in ADR docs. |
| Requirement evidence | Ground Control traceability, canonical repo `Brad-Edwards/shifter` | Use existing `DOCUMENTS` links for doc artifacts and `GITHUB_ISSUE` for the tracking issue. |
| Release notes | `changelog.d/README.md` | Add fragments for user-visible behavior or pipeline changes; do not treat fragments as docs deliverables. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: `/docs/` is routed through `config.urls` to
  `documentation.urls`, and both docs views are decorated with
  `@login_required` and `@require_GET`. New documentation pages should be
  content files under the existing tree, not routes that bypass login or method
  restrictions. The sidebar hides docs for CTF-only participants; broadening that
  audience is a product/access decision, not a docs-content change.
- Input and path validation surface: `doc_page` must continue to sanitize the
  request slug with `_sanitize_path` and resolve it through `_doc_file_map`, a
  trusted walk of `DOCS_ROOT`. Do not construct filesystem paths from request
  input or expose `_deprecated` / hidden files.
- HTML and Markdown sanitization surface: `_render_markdown` uses the existing
  Markdown extension list plus Bleach `ALLOWED_TAGS` and `ALLOWED_ATTRIBUTES`.
  Docs content must fit that allowlist. If a feature needs richer embeds, treat
  allowlist expansion as a security change with tests.
- Secret-handling surface: docs and examples must not include credentials,
  tokens, private keys, live account IDs, live VPC/subnet IDs, or raw generated
  env payloads. Reference canonical setup docs such as
  `docs/dev/deploy-secrets.md` and use placeholders/examples that satisfy
  gitleaks and ADR-004 live-identifier checks.
- Env-binding and config-shape surface: documentation may explain environment
  variables, Terraform variables, Helm/Kubernetes env files, and Django settings,
  but it must not become a new source of truth for those values. When a feature
  changes a config shape, update the owning schema/validator and the docs that
  describe it in the same change.
- Workflow and validator surface: ordinary in-app docs changes are image
  content and route through the `portal_image` path filter; top-level `docs/**`
  is ordinary docs unless it is guardrail documentation. Changes to
  `.github/**`, `.gc/**`, `docs/adr/**`, `scripts/adr_guard/**`, or the ADR
  enforcement page must satisfy the guardrail-docs rule and the repo-required
  ADR gate.
- OS/process exposure surface: documentation content should not introduce a
  build-time or runtime shell boundary. If future enforcement uses a helper
  script, keep it repo-native, argv-array based, and ensure diagnostics print
  file paths or slug names only, not document bodies or secret-like strings.
- Error-envelope surface: invalid docs requests should keep returning 404
  messages such as "Document not found" or "Invalid path". Do not surface
  absolute paths, traceback text, raw Markdown, secrets, or renderer internals in
  user-visible errors.
- Observability surface: docs rendering currently has no bespoke logging or
  audit trail. Do not add a separate logging schema for docs coverage. If a
  future guard fails, report missing artifact identifiers and remediation paths
  through the existing CI/ADR guard style.

## Extensibility Seam

The next reasonable change is automated or semi-automated documentation coverage
for "major feature" PRs. The seam should be a single requirement/feature
classification plus expected user-doc and technical-doc artifact identifiers,
preferably derived from Ground Control traceability or one small repo-native
mapping if traceability cannot answer the question locally.

Do not hardcode separate per-app checks or duplicate Markdown parsers. A future
guard should be parameterized by requirement UID or issue number and expected
documentation slugs, then reuse the existing docs tree and ADR guard reporting
style.

## Whole-Repo Scope For Future Work

In scope when a future implementation touches documentation coverage:

- `shifter/shifter_platform/documentation/docs/index.md`
- `shifter/shifter_platform/documentation/docs/features/index.md`
- `shifter/shifter_platform/documentation/docs/technical/index.md`
- relevant in-app docs pages under `features/`, `how-to/`, `scenarios/`,
  `reference/`, or `technical/`
- `docs/architecture/*` for preflight or architecture-review notes
- `shifter/shifter_platform/documentation/views.py` and documentation tests only
  if renderer, navigation, sanitization, or slug behavior changes
- `.github/workflows/deploy.yml`, `.github/quality-path-filters.yaml`,
  `scripts/adr_guard/**`, and `docs/adr/**` only if documentation coverage
  becomes enforced policy
- Ground Control traceability for `DOCUMENTS` links to requirement and issue
  evidence

Out of scope unless directly required by a later accepted issue: new Django
models, a docs database, a CMS workflow, a search service, unauthenticated public
docs hosting, ADR registry changes, deployment branch routing, Terraform/K8s
schema changes, and new exception or logging hierarchies.

## Gotchas And Anti-Patterns

- Do not conflate user docs with technical docs. A feature guide explains how to
  use the capability; technical docs explain architecture, operation, config,
  integration, and failure modes.
- Do not conflate in-app docs with top-level repo architecture notes. Product
  users should not need to read preflight notes to operate a feature.
- Do not add orphaned Markdown pages. A page that is not reachable from an index
  is not a reliable deliverable.
- Do not make `changelog.d/` fragments, PR body text, or issue comments stand in
  for durable documentation.
- Do not add content-specific tests that assert exact prose. Test navigation,
  rendering, sanitization, and coverage invariants instead.
- Do not create a new schema, DTO, service, repository, or exception hierarchy
  for documentation deliverables.
- Do not weaken docs sanitization to make embedded HTML work. Prefer Markdown,
  fenced code blocks, and the existing Mermaid support.
- Do not duplicate config tables across docs. Link to the canonical owner when a
  config surface already has one.
- Do not document secret values, live infrastructure identifiers, or generated
  deploy payloads. Describe secret names, storage locations, and retrieval
  workflows instead.
- Do not route future docs coverage enforcement around ADR-002/ADR-003. If it is
  a guardrail, it must live in the existing architecture enforcement model.

## Non-Goals

- No implementation of the missing documentation corpus in this preflight.
- No new documentation renderer, CMS, wiki integration, database model, or search
  index.
- No new authorization model, public docs surface, audit framework, telemetry
  schema, exception hierarchy, or config schema.
- No ADR registry update unless future implementation changes enforceable
  architecture policy.
- No Terraform, Kubernetes, deployment, or runtime behavior change.
