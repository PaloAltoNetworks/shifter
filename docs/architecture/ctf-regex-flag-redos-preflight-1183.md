# CTF Regex Flag ReDoS Preflight

Status: pre-implementation guidance

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1183>

Issue #1183 is a security maintenance fix for regex-backed CTF flags. The
invariant is that participant-triggered flag verification has bounded CPU cost
even when an organizer configures a regex flag. This is not a new flag type,
scoring workflow, parser framework, or CTF schema redesign.

## Boundary

- The canonical write boundary remains `ctf.services.challenge.add_flag`,
  `update_flag`, and `create_challenge` / `update_challenge` when they create
  `CTFFlag` rows from `flags`. Organizer views and APIs should keep delegating
  to those services.
- The canonical runtime boundary remains `ctf.services.submission.submit_flag`
  -> `ctf.services.challenge.verify_flag` -> `verify_single_flag`. Do not move
  regex decisions into views, templates, JavaScript, model `save()`, middleware,
  WAF rules, or database constraints.
- Regex flags are still organizer-authored match policies stored in
  `CTFFlag.flag_hash`. Static flags remain hashed secrets; programmable and HTTP
  flags remain separate validator concepts. Do not conflate these contracts.
- Submitted flag length must be capped before regex evaluation. The existing
  `CTFSubmission.submitted_flag` `max_length=500` is a persistence backstop, not
  a CPU bound, because verification currently runs before insertion.

## Architecture Decisions

- Use a regex engine or wrapper that provides an execution timeout or linear-time
  guarantee. Standard-library `re.fullmatch()` has no timeout and cannot close
  this finding by itself.
- Creation-time regex validation must reject syntactically invalid patterns and
  known unsafe constructs through the same service helper used by all flag write
  paths. Do not add endpoint-local regex validators or duplicate allowlists.
- Runtime regex verification must fail closed: invalid, timed-out, rejected, or
  over-length regex submissions return `False` / incorrect, not a 500 and not a
  participant-visible diagnostic about the pattern internals.
- If new runtime tunables are needed, keep them provider-neutral Django settings
  such as match timeout and submitted-flag length cap. Parse them through the
  existing settings/env-manifest pattern and keep `config/env-manifest.json`
  current. Do not add Terraform, Kubernetes, or per-event knobs for this fix.
- Keep the cap compatible with existing persistence unless a broader product
  decision changes both together: `CTFSubmission.submitted_flag` currently stores
  at most 500 characters and `CTFChallengeForm.flag` already caps organizer form
  input at 500.
- Do not hold the participant row lock while performing regex matching. The
  current submission service intentionally verifies flags before the lock because
  validators can be expensive or external; regex matching must become bounded
  instead of moving unbounded work into the critical section.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Flag write validation | `ctf.services.challenge._flag_hash_for_payload`, `add_flag`, `update_flag`, `create_challenge`, `update_challenge` | Centralize regex compilation/safety checks here so JSON, HTML, and live-repair writes share one policy. |
| Runtime dispatch | `verify_single_flag`, `_verify_regex_flag`, `verify_flag` | Preserve the boolean verifier contract and existing flag-type dispatch. |
| Submission workflow | `ctf.services.submission.submit_flag` | Keep availability, attempt limits, cooldowns, duplicate-solve protection, persistence, and leaderboard updates unchanged. |
| Request parsing | `ctf.views._parsing._parse_body_object`, `_get_body_str`; DRF wrapper `ctf.api._base.JSONBodySerializer` | Body shape and string type errors stay at the HTTP boundary; domain length/security checks stay in services. |
| Auth and scopes | `ctf.views._access`, `ctf.api._base.CTF_*_PERMISSIONS`, `shared.api_tokens.scopes` | Organizer ownership and participant event scoping still apply; auth is not a regex safety control. |
| Errors | `ctf.exceptions.CTFValidationError`, `_json_error`, `_error_tuple`, `shared.api.errors` | Creation-time rejection maps to controlled 400 envelopes; runtime mismatch stays an incorrect flag result. |
| Logging | module loggers plus `shared.log_sanitize.safe_log_value` / `safe_log` | Log ids, policy names, lengths, and timeout classes only. Never log submitted flags or full regex patterns. |
| HTTP validator precedent | `ctf.validators` timeout/capping/fail-closed patterns | Reuse the bounded-resource style; do not merge regex policy into HTTP validator URL/DNS policy. |
| Settings manifest | `config/settings.py`, split `config/_*.py` modules, `config/_env_manifest.py`, `tests/config/test_env_manifest.py` | Any new env-bound setting must be generated into the manifest and tested. |
| Tests | `tests/ctf/test_flag_verifiers.py`, `test_challenge_services.py`, `test_programmable_flags.py`, `test_submit_flag_rate_limit_api.py`, DRF token tests | Cover service helper behavior, add/update rejection, runtime timeout/fail-closed behavior, length cap, and API envelopes. |

