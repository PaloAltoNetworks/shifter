# Provisioner Persistence Boundary — Phase 7 Preflight (#1839)

Status: pre-implementation guidance

Date: 2026-07-27

Issue: GitHub #1839, phase 7 of #478

This note narrows ADR-043-R1/R5/R7 and the earlier provisioner persistence
preflights to the residual-grant, effective-privilege, and event-binding
cleanup. It fixes the repository-wide boundary and proof posture; it is not an
implementation plan.

## Decision

Phase 7 is a least-privilege consolidation, not another persistence redesign.
Keep the surviving cyberscript provision/destroy writers exactly as a reviewed,
named allowlist until that path is removed; revoke everything else by forward
migration and prove the live effective privilege posture with PostgreSQL tests.

The provisioner is no longer a range-event publisher. Standard range events
remain ADR-025 notifications owned by the platform runtime: Engine state
mutation, audit intent, and `RangeEventOutbox` enqueue belong to the
platform-owned transaction, and only the outbox drainer publishes to SNS or
Pub/Sub. The provisioner runtime therefore must not retain an event-topic
binding, event-bus dependency, or environment contract that suggests it still
owns that side effect.

The phase-7 allowlist is closed and justified per surviving live writer. It is
not a temporary “skip failing rows” list and must not be widened merely because
the tree still contains direct SQL.

## Authoritative Boundary For This Phase

The only direct domain-table privileges `provisioner_lambda` may retain after
phase 7 are the ones required by the surviving cyberscript provision/destroy
path and the already-reviewed ADR-043-R6 coordination RPC execution rights:

- `engine_instance`: `SELECT`, `UPDATE`
- `engine_subnet`: `UPDATE`
- `engine_app`: `SELECT`
- `engine_request`: `SELECT`
- `engine_operation_input`: `SELECT`
- `engine_operation_result_inbox`: `INSERT`
- `mission_control_range`: `SELECT`, plus `UPDATE` only on the reviewed column
  allowlist
- the exact subnet-coordination routine `EXECUTE` grants from phase 6

For `mission_control_range`, only these `UPDATE` columns survive in this phase:

- `status`
- `error_message`
- `paused_at`
- `ready_at`
- `updated_at`
- `provisioned_instances`
- `vpn_access_binding`
- `ngfw_instance_id`
- `destroyed_at`
- `range_config` only if the live tree still proves a reviewed writer; absent
  that proof it stays revoked per phase 6

Everything else is denied, including:

- all `engine_range_event_outbox` table and sequence access;
- `engine_app` `UPDATE`;
- `engine_subnet` `SELECT`;
- all direct `engine_subnetallocation` access;
- stale Mission Control table reads for dropped or moved models; and
- every non-allowlisted `mission_control_range` column update.

The allowlist lives in the PostgreSQL effective-privilege suite as named
entries with writer justification. The migration only changes grants; the test
is the enforcing gate.

## Canonical Incumbents To Reuse

Use the existing repository incumbents. This issue should not invent any new
abstractions.

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Forward-only role/grant changes | `engine` / `mission_control` Django migrations, especially `0042`, `0043`, `0046`, `0047` patterns | Reconcile against the live catalog before issuing `REVOKE`; absent relations/columns must be skipped, not named optimistically. |
| Effective privilege proof | `tests/engine/services/test_provisioner_effective_privileges_postgres.py`, earlier PostgreSQL grant tests from phases 4/6 | Assert the exact live allowlist and explicit denials with `has_*_privilege` checks; SQL text in a migration is not evidence. |
| Surviving direct writers | `provisioner_db.py`, `provisioner_db_ngfw.py`, `ngfw_runtime.py`, subnet-coordination adapter | Verify the live tree against the allowlist before touching grants; do not trust historical issue text over code. |
| Operation boundary integration | `shared.operation_envelope`, `engine_operation_input`, `engine_operation_result_inbox`, `apply_operation_results` worker | Phase 7 does not change the operation boundary; it only removes leftover bypasses and proves the residual exception. |
| Range-event delivery | ADR-025, `RangeEventOutbox`, `drain_range_event_outbox`, `reconcile_range_events`, shared event payload/constants | Keep one event pipeline. Do not replace the removed provisioner publish path with another side channel. |
| Runtime env contract | `config/_env_manifest.py`, generated `config/env-manifest.json`, `installation.runtime_inventory`, `engine.ecs._GCP_PROVISIONER_ENV_KEYS`, `scripts/gcp/render_runtime_env.py`, Terraform task definition, Helm/base manifests, admission allowlists, parity tests | Remove provisioner-only stale env at every canonical surface. No module-local `os.environ` fallback or provider-only shadow list. |
| Secret/env classification | `shared.cloud.sensitive_env`, `tests/shared/cloud/test_sensitive_env.py`, `tests/shared/cloud/test_gcp_runtime_role_parity.py` | Event-topic identifiers are plain config, not secrets; removing them must still preserve classifier and forwarding-list parity. |
| Error/logging posture | `shared.errors`, `shared.api.errors`, provisioner `log_redact`, platform `shared.log_sanitize` | A privilege failure or env-shape mismatch must surface as an operator-visible failure without leaking SQL text, table names, or secrets into public envelopes. |

