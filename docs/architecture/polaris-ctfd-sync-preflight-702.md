# Polaris CTFd Sync Preflight

Issue: GitHub #702, "`sync_polaris_ctfd.py` drops flag rows on re-sync
(update path)".

This note records the architecture boundary for the future implementation. It is
intentionally not an implementation plan.

## Boundary

The fix belongs in the standalone workshop CTFd sync path:

- `scripts/ctfd-workshop/sync_polaris_ctfd.py`
- shared helpers in `scripts/ctfd-workshop/common.py`
- reused or factored helpers currently in
  `scripts/ctfd-workshop/sync_polaris_ctfd_onboarding.py`

The sync contract is: the checked-in Polaris board JSON is the source of truth
for CTFd challenge metadata, flags, hints, prerequisites, and tags. A re-sync
must reconcile dependent CTFd rows every time a challenge is upserted, regardless
of whether the challenge was created or updated.

Keep these concepts separate:

- Manifest challenge id: the logical id in `ctfd-challenges.json` /
  `ctfd-onboarding.json`, used for ordering, prerequisites, smoketests, and
  reporting.
- Live CTFd challenge id: the API-generated id used in `/api/v1/challenges/*`,
  `/flags`, `/hints`, and `/tags`.
- CTFd flag rows: external scoreboard rows with `type`, `content`, and `data`.
- Shifter native `CTFFlag` rows: Django-owned, hashed flags under
  `shifter/shifter_platform/ctf`. They are a semantic reference only; they are
  not the storage model for this standalone CTFd board.
- Range/bake content: files and services inside Polaris ranges. CTFd row sync
  does not prove the flag is present in a rendered artifact.

Do not treat the existing category gate in `sync_polaris_ctfd.py` as the
contract. It currently restricts flag/hint/tag sync to `Start Here` and Missions
6-9; the source JSON contains flags and hints for every mission challenge.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| CTFd HTTP access | `scripts/ctfd-workshop/common.py::CtfdClient` | Reuse the existing headers, timeout, JSON handling, and token auth. Do not add another HTTP client or requests wrapper for the same API. |
| CTFd pagination | `sync_polaris_ctfd.py::get_all_items` and `scenario_smoketest.ctfd_check` | CTFd silently caps list responses. Any all-board read must page until CTFd metadata says done. |
| Board source | `scenario-dev/polaris/build/ctfd-challenges.json`, `ctfd-onboarding.json` | Do not duplicate challenge names, ids, categories, flags, hints, or tags into another schema. Validate the existing manifest instead. |
| Page/front matter parsing | `sync_polaris_ctfd_onboarding.py::load_pages`, `parse_page`, `upsert_page` | Page sync is adjacent but not the bug. Keep page behavior unchanged unless a test proves it is coupled. |
| Challenge upsert | `sync_polaris_ctfd_onboarding.py::upsert_challenge` and `sync_polaris_ctfd.py::build_payload` | Preserve the existing challenge payload shape and live-id return path. Reconcile child rows after every returned live id. |
| Flag helper behavior | `ensure_static_flag` in onboarding/seed scripts | Factor rather than copying, but generalize beyond one static flag. The issue requires comparing expected rows by `(type, content)` and removing stale rows. |
| Hint helper behavior | `ensure_hints` in onboarding script and `lessons-1.md` | Keep title/order derivation compatible, and include CTFd's polymorphic discriminator (`type: standard`) in write payloads. |
| Live-board verification | `scenario-dev/polaris/tests/scenario_smoketest/ctfd_check.py` | Reuse the readback idea: GET challenge flag rows after sync and fail non-zero on empty required rows. Apply the same readback discipline to source hints. Mutation stays in `scripts/ctfd-workshop/*`. |
| Bake/content verification | `verify_flags_baked.py` and `polaris-scenario-smoketest-preflight-617.md` | Keep CTFd row presence separate from rendered-artifact and participant-path verification. |
| Architecture gates | `.ground-control.yaml`, `.gc/plan-rules.md`, `scripts/adr_guard/adr_guard.py` | Architecture/doc changes pass ADR guard. Do not weaken workflow or guardrail enforcement. |

