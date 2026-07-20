# Mission Control Walkthrough Flags Preflight

Issue: GitHub #560, "Architecture review: remove literal CTF flags from Mission
Control runtime code".

This note records the architecture boundary for the future implementation. It is
intentionally not an implementation plan.

## Boundary

Mission Control runtime code may render a participant handoff page, but it must
not own challenge answers, walkthrough challenge metadata, or flag-submission
policy.

The current checkout already has `mission_control.views._pages.walkthrough`
rendering only the configured CTFd URL. Preserve that shape unless a later
product decision moves the page back to native CTF content. If richer
participant walkthrough content is needed, keep the source in the CTF/CTFd
content domain and route users there; do not reintroduce literal `FLAG{...}`
values, answer maps, or challenge rows in Mission Control Python, templates,
JavaScript, settings defaults, locale strings, or comments.

There are two valid ownership paths:

- Standalone Polaris/CTFd: challenge/page/hint/flag content belongs to the
  Polaris board source and `scripts/ctfd-workshop/*` sync path. Mission Control
  should link to CTFd through `CTFD_PLATFORM_URL` only.
- Native Django CTF: challenge metadata and flag verification belong to the
  `ctf` app (`CTFChallenge`, `CTFFlag`, and `ctf.services.challenge`). Native
  CTF pages should live under `ctf` routes/services, not behind direct
  `mission_control` imports.

## Architecture Decisions

- Keep `mission_control/views/_pages.py::walkthrough` as a thin authenticated
  page renderer: page title, active nav, and `CTFD_PLATFORM_URL`.
- Treat `CTFD_PLATFORM_URL` as non-secret deployment configuration. It may be
  read through `config/settings.py` and represented in `config/env-manifest.json`;
  it must not carry flags, CTFd admin tokens, invite tokens, or participant
  credentials.
- Do not make `scenario-dev/polaris/build/**` a Django runtime dependency.
  ADR-004-R8 treats that tree as generated/runtime material, it is gitignored,
  and it may be absent from a normal checkout.
- Add the regression guardrail to an existing enforcement surface, preferably a
  path-aware `adr_guard` check or a tightly scoped gitleaks rule. The rule should
  catch `FLAG{...}` literals in Mission Control runtime surfaces without scanning
  intentional CTF content, docs, tests, fixtures, or Polaris scenario sources.
- If enforcement files change, update the ADR registry/docs in the same change
  per ADR-002. If only tests and runtime code change, no new ADR is required.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Mission Control page rendering | `mission_control/views/_pages.py`, `_render_via_pkg`, `templates/mission_control/walkthrough.html` | Keep the view presentation-only. No challenge answer maps or CTF row parsing here. |
