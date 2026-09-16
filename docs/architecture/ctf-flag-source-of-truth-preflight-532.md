# CTF Flag Source-of-Truth Preflight

Status: pre-implementation guidance

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/532>

> **Decision (implemented).** The issue chose a **single-release full removal**:
> the legacy `CTFChallenge.flag_hash` column, its runtime read fallback, and the
> dual-write are all removed in this change, after a one-shot data migration
> backfills `CTFFlag` from any usable legacy hash. This deliberately overrides the
> expand-and-contract sequencing recommended below (keep-the-column-this-release,
> a retained v1 import adapter, later contract release). The rolling-deploy risk
> that motivated expand-and-contract was raised and accepted (CTF is not serving
> under rolling replacement / a maintenance-window deploy covers it). The transfer
> format IS advanced to `shifter-challenges/v2` per the guidance below, but legacy
> `v1` exports are rejected on import rather than adapted (no compatibility layer).
> The boundary, semantics, backfill, admin, logging, and secret-handling
> guardrails below are otherwise adopted as written.

Issue #532 removes the ambiguity between `CTFChallenge.flag_hash` and
`CTFFlag`. The architectural invariant is that every recoverable challenge has
one or more active `CTFFlag` rows, and those rows are the only persisted source
used to decide whether a submission is correct. Multiple active flags keep the
existing any-of semantics.

`CTFChallenge.flag_hash` is a transitional storage field, not a second answer.
The physical column cannot be removed in the canonicalization release because
the production deployment paths run migrations before replacing all old
application instances. Its read compatibility and later removal therefore need
an explicit expand-and-contract boundary.

## Boundary And Semantics

- `CTFFlag` is the canonical aggregate for static, regex, programmable, HTTP,
  and registered extension flag types. Do not add a replacement flag DTO,
  repository, validator hierarchy, or challenge-level flag encoding.
- The plaintext `flag` input remains a compatibility convenience for HTML,
  CTFd, and simple API callers. Normalize it at the challenge service boundary
  to one static `flags` entry; never persist it only in
  `CTFChallenge.flag_hash`.
- Reject a write payload that supplies both `flag` and `flags`, and reject an
  explicitly empty `flags` list. On update, an absent or blank compatibility
  `flag` leaves the current flag set unchanged; a nonblank value atomically
  replaces it with one static `CTFFlag`.
- A challenge must retain at least one active flag. Serialize flag-set
  replacement and last-flag removal with a lock on the parent `CTFChallenge`
  row. Prevalidate and hash input before acquiring that lock, and never perform
  programmable or HTTP verification while holding it.
- Preserve `CTFBaseModel` soft-deletion semantics when replacing flags. A
  `challenge.flags.all().delete()` queryset hard-deletes rows and is not an
  acceptable replacement path.
- Keep ownership, event-state validation, live flag repair, content-hydration
  drift handling, audit emission, release-task behavior, and transaction
  boundaries in the existing challenge services. Models, views, serializers,
  admin classes, and migration code must not recreate that workflow.

## Compatibility And Persistence Contract

The canonicalization release is the expand phase:

- Backfill a static `CTFFlag` only when a challenge has no active flag rows and
  its legacy value has a supported stored-hash prefix (`$2`, `pbkdf2:`, or
  `sha256:`). Copy the digest; never hash a stored hash again. Use
  `case_sensitive=True` and `order=0` to preserve legacy behavior.
- Use a Django `RunPython` migration with historical models from
  `apps.get_model`. Do not import runtime models, services, validators, or
  logging helpers into the migration. Include recoverable soft-deleted
  challenges so restoring one cannot revive a gap.
- Existing active `CTFFlag` rows always win and must not be duplicated. An
  active challenge whose only legacy value is missing, a sentinel such as
  `multi-flag`, or another unsupported value is invalid migration input; fail
  deployment with bounded counts and identifiers, never stored flag material.
- Make the reverse data migration a no-op. It cannot distinguish a backfilled
  row from later user-authored canonical data safely, and the retained legacy
  column already permits application rollback during the expand release.
