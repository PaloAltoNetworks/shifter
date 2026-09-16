# Active CTF Content Refresh Preflight

Issue: GitHub #1971.

Status: pre-implementation guidance. This note changes no runtime behavior and
is not an implementation plan.

Issue #1971 intentionally supersedes the "new event only" revision policy in
`ctf-scenario-content-hydration-preflight-1907.md` for one narrow case: an
organizer may explicitly reconcile a managed event to the currently configured,
digest-pinned revision of the same scenario. ADR-024 and ADR-034 still govern
catalog and content-ingestion boundaries; no new ADR is needed unless the later
implementation changes those decisions.

## Boundary And Vocabulary

A refresh is an in-place revision of bundle-managed native CTF content. It is
not a second hydration schema, a scenario change, a CTFd import, a RAES pack
registration or launch, or an implicit background sync.

- `CTFChallenge.source_id` is the stable identity used to match a bundle
  challenge to its existing event row. A display name is mutable content, not
  identity.
- `CTFContentHydrationReceipt` is the current managed-content projection. The
  declared digest is the revision fence; the shared audit stream is the
  immutable history of revision changes.
- `CTFFlag` remains the only persisted source of flag truth. "Evidence key" in
  this issue is proof/validator material supplied through the existing bundle
  flag contract, not a new challenge column or evidence schema.
- The target revision is the server-configured reference resolved through
  `resolve_scenario_ctf_content`. The organizer does not submit an object key,
  URL, bundle body, flag, validator configuration, or target digest.

Only an event with a managed-content receipt may use this path. Foreign/manual
event content remains outside the reconciler, and an event may never change its
`scenario_id` through refresh.

## Reconciliation Policy

### Preserve durable event identity and history

Match existing challenges by `(event_id, source_id)` and update those rows in
place. Preserving the challenge UUID keeps submissions, ratings, attachments,
webhooks, organizer links, and historical score records attached to the same
logical challenge. Never delete and recreate the event or its matched
challenges merely to adopt a new bundle digest.

The bundle owns only fields present in `BundleChallenge` plus its flags, hints,
and prerequisite edges. Organizer-owned overlays that the bundle cannot express
(for example attachments, tags, topics, `release_time`, and `next_challenge`)
must not be erased as an incidental side effect. Do not infer ownership from a
field's current value.

Static flag hashes cannot prove equality with a new plaintext declaration
because they are salted. On a real revision, validate and hash the target flag
set again through the canonical flag policy; do not persist a comparison digest
or log plaintext to make diffing easier. Flag writes are atomic with the rest of
the revision, so readers see the old committed set or the new committed set,
never an empty/intermediate set.

### Lifecycle determines the allowed change set

`DRAFT` and `REGISTRATION` events have no legitimate solve or hint-usage ledger,
so the complete managed graph may be reconciled there, including source-id
additions/removals and hint/prerequisite changes, while preserving matched
challenge UUIDs. The service must assert that absence before a structural
reconcile; unexpected submissions, hint usage, or ratings are a state conflict,
not data to cascade away.

`ACTIVE` and `PAUSED` are live-event states. Their refresh allowlist is limited
to bundle-owned presentation/verification fields:

- challenge name, description, category, difficulty, flag format, solution,
  display order, visibility, target instance/port; and
- the complete flag set, including type, order, case sensitivity, static or
  regex proof material, and HTTP validator configuration.

The live path must reject the entire revision, without partial writes, if it
adds/removes/renames a `source_id`, changes hints or prerequisite edges, or
changes `points`, `minimum_points`, `decay_function`, `decay_solve_count`, or
`max_attempts`. Those values affect authoritative submissions, hint usage,
attempt gates, dynamic repricing, and materialized participant/team scores.
Ignoring an unsafe difference while marking the target digest pristine would
be false provenance; silently repricing or deleting history would be worse.

`ENDED`, `CANCELLED`, and `ARCHIVED` content is historical evidence and is not
refreshable. A paused event follows the live policy because pausing does not
erase its earlier competition ledger.

