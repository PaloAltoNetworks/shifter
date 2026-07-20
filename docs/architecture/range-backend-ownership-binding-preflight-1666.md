# Range Backend Ownership Binding Preflight

Issue: GitHub #1666, "Bind admitted range backend/purpose to Engine operation
state for destroy-after-selector-flip."

This is requirement-free pre-implementation guidance. The issue title, body,
and acceptance criteria are the shipping contract. This note does not implement
the change and is not an implementation plan.

ADR-030 already owns live-fire admission and ADR-039 already requires backend
identity in the range-operation context, convergent destroy, immutable operation
generations, and retained cleanup evidence. No new ADR is needed. This note
specializes those decisions for the existing CMS -> Engine -> provisioner path.

## Decision Boundary

`GCP_RANGE_BACKEND` answers which GCP backend the deployment would admit for a
*new* launch. It is not durable resource ownership. Once CMS admits a provision,
the resulting backend and trusted `InstantiationPurpose` become immutable
Engine-owned facts for that range. Provision, provision-failure compensation,
destroy, repeated destroy, and any re-drive of those operations use those facts;
they do not reselect from the process environment.

The binding is platform admission/ownership metadata. It is not scenario intent,
ACES semantics, product provenance, deployment tier, or public lifecycle state.
It therefore does not belong in `RangeSpec`, `RequestSpec`, the ACES
`ProvisioningPlan`, scenario YAML, `RangeSource`, `ENVIRONMENT`, public API DTOs,
events, or provider output/state JSON.

## Architecture Decisions And Guardrails

- Make the existing CMS live-fire gate return its canonical
  `BackendAdmission` result instead of discarding it. Pass that trusted result
  beside, never inside, the legacy `RequestSpec` and ACES compiled plan. The
  legacy Engine create service and `CmsAcesDispatchPort` are the two handoff
  seams. A direct GCP Engine create call without an admitted binding must fail
  closed; Engine must not silently re-read the selector to manufacture one.
- Persist only the normalized backend and `InstantiationPurpose` as scalar,
  non-secret fields on the Engine `Range`, in the same transaction that creates
  that range and before a launch intent can be enqueued. Keep them nullable for
  pre-migration and non-GCP rows, use values from
  `shared.range_instantiation_policy`, and reject unknown values. Do not store
  the full `BackendAdmission`, its message, or another JSON envelope.
- Treat the fields as write-once ownership. Idempotent create with the same
  request must verify the same binding; a different binding is an ADR-039
  `conflict`, not an update. Status transitions, dispatch failure, operation-
  generation rotation, destroy success, and soft deletion never clear or
  rewrite ownership.
- Reuse `Range.provisioner_operation_id` plus `ProvisionerLaunchIntent` as the
  operation-generation and delivery identity. Do not duplicate backend/purpose
  in launch-intent JSON. The intent already authorizes a canonical command
  against the current locked `Range`; the immutable Range binding supplies the
  lifecycle adapter context.
- The standalone provisioner already resolves `--request-id` through
  `provisioner_db.get_range_data_by_request_id()` (and the ACES counterpart).
  Extend that single read projection with the scalar binding and pass it
  explicitly through `terraform_ops`, `terraform_vars`, and
  `range_terraform_runner`. Backend-sensitive variable/config helpers must
  accept the bound backend; a downstream `is_gce_range_cell_backend()` or
  `get_gcp_range_backend()` call during destroy would reintroduce the bug one
  layer lower.
- Capture the resolved binding once at operation start and reuse it for the
  provision-failure cleanup in `_attempt_terraform_auto_cleanup`. Do not
  resolve again after a failure. `destroy` must not rerun live-fire admission:
  a historical `gdc` + `live_fire` pair is denied for new provision but remains
  authorized for ownership-scoped cleanup.
- Keep the existing structured provisioner commands unchanged. The preferred
  transport is the request-scoped DB read, so no backend/purpose enters argv,
  Job env, the runtime ConfigMap, or a per-Job Secret. This avoids creating a
  second selector and avoids the impossible requirement that a persisted
  `gdc` owner equal a deploy-wide ConfigMap whose selector is now `gce`.
