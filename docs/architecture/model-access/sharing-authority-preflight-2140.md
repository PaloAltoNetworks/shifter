# Sharing membership and authority preflight — #2140 / M20

Inspected repository baseline: `43e6b79fc44812fe22f6b8283f7274404e7ccbd7`,
2026-09-14. This note specializes [ADR-060](../../adr/060-model-access-allocation-accounting.md),
the [sharing contract](sharing.md), the [architecture](architecture.md), and the
[security design](security.md) for M20. It is architecture guidance, not an
implementation plan or evidence that the capability is complete. No runtime
behavior is added by this preflight.

## M20 implementation evidence (2026-09-14)

Issue #2140 implements this preflight without changing the installation catalog
or introducing another HTTP surface. The closed authority contract and neutral
invalidation port live in `shared.model_access`. Engine persists owner-qualified
selector, subject, publisher and funded-eligibility evidence behind monotonic
PostgreSQL fences. The composition root resolves bounded unions and performs
owner resolution, projection and binding publication in one transaction.

The owner adapters are deliberately separate: CMS correlates canonical Engine
range UUIDs and CMS request instances; CTF owns event, team, cohort, participant
and explicit-spare membership; Management owns user/group/operator and funded
group eligibility; Workspaces owns workspace/organization publication authority
and containment. CTF reaches Engine only through `ctf.bridges -> cms.services ->
engine.services`; isolated Management and Workspaces code emits the closed
command through `shared.model_access.authority_port`.

Mutation fencing covers canonical Engine range creation/status/owner/workspace
changes, identity disable/delete and group M2M/delete/bulk changes, workspace
membership/lifecycle/ownership and organization-admin changes, and CTF
participant/team/cohort/event/staff/spare/range-attachment changes. Owner rows
are the first lock; the shared fence is the second. Bulk invalidations are
chunked to the contract bound. Strict sharing audit writes remain inside the
same transaction, so audit or binding-publication failure rolls the projection
back and a retry reassesses from owner state.

Evidence is exercised by the owner contract suites plus
`tests/engine/services/test_model_access_authority_postgres.py`, which uses real
PostgreSQL row contention for removal/projection serialization and covers bulk
invalidation, canonical owner transfer, failed publication rollback and retry.
Later allocation/grant work still owns consumption of this fence; this evidence
does not mark all of PLAT-202 complete.

M19 established the Engine-owned sharing records and publication facade. M20
must connect them to the repositories that actually own ranges, CTF membership,
identity, workspaces, organizations, and publisher authority. It must not turn
Engine into a second owner of those facts or create another range/IAM lifecycle.

## Existing gaps that constrain M20

| Current repository fact | Required consequence |
| --- | --- |
| `shared.model_access` already owns closed selectors, `OwnedReference`, `SharingBinding`, policy compilation, canonical JSON and catalog validation. | Extend this contract boundary for projected evidence. Do not add a serializer-only, CMS-only, or Engine-private competing shape or another policy evaluator. |
| `engine.services._sharing_persistence.MembershipEvidence` is an Engine-local dataclass with a free-form state and `list[str]`; `publish_membership_projection()` overwrites evidence without a monotonic comparison. | Replace the loose seam with one closed shared projection contract. Validate state, complete typed member references, bounds, times and revisions before persistence. A lower revision rejects; an identical replay is idempotent; conflicting content at the same revision rejects. |
| Effective-policy matching compares only `OwnedReference.reference` to a string member list. | Membership identity is the complete owner-qualified reference. Never discard the owner namespace or infer type by splitting a display string. |
| `publish_sharing_binding()` and `drain_sharing_binding()` structurally validate a supplied publisher identity but do not prove that actor's current authority over the complete collection. | Publisher identity, authority source and authority revision are server-derived evidence tied to the exact selector digest and deployment. Validation/preview is not such evidence. Publish and drain recheck the locked evidence. |
| Snapshot matching reads frozen members and the catalog digest but not a current authorization fence. | Snapshot freezes inclusion only. Every snapshot member must also pass the current subject-authorization fence; a removed, transferred, disabled or otherwise ineligible subject is denied immediately. |
| The existing fence is attached to one binding projection and drain advances it by iterating projections. | Large-group revocation needs a shared, synchronously checked authorization revision before bounded per-binding/per-member reassessment. The authoritative mutation must not synchronously walk every grant or depend on asynchronous fan-out for denial. |
| `SelectorKind.CTF_COHORT` is published, but the CTF domain has no persisted cohort identity or membership service. The existing `cohort_size` is capacity metadata only. | Do not alias a cohort to an event, team, bracket, label, query, or numeric capacity declaration. Cohort publication remains fail-closed until CTF owns a stable cohort/member contract with unambiguous event and spare semantics; if its selector shape changes, version and republish the shared contract rather than guessing. |

