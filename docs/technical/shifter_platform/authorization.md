# OpenFGA authorization service

Issue #2315 introduces the S2 authorization model and administration surface. It does not perform the S8 cutover of existing protected application surfaces. Until that later slice, this service is exercised by the authorization administration API and conformance tests only; existing permission checks are not fallbacks for an OpenFGA denial.

## Ownership boundaries

- `shared.authorization` owns the closed action, target, principal, decision, predefined-policy and relationship contracts. No caller may provide a raw OpenFGA relation or object string.
- `config.openfga_authorization` is the only runtime SDK adapter. It owns transport configuration and converts provider failures into bounded fail-closed decisions.
- `workspaces.services` resolves SQL-owned principal identities and account/organization/workspace ancestry, applies delegation rules, and owns the durable mutation journal.
- OpenFGA is authoritative for group membership, policy assignment, direct grants, predefined administrator/operator assignment and explicit exclusions.
- PostgreSQL owns identities, resource ancestry, display metadata, caller-and-scope idempotency namespaces, operation outcomes and per-relationship serialization fences. It does not mirror effective permissions.

## Closed model

The model is generated from the action catalog and pinned to OpenFGA 1.20.0 and `openfga-sdk` 0.10.4. Its concrete types are `principal`, `group`, `role`, `installation`, `account`, `organization`, `workspace`, `event` and `range`.

Each action has one `grant_*`, `deny_*` and `can_*` relation. Administrative decisions include the explicit grant, administrator and installation-operator paths; non-administrative decisions include only the explicit grant. The internal non-delegable `delegate_authorization` action is reachable only through administrator/operator relations and proves that a native membership or role assignment cannot amplify descendant authority. Every decision subtracts its action denial and inherited exclusion paths. Account, organization, workspace and event administrators inherit only through explicit parent tuples. A resource cannot acquire authority from another account because its ancestry tuple is singular and SQL ancestry is re-resolved before mutation.

Groups and custom roles use native usersets (`group#member` and `role#assignee`). Every mutation writes through an immutable `authorization_binding` generation. The next generation permanently supersedes the prior binding, so a delayed earlier transaction remains inert even if it arrives after a confirmed revocation. Revocations publish the new binding through an exclusion relation; predefined administrator/operator revocation uses a policy-specific `deny_administrator` or `deny_operator` relation, so it cannot accidentally suppress an unrelated direct action grant.

The predefined catalog contains Application Administrator, Installation Operator, Account Administrator, Organization Administrator, Workspace Administrator and Event Administrator policies, each with a matching assignment-group identity. Human and service principals use the same `principal:<uuid>` model type and have identical action coverage. Application Administrator is defined by exact set equality with every catalog entry marked administrative.

## Supported SDK operations

The runtime adapter permits only:

| Operation | Runtime behavior |
| --- | --- |
| `check` | Pinned model, concrete object and `HIGHER_CONSISTENCY`; false or any exception denies. |
| `batch_check` | Correlation IDs are mandatory, unique and complete; a missing, duplicate or errored item fails the whole batch closed. |
| `write` | One append-only transactional request containing the generation candidate, effective relation and prior-generation supersession; duplicate writes are idempotent and SDK retries are disabled. |
| `read` | Exact reads of every generation-bound write tuple with `HIGHER_CONSISTENCY`, used only to confirm or reconcile a durable mutation. |
| `read_changes` | Bounded diagnostic metadata only; tuple payloads never cross the provider port. |

Before single or batch evaluation, the adapter reads the bounded parent relations and requires an exact match with the caller's SQL-resolved scope. Missing, extra, or stale parent links deny, even if a direct permission would otherwise allow the action. These reads validate structure; OpenFGA still evaluates all permissions. The runtime adapter has no create-store, write-model or migration method. `python manage.py render_openfga_model` emits the pinned DSL for a separately controlled deployment-admin workflow.

## Durable write protocol

1. Resolve the active actor, subject and exact SQL ancestry again at execution time. Each descendant check carries that descendant's own scope; leaf mutations must appear in the owning domain's bounded SQL inventory.
2. Validate the credential ceiling and check delegation action-by-action. Self-add, unknown subjects, cross-scope metadata and incomplete evaluator results deny before external I/O.
3. Lock the stable relationship fence in PostgreSQL and record a `requested` operation plus audit event, including the immutable provider store/model binding. Recovery refuses a different store or model.
4. Commit SQL, then issue one append-only OpenFGA transaction for that fence generation. SQL locks are never held across network I/O.
5. Read every exact generation tuple from the primary-backed API. Matching state records `confirmed`; a transport failure or mismatch records `unresolved` and leaves the fence blocked.
6. Redelivery and the explicit CSRF-protected operation-reconciliation `POST` lease and recover both `requested` and `unresolved` operations. Status `GET` requests are observational and never write. Recovery performs the exact read first and, when needed, safely replays the idempotent generation write before readback. An expired lease is reclaimable after process loss. Conflicting edits remain blocked until the ambiguous operation is confirmed. Because a newer generation permanently supersedes its predecessor in OpenFGA, an older timed-out write that arrives later cannot revive access.

Pre-provider validation failures record `denied`. The operation journal persists trusted request attribution independently from the mutated principal, so requested, confirmed, denied and unresolved audit events retain the initiating session or API-token actor plus request metadata without recording provider responses, tokens or raw tuples.

## API and UI

The workspace administration API exposes closed endpoints for action and predefined catalogs, scoped group/policy metadata, group membership, custom-policy assignment, policy actions, direct actions, predefined administrator assignment and bounded operation status. Public UUIDs are used throughout. Sessions remain CSRF protected; API tokens receive exact per-action scopes that form a non-amplifiable credential ceiling.

Explicit reconciliation rechecks the caller's current authority and credential ceiling for every action the recorded operation can replay. A credential that can view operation status cannot use recovery to issue an otherwise forbidden grant.

The Administer surface uses the common client and TanStack Query. Mutations do not retry automatically. Requested and unresolved results use bounded observational status polling and expose an explicit **Reconcile status** action, which performs the protected reconciliation mutation and displays the eventual terminal state rather than treating a response snapshot as proof.

## Verification

Fast tests cover catalog/model drift, invalid contracts, SDK failures, escalation attempts, operation states and API bounds. `scripts/run_openfga_integration.sh` starts digest-pinned OpenFGA 1.20.0 and PostgreSQL containers with TLS and preshared authentication, publishes the generated model, and runs the released-server suite against the real SDK. The blocking `shifter-platform-openfga` quality job invokes that harness for platform changes and fails if required integration configuration is absent. The suite covers direct, group, custom-role and scoped predefined usersets, inheritance, human/service parity, deny precedence, TLS/auth failure, native transactional tuple writes, PostgreSQL fencing, concurrent idempotency-key contention, concurrent revoke-versus-mutate, indeterminate writes and monotonic revocation.
