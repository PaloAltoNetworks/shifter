# Digest-Pinned Scenario CTF Content Hydration Preflight

Requirement: CTF-1405. Issue: GitHub #1907.

Status: pre-implementation guidance.

Revision note: GitHub #1971 intentionally supersedes this note's "new event
only" policy for an explicit, policy-checked refresh of the same managed event;
see `ctf-active-content-refresh-preflight-1971.md`. The #1971 note does not
change runtime behavior by itself.

This note fixes the boundaries and cross-cutting obligations for native CTF
event-content hydration. It is not an implementation plan and does not change
runtime behavior. ADR-024 and ADR-034 already govern the relevant catalog,
content-ingestion, entitlement, and executable-content decisions; CTF-1405 does
not need another ADR unless implementation changes one of those decisions.

## Boundary And Vocabulary

CTF-1405 hydrates a native `CTFEvent` challenge graph. It does not hydrate a
range specification and it does not register, mutate, or launch a RAES
environment pack.

Keep these three concepts separate:

1. `RaesPackageSource` and `cms.scenarios.registry` identify a launchable
   scenario and retain reference-only package provenance.
2. A deployment-owned CTF content reference maps a scenario id to one bounded,
   digest-pinned private object.
3. A native CTF event-content service validates and atomically creates
   `CTFChallenge`, `CTFFlag`, `CTFHint`, and
   `CTFChallengePrerequisite` state.

The resolver obtains trusted bytes for item 2 and hands a validated, data-only
bundle to item 3. A future Django application/plugin may replace the resolver
and call the same event-content service with the same bundle contract. Neither
the deployment-config mechanism nor an object-storage type belongs in the
event-content service contract.

The current code uses RAES terminology after the ADR-024 hard cutover. The
historical ACES issue lineage in #1232 and #1252 does not authorize ACES aliases,
parallel models, compatibility paths, or a second catalog.

## Architecture Decisions

### Two closed, versioned data contracts

The reference contract and bundle contract have different owners and must not
be collapsed into one schema.

- The deployment reference is a bounded, versioned allowlist. Each entry has
  exactly a scenario id, a contained object key, and a lowercase
  `sha256:<64 hex>` digest. Bucket, prefix, maximum bytes, credentials, and
  provider are server-owned settings, not entry fields.
- The reference JSON parser rejects duplicate JSON keys before ordinary object
  construction, then rejects duplicate scenario ids, unknown fields, excessive
  entries/bytes, invalid scenario ids, absolute or parent-traversing keys,
  keys outside the configured prefix, and malformed digests. An empty reference
  set is valid and preserves current behavior.
- The bundle has an explicit contract/version discriminator and scenario id.
  Its closed challenge entries contain stable bundle-local ids, supported
  scalar native challenge fields, one or more flags, ordered hints, and
  prerequisite references to those ids. Unknown fields and unknown contract
  versions fail closed.
- Every collection, string, integer, JSON object, and nesting depth is bounded
  before persistence. Duplicate stable ids, active challenge names, flag/hint
  orders, prerequisite edges, missing prerequisite targets, self-edges, and
  cycles are bundle-level errors.
- The bundle schema is the only serialized hydration schema. Do not duplicate
  it in a serializer, a model JSON field, a management command, or a
  plugin-specific DTO. Transport adapters may validate transport types, but
  domain and graph policy remains authoritative in the CTF-owned contract.

The reference contract belongs in `shared` because both the composition root
and resolver need a provider-neutral shape. The bundle and hydration receipt
are native CTF concepts and remain under `ctf`; moving them into `shared` merely
to avoid a proper service call would erase domain ownership.

### Resolution is bounded and immutable

The current resolver must use `shared.cloud.get_object_storage()` and the
`ObjectStorage` protocol. It must not import an AWS/GCP SDK directly, accept a
URL, mint a presigned URL, or shell out to a cloud CLI.

Resolution has the following security properties:

- Resolve only the configured bucket and prefix with the deployment workload's
  bucket-scoped read identity. Config presence grants no user authorization.