## Cross-Cutting Layers

Security layers the future design must satisfy:

- Auth surface: this remains an operator-run CLI using a CTFd admin API token.
  It must not add a participant-facing Django route, CTFd plugin, browser
  control, or Kali-side submission helper.
- CTFd token handling: preserve `CTFD_TOKEN` as the primary path. If a new token
  input is added, prefer a token file with restrictive permissions. Do not add
  new docs or examples that put admin tokens in process argv; existing `--token`
  compatibility should not be expanded.
- CTFd API shape: all calls go through `CtfdClient`, which sets
  `Authorization: Token`, `Accept: application/json`, and
  `Content-Type: application/json`. Do not bypass this for ad hoc `urllib`,
  `requests`, or shell `curl` calls.
- Manifest validation: before mutating CTFd, reject duplicate manifest ids,
  duplicate source names, missing names/categories, unsupported flag row shapes,
  or expected challenges with no flags unless there is an explicit future
  allow-empty contract. Empty source flags must be a source error, not a live
  sync success.
- Live identity validation: fail on duplicate live CTFd challenge names for the
  selected board scope. Updating the first matching name is unsafe while sync is
  still name-keyed.
- Flag-row policy: compare expected and live rows by stable CTFd API fields,
  starting with `(type, content)` and carrying `data` as CTFd requires. Static,
  regex, and future supported types must use one reconciliation path instead of
  one-off `ensure_static_flag` logic.
- Hint-row policy: reconcile source hints on every challenge upsert. CTFd hint
  PATCH/POST payloads must include `type: standard` as well as challenge id,
  title, content, cost, and requirements to avoid the historical NULL
  discriminator failure. Post-sync readback should fail when a challenge with
  source hints has no live hint rows.
- Dry-run gate: dry-run may print planned create/update/delete/verify actions,
  but must not perform read-modify-write calls or claim live verification. The
  real sync should verify after mutation.
- Secret handling: CTFd admin tokens, participant credentials, raw static flag
  contents, regex flag bodies, and full API response bodies must not be printed,
  logged, archived, or placed in argv. Logs may include challenge id, challenge
  name, row counts, row type, and action names.
- OS/process exposure: use Python JSON request bodies through `CtfdClient`. Do
  not shell out to `curl`, pass flags or tokens through subprocess arguments, or
  write temporary files containing flag values unless a future operator workflow
  explicitly owns their permissions and cleanup.
- Error envelopes: CLI failures should exit non-zero with challenge id/name and
  sanitized reason. Avoid dumping `argparse.Namespace`, authorization headers,
  full request bodies, or CTFd response payloads that may contain flag content.
- Config and validation gates: changes under `scripts/ctfd-workshop/**` should
  have focused local tests with a fake `CtfdClient`; architecture changes pass
  `python3 scripts/adr_guard/adr_guard.py --all --level ci`.

Maintainability incumbents the implementation must build on:

- `CtfdClient` and `get_all_items` for CTFd transport and pagination.
- `load_json`, `build_payload`, `resolve_prerequisites`, and
  `upsert_challenge` for the existing source-to-live challenge flow.
- Existing onboarding helper semantics for default hint titles and challenge
  payload fields.
- `scenario_smoketest.ctfd_check` for read-only flag-row verification behavior.
- Native CTF service tests only as concept checks for replacement semantics:
  when a caller supplies a child collection, the existing collection is replaced
  intentionally and atomically. Do not import native Django services into this
  standalone CTFd script.

Extensibility seam:

Keep the seam at the row-reconciliation boundary: a small helper should accept a
live challenge id, source row list, live row fetch function, row key function,
and create/patch/delete callbacks. Flags and hints can then share the same
"expected set vs live set" discipline without a generic framework or a second
manifest. The next likely variation is regex/bare-hash flag rows, non-empty
`data`, or id-keyed sync; those should be enabled by row-shape normalization and
a future live-id mapping field, not by editing every challenge loop again.

