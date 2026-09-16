# Provisioner Subnet Coordination Preflight (#1838)

Status: pre-implementation guidance

Date: 2026-07-27

Issue: GitHub #1838, phase 6 of #478

This note narrows ADR-043-R6 for subnet/CIDR reservation. It fixes the
coordination and security boundary; it is not an implementation plan.

## Decision

Subnet reservation remains synchronous and PostgreSQL-serialized, but direct
provisioner access to `engine_subnetallocation` is replaced by a small,
closed, versioned Engine-owned PostgreSQL coordination RPC. The standalone
provisioner invokes that RPC over its existing psycopg/TLS/IAM connection.
Engine callers use an Engine service facade over the same coordination
contract. There is one reservation policy and one persistence path.

This is the narrow exception ADR-043-R1 permits. It is not a generic stored
procedure API, repository, query language, patch surface, HTTP endpoint, or
second operation-result workflow. The RPC surface supports only:

- reserve a bounded set of CIDRs for the current provision operation;
- read the current Range's existing ordered reservation result for
  provision retry or destroy;
- idempotently release that Range's owned reservations from the current
  provision-compensation or destroy operation; and
- reconcile a bounded provider-network CIDR observation while reserving.

The reservation request is anchored to the existing `operation_id` and
`request_id`. The Engine-owned implementation resolves the current Range and
generation server-side; a caller-supplied integer `range_id`, owner, status,
table name, column name, or arbitrary predicate is never authority.

## Serialization And Persistence Invariants

- Reservation still executes under
  `LOCK TABLE engine_subnetallocation IN EXCLUSIVE MODE` in the same database
  transaction that reconciles observed cloud CIDRs, selects candidates, and
  inserts all requested reservations. There is no advisory-lock, row-lock,
  optimistic-retry, or uniqueness-only substitute. Lock failure fails the
  operation.
- `SubnetAllocation` and its `unique_cidr_per_vpc` database constraint remain
  the durable occupied-set and final collision backstop. A reservation batch is
  all-or-nothing.
- The provider inventory observation is supplied through the existing
  provisioner `NetworkInventory` adapter. The coordination implementation
  revalidates it and merges drift rows while holding the table lock; malformed
  observations fail closed rather than being skipped.
- Provision retry is ownership-idempotent. The same current operation and request returns
  the same ordered CIDRs when its requested shape agrees. A changed network,
  count, prefix size, or logical subnet ordering is a conflict, not permission
  to leak a second batch.
- Drift-observed rows remain unowned occupancy evidence and cannot be released
  by a range cleanup. Release is scoped from the server-resolved operation and
  request, is idempotent, and happens only on the existing successful-destroy or
  failed-provision compensation paths.
- PostgreSQL is the semantics oracle. SQLite/unit tests may cover parsing and
  policy, but only the existing PostgreSQL lane can prove blocking,
  transaction rollback, uniqueness, effective privileges, and routine
  execution.

## Contract And State Ownership

The dependency-light coordination contract belongs under `shared`, beside
`shared.operation_envelope` and the other provisioner wire contracts. It uses
the existing `cyberscript.exceptions.ValidationError` boundary error rather
than adding an exception hierarchy. It is closed and bounded on:

- independent coordination contract version;
- canonical UUID `operation_id` and `request_id`;
- the existing `range` discriminator, or `raes-range` when that backend adapter
  must realize open network intent, plus the action-appropriate `provision` or
  `destroy` operation;
- provider-neutral network identifier and canonical IPv4 network;
- bounded requested subnet count and supported prefix lengths;
- bounded, canonical provider-observed CIDRs; and
- an ordered reservation result with logical subnet correlation and CIDRs.

`Range.range_config` remains authored/compiled intent. Reservation must not
update it or mutate the parsed authored object as scratch state. Compose an
operation-local realization value from the authored subnet order plus the
reservation result and pass that value to the existing Terraform/range-cell
builders. On destroy, reconstruct the same realization value from owned
allocations; do not "repair" `range_config`.