- Call `head_object`, enforce the object-size cap, and pass the returned
  `etag`/`generation` identity to `download_object`. A changed object is a
  precondition failure, not a retry against new bytes.
- Download to a private temporary directory/file, clean it on every outcome,
  and compute SHA-256 over the exact downloaded bytes. Verify the declared
  digest before JSON decoding or any database mutation.
- Use JSON as data only. Do not extract archives, import modules, evaluate
  expressions, deserialize Python objects, invoke hooks, or execute anything
  supplied by the bundle.
- Provider I/O and parsing occur before a database transaction or event-row
  lock. The parsed immutable value object is the input to persistence; no
  mutable object is reread after verification.

`shared.raes.object_source.stage_object_pack` is the incumbent for the
head/bound-download/private-staging lifecycle. Reuse its object-storage
primitives and cleanup posture, not its tar extraction or RAES package
semantics.

### Native CTF owns validation and mutation

The event-content service is one public CTF service boundary. It must preserve,
or factor out and reuse, the existing rules owned by:

- `ctf.services.challenge.create_challenge` and its mutable-field allowlist,
  native model constraints, release-time/event rules, and release scheduling;
- `ctf.services.challenge.add_flag`,
  `_flag_hash_for_payload`, and `hash_flag` for storage and flag policy;
- `ctf.services.regex_policy` for bounded, safe regex validation;
- `ctf.validators` for named and HTTP validation, including HTTPS-only
  endpoints, DNS/address policy, actual-IP pinning, TLS SNI/Host preservation,
  timeouts, response caps, and no redirects;
- `ctf.services.hint.add_hint` for hint policy; and
- `ctf.services.challenge.add_prerequisite` for same-event, duplicate, cycle,
  and event-row serialization rules.

The bundle validator performs closed-shape, resource, cross-reference, and DAG
validation before mutation. It delegates native field and validator policy to
the same CTF-owned pure validators used by interactive service calls. If those
rules are currently private or coupled to a row write, factor them into one
CTF-owned helper and make both callers use it; do not restate them.

Bundle flag types form an explicit contract allowlist. They are not every value
returned by `ctf.extensions.registered_flag_types()` or
`ctf.validators.list_validators()`. In particular, the test-only
`always_true` named validator must never become package-usable merely because it
is registered. A programmable flag, if the contract supports it, selects only
an explicitly allowlisted, preinstalled name and a closed, bounded parameter
shape. The bundle never supplies a dotted import, callable, code body, template,
or executable. HTTP flags continue through the incumbent SSRF/DNS-pinning
policy; their URLs, query strings, and headers are private data.

`ctf.services.transfer.import_challenges` is not this boundary. Its intentional
partial-success behavior, format inference, CTFd adaptation, stored-hash import,
and lack of stable prerequisite ids conflict with CTF-1405. Do not expand,
wrap, or silently route hydration through it.

### One atomic event-content operation

All externally supplied bytes are resolved and validated before persistence.
The native mutation then runs in one outer `transaction.atomic()` and locks the
event row before inspecting or creating content. Inner native service
transactions remain nested savepoints; they are not a reason to commit each
challenge independently.

Within that atomic unit:

- recheck event ownership and that the event is content-modifiable;
- reject any pre-existing live challenge, flag, hint, or prerequisite rows
  unless a matching successful hydration receipt proves this is an exact
  replay;
- create the complete native graph through the CTF-owned service/validation
  boundaries;
- persist one CTF-owned hydration receipt; and
- write the successful audit event with `strict=True`.

Any exception rolls back the graph, receipt, release-scheduling state, and
success audit together. An explicit pre-activation operation may leave the
already-existing draft event intact, but it must expose no partial event
content. If hydration is composed with event creation, the event and its
content use the same database atomic unit after resolution.

The receipt is one per event and contains only bounded evidence: scenario id,
reference/bundle contract versions, declared digest, realized object identity
metadata where non-sensitive, counts, outcome/state, actor attribution, and
timestamps. It never stores the bundle body, object URL, flag value/hash,
validator secret/header, credential, or runtime configuration.