## Security And Cross-Cutting Layers

The intended design passes these layers:

1. **Launch authorization and domain policy.** No new user-facing surface is
   introduced. Existing CMS/Engine lifecycle authorization remains the only
   end-user policy gate. Grant revocation must not move authority into the
   provisioner or into payload-owned identifiers.
2. **Database authentication and least privilege.** Reuse
   `provisioner_db.get_db_connection`, provider DB-auth adapters, IAM/workload
   identity, and TLS. The principal keeps only the reviewed table privileges
   plus the narrow coordination `EXECUTE` rights. No new broad table grants, no
   historical migration edits, no temporary “rollout” widening.
3. **Privilege proof surface.** The security boundary is the live catalog, not
   authored SQL. Reuse PostgreSQL `has_table_privilege`,
   `has_column_privilege`, `has_sequence_privilege`, and
   `has_function_privilege` checks, plus any needed executable probes, so
   inherited or `PUBLIC` grants cannot hide.
4. **Runtime env shape.** Reuse the typed settings/env-manifest/runtime-inventory
   path. Removing the provisioner event binding means removing it from the
   provisioner forwarding contract and every renderer/manifest that feeds that
   contract. Do not leave a dead env key in one provider path “for symmetry”.
5. **OS/process exposure.** Provisioner argv remains the canonical resource,
   operation, and correlation ids only. Removing the event binding means no
   event-topic identifier should be passed in argv, child-process args,
   Terraform vars, temp files, or logs as a replacement.
6. **Error envelopes and logging.** Permission denials, missing grants, or env
   drift must fail closed and remain operator-visible, but they still must go
   through the existing bounded failure vocabulary and sanitizers. Do not leak
   relation names, SQL fragments, provider payloads, or secret refs into range
   error text, websocket/API envelopes, or normal logs.

## Maintainability And Whole-Repo Scope

The implementation must treat these as one cross-cutting change, not isolated
file edits:

- Django migration history in `engine/migrations` and `mission_control/migrations`
- PostgreSQL privilege tests under `tests/engine/services`
- provisioner direct-writer modules (`provisioner_db*`, `ngfw_runtime`, subnet
  coordination adapters)
- provisioner env forwarding contract in `engine.ecs._GCP_PROVISIONER_ENV_KEYS`
- installation/runtime inventory and parity backstops
- generated manifest flow: `config/_env_manifest.py` → `config/env-manifest.json`
- AWS task/runtime definitions and GCP runtime renderer/manifests/admission
  policy
- local-dev launcher shims only where they mirror the runtime contract rather
  than intentionally support a different contract

The repository already has dedicated parity tests for generated env keys,
forwarded provisioner env keys, and sensitive/plain env partitioning. Reuse
those existing backstops rather than adding a parallel validator.

## Extensibility Seam

The next expected change is the RAES/cyberscript cutover removing the surviving
direct writers. Phase 7 must therefore encode the residual privilege posture as
a small, named data seam:

- one closed table-privilege allowlist;
- one closed `mission_control_range` update-column allowlist; and
- one closed coordination-routine signature allowlist.

That seam belongs in the effective-privilege test, not scattered across
migrations, comments, and provider manifests. When the last direct writer goes
away, phase 8 should tighten the same allowlist artifact rather than rediscover
the posture from scratch.

Do not parameterize this into a generic grant framework, role matrix, or
dynamic schema walker. The seam is a reviewed allowlist for one principal.

## Gotchas And Anti-Patterns

- Do not broaden the allowlist to make the test green. If a writer outside the
  allowlist appears, either migrate that writer or bring back a reviewed
  justification.
- Do not replay historical grant SQL against the current schema. Earlier
  migrations granted tables and columns that later moved or disappeared.
- Do not treat table-level `UPDATE` visibility in `information_schema` as proof
  that every column is allowed; column-level checks remain authoritative for
  `mission_control_range`.
- Do not leave a stale event-topic env var in one runtime path after removing it
  from another. Manifest drift is a real boundary bug here.
- Do not replace the removed provisioner outbox/event path with direct SNS,
  Pub/Sub, or callback publishing from the provisioner.
- Do not create a second privilege test suite, a YAML grant registry, a generic
  repository wrapper, or another exception hierarchy for this issue.
- Do not weaken the existing sensitive-env or runtime-role parity tests to make
  config cleanup easier.
- Do not claim the provisioner is fully table-decoupled yet. This phase still
  contains an explicit, temporary direct-write exception for the surviving
  cyberscript path.

## Non-Goals

- No migration of the remaining cyberscript provision/destroy writers to the
  operation-result applier in this issue.
- No redesign of ADR-025 event delivery, worker topology, or alerting.
- No new authentication path, callback endpoint, queue, or public API.
- No provider IAM redesign, DB principal split, or per-tenant isolation claim.
- No cleanup of unrelated grants or runtime env keys outside the provisioner
  persistence boundary touched by this phase.