Existing `CTFSubmission` and `CTFHintUsage` rows are never revalidated,
rewritten, or deleted. Previously awarded points remain factual. Refresh changes
which proof future attempts accept; it does not retroactively change which
attempts were correct.

### One explicit, fenced, atomic operation

Resolve and fully validate the configured object before opening a database
transaction or taking an event lock. The mutation then uses one outer
`transaction.atomic()`, locks the `CTFEvent` and its receipt, rechecks ownership,
scenario identity, lifecycle policy, and the caller's expected current digest,
and applies the complete accepted revision.

The expected-current-digest comparison is an optimistic fence between the
organizer's displayed status and the write. It is not a caller-selected target.
A mismatch is a conflict, not permission to apply whichever revision won the
race. Exact replay of a pristine current digest is a no-op. An explicit refresh
may restore a drifted managed graph from its configured bundle, including when
the configured digest is unchanged, but only after the same lifecycle/diff
policy succeeds.

The receipt remains one row per event and is updated to the realized target
evidence and counts only after the graph is complete. Its state becomes
`PRISTINE` in the same commit. The bounded result and strict audit event must
distinguish `created`, `noop`, and `refreshed`; refresh audit records include the
previous and target digests, actor, event/scenario ids, bounded counts, and
changed-field/count categories, never content values.

All native validation must finish before the first mutation. A validation,
constraint, audit, or persistence failure rolls back flags, challenge fields,
graph changes, receipt evidence, and the success audit together. Two-phase
renames or another collision-safe technique are required when pre-activation
reconciliation swaps challenge names; row-by-row renaming can violate
`unique_active_challenge_name_per_event` even when the target bundle is valid.

### Submission cutover semantics

Live refresh and flag verification can overlap. `submit_flag` intentionally
performs regex/HTTP verification before participant locks, so the refresh must
not move external validation under an event/receipt lock. The accepted contract
is:

- the transaction commit is the cutover for verification attempts that have
  not yet read a flag set;
- a verification already using the old committed flag set may finish under that
  old revision; and
- live-safe refresh cannot change scoring/attempt fields, preventing a mixed
  old/new scoring decision.

This linearization rule needs PostgreSQL concurrency coverage. If implementation
chooses a stricter generation fence for in-flight submissions, that fence must
be short-lived around persistence and must not serialize outbound HTTP or regex
work under an event-wide lock. Do not assume `PAUSED` alone drains in-flight
requests: the current submission service checks event state before verification
and does not recheck it under a lifecycle lock.