- Keep `GCP_RANGE_BACKEND` in the Job only as existing deployment configuration
  for new-provision validation and backend-specific settings compatibility. It
  must not control a bound destroy. If implementation changes the Job env shape
  despite this design, it must update `_GCP_PROVISIONER_ENV_KEYS`,
  `sensitive_env`, runtime-inventory/renderer parity, both admission manifests,
  ConfigMap equality rules, and structural tests together; a per-operation
  value must not be falsely validated as equal to the deploy selector.
- Legacy NULL bindings are compatibility state, not permission to use the
  current selector. Resolve them only from durable, ownership-proven evidence
  or an explicit operator backfill while the historical selector is known,
  then persist the backend under a row lock before dispatch. Existing
  `engine_instance.state` provider/asset discriminants and request-owned
  provider labels are evidence; names alone, scenario shape, current env, and
  successful VM boot are not. Ambiguous or evidence-free rows fail with an
  authored `prerequisite` diagnostic and retain cleanup state for explicit
  repair.
- A schema migration must therefore remain deployable with legacy rows present;
  it must not blindly label every old row `gdc` or `gce`. Rollout must establish
  the binding for active legacy rows before the selector changes. Partial-create
  rows with no provider output need that explicit pre-flip backfill because no
  later code can infer lost historical configuration honestly.
- Keep notification events provider-neutral and ID/status-only. Backend and
  purpose may be logged as closed public enum values with request/range
  correlation, but range specs, provider inventories, kubeconfigs, credentials,
  ConfigMap bodies, and raw exceptions remain prohibited.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Product auth and ownership | Mission Control DRF permissions, CTF organizer/participant gates, `ctf.bridges.cms_create_range`, CMS destroy ownership checks | Do not expose a new backend/purpose input. Existing user and range ownership gates remain first. |
| New-range admission | `cms.services.create_range_dispatch`, `_assert_live_fire_backend_admitted`, `shared.range_instantiation_policy.BackendAdmission` / `InstantiationPurpose` | Preserve one policy evaluation shared by legacy and ACES creation and carry its result forward; do not parse `gce`/`gdc` again. |
| Realization schemas | `RequestSpec` / `RangeSpec`, persisted-spec envelopes, ACES `ProvisioningPlan`, `shared.range_cells` | Keep platform ownership adjacent to these artifacts, never embedded in them and never represented by another topology DTO. |
| Engine ownership/state | `engine.models.Range`, `engine.services._range`, `engine.services._aces_range`, Django migrations | Store one write-once scalar binding on the authoritative range row before dispatch. Do not add a per-provider repository or operation table. |
| Operation delivery and replay | `engine.launch_intents`, `Range.provisioner_operation_id`, `ProvisionerLaunchIntent`, `engine.ecs`, launch-outbox worker | Preserve canonical command validation, range authorization, generation fencing, idempotent Job identity, and sanitized retry state. |
| Provisioner read boundary | `provisioner_db.get_range_data_by_request_id`, `get_aces_range_data_by_request_id` | Extend the incumbent request-scoped projection; do not add another DB JSON document or query path. This is still subject to #478's later direct-SQL replacement. |
| Range lifecycle routing | `terraform_ops`, `terraform_vars.build_range_variables`, `range_terraform_runner`, `aces_range_ops` | Pass the bound backend explicitly through the existing lifecycle path and keep GDC/GCE resource modules private behind it. |
| Cleanup/state | `SubnetAllocation`, `state_helpers`, GDC ownership labels, GCE range-cell ownership contracts, Terraform state cleanup | Keep recovery evidence and the backend binding until resource absence is observed. Repeated absence is success; shared resources are not deleted. |
| Events/reconciliation | `RangeEventOutbox`, `drain_range_event_outbox`, Engine handlers, `reconcile_range_events` | Keep binding out of events. Re-drives read the unchanged Engine binding; projection reconciliation must not rewrite it. |
| Errors | ADR-039 codes, provisioner/shared `CloudError`, `CMSError.details`, CTF error mapping, `shared.api.errors` | Missing/corrupt binding is `prerequisite`; generation/binding mismatch is `conflict`; denied new provision remains `identity-or-policy`. Use authored bounded messages, not raw exception strings. |
| Logs and secrets | `shared.log_sanitize`, provisioner `log_redact`, provider secret stores, ephemeral Job Secret handling | Log enum decisions and safe correlation only. No secret value or config blob enters scalar fields, JSON, argv, events, or logs. |
| Job/runtime policy | `GCPTaskRunner`, `shared.cloud.sensitive_env`, both `restrict-provisioner-jobs` policies and structural parity tests | Preserve pinned image, grammar, env equality, launcher identity, non-root/read-only runtime, and Secret-backed sensitive env. No Job-contract change is needed for the chosen DB transport. |