The synchronous reservation result is not an update to immutable
`OperationInput`, and it is not an `OperationResultInbox` lifecycle result.
Those are different contracts and workflows. Durable realized network state
continues to live in `SubnetAllocation` before mutation and in Engine subnet
state after provider realization. A later authoritative cyberscript provision
result may compose the same shared subnet-binding shape; phase 6 must not create
a second shape in anticipation of that cutover.

The extensibility seam is the provider-neutral request's ordered subnet
descriptors and prefix length, not AWS `vpc_id` naming, the current `"10.1"`
string prefix, or a hard-coded `/28` inside the coordination API. Current
Cyberscript ranges still request `/28`; retaining the parameter lets the
already-supported `/24` policy or another provider reuse the same boundary.

## Security And Cross-Cutting Layers

| Layer | Required treatment |
| --- | --- |
| User authorization | No new user-facing surface. CMS/Engine launch authorization remains authoritative. The RPC additionally resolves the persisted operation input/current Range generation and rejects missing, stale, wrong-request, wrong-resource, and non-provision identities before mutation. The provisioner workload identity is not tenant isolation. |
| Contract validation | Reuse `shared.operation_envelope` UUID/discriminator conventions and the persisted RangeSpec validators; add only the coordination-specific closed parser. Validate at the Engine producer/service edge, again in the provisioner before cloud access, and at the privileged database routine boundary. A dataclass, type hint, JSON value, or SQL cast is not validation. |
| Database security | Reuse `provisioner_db.get_db_connection`, provider DB-auth adapters, IAM/workload identity, and TLS. The role receives EXECUTE only on the exact coordination routines. Security-definer routines use fixed fully-qualified objects, a safe fixed `search_path`, no dynamic SQL, an owner that is not `provisioner_lambda`, and explicit `REVOKE ... FROM PUBLIC`. |
| Effective privileges | Forward migrations revoke all provisioner SELECT/INSERT/UPDATE/DELETE rights on `engine_subnetallocation`, sequence USAGE/SELECT, and UPDATE on `mission_control_range.range_config`. PostgreSQL tests use `has_table_privilege`, `has_sequence_privilege`, `has_column_privilege`, and executable positive/negative probes so inherited or PUBLIC grants cannot hide. Historical migrations remain untouched. |
| Secrets and environment | The contract is secret-free: UUID correlation, network identifiers, CIDRs, counts, and versions only. It adds no env var, token, URL, credential, or secret reference. Existing `engine.ecs._GCP_PROVISIONER_ENV_KEYS`, installation runtime inventories/renderers, `config/env-manifest.json`, and `shared.cloud.sensitive_env` therefore stay unchanged. Continue through `config.load_range_network_config`; do not add module-local env spellings or a production fallback for missing/invalid network identity/CIDR. |
| OS/process exposure | Add nothing to argv, child-process arguments, Terraform CLI `-var`, temporary files, or Kubernetes literal secret env. The existing request/operation UUID command correlation is sufficient; the reservation request/result travel over the database connection and as in-memory Terraform/range-cell inputs. |
| Errors | Provider inventory errors remain `CloudNetworkInventoryError`; contract failures use the shared validation error; the adapter maps database/routine failures once to fixed coordination reason codes. Reuse the existing bounded operation failure result and `shared.api.errors` if an error ever reaches a public response. SQL text, routine/table names, provider bodies, allocation lists, and raw exception strings must not reach Range error text, events, audit context, or API envelopes. |
| Logging and signals | Reuse provisioner ECS logging, `log_redact`, platform `shared.log_sanitize`, and the current provider exhaustion alarm. Log safe operation correlation, version, count, prefix size, disposition, wait/failure class, and drift count; do not log payloads, DB credentials/tokens, full provider responses, or raw exception bodies. Preserve an operator-visible release-failure signal so leaked reservations are actionable. |

## Canonical Incumbents

- Persistence and constraints: `engine.models.SubnetAllocation`,
  `unique_cidr_per_vpc`, Django `transaction.atomic`, and the existing
  PostgreSQL semantics lane.
- Coordination identity and fencing: `engine.launch_intents`,
  `ProvisionerLaunchIntent`, `OperationInput`, `Range.provisioner_operation_id`,
  `shared.operation_envelope`, and
  `provisioner_db_operation_input.get_operation_input`.