| CTFd handoff config | `config/settings.py::CTFD_PLATFORM_URL`, `config/env-manifest.json` | URLs only. No flag values, tokens, or participant credentials in settings defaults or env manifests. |
| Standalone CTFd content | `scripts/ctfd-workshop/ctfd_reconcile.py`, `sync_polaris_ctfd.py`, `sync_polaris_ctfd_onboarding.py`, `polaris_manifest.py` | Reuse source-to-live CTFd normalization, validation, pagination, and row reconciliation. Do not add a second CTFd schema/client. |
| Polaris source order | `scenario-dev/polaris/README.md`, existing Polaris preflight notes | Reconcile against the documented scenario source order; do not make older design prose or live CTFd edits authoritative. |
| Native CTF flags | `ctf.models.CTFChallenge`, `ctf.models.CTFFlag`, `ctf.services.challenge.hash_flag`, `verify_flag`, `add_flag`, `update_flag` | Reuse hashed/static/regex/programmable/http flag policy inside CTF. Do not duplicate flag validators in Mission Control. |
| Native CTF errors and validation | `ctf.exceptions`, `ctf.views._parsing`, service-layer validation | Keep CTF request/body/domain errors in CTF. Do not add a Mission Control exception hierarchy for CTF content. |
| Logging | `shared.log_sanitize.safe_log_value`, `safe_log_id`, `safe_log_fingerprint`, ECS logging config | Log route/action and sanitized identifiers only. Never log flags, CTFd tokens, raw CTFd payloads, or signed URLs. |
| Import enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py` | Mission Control may import `shared`, `management.services`, `cms.services`, and `engine.services`; it may not import `ctf` directly. |
| Secret/static checks | `gitleaks`, `detect-private-key`, ADR-004 `adr_guard` checks, `.github/workflows/deploy.yml` precommit job | Extend the existing CI/pre-commit path; avoid a standalone scanner with a different policy model. |
| Tests | `tests/mission_control/test_views.py`, integration page-render tests, `scripts/adr_guard/tests/test_adr_guard.py`, `scripts/ctfd-workshop/test_sync_polaris_ctfd.py` | Add HTTP/render and guardrail tests at the owning boundary. Do not rely only on helper tests. |

## Cross-Cutting Layers

Security layers the future design must satisfy:

- Auth surface: `walkthrough` remains `@login_required` and GET-only. CTFd
  challenge submission remains behind CTFd auth; native CTF challenge views
  remain behind CTF participant/organizer decorators and service ownership
  checks.
- Secret-handling surface: Mission Control stores or renders no challenge
  answers. Native CTF stores static answers hashed through `hash_flag` and flag
  rows; standalone CTFd content stays in the CTFd sync/source path. CTFd admin
  tokens remain in `CTFD_TOKEN` or local operator inputs, never in Django
  settings, templates, logs, or process argv examples.
- Config/env shape: `CTFD_PLATFORM_URL` is the only Mission Control walkthrough
  runtime setting currently justified. New settings must use the existing
  settings parser style and update `config/env-manifest.json`; secret-bearing
  values need the repo's existing secret-delivery path, not plain env defaults.
- Import-boundary gate: `.importlinter` and `check_layer_imports` must pass.
  A fix that imports `ctf.models`, `ctf.services`, or private CTF modules from
  Mission Control fails the architecture boundary even if the local page works.
- Static-check gate: the regression check should scan Mission Control runtime
  Python/templates/static assets for `FLAG{...}` literals and fail without
  echoing the matched value. It should intentionally exclude tests, docs,
  CTF-owned templates/models/services where examples such as `FLAG{...}` are
  format hints, and Polaris scenario content where flags are challenge content.
- OS/process exposure: do not move flags into shell command arguments,
  Kubernetes ConfigMaps, GitHub workflow summaries, generated filenames,
  checked-in env files, or CTFd sync logs. Python JSON bodies through
  `CtfdClient` are the existing CTFd mutation path.
- Error/log envelope: user-facing errors may say CTFd or walkthrough content is
  unavailable. They must not include flag text, CTFd response bodies, admin
  tokens, invite links, signed Guacamole URLs, or raw exception payloads.

Maintainability incumbents the implementation must build on:

- `mission_control/views/_pages.py` and `templates/mission_control/walkthrough.html`
  for the current handoff page.
- `config/settings.py` and `config/env-manifest.json` for the CTFd URL setting.
- `scripts/ctfd-workshop/ctfd_reconcile.py` and `polaris_manifest.py` for
  standalone CTFd content normalization and validation.
- `ctf.services.challenge`, `ctf.models.flag`, and CTF tests for native flag
  semantics.
- Existing pre-commit/CI gates: gitleaks, ADR guard, import-linter, and
  `check_layer_imports`.

Extensibility seam:

Keep the seam at a small event handoff descriptor: target URL, label, optional
event slug/path, and optional help text. For the current page, that descriptor is
just `CTFD_PLATFORM_URL`. If per-event or per-board routing is later needed,
parameterize the URL/path/label at that boundary; do not add challenge rows,
flag values, or CTFd flag normalization to Mission Control.

For standalone CTFd, future accepted flag forms belong at
`ctfd_reconcile.normalize_flag` / `ensure_flags`, not in page copy or Django
views. For native CTF, future flag types belong in `ctf.services.challenge` and
`ctf.validators`, not in Mission Control.

## Whole-Repo Scope

Likely implementation surfaces:

- `shifter/shifter_platform/mission_control/views/_pages.py`
- `shifter/shifter_platform/templates/mission_control/walkthrough.html`
- `shifter/shifter_platform/mission_control/urls.py` only if routing changes
- `shifter/shifter_platform/config/settings.py` and `config/env-manifest.json`
  only if walkthrough settings change
- `shifter/shifter_platform/tests/mission_control/test_views.py`
- `scripts/adr_guard/adr_guard.py`, `scripts/adr_guard/tests/test_adr_guard.py`,
  `.gitleaks.toml`, `.pre-commit-config.yaml`, `.github/workflows/deploy.yml`,
  and `docs/adr/**` if the static guardrail changes
- `scripts/ctfd-workshop/**` and `scenario-dev/polaris/**` only if the issue is
  resolved by making CTFd content/publish sources more explicit
- `shifter/shifter_platform/ctf/**` only if the page is deliberately moved to
  native CTF ownership

## Gotchas And Anti-Patterns

- Do not move literal flags from a view into a Python constant, settings default,
  template, translation string, JavaScript file, comment, fixture imported by
  runtime, or fallback branch.
- Do not solve the import boundary by adding `ctf` to Mission Control's allowed
  imports unless a separate architecture decision accepts that coupling.
- Do not copy `CTFChallenge` / `CTFFlag` shapes, CTFd flag rows, or validation
  rules into Mission Control DTOs.
- Do not scan the entire repo for `FLAG{...}` without a path policy. Tests,
  docs, CTF examples, and Polaris scenario content intentionally contain flags.
- Do not track `scenario-dev/polaris/build/**` just to make a data source
  "explicit"; ADR-004-R8 blocks that generated/runtime tree.
- Do not make live CTFd admin edits the durable source of truth. Backport event
  changes into the reviewed source/sync path.
- Do not print raw flags in guardrail failures, sync logs, test assertion
  messages, GitHub annotations, or exception text.
- Do not conflate `flag_format` hints such as `FLAG{...}` with actual challenge
  answers. The regression guardrail should target answer-shaped literals in
  Mission Control runtime surfaces.

## Non-Goals

- Implementing issue #560 in this preflight.
- Changing challenge flags, scoring, hints, prerequisites, CTFd sync semantics,
  native CTF submission behavior, or event lifecycle.
- Migrating standalone CTFd content into Django or native CTF content into
  Mission Control.
- Rebaking Polaris artifacts, mutating live CTFd, changing AWS/GCP/Terraform/
  Kubernetes state, or running event operations.
- Creating a generic content CMS, new CTFd SDK, new exception hierarchy, new
  logging framework, or new challenge schema.

## Validation Expectations

At minimum, changes on this path should run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter
```

Add focused tests for the touched boundary:

- Mission Control render tests proving the walkthrough view uses explicit
  configuration and emits no challenge flags.
- Guardrail tests proving Mission Control runtime `FLAG{...}` literals fail and
  intentional CTF/Polaris/test/doc occurrences do not.
- CTFd sync tests if the explicit data source or publishing behavior changes.