- Retain one isolated, named read adapter for a zero-`CTFFlag` challenge with a
  supported legacy static hash. It exists only for the old-writer window during
  rolling replacement, logs a warning containing safe identifiers, and fails
  closed for every other value. Never check legacy storage after a canonical
  row exists, and never repair data as a side effect of participant submission.
- Remove the fallback and then the legacy field only in a later contract
  release, after all deployments run canonical-only writers and a zero-gap
  audit confirms that no recoverable challenge lacks an active `CTFFlag`.
  Completion evidence, not a date or environment flag, is the compatibility
  exit condition.

The one-shot migration path in `scripts/portal-deploy/deploy_portal.sh` and the
ASG migration/instance-refresh ordering in
`.github/workflows/_shifter-platform.yml` are part of this contract. Do not
change those workflows or remove the column in the expand release: the new
image migrates the database while old containers or instances can still be
serving and writing.

## Transfer And Content Formats

- The default Shifter transfer format currently emits both top-level
  `flag_hash` and `flags`, reproducing the ambiguity outside the database. Emit
  a new `shifter-challenges/v2` format whose only verification material is a
  required, nonempty `flags` collection. Do not silently change the meaning of
  `shifter-challenges/v1`.
- Keep v1 import as a bounded adapter. If v1 has flag rows, they win and the
  top-level hash is ignored. If it has none, synthesize one static flag only
  from a supported legacy hash. Reject sentinels and malformed material with a
  controlled, nonsecret error.
- A trusted transfer import needs a narrow internal stored-material path because
  bcrypt/PBKDF2 digests must not be rehashed. That path still validates flag
  type, regex policy, programmable configuration, and HTTP configuration, and
  still enforces service-level event ownership. It is not a general repository
  abstraction or a public organizer write schema.
- Preserve the closed `shifter-ctf-content/v1` content-bundle schema and its
  nonempty `flags` validation. `ctf.services.content_hydration` already adapts
  bundles into the canonical challenge service and should not gain another
  flag representation.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Flag storage and lifecycle | `ctf.models.CTFFlag`, `CTFBaseModel`, `SoftDeleteManager` | Keep flag type, order, case sensitivity, validator configuration, and soft deletion in the existing model contract. |
| Challenge writes | `ctf.services.challenge.create_challenge`, `update_challenge`, `add_flag`, `update_flag`, `remove_flag` | Normalize every caller here; preserve actor ownership, event-state checks, audit, live repair, drift handling, and atomicity. |
| Flag validation and hashing | `_flag_hash_for_payload`, `hash_flag`, regex policy, `_validate_programmable_config`, `validate_http_flag_config` | Validate and hash once; do not duplicate per-endpoint or model validation. |
| Runtime verification | `verify_flag`, `verify_single_flag` | Keep any-of dispatch and fail-closed boolean behavior; only the bounded legacy adapter may precede the later contract release. |
| Submission workflow | `ctf.services.submission.submit_flag` | Preserve participant eligibility, availability, cooldowns, attempt accounting, locking, scoring, persistence, and leaderboard behavior. |
| Classic request shapes | `ctf.views._parsing._parse_body_object`, `_get_body_str`; `CTFChallengeForm.to_service_data` | HTTP/form shape checks stay at the boundary; canonical flag-set invariants stay in services. |
| DRF request shapes | `ChallengeWriteSerializer`, `FlagWriteSerializer`, `JSONBodySerializer` | Tighten the existing schemas as needed; do not add parallel challenge or flag DTOs. |
| Auth and ownership | `ctf.views._access`; `CTF_ORGANIZER_PERMISSIONS`; `CTF_PARTICIPANT_PERMISSIONS`; `_resolve_owned_event`, `_resolve_owned_challenge`; service ownership assertions | All browser, token, import, and non-HTTP writes retain their existing policy gates. |
| Domain errors | `ctf.exceptions.CTFValidationError`, `CTFStateError`, `CTFPermissionError` | Reuse the hierarchy and its current HTTP mappings. |
| API errors | legacy `_json_error` / `_error_tuple`; `ctf.api._base._canonical_error_response`; `shared.api.errors.api_error_response` | Keep both established envelope contracts and exclude verification material. |
| Logging and audit | module loggers, `shared.log_sanitize.safe_log_value`, existing CTF audit/live-repair helpers | Emit action, counts, and safe ids only; never emit hashes, plaintext, patterns, headers, or submissions. |
| Import/export | `ctf.services.transfer.SHIFTER_FORMAT` and its format discriminator | Version the wire contract and keep v1 adaptation in one place. |
| Content ingestion | `ctf.content_bundle`, `ctf.services.content_hydration` | Continue using their schema validation, receipt, drift, and service delegation. |
| Concurrency tests | `tests/ctf/test_services/test_submission_concurrency.py` | Use the repository's real-PostgreSQL transaction pattern to prove the parent-lock invariant. |
| Migration tests | existing `MigrationExecutor` tests under `tests/` | Prove forward backfill, idempotent preservation, invalid-row failure, soft-deleted recovery, and safe reversal. |