## Cross-Cutting Layers

- Auth surface: organizer regex creation still passes `@login_required`,
  `@ctf_organizer_required`, DRF/session/token permissions, endpoint scope
  checks, `_resolve_owned_challenge_json`, and service-level
  `_assert_actor_owns_event`. Participant submissions still pass
  `@ctf_participant_required`, event-scoped participant resolution, and
  `assert_challenge_available_for_participant`.
- Payload validation surface: JSON bodies must still be objects; `flag` must
  still be a string where required. Length and regex-safety checks are domain
  policy and must be enforced by the services so non-HTTP callers cannot bypass
  them.
- Config shape surface: `CTFFlag.flag_type`, `flag_hash`, `case_sensitive`, and
  `validator_config` remain the persistence contract. Regex safety metadata
  should not require migrations unless the selected engine genuinely needs
  persisted metadata.
- Runtime resource surface: regex verification must have both a match timeout or
  linear-time guarantee and a submitted-flag length cap before matching. The
  solution must not shell out, spawn subprocesses, put flags/patterns in argv,
  write temp files, or rely on process-global alarms that can bleed across
  concurrent requests.
- Secret-handling surface: submitted flags, static flag plaintext, regex
  patterns, challenge solutions, session cookies, CSRF tokens, API tokens, HTTP
  validator headers, and query-string secrets stay out of logs, errors, docs
  examples, command lines, and test snapshots.
- Error-envelope surface: legacy CTF JSON routes keep flat controlled
  `{"error": "..."}` messages for creation-time validation errors; canonical
  `/api/v1/ctf/` routes keep the shared `{"error": {...}}` envelope via
  `_canonical_error_response`. Runtime regex failures should look like an
  incorrect submission, not a validation exception to the participant.
- Persistence surface: successful submissions still create `CTFSubmission` under
  the existing model validation and uniqueness constraints. Over-length
  submissions should be rejected or fail closed before regex evaluation and must
  not produce database `DataError` / model validation leakage.
- Import-boundary surface: CTF may use `shared` helpers but must not import
  `engine` or `mission_control` directly. Do not move regex safety into shared
  unless another app has the same domain need.
- Dependency/build surface: if a new regex package is selected, add it as a
  runtime dependency in `shifter/shifter_platform/pyproject.toml`, update the
  lockfile, and keep tests deterministic without requiring unbounded matches.

## Extensibility Seam

The seam belongs in a small CTF regex-policy helper consumed by both
`_flag_hash_for_payload` and `_verify_regex_flag`. It should accept the pattern,
case-sensitivity flag, submitted value, and policy parameters such as timeout and
maximum submitted length. That gives a future change one place to adjust the
engine, timeout, length cap, metrics, or stricter pattern policy without
touching views, submission scoring, flag storage, or API routing.

## Gotchas And Anti-Patterns

- Do not claim safety from `re.compile()` alone; it proves syntax, not bounded
  matching complexity.
- Do not add only a submitted-flag length cap and leave unsafe patterns running
  under stdlib `re` with no timeout/linear guarantee.
- Do not run dangerous regex/input pairs in tests without forcing a timeout via
  the selected engine or mocking the timeout path.
- Do not store compiled regex objects on models or in process-global mutable
  caches unless cache size, invalidation, thread safety, and policy updates are
  explicitly bounded.
- Do not return raw regex errors, timeout text, pattern strings, or submitted
  flag values to participants.
- Do not add a second CTF exception hierarchy, regex DTO, flag schema, or
  per-endpoint validation copy.
- Do not broaden flag semantics while fixing this issue: partial matches,
  multiline surprises, new flag types, or configurable participant feedback are
  separate product decisions.

## Non-Goals

- Implementing the fix in this preflight note.
- Redesigning CTF scoring, challenge availability, attempt limits, cooldowns,
  hints, live flag repair, HTTP validators, programmable validators, or CTFd
  sync.
- Adding organizer UI for regex safety policy, per-event regex settings,
  background workers, queues, WAF/DDOS controls, or infrastructure egress
  controls.
- Migrating existing stored regex flags unless the implementation discovers a
  concrete incompatible pattern policy and handles it as a separate data
  migration decision.
- Adding a new ADR. Existing service-boundary, DRF-envelope, settings-manifest,
  import-boundary, and logging guardrails are sufficient for this scoped fix.