Every path back to `ACTIVE`, including `resume_event`, must reuse
`assert_event_content_hydration_ready` under the event lock. The current resume
path is a bypass relative to the #1907 invariant and must not remain one once a
refresh/restore surface exists.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Obligation |
| --- | --- | --- |
| Reference/config shape | `shared.schemas.ctf_content_reference`, `config/_ctf_content_settings.py` | Keep the closed scenario/key/digest catalog, bounds, prefix containment, duplicate rejection, and startup failure. Do not add refresh config or a second digest parser. |
| Bundle shape | `ctf.content_bundle` | Reuse the sole closed `shifter-ctf-content/v1` parser and immutable DTOs; do not add a refresh DTO that restates challenge/flag/hint fields. |
| Resolution | `ctf.services.content_resolution`, `shared.cloud.get_object_storage`, `ObjectStorage` | Preserve head/download identity preconditions, byte cap, private staging, SHA-256 verification, cleanup, and provider neutrality. |
| Persistence identity | `CTFChallenge.source_id`, `CTFContentHydrationReceipt`, active-row managers/constraints | Match by source id, preserve challenge UUIDs and historical FKs, and update one current receipt under row locks. |
| Challenge policy | `_CHALLENGE_MUTABLE_FIELDS`, native model/DB constraints, release scheduling | Reuse/factor native pure field validation; keep bundle ownership distinct from organizer overlays and live-safe policy distinct from ordinary interactive editing. |
| Flag policy | `CTFFlag`, `_flag_hash_for_payload`, `hash_flag`, `regex_policy`, `ctf.validators` | Reuse hashing, safe regex, HTTPS/SSRF/DNS-pinning, timeout, response-cap, and no-redirect policy. A bundle still cannot select extension-discovered executable code. |
| Scoring history | `CTFSubmission`, `CTFHintUsage`, `ctf.services.scoring`, materialized leaderboard recompute | Preserve authoritative rows and points. Reject live scoring/ledger topology changes rather than invoking recompute as a substitute for policy. |
| Authorization | `CTF_ORGANIZER_PERMISSIONS`, `ctf:event:write`, `_resolve_owned_event`, `assert_actor_owns_event` | Require session/API-token admission, organizer role, event-write scope, exact owner check in HTTP and service layers. No delegated staff capability is implied. |
| Errors | `ctf.exceptions`, `_CtfApiError`, `shared.api.errors` | Map stale revision/unsafe diff/state to controlled conflict envelopes with stable codes. Never call `CTFError.to_dict()` when details may contain content coordinates or validator data. |
| Audit/logging | `ctf.services.audit`, `shared.audit`, `shared.log_sanitize` | Use strict transactional success audit and sanitized ids/digests/counts. Omit bodies, proof values, hashes, URLs, headers, object keys, temp paths, and provider exception text. |
| API/OpenAPI | `ctf.api.organizer`, typed serializers, `ctf/api/urls.py`, committed OpenAPI artifact | Keep refresh a content operation, not a lifecycle action. Expose only bounded organizer status/result fields and regenerate the canonical client schema. |
| SPA state | `frontend/src/api/ctfAdmin.ts`, `ctfKeys`, `EventDetailPage` | Reuse the shared client/CSRF/error behavior and invalidate organizer event/challenge plus participant challenge caches after success. Do not hand-copy generated API types. |
| Import boundaries | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `ctf.services` facade | CTF may consume `shared` and the CMS public facade, never provider SDKs, Engine, Mission Control, or CMS internals. Export the reconciler through the existing CTF facade. |

Public individual challenge/flag/hint mutators own interactive edit state gates,
drift marking, and per-item audits. A single bundle reconciliation should not
loop through those workflows and emit misleading live-repair/drift transitions.
Factor and reuse their pure validation/hash/constraint helpers inside the CTF
domain, while keeping one refresh transaction and one revision-level audit.
That is reuse of policy, not a second mutation stack.

## Security And Runtime Gates

- **HTTP admission:** the canonical DRF session/token authentication remains in
  force. Session writes retain CSRF protection; API tokens require
  `ctf:event:write`. URL UUID and the bounded expected digest use typed
  serializers, then ownership is checked again in the service.
- **Storage authorization:** event ownership authorizes the CTF operation;
  deployment config does not. Object access still uses the portal's existing
  workload identity and read-only bucket/prefix grant. No request credential,
  presigned URL, static cloud key, participant access, or provider SDK enters
  CTF.
- **Reference and bundle validation:** `_ctf_content_settings.py` and
  `shared.schemas.ctf_content_reference` validate env/catalog shape at startup;
  `content_resolution` validates object identity/digest; `content_bundle`
  validates JSON shape, bounds, graph, regex, and HTTP policy; native helpers
  validate persistence semantics. Unknown fields and versions fail closed at
  their owning layer.
- **Secret handling:** static proof plaintext exists only in the validated
  in-memory bundle long enough to be salted/hashed. Regex and HTTP validator
  configurations remain private content. Neither organizer status/result nor
  errors, audit, logs, OpenAPI examples, frontend state, or tests expose them.
- **OS/process exposure:** reuse `entrypoint.sh`'s secret-to-environment binding,
  `content_resolution`'s private temporary staging, and workload identity. The
  refresh introduces no environment variable, ConfigMap, Terraform output,
  command argument, shell command, subprocess, public file, or download URL.
  Bundle bytes and flag/validator material never enter process argv.
- **Error envelope:** resolver/parser/provider exceptions become existing
  generic `CTFValidationError`/`CTFStateError` codes and the shared
  `{"error": {...}}` response with request id. Safe field names/counts may
  explain an unsafe diff to the organizer; values, URLs, object identity, and
  exception text may not.