The existing application-level `choices` and JSON fields are not sufficient
persistence guards. Closed states/modes/affinities need database check
constraints where they are persisted, revisions must remain positive and
monotonic, and canonical member sets must be sorted, unique and bounded before
they enter JSON storage.

## Keep the authority concepts separate

The following facts may change together, but they are not interchangeable:

- **Selector membership** says which logical range/draw references a collection
  includes. Snapshot and dynamic mode apply only to this fact.
- **Subject authorization** says whether an included range/user still has live
  authority to receive model access. Snapshot mode never freezes it.
- **Publisher authority** says whether the actor controls the complete selected
  collection and may publish or drain the binding. Membership in the collection
  grants no publication right.
- **Spending eligibility** is an independently approved fact. An ordinary or
  self-service Django group membership may make a range applicable, but cannot
  activate funded model access by itself.

Likewise, stable object identity, immutable binding definition revision,
selector membership revision, shared authorization/fence revision, spending-
eligibility revision, routing revision, catalog digest, range execution
generation, and grant epoch keep separate columns and names. A change in one
must not reset or impersonate another.

## Authoritative resolution matrix

| Selector | Canonical owner and source | Boundary rule |
| --- | --- | --- |
| `selected_ranges` | CMS/Engine's actual request-to-range binding and the Engine range public UUID; a pre-realization CTF selection uses the existing stable participant/spare draw UUID. | Resolve the submitted IDs to canonical owner-qualified references under the actor's real scope. CMS integer primary keys, names, scenario labels and range status are not identities. |
| `ctf_event` | `CTFEvent`, live `CTFParticipant` rows and `CTFSpareRange`, with actual participant/spare-to-CMS range bindings. | CTF owns event membership and spare inclusion; CMS owns realized range binding. Preserve that split through `ctf.bridges -> cms.services -> engine.services`. Event authority comes from `ctf.services.authorization`, not organizer group membership alone. |
| `ctf_team` | Event-native `CTFTeam` and its live participants, then their actual range bindings. | Team name/invite code and cached score/status are not authority. Validate the team belongs to the selected event. `include_spares` needs an explicit CTF-owned meaning; it cannot silently mean every event spare. |
| `ctf_cohort` | No canonical repository owner exists yet. | This is a contract gap, not permission to improvise. Define a stable CTF-owned identity/membership and spare rule or reject publication. |
| `user` | Canonical Django user ID plus actual current owner bindings in CMS/Engine across CTF and standalone use. | The launching operator, email, active-event profile and CTF participant row are not substitutes for canonical ownership. User inactivity is a separate deny-authoritative fence. |
| `auth_group` | Django auth-group primary key and direct persisted memberships, followed by each user's actual owned ranges. | Names and identity-provider claim strings are not identities; no transitive groups. Use the existing group reconciliation only to reach canonical Django membership. Require separate spending eligibility for self-service membership. |
| `workspace` | Workspaces owns the public workspace UUID and publisher authority; CMS/Engine scalar `workspace_id` range bindings own collection membership. | A workspace collection means ranges actually bound to that workspace, not every range owned by a workspace member. Never pass a Workspaces ORM object across the boundary. |
| `organization` | Workspaces owns organization UUID/admin authority and workspace containment; actual ranges come from CMS/Engine workspace bindings. | Organization membership is not workspace membership. Include ranges bound to the organization's workspaces, not arbitrary ranges owned by organization users. |
| `named_collection` | Engine owns the named definition; each atomic selector remains resolved and authorized by its owner. | Set union grants no new authority. The publisher must control every atom; one unavailable or unauthorized atom denies the whole publication. No recursive collections. |
| `all_ranges` | Engine deployment inventory, bounded by the catalog deployment ID. | Active platform-operator authority only, never `is_staff`, a group, workspace role, or CTF event delegation. Centralize the active/non-temporary superuser predicate through `management.services`; do not copy the CTF-specific precedent into every caller. |

Future eligible members of a dynamic collection enter only after fresh owner
projection and normal policy/capacity admission. A membership write alone never
mints a grant. Empty, deleted, unknown, foreign-deployment and stale sources deny;
an empty set never widens to all ranges.