- Authored input validation: `shared.schemas.persistence`, Cyberscript
  `RangeSpec`/subnet schemas, and the operation-local input projection. Do not
  add a table-shaped subnet DTO or another authored range schema.
- Cloud observation and alerting: `cloud.types.NetworkInventory`,
  `cloud.{aws,gcp}.network`, `CloudNetworkInventoryError`, and the existing
  exhaustion-alarm adapter.
- Realization shaping: `terraform_vars`, `shared.range_cells`,
  `state_helpers._build_subnet_state`, and the existing validated provider
  output path. Compose CIDRs into a working realization value, not
  `range_config`.
- Connection/security posture: `provisioner_db.get_db_connection`,
  `cloud.{aws,gcp}.db_auth`, `engine.ecs._env`,
  `shared.cloud.sensitive_env`, installation runtime inventory/renderers, and
  provider deployment tests.
- Failure and observability: `shared.operation_results` reason codes and bounds,
  `terraform_ops` compensation, provisioner `log_redact`, platform
  `shared.log_sanitize`, and ECS formatters.
- Migration convention: forward-only role-aware revoke migrations and the
  effective-privilege tests established by Engine phases 4/5.

## Whole-Repo Surfaces In Scope

- Engine: allocation/subnet model and service facade, launch-operation
  identity, new coordination persistence boundary, migrations, admin/read
  consumers, and PostgreSQL service/migration tests.
- Provisioner: `components/network`, `range_subnet_allocation.py`,
  `terraform_ops.py`, `terraform_vars.py`, `config/_range.py`,
  `provisioner_db.py`, operation-input reader, provider network adapters,
  failure compensation, and their tests.
- Shared/runtime: the dependency-light coordination contract, operation
  envelope/results, RangeSpec persistence/schema validation, range-cell/state
  contracts, error/log sanitizers, the provisioner Docker copy boundary,
  import-linter rules, env inventories/renderers, and AWS/GCP task identities.
- Enforcement: ADR guard, migration drift check, provisioner/platform
  lint/type/unit suites, and real PostgreSQL serialization/effective-privilege
  tests.

## Gotchas And Anti-Patterns

- Do not replace the table lock with `select_for_update`, an advisory lock,
  `ON CONFLICT`, retry-on-`IntegrityError`, or a preflight "is free" query.
- Do not expose raw table DML, a caller-selected `range_id`, generic SQL,
  SECURITY INVOKER access backed by retained grants, or a broad
  security-definer function. PostgreSQL grants are part of the API.
- Do not create an internal HTTP callback, command queue, polling table,
  outbox/inbox result, broker request/reply flow, or second retry/DLQ vocabulary
  for this synchronous reservation.
- Do not duplicate CIDR generators, cloud inventory adapters, RangeSpec/subnet
  schemas, validators, status enums, failure codes, exception hierarchies,
  connection factories, or log sanitizers.
- Do not trust caller-provided ownership, accept a stale operation generation,
  fall back when operation identity is missing, silently reallocate on retry,
  release drift evidence, partially reserve a batch, or swallow release failure
  without an operator signal.
- Do not persist realized CIDRs into `range_config`, patch the immutable
  operation-input row after launch, or rely on positional mutation of the
  authored dict as durable state.
- Do not log the allocated CIDR list or pass it in argv merely because CIDRs
  are not credentials; it is infrastructure topology and unnecessary for
  correlation.
- Do not edit migrations 0018/0019 or Mission Control 0038. Add forward
  migrations and prove the final effective privilege posture.

## Non-Goals

- No public API, new authentication method, new network endpoint, broker,
  worker, generic workflow engine, repository framework, or cross-service ORM.
- No provider networking, Terraform/Pulumi state, range-cell, scenario DSL,
  authored RangeSpec, subnet lifecycle model, or cloud-IAM redesign.
- No conversion of the cyberscript provision/destroy result family from shadow
  to authoritative application; that residual ADR-043 cutover remains separate.
- No cleanup of unrelated provisioner domain-table grants or direct SQL beyond
  the allocation table and `range_config` capability named by #1838.
- No claim that a database function creates per-tenant isolation or removes the
  need for generation/ownership checks and least privilege.