## Cross-Cutting Security And Validation Layers

1. **HTTP/product authorization.** Mission Control and CTF continue to
   authenticate the caller, derive `RangeSource`, and authorize ownership.
   Backend and purpose are never accepted from an HTTP body, query, form, flag,
   scenario, or participant-controlled callback.
2. **Scenario/plan shape.** CMS hydration and the canonical Pydantic persisted
   envelope validate legacy intent; the ACES runtime validates its serialized
   plan; `shared.range_cells` validates the closed GCE realization request.
   Ownership fields do not extend any of these schemas.
3. **Admission/config shape.** `evaluate_gcp_backend_admission()` remains the
   only new-provision policy and `normalize_gcp_range_backend()` the only
   selector parser. Engine accepts only its admitted normalized result. Destroy
   validates the persisted closed values but does not apply provision policy.
4. **Persistence and concurrency.** Range creation and binding commit together.
   Existing request idempotency verifies equality; launch-intent row locks and
   `provisioner_operation_id` fence stale generations. Legacy binding repair is
   also compare-and-set under a row lock.
5. **Process and OS exposure.** Container argv remains
   `range|aces-range <operation> --request-id <uuid>`. Binding arrives from the
   already-required DB connection, not argv, environment, a mounted file, or a
   config blob. Existing subprocess argv arrays, private temporary kubeconfigs,
   bounded workspaces, and cleanup rules remain in force.
6. **Kubernetes admission/runtime.** `GCPTaskRunner` still supplies the pinned
   image, canonical args/env, launcher identity, ephemeral sensitive-env Secret,
   four writable volumes, non-root/drop-ALL/read-only-root security context, and
   deterministic Job identity. Base and Helm admission policies stay
   equivalent. A needless env addition would have to pass all those validators.
7. **Secret handling.** Backend and purpose are public enum values. DB password
   and field-encryption material remain Secret-backed; `GDC_ACCESS_SECRET_ID`
   remains a reference and the kubeconfig value stays in Secret Manager and
   restrictive temporary files. No provider credentials, secret references,
   `range_config`, or state payload are copied into the binding or launch intent.
8. **Provider ownership.** GDC cleanup retains request/range labels and existing
   idempotent delete semantics; GCE cleanup retains the closed range-cell
   ownership contract. Compatibility discovery must prove installation/request
   ownership and must not delete from deterministic names alone.
9. **Error envelopes and observability.** Internal exceptions map once to the
   ADR-039 classification. Events and API/websocket errors receive fixed,
   bounded messages. Logs may record normalized backend, trusted purpose,
   operation, and stable code; raw Kubernetes/SDK stderr, provider payloads,
   database rows, and exception strings do not cross those boundaries.

## Extensibility Seam

The seam is the existing closed `(backend, InstantiationPurpose)` admission
result persisted on `Range` and supplied as an explicit parameter to the
existing lifecycle router. #1354 can add a trusted product/operator purpose by
extending the single purpose enum and policy mapping; the CMS caller supplies
that result through the same Engine handoff. It must not require scenario or
ACES schema changes, a new command, another event family, or booleans such as
`uses_gdc`, `unsafe_mode`, or `allow_legacy`.

Keep enough field width and helper signatures for another closed GCP backend
value, but do not implement ADR-039's future adapter factory or invent a generic
placement taxonomy here. Backend-specific config loaders should take the bound
backend/operation context explicitly so the next adapter does not require more
ambient selector reads.

## Whole-Repository Surfaces In Scope