## Cross-Cutting Layers

- **Organizer authorization:** Classic routes continue through login and CTF
  organizer decorators. DRF routes continue through session/API-token
  authentication, active-actor and scope checks, organizer permissions, owned
  event/challenge resolution, and the service ownership assertion. Transfer
  import must not bypass the last check merely because its material is trusted.
- **Participant authorization:** Submission continues through participant
  authentication and event-scoped participant resolution, then
  `assert_participant_can_compete` and
  `assert_challenge_available_for_participant`. Canonicalizing storage must not
  weaken availability or scoring policy.
- **Request and schema validation:** Legacy JSON uses `_parse_body_object` and
  `_get_body_str`; DRF uses the existing serializers and
  `JSONBodySerializer`; HTML uses `CTFChallengeForm`; content imports use the
  content-bundle parser. Cross-field exclusivity, nonempty flag sets, hashing,
  and type-specific policy belong in the challenge service so non-HTTP callers
  cannot bypass them.
- **Secret handling:** Plain static flags must be hashed immediately. Stored
  hashes, regex patterns, programmable/HTTP configuration, validator headers,
  transfer material, and submitted flags are sensitive. Do not expose them in
  Django admin, challenge-detail templates, participant responses, logs,
  exceptions, metrics labels, snapshots, or migration diagnostics. Authorized
  full-fidelity export remains the sole intentional response surface for stored
  verification material.
- **Django admin and browser exposure:** Remove direct editing of
  `CTFChallenge.flag_hash` from `CTFChallengeAdmin`. Do not replace it with a raw
  `CTFFlag` inline that bypasses services or reveals stored material. Existing
  organizer service-backed screens remain the write surface, and the classic
  challenge detail must stop describing legacy fallback as normal behavior.
- **Configuration and environment shapes:** This change needs no setting,
  environment variable, provider parameter, Terraform input, Kubernetes
  object, or feature flag. If scope changes to add one, it must use the existing
  Django settings and `config/env-manifest.json` validation path; no such knob
  is justified for the compatibility exit gate.
- **OS and deployment exposure:** Run data migration through the existing
  `manage.py migrate` deployment path. Do not create commands that put flags or
  hashes in process arguments or environment variables, shell out, write
  verification material to temporary files, or print it to deployment output.
- **Error envelopes:** Organizer validation and state failures keep controlled
  4xx responses through the existing legacy and DRF adapters. Participant
  verification failures remain an incorrect/false result and reveal neither
  which canonical flag was evaluated nor why a validator failed. Migration
  failure reports bounded identifiers/counts only.
- **Observability:** Use module loggers, sanitized values, and existing CTF
  audit/live-repair hooks. Record compatibility-path use, backfill counts, and
  invariant violations without flag material. The current legacy-sentinel log
  that formats `legacy_hash` must not survive the change.