Exact receipt/reference/digest replay against pristine managed content is a
no-op. A changed reference/digest, different scenario, pre-existing foreign
content, or a receipt marked drifted is a conflict; CTF-1405 has no implicit
replace, merge, reconcile, delete-and-recreate, or downgrade operation.

Every native content mutation path, including organizer edits and live flag
repair, must participate in the managed-content policy in the same transaction:
either it is refused for managed content, or it marks the receipt drifted and
prevents activation/replay from claiming a match. The consistent default is to
mark an authorized native edit as drift and fail later activation/replay; it
preserves the existing emergency repair surface without silently pretending the
event still equals its bundle. Do not try to rediscover equality from salted
static-flag hashes, and do not store an unsalted digest of low-entropy flag
plaintext as an oracle. Admin and bulk-write surfaces must not bypass this
policy.

### Activation is the fail-closed gate

All routes to `ACTIVE` share one service-level readiness check. Both
`start_event` and `activate_event`, including scheduled/internal callers, must
refuse activation when the event's scenario has a configured content reference
but lacks a matching successful, pristine hydration receipt. A scenario with
no reference follows current behavior exactly and requires no synthetic receipt.

The check belongs in the lifecycle service, not only in an API view, event
creation form, scheduler, or frontend. Opening registration may remain distinct
from activation, but it must not become an alternate way to bypass hydration
readiness.

### Audit, logging, and errors disclose bounded evidence only

Use `shared.audit.AuditEvent`, existing `AuditAction` values
(`CREATE`/`UPDATE`/`FAILED` as applicable), and an existing entity vocabulary
such as `CONFIG` with the CTF UUID-to-int convention. Do not create a second
audit table, writer, or exception-only log. Success is strict and transactional;
no-op and failure outcomes are also auditable with stable reason codes after the
content transaction has settled.

Logs and audit state may contain sanitized scenario/event identifiers, declared
digest, non-sensitive version/identity metadata, counts, duration, outcome, and
stable reason code. Use `safe_log_value` for bounded non-secret input and
`safe_log_fingerprint`/omission for private object keys, endpoint coordinates,
and sensitive identifiers. Never log the body, flag material, validator
configuration, provider exception text, temporary path, URL, request headers,
or parsed snippets.

Resolver failures translate `CloudStorageError`,
`ObjectPreconditionError`, digest/shape failures, and unexpected parser errors
into the existing `CTFValidationError`/`CTFStateError` categories with stable
codes and generic messages. Any HTTP surface renders them through
`shared.api.errors` and `_CtfApiError`; it must not serialize `CTFError.details`
when those details could include private refs, provider diagnostics, validator
configuration, or content fragments.

## Cross-Cutting Gates

