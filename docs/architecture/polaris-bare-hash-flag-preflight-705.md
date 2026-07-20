# Polaris Bare-Hash Flag Submission Preflight

Issue: GitHub #705, "CTFd: accept flag submissions as either FLAG{hash} or
bare hash."

This note records the architecture boundary for the future implementation. It is
intentionally not an implementation plan.

## Boundary

The fix belongs to the standalone Polaris CTFd board acceptance path, not the
native Django CTF app and not the range artifacts:

- `scenario-dev/polaris/build/ctfd-challenges.json`
- `scenario-dev/polaris/build/ctfd-onboarding.json`
- `scripts/ctfd-workshop/ctfd_reconcile.py`
- `scripts/ctfd-workshop/polaris_manifest.py`
- `scripts/ctfd-workshop/sync_polaris_ctfd.py`
- `scripts/ctfd-workshop/sync_polaris_ctfd_onboarding.py`

The canonical answer remains `FLAG{16-hex}` in source-controlled challenge
content and walkthroughs. Bare-hash acceptance is an input-acceptance alias for
participants who copy only the inner hex string.

Prefer making CTFd server-side flag validation authoritative through the
existing source-to-live flag-row reconciliation. A browser normalizer may improve
UX later, but it must not be the only correctness path unless the repo also
adds a durable, source-controlled CTFd theme/config sync and tests it against the
pinned CTFd frontend.

## Architectural Decisions

- Reuse the existing CTFd row reconciliation path. `ctfd_reconcile.ensure_flags`
  already reconciles source flag rows against live CTFd flag rows and
  `polaris_manifest.SUPPORTED_FLAG_TYPES` already allows `static` and `regex`.
- Keep the alias exact to the canonical challenge answer. Never add
  `^[0-9a-f]{16}$` as a per-challenge regex; that would accept any 16-hex string
  for every challenge that has the row.
- If the implementation wants a single live CTFd row per source flag, generate an
  exact case-insensitive regex from `FLAG{<hex>}` such as
  `^(?:FLAG\{<hex>\}|<hex>)$` with CTFd `data: case_insensitive`. If it keeps
  static rows, add only the exact bare value for the same `<hex>`, not a broad
  shape regex.
- Keep source JSON as the source of truth. Do not patch live CTFd manually as the
  durable fix, and do not duplicate the Polaris challenge schema.
- Keep Shifter native `CTFFlag` semantics separate. The Django app's
  `CTFFlag`, `verify_flag`, `submit_flag`, and challenge templates are semantic
  references only for this issue; they are not the deployed Polaris CTFd board.

## Cross-Cutting Concerns To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| CTFd API access | `scripts/ctfd-workshop/common.py::CtfdClient` | Reuse token headers, JSON bodies, and timeout handling. Do not shell out to `curl` or add another HTTP client. |
| Flag reconciliation | `ctfd_reconcile.normalize_flag`, `ensure_flags`, `reconcile_rows` | Put alias generation at this boundary so full and onboarding sync behave the same way. |
| Manifest validation | `polaris_manifest.validate_manifest`, `SUPPORTED_FLAG_TYPES`, `SyncError` | Validate only supported source shapes and exact `FLAG{16-hex}` alias derivation before mutation. |
| Full-board sync | `sync_polaris_ctfd.py` | Sync main challenges, onboarding, pages, prerequisites, hints, tags, and flags through one source-controlled path. |
| Onboarding sync | `sync_polaris_ctfd_onboarding.py` | The Start Here warm-up must accept the same forms as the main board. |
| Tests | `scripts/ctfd-workshop/test_sync_polaris_ctfd.py::FakeCtfdClient` | Extend focused fake-client tests for generated rows, idempotency, stale-row deletion, and invalid broad regex rejection. |
| Live readback | `polaris_manifest.verify_challenge_rows` and `scenario_smoketest.ctfd_check` | Readback must prove row presence; correctness should be covered by unit tests and at least one UI/API submission smoke test before an event. |
| Event lessons | `scenario-dev/polaris/lessons-4.md` | Use as provenance only. Do not make lessons notes a participant-facing or sync source. |
| Changelog | `changelog.d/README.md` | A user-visible fix should add `changelog.d/705.fixed.md`; do not edit `CHANGELOG.md` directly. |

## Security Layers

- CTFd auth surface: participants still submit through CTFd's
  `/api/v1/challenges/attempt` path, which enforces login, team mode, paused
  state, hidden/locked challenges, prerequisites, rate limits, solve creation,
  and CTFd's normal response envelope.
- CTFd flag policy: the alias must match only the challenge's own canonical
  hex. Broad regexes, optional wrappers that accept malformed `FLAG{hex`, and
  global "any hex" patterns are not acceptable.