## Transaction and dependency boundary

The security mutation invariant is: lock the authoritative owner row, recheck
authority, apply the owner change, synchronously advance/persist the minimal
Engine fence projection, write the strict audit event, and commit one database
transaction. Optional bounded reassessment may follow commit, but request and
refresh admission already reject the prior revision. Lock owner mutexes first
and Engine fence/projection rows second, in sorted stable-ID order for bulk
operations.

Reuse the repository's permitted dependency paths:

- CTF membership/event/spare changes go through `ctf.bridges`, then the public
  `cms.services` facade, then `engine.services`. Do not import Engine from CTF or
  add an Engine callback into CTF.
- CMS range owner/workspace/lifecycle services already have a permitted public
  Engine edge. Publish the fence inside their existing atomic owner/rebind
  transaction; do not add a second range mutation.
- `workspaces` and `management` are deliberately isolated from Engine by
  `.importlinter` and `scripts/check_layer_imports/layer_imports.yaml`. Their
  synchronous projection uses a narrow neutral command port under `shared`,
  with one Engine adapter bound at startup. Follow `shared.audit.port` and
  `shared.workspace_invitation_handoff` semantics: one typed command, one
  binding, idempotent same binding, conflicting/missing binding fails closed.
  This is not a general event bus or a repository callback API.
- Engine persists projections and evaluates already-authorized inputs. It never
  queries or imports CTF, CMS, Workspaces, or identity models at request time.
  Keep `shared.model_access.effective_policy` pure and repository-free.

The projection call is mandatory and rollback-coupled when a live policy can be
affected. Do not use `transaction.on_commit`, a signal-only implementation,
best-effort logging, an outbox, Celery/RQ, or a remote broker call as the
revocation fence. A globally disabled feature may use an explicit bound no-op;
a missing adapter or projection while live policy exists is unavailable/denied,
not silently ignored.

### Mutation coverage is a contract

| Owner | Mutations that must share the fence transaction |
| --- | --- |
| CTF | Participant add/delete/status/event/team changes; `create_team`, `join_team`, `leave_team`, `remove_member`, `disband_team`; event delete; event staff add/revoke/role and owner transfer; spare create/status/consume/cleanup/recovery and participant range attachment. The duplicate legacy team-join write in `ctf/views/participant.py`, CTF admin participant/team/event inlines, and queryset bulk updates must be routed through the owner service or made non-mutating. |
| Identity | `management.lifecycle.transition_account`, `management.services.mark_user_deleted`, active/superuser changes, Django user/group admin edits, `config.user_type_sync`, `config.organizer_authority`, forward and reverse group add/remove/clear, group deletion, and supported bulk/API updates. `m2m_changed` does not cover every queryset update or cascade, and `post_clear` lacks the removed member set; invalidate the shared group revision rather than relying on per-member callbacks. |
| Workspaces/organizations | Membership add/invitation acceptance/role/remove/leave, workspace ownership transfer including `_admin_transfer`, archive/restore/delete, organization-admin membership changes and workspace containment changes. Workspace member changes affect publisher authority; actual workspace selector membership still comes from range bindings. |
| CMS/ranges | Range creation/admission, deletion, owner reassignment and optional rehome in `_range_reassign`, workspace rebind in `_range_workspace_admin`, and every CTF participant/spare attachment or transfer. Preserve the existing CMS Request/RangeInstance/Engine Range consistency checks. |
| Engine sharing | Binding publish/edit/drain, selector replacement and projection refresh. Definition edits use the definition CAS; owner evidence uses its own monotonic revisions. Preserve pool/account/liability references when a member or binding leaves. |

Model signals may provide defense-in-depth for unavoidable Django admin M2M
paths, but they are not the primary service boundary. `QuerySet.update()`, bulk
operations and cascades bypass common signal assumptions. Every supported write
surface must either call the same owning service or be deliberately read-only.

## Cross-cutting gates