If id-keyed sync is introduced later, do not overload the existing manifest
`id`. That id already drives prerequisites and smoketests and is not the same as
the live CTFd database id.

Whole-repo surfaces in scope for the future implementation:

- `scripts/ctfd-workshop/sync_polaris_ctfd.py`
- `scripts/ctfd-workshop/sync_polaris_ctfd_onboarding.py`
- `scripts/ctfd-workshop/common.py`
- `scripts/ctfd-workshop/seed_ctfd.py` if shared helpers are factored
- `scripts/ctfd-workshop/README.md` for operator invocation and verification
- `scenario-dev/polaris/build/ctfd-challenges.json`
- `scenario-dev/polaris/build/ctfd-onboarding.json`
- `scenario-dev/polaris/lessons-1.md` and `lessons-4.md`
- `scenario-dev/polaris/tests/scenario_smoketest/ctfd_check.py`
- `scenario-dev/polaris/tests/test_scenario_smoketest.py` for readback precedent
- `scenario-dev/polaris/build/verify_flags_baked.py`
- `docs/architecture/polaris-scenario-smoketest-preflight-617.md`
- `docs/architecture/polaris-scenario-bake-preflight-618.md`
- `shifter/shifter_platform/ctf/services/challenge.py`,
  `ctf/services/hint.py`, and their tests as semantic references only
- `.ground-control.yaml`, `.gc/plan-rules.md`, and `scripts/adr_guard/adr_guard.py`

## Gotchas And Anti-Patterns

- Do not "fix" only the create/update branch. The current full-board script
  skips most mission flags because child-row sync is behind a category allowlist.
- Do not keep `ensure_static_flag` as a single-row, first-flag-only helper. The
  issue asks for source-JSON flags, plural, compared by CTFd row identity.
- Do not delete live rows before validating the complete source manifest. A bad
  JSON file should fail before it can remove event-critical rows.
- Do not silently preserve stale rows that are not in the source JSON. Direct
  live-event hotfixes must be backported into the JSON if they are intentional.
- Do not print raw flag values in "missing", "stale", mismatch, or exception
  output. Existing bake tooling is allowed to prove artifact presence; this sync
  tool should keep board answers out of operator logs by default.
- Do not create duplicate schemas for flags, hints, tags, pages, or challenges.
  Normalize the existing JSON at the boundary, then use that normalized shape.
- Do not treat manifest logical ids as CTFd live ids. Prerequisite resolution
  already depends on translating manifest ids to live ids after upsert.
- Do not bypass CTFd pagination. The event notes already record silent CTFd list
  caps.
- Do not patch CTFd hints without the polymorphic `type` field. That previously
  produced NULL hint types and participant-facing 500s.
- Do not solve this by submitting a test flag or creating participant solves.
  Verification is row readback, not scoring-path mutation.
- Do not make the standalone CTFd script depend on Django settings,
  `shifter_platform` app initialization, native CTF models, or database state.
- Do not widen the scope into page copy, CTFd user provisioning, range content,
  AMI bake, or Guacamole fixes while repairing board row reconciliation.

## Non-Goals

- Implementing the issue in this preflight.
- Migrating the board to id-keyed sync in the same fix unless a separate design
  decides how live CTFd ids are stored and bootstrapped.
- Changing Shifter's native CTF app, flag hashing model, hint unlock workflow,
  participant auth, scoring, or event lifecycle.
- Fixing the bare-hash/`FLAG{...}` submission-format request.
- Fixing the "Follow the Money" rendered PDF content bug.
- Replacing `verify_flags_baked.py`, the scenario smoketest, or
  `run-all-smoketests.sh`.
- Building a generic CTFd SDK or scenario packaging framework.
- Mutating submissions, solves, users, teams, pages, scores, ranges, AWS, or
  Terraform state as part of CTFd row verification.