- **Observability:** log/audit sanitized event/scenario ids, previous/target
  digest, outcome, duration, and bounded counts. Use `safe_log_value` for
  bounded identifiers and fingerprint/omit private coordinates. A successful
  revision audit is strict and in the content transaction.

The deployment/runtime surfaces in scope for regression, but not expected to
need new configuration, are `config/env-manifest.json`, `entrypoint.sh`, the GCP
runtime renderer and portal workload IAM, AWS portal SSM/user-data/redeploy
bindings and IAM prefix policy, and the AWS EKS runtime environment. The current
bucket/prefix/max-bytes/reference shapes already cover refresh.

## Extensibility Seam

Keep the existing resolver-to-domain seam: `ResolvedCtfContent` plus event and
actor attribution enters the CTF-owned reconciliation service. Add the
organizer-observed **expected current digest** as the optimistic concurrency
parameter; the configured `ResolvedCtfContent.evidence.declared_digest` remains
the server-owned target. Do not add a caller-controlled mode that weakens live
policy.

The next reasonable variation is a read-only preview of the same bounded diff.
Centralize diff classification (presentation/verification-safe versus
score/ledger-unsafe) inside the reconciliation domain so preview and apply can
share it without duplicating bundle schemas or field allowlists. A future
bundle version extends the central discriminated parser and classifier, not
every API, resolver, provider adapter, or frontend component.

## Gotchas And Anti-Patterns

- Do not match challenges by name, order, database UUID from the bundle, or
  positional index; only `source_id` is authored stable identity.
- Do not delete/recreate matched challenges, the event, submissions, ratings,
  hint usage, or scores.
- Do not treat a changed count as sufficient drift detection, or call the
  current `_content_shape_matches` a reconciler; it intentionally checks only
  replay shape.
- Do not compare static flag hashes, persist unsalted proof fingerprints, or
  retain old flags as an undocumented grace set.
- Do not apply safe fields and ignore unsafe ones while recording the target
  digest as pristine. Reject atomically with field names/counts only.
- Do not let ordinary organizer CRUD, Django admin, a management command, the
  scheduler, event creation, page reads, or process startup become alternate
  refresh workflows.
- Do not overload `hydrate_event_ctf_content`'s `created: bool` result so
  "refreshed" is indistinguishable from no-op, and do not reuse
  `audit_live_flag_repair` for a bundle revision.
- Do not put refresh into `EventLifecycleRequestSerializer`; content revision
  and event status transition are different concepts.
- Do not download or parse while holding database locks, and do not hold locks
  across HTTP flag verification.
- Do not assume pausing drains in-flight submissions or that `resume_event`
  currently enforces managed-content readiness.
- Do not create a CTF-local cloud client, auth class, audit table, exception
  hierarchy, error envelope, content schema, or client type copy.

## Non-Goals And Implementation Boundaries

- No automatic fleet-wide refresh, startup reconciliation, polling, scheduler,
  queue, or background job.
- No scenario switch, catalog/RAES pack mutation, content publication, object
  upload, entitlement, or provider-IAM redesign.
- No CTFd synchronization and no change to the private scenario-side access
  fix described in the issue.
- No retroactive rescore, submission revalidation, attempt deletion, hint-usage
  rewrite, leaderboard semantics change, or historical event refresh.
- No new flag type, programmable code loading, HTTP egress policy, or broadened
  validator contract.
- No general-purpose merge engine. The only supported merge is the explicit,
  policy-checked replacement of fields owned by the validated bundle on the
  same managed event.

Focused regression coverage belongs beside
`test_content_hydration.py`, `test_content_hydration_concurrency.py`,
`test_flag_source_of_truth.py`, `test_mid_event_operations.py`, and the CTF API
contract tests. It must prove stale title/flag replacement on the same challenge
UUID, new-proof acceptance and old-proof rejection, exact retry, drift restore,
unsafe live-diff rollback, strict-audit rollback, owner/scope/error-envelope
behavior, resume readiness, and PostgreSQL refresh races without exposing proof
material.