| Layer and incumbent | Required satisfaction |
| --- | --- |
| HTTP authentication and authorization | Preserve the bearer-first `ApiTokenAuthentication`/`SessionAuthentication` chain, CSRF-protected sessions, exact scopes from `shared.api_tokens.scopes`, and owner-domain permission classes. CTF publication reuses `ctf.services.authorization.resolve_event_authority`; workspace/organization authority stays in `workspaces.services`; deployment-all is operator-only. If M20 exposes no HTTP surface, do not create one merely to move projections. |
| Request and contract shape | DRF serializers shape HTTP only; owner services revalidate. Shared projection data uses `shared.model_access.ClosedModel`, `OwnedReference`, closed enums, canonical sorting/deduplication, selector bounds, timezone-aware freshness and exact deployment/selector digests. Do not hand-edit a generated schema or publish live membership in the installation catalog. |
| Installation/runtime configuration | `shifter/installation/loader.py` and `model_access.py`, the published v1 schema, `shifter/shifter_platform/config/_model_access_settings.py`, and `shifter/shifter_platform/shared/model_access/runtime.py` remain the only catalog gates. M20 needs no new YAML block, environment variable, mount, Helm value or Terraform input: Engine database state is the live authority. |
| Persistence and admission | Reuse Engine service facades, transactions, row locks, immutable revisions, deployment scoping and the one effective-policy compiler. Persist source owner, full typed references and independent monotonic revisions; enforce closed values and uniqueness in PostgreSQL. M20 must expose and race-test one atomic checked-fence operation that rejects a stale request/refresh projection. Downstream grant/broker work owns wiring that operation into live allocation and transport, not a second fence implementation. |
| Secrets and OS exposure | Projection and audit payloads contain IDs, digests, states, revisions and bounded counts only. No provider credential, broker capability, prompt, email/roster, token or secret reference is needed. Add nothing to process argv, environment, metadata, Terraform state, Helm values, operation JSON, support bundles or guest files. Existing broker enrollment/secret handling remains unchanged. |
| Error envelopes | Reuse owner-domain errors (`CTFError`, workspace classified errors, `CMSError`) and `SharingError(EngineError)` with stable authored codes. API views map through `shared.api.errors.api_error_response`; never return `str(exc)`, ORM errors, selector rosters or backend responses. Missing versus foreign versus unauthorized resources remain an opaque denial; stale/conflict/unavailable are distinct safe classes only where the caller is already authorized. |
| Audit, logs and metrics | Use `shared.audit`, the existing `SHARING_PUBLISH`, `SHARING_DRAIN`, and `SHARING_MEMBERSHIP` vocabulary, trusted request attribution, and `strict=True` within security mutations. Use `shared.log_sanitize`; log only safe IDs/fingerprints, revisions, state and bounded counts. No raw member lists, emails, provider identifiers, prompts, response bodies or high-cardinality per-member metrics. Do not create another audit table or catch/swallow hierarchy. |

## Evidence and invariants

Real PostgreSQL transaction tests must race removal/disable/owner transfer/group
clear against projection refresh and request/grant admission. Follow the threaded
patterns in `shifter/shifter_platform/tests/cms/test_range_create_concurrency.py`,
`shifter/shifter_platform/tests/workspaces/test_quota_concurrency_postgres.py`,
and `shifter/shifter_platform/tests/ctf/test_content_refresh_concurrency.py`;
an ordinary `pytest.mark.django_db(transaction=True)` test alone does not prove
the race.

Contract and service tests must cover lower-revision rejection, exact replay,
same-revision conflict, failed publication rollback/retry, stale/unknown/deleted
sources, selected and union bounds, snapshot removal, dynamic addition, group
clear/delete, and one user with two CTF events plus a standalone range. Prove an
event organizer cannot publish across another event, an ordinary group join
cannot activate funded access, all-ranges is operator-only, and revoking one
member does not rotate or disable the shared provider identity. Import-linter,
layer checker, migration/constraint tests and ADR guard remain mandatory.

## Extensibility and non-goals

The extension seam is one closed mapping from the existing `SelectorKind` to an
owner resolver, plus the shared projection contract. A future selector kind adds
a versioned contract member and one owner adapter; it does not add branches to
effective policy, provider routing, allocation, every mutation service, or a
generic group supertype. A future cloud, model, account or shard remains catalog/
provider data and does not change membership authority. Deployment ID stays
explicit on every projection so future tenant placement cannot accidentally
create a global fence.

M20 does not implement shard allocation, account/budget ledgers, grant issuance
or grant-epoch consumption, live broker wiring/transport proof, provider IAM,
credentials, scenario/RAES fields, capacity planning, management UI, a general
workflow/event system, or multi-cloud qualification. Those remain with their
existing work packages. The checked-fence contract and concurrency proof are in
scope even though later allocation/grant work consumes them. M20 does not rotate
a shared provider credential on membership loss, erase prior spend/liability,
grant access from a label/name/provider claim, make workspace membership imply
access to another member's range, or declare PLAT-202 complete.