- architecture/operator truth: ADR-030, ADR-039,
  `gdc-vm-runtime-live-fire-gate-preflight-1348.md`,
  `provider-neutral-range-substrate.md`, `gcp-range-cell-deploy.md`, and
  `gdc-provisioning.md`;
- product admission: CMS legacy and ACES create services/dispatch port, Mission
  Control endpoints, CTF participant/batch/spare/recovery callers, and internal
  management commands;
- Engine: `Range` and its migration, legacy/ACES create and destroy services,
  launch intents, ECS/GCP dispatch, operation-generation cleanup, status
  handlers, outbox, and CMS status reconciler;
- provisioner: CLI grammar, `provisioner_db`, `terraform_ops`, `terraform_vars`,
  `range_terraform_runner`, `aces_range_ops`, config/network loaders, GDC
  network/VM/Pod deletion, GCE range-cell deletion, subnet allocation, state
  cleanup, events, and redaction;
- config/runtime verification: `installation.runtime_inventory`, the published
  backend contract, `scripts/gcp/render_runtime_env.py`, Django env manifest,
  `_GCP_PROVISIONER_ENV_KEYS`, `sensitive_env`, `GCPTaskRunner`, and renderer /
  Django / provisioner parity tests. These remain unchanged under the preferred
  DB transport but are mandatory scope if an env key is introduced; and
- host enforcement: provisioner launcher RBAC, both admission-policy manifests,
  their base/Helm equivalence tests, Pod Security/runtime context, ephemeral
  Secrets, workload identity, and temporary kubeconfig handling.

## Gotchas And Anti-Patterns

- Do not pass the admitted result only as a second environment read; CMS gate
  and Engine persistence must use the same evaluated value or a selector flip
  can race between them.
- Do not route bound destroy, variable construction, state-prefix cleanup, ACES
  teardown, or compensation through `get_gcp_range_backend()` indirectly.
- Do not overwrite the deploy-wide `GCP_RANGE_BACKEND` per Job. Besides
  conflating selection with ownership, the value would fail the current
  ConfigMap-equality admission rule after the exact selector flip this issue
  must support.
- Do not trust a caller-supplied env purpose. A compromised launcher could pair
  `gdc` with `non_user_validation` and bypass the #1348 provision denial. The
  trusted value comes from the locked Engine row.
- Do not infer legacy ownership from `RangeSpec`, scenario id, `RangeSource`,
  environment tier, current selector, resource name alone, or which provider
  happens to answer first. Do not silently label ambiguous legacy rows.
- Do not reject GDC destroy because its historical purpose was live-fire. The
  policy denial prevents new mutation; cleanup of already-owned resources is
  mandatory containment hygiene.
- Do not clear the binding, subnet allocation, or adapter recovery evidence on
  a partial/unknown destroy. Existing auto-cleanup currently releases subnet
  allocations after its best-effort attempt; code touched here must not make a
  failed cleanup look complete or permit an allocation collision.
- Do not add backend/purpose to launch-intent JSON, Range state JSON, status
  events, audit state, error details, metrics labels, or logs containing a full
  config/state payload. Scalar Range columns are the authority.
- Do not add another backend enum/parser, validator, exception hierarchy,
  lifecycle service, repository, task command, event type, or GDC cleanup path.
- Do not modify immutable published-contract snapshots to accommodate a runtime
  key. If a later design genuinely adds one, use the canonical contract
  generation/versioning workflow.

## Non-Goals And Implementation Boundaries

- No code, migration, tests, runtime backfill, or implementation plan is part of
  this note.
- No change to the #1348 provision gate, its approved GCE live-fire backend, or
  the defense-in-depth GDC denial.
- No new approved containment model or relaxation of ADR-030.
- No design of BAS/demo/image/operator-validation product workflows; #1354 owns
  purpose expansion.
- No provider-neutral substrate refactor, new adapter factory, ACES cutover,
  RangeSpec/plan redesign, public lifecycle change, task-runner redesign, or
  event/reconciler redesign.
- No removal of GDC infrastructure or cleanup support, and no assumption that a
  selector flip removes the credentials/config needed to destroy retained GDC
  resources.