- **Import boundaries:** CTF may use `shared` contracts but must not import
  `cyberscript` directly or reach across `engine` or `mission_control`. This
  domain correction belongs inside the existing CTF service boundary.

## Extensibility Seam

The extensibility seam is the existing `flags` collection and flag-type
dispatch: organizer wire inputs normalize into `CTFFlag` payloads through
`_flag_hash_for_payload`, and runtime behavior dispatches through
`verify_single_flag`. A future flag type or validator policy should extend
those two points without changing challenge persistence, submissions, views,
or scoring.

The transfer format discriminator is the separate wire-version seam. Future
export variations receive a new version and one importer adapter rather than
new top-level challenge flag fields. The compatibility `flag` input remains a
boundary alias, not a parameter propagated through the domain.

## Required Evidence

- Service tests intentionally cover the plaintext compatibility input,
  canonical single and multiple flags, conflicting/empty inputs, replacement,
  last-flag refusal, soft deletion, and strict CTFFlag precedence.
- A real-PostgreSQL concurrency test proves concurrent removal/replacement
  cannot leave zero active flags.
- Migration tests cover supported hash families, existing canonical rows,
  recoverable soft-deleted challenges, invalid active rows, rerun safety, and
  no-op reversal without importing runtime models.
- API, form, CTFd import, content hydration, and live-repair tests demonstrate
  that every write surface reaches the same service invariant and preserves its
  existing auth/error contract.
- Transfer tests cover v2 output, v1-with-flags precedence, v1 legacy-only
  adaptation, invalid sentinel rejection, ownership, and the absence of raw
  material in errors and logs.
- A rollout audit demonstrates zero recoverable challenges without an active
  flag before a later change removes fallback or the database column.

## Gotchas And Anti-Patterns

- Do not dual-write or synchronize `CTFChallenge.flag_hash` and `CTFFlag`; that
  merely preserves two sources of truth.
- Do not accept legacy storage as a second possible answer when canonical rows
  exist, and do not keep `multi-flag` or programmable/HTTP sentinels as data.
- Do not rehash imported or migrated digests, guess at unknown legacy formats,
  or fabricate flags for corrupt active challenges.
- Do not remove or replace the last flag without locking the parent challenge,
  and do not rely on a pre-lock count that concurrent requests can invalidate.
- Do not use queryset deletion for a soft-deleted aggregate or introduce a
  database trigger/cross-table constraint to replace the service invariant.
- Do not repair missing rows during participant verification; it has no
  organizer actor, creates hidden writes, and races with legitimate updates.
- Do not expose raw stored values in Django admin, templates, logs, errors,
  migration output, command-line arguments, or client-side state.
- Do not mutate transfer v1 in place, duplicate transfer validation in views,
  or let trusted import become an authorization bypass.
- Do not remove the legacy column in the same release that backfills it. The
  deployment topology allows old code to run after the migration.
- Do not add a new flag schema, repository, exception hierarchy, audit path,
  serializer family, environment switch, or generic migration framework.

## Non-Goals

- Implementing the model, service, migration, API, UI, admin, transfer, or test
  changes in this preflight.
- Physically removing `CTFChallenge.flag_hash` in the canonicalization release;
  that is a later contract release after the exit gate is satisfied.
- Changing any-of flag semantics, scoring, challenge availability, cooldowns,
  attempt limits, hints, participant persistence, live repair, or leaderboard
  behavior.
- Redesigning regex, programmable, HTTP, or registered extension validators, or
  changing CTFd flag semantics beyond persisting its input canonically.
- Encrypting `CTFFlag` or `CTFSubmission`, redesigning authorized exports, or
  fixing unrelated admin exposure outside the challenge flag surface.
- Adding infrastructure, background work, a database trigger, a feature flag,
  or a new ADR. Existing service-boundary, validation, error-envelope, logging,
  deployment, and import-boundary rules are sufficient; this issue-scoped note
  records the domain cutover contract.