| Layer | Canonical incumbent | CTF-1405 obligation |
| --- | --- | --- |
| Catalog identity | `cms.scenarios.registry`, `ScenarioMetadata`, `RaesPackageSource`, `shared.schemas.raes_package_source` | Resolve the existing scenario id; do not store content refs/bodies or CTF state in catalog rows, duplicate access flags, or create a second catalog. CTF reaches CMS only through `cms.services`/`ctf.bridges`. |
| Deployment config | `config/_capacity_planning_settings.py`, `shared.capacity.catalog`, `config/_env_manifest.py`, `config/env-manifest.json` | Parse one closed, bounded reference contract at the composition root and fail startup on a declared malformed map. Reject duplicate JSON keys. Keep no-reference deployments inert. |
| Provider selection | `shared.cloud.get_object_storage`, installation capability registry | Use the installed backend's declared storage capability; never infer AWS, bypass capability checks, or import a provider adapter from CTF. |
| Object identity and bounds | `ObjectStorage.head_object` / `download_object`, AWS/GCP storage adapters, `shared.raes.object_source` | Enforce content length and exact ETag/generation before trusting bytes; then verify the declared digest. |
| Workload identity | GCP `platform/terraform/gcp/modules/portal/iam`; AWS `platform/terraform/modules/portal/ec2` | Add only portal read access, scoped to the configured bucket/prefix. No write/list-wide grant, static access key, request credential, or participant access. |
| Auth and ownership | `CTF_ORGANIZER_PERMISSIONS`, `ctf:event:write`, `_resolve_owned_event`, `assert_actor_owns_event` | An explicit operation is organizer-authenticated, exactly scoped, and owner-checked in both HTTP and service layers. Automatic/system composition still carries actor attribution and cannot use config as authorization. |
| Reference validation | shared-native closed reference parser | Validate version, count/bytes, scenario id, contained key, digest, duplicates, and unknown fields before any storage call. |
| Bundle validation | one CTF-owned closed bundle contract plus native pure validators | Validate bytes/UTF-8/JSON/duplicate keys/schema/bounds/domain fields/flags/hints/graph completely before a DB write. |
| Flag security | `_flag_hash_for_payload`, `hash_flag`, `regex_policy`, `ctf.validators` | Hash static plaintext immediately, enforce regex and HTTP policy, and use an explicit package validator allowlist. Never persist/log plaintext or execute package code. |
| Persistence and concurrency | `transaction.atomic`, event row lock, native challenge/hint/prerequisite services | Serialize against edits and lifecycle, create all-or-nothing, preserve DB constraints, receipt identity, and drift policy. |
| Audit | `shared.audit`, `ctf.services.audit` | Emit bounded existing vocabulary; strict success audit is in the mutation transaction. |
| Logging | `shared.log_sanitize` | Log identifiers/digest/counts/outcomes only; fingerprint or omit private coordinates. |
| Errors/API | `ctf.exceptions`, `shared.api.errors`, CTF API organizer helpers | Reuse the hierarchy/envelope and fixed public messages; no raw storage/parser/validator data. |
| Imports | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml` | Keep CTF independent of provider SDKs and CMS internals; keep config on public service/shared contracts; do not import RAES tooling outside `shared.raes`. |

## Configuration And Host/Runtime Exposure

The CTF resolver needs its own server-owned settings namespace for reference
map, bucket, prefix, and maximum object bytes. It may point at the same physical
bucket a deployment already operates, but it must not overload
`RAES_PACKAGE_BUCKET`, `RaesPackageSource.package_ref`, or RAES archive size
settings: their ownership, object shape, and lifecycle are different.

New settings must be represented consistently in:

- the Django `config/_*.py` composition module and `config/env-manifest.json`;
- runtime configuration renderers and their parity tests;
- GCP environment/platform-core/portal-IAM variables and Kubernetes runtime
  binding;
- AWS environment/portal variables, SSM/user-data/redeploy binding, and portal
  role prefix policy; and
- local/CI deployment validation and operator documentation.

The bundle body and flag/validator values never belong in an environment
variable, Terraform variable/output, tfvars file, ConfigMap, Helm value/history,
SSM command string, shell trace, or process argument. The reference map is
bounded deployment metadata, not a credential, but private object keys should
still use the existing private runtime-config/secret-hydration surface or a
private mounted config rather than public rendered artifacts. Storage
credentials come only from the existing instance/workload identity.

The runtime performs no `curl`, `aws`, `gcloud`, shell, Docker, Terraform, or
subprocess invocation. Temporary bytes use private filesystem permissions and
are removed in `finally`; they are never copied into a public media/static
directory or offered through a download endpoint.

## Extensibility Seam

The durable seam is:

```text
deployment resolver ─┐
future plugin resolver ├─> validated CTF content bundle ─> native event-content service
other trusted resolver ┘
```

The parameter at that seam is the immutable, versioned bundle value plus
actor/request attribution—not bucket, URL, provider client, deployment setting,
or plugin object. The event-content result is a bounded created/no-op receipt,
not ORM internals.

The next resolver may acquire bytes differently, but it must satisfy the same
trusted-byte preconditions before calling the service. Adding a new explicitly
supported flag validator or bundle version extends the central discriminated
contract/allowlist; it does not require edits to event creation, activation,
catalog projection, object-storage adapters, or every resolver.

Do not introduce plugin discovery, installation, lifecycle, entitlement, or
package execution for CTF-1405. Existing `ctf.extensions` remains the Django-app
runtime extension mechanism, not an authorization source for package-declared
validators.

## Whole-Repository Scope For The Later Implementation

The implementation must evaluate, and change only as needed:

- ADR-024 and ADR-034 in `docs/adr/index.yaml`;
- `docs/architecture/uniform-content-ingestion-contract.md`,
  `docs/architecture/uniform-content-ingestion-preflight-1578.md`, and
  the catalog/package boundary preflights for #1232/#1252;
- `cms/scenarios/registry.py`, `cms/models/scenarios.py`,
  `shared/schemas/raes_package_source.py`, and
  `cms/services/_content_ingestion.py` for boundary regression protection, not
  CTF body persistence;
- `shared/cloud/{__init__,types,exceptions}.py`, both provider storage
  adapters, and `shared/raes/object_source.py`;
- Django configuration, environment manifest, provider renderers, Terraform
  variables/IAM, AWS SSM/user-data/redeploy, and GCP Kubernetes runtime binding;
- `ctf/models/{event,challenge,flag,hint,taxonomy}.py`,
  `ctf/services/{event,challenge,hint,audit}.py`, `ctf/exceptions.py`, and the
  public `ctf.services` facade;
- CTF organizer permissions, scopes, serializers/views, and shared error
  envelopes only if an explicit hydration endpoint is selected;
- `ctf/bridges.py`, `.importlinter`, and
  `scripts/check_layer_imports/layer_imports.yaml`;
- operator and technical documentation for publication, reference binding,
  timing, audit evidence, failure recovery, and future resolver migration; and
- unit contract/config tests, provider-neutral resolver tests, service/API
  tests, negative-security tests, and real PostgreSQL transaction/concurrency
  tests for rollback, edit/lifecycle races, retry, drift, and activation.

Repository fixtures and examples must use neutral ids, keys, endpoints, and
non-operational flag values. Scenario names, credentials, private
object coordinates, and real validator endpoints remain in deployment
configuration or private artifacts.

## Gotchas And Anti-Patterns

- Do not add CTF challenge content to `CTFScenarioTemplate.flags`. Those are
  range/DSL declarations, not native CTF scoring validators.
- Do not use `cms.scenarios.hydrator` for native challenge rows or call this
  operation generic "scenario hydration" without the CTF event-content
  qualifier.
- Do not store the reference or body in `Scenario.definition`,
  `RaesPackageSource.provenance`, event `range_config`, an audit row, or a
  general JSON blob.
- Do not use `ctf.services.transfer`, CTFd format sniffing, per-entry
  transactions, partial success, or direct ORM bulk creation that bypasses CTF
  policy.
- Do not accept organizer/request-supplied bucket, prefix, URL, digest override,
  filesystem path, credentials, or validator code.
- Do not make every registered extension or named validator package-usable.
- Do not hold database locks during network reads or expose content before the
  receipt and strict audit commit.
- Do not implement idempotency as query-then-skip, silently overwrite drift,
  merge with foreign content, or claim equality from scenario id alone.
- Do not add a second exception hierarchy, audit writer, storage client,
  configuration parser, package catalog, or plugin registry.
- Do not log exception strings from storage/parser/validator layers when they
  may contain keys, endpoints, headers, or payload snippets.
- Do not place private content or reference metadata in command argv, public
  deployment output, repo fixtures, screenshots, or examples.

## Non-Goals

CTF-1405 does not include acquisition, licensing, subscription, entitlement,
marketplace/registry clients, upload/publication APIs, signing infrastructure,
or storage credentials. It does not redesign RAES package registration,
scenario launchability, range hydration/provisioning, supporting-asset
orchestration (CTF-909/#623), signed-receipt participant/range binding (#1906),
CTFd synchronization, event replacement/upgrade, plugin installation/lifecycle,
new validator execution engines, or participant access to object storage.

The architecture/documentation gate for this note is:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```