- CTFd admin API token: operator sync still uses `CTFD_TOKEN` or the existing
  `--token` compatibility path through `CtfdClient`. Do not expand argv-token
  examples or write admin tokens to files.
- Secret/logging surface: sync output may name challenge names, row types, and
  actions, but must not print raw flag content, raw CTFd flag payloads, admin
  tokens, cookies, or full API responses. CTFd itself logs participant
  submissions; do not add additional repo-side flag logging.
- Config/theme surface: if a browser normalizer is added, use CTFd's existing
  `theme_footer`/plugin surface from a source-controlled artifact and sync it
  through `CtfdClient`. Do not paste live-only JS into the CTFd admin UI, load
  remote scripts, or create a custom endpoint that bypasses CTFd CSRF/auth.
- OS/process exposure: keep mutations in Python JSON request bodies. Do not pass
  flag values or tokens through subprocess argv, shell snippets, generated file
  names, or temporary files.
- Error envelopes: `SyncError` and CLI failures should identify the challenge
  and sanitized reason. Avoid dumping request bodies, response bodies, headers,
  or regex content that reveals flags.
- Repository gates: changes under `scripts/ctfd-workshop/**` need focused tests.
  Architecture/workflow-impacting changes must pass the repo ADR guard, and
  Python changes in `shifter/shifter_platform` would additionally need the
  platform lint/import gates.

## Extensibility Seam

Keep the seam at flag-row normalization, not inside CTFd UI event handlers and
not in every challenge JSON entry. A small helper should derive accepted forms
from one source flag and return the live CTFd row shape. The next likely
variation is a different wrapper prefix, a different hex length, or an explicit
per-flag `accepted_forms` policy; those should change one normalization helper
or one optional source field, not every sync loop, challenge description, or
theme script.

Whole-repo surfaces in scope for the future implementation:

- `scripts/ctfd-workshop/ctfd_reconcile.py`
- `scripts/ctfd-workshop/polaris_manifest.py`
- `scripts/ctfd-workshop/sync_polaris_ctfd.py`
- `scripts/ctfd-workshop/sync_polaris_ctfd_onboarding.py`
- `scripts/ctfd-workshop/test_sync_polaris_ctfd.py`
- `scripts/ctfd-workshop/README.md`
- `scenario-dev/polaris/build/ctfd-challenges.json`
- `scenario-dev/polaris/build/ctfd-onboarding.json`
- `scenario-dev/polaris/lessons-4.md`
- `scenario-dev/polaris/tests/scenario_smoketest/ctfd_check.py`
- `changelog.d/705.fixed.md`
- `.ground-control.yaml`, `.gc/plan-rules.md`, and `scripts/adr_guard/adr_guard.py`

## Gotchas And Anti-Patterns

- Do not use `(?i)^[0-9a-f]{16}$` for every challenge. It accepts any 16-hex
  string and destroys answer specificity.
- Do not rely on a theme-only JavaScript hook as the authoritative fix. It would
  miss API clients and is coupled to CTFd's pinned frontend internals
  (`x-model`, challenge modal handlers, and plugin view hooks).
- Do not edit `temp/CTFd` as if it were the production source. The deployed CTFd
  is cloned at bootstrap from the pinned `ctfd_repo_url`/`ctfd_git_ref`.
- Do not confuse source manifest keys (`type`, `content`, `data`) with Shifter
  native Django keys (`flag_type`, `flag`, `case_sensitive`).
- Do not add a second CTFd manifest, a second CTFd client, a second flag
  validator, or a custom submission API.
- Do not change range-baked artifacts to remove `FLAG{...}`. Participants should
  still see canonical flags in content; CTFd simply accepts the inner hash too.
- Do not make stale-row deletion unsafe. Validate the complete manifest and alias
  derivation before any live mutation.
- Do not let dry-run claim live correctness. Dry-run can report planned row
  shapes without writing; real sync/readback plus a submission smoke test proves
  acceptance.

## Non-Goals

- Implementing the issue in this preflight.
- Changing Shifter native CTF scoring, submissions, `CTFFlag`, templates, or
  Django API responses.
- Forking CTFd, building a custom CTFd plugin, or introducing a durable theme
  pipeline unless the implementation deliberately chooses the browser-normalizer
  route and accepts that extra operational surface.
- Mutating live CTFd, creating solves, altering participant accounts, changing
  challenge content, changing range files, or rebaking Polaris assets.
- Fixing unrelated CTFd sync, Guacamole, onboarding, PDF bake, Terraform, or
  Kubernetes issues.
