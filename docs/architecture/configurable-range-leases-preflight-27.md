# Configurable range leases preflight (#27)

Status: pre-implementation guidance. Date: 2026-09-13.

Contract: the supplied title, body and acceptance criteria of
[issue #27](https://github.com/Brad-Edwards/shifter/issues/27). No Ground Control
requirement is attached. This note records boundaries and decisions, not an
implementation plan or a claim that configurable leases already ship.

Issue #2169's
[runtime lease-policy preflight](runtime-mission-control-lease-policy-preflight-2169.md)
supersedes this note's tenant-hierarchy non-goal and deploy-rollout-only policy
assumption. The typed deployment policy remains the fallback contract; #2169
defines its runtime tenant/group precedence and preserves the same generation,
extension, cleanup, and CTF boundaries.

## Decisions

**One deployment policy.** Use the existing root `shifter.yaml` contract with a
provider-neutral `settings.mission_control_leases` block. Its fields are
`initial_days`, `extension_days`, `maximum_days` (defaults 30, 30, 365), and
`extensions_enabled` (default true). Days are whole elapsed 24-hour periods;
deadlines are timezone-aware UTC instants, not calendar months or local dates.
The boolean answers the issue's extension-disable requirement without making
zero an allowed duration or disabling destruction.

Keep one small, immutable typed policy and its semantic validation under
`shared`, with installation and Django settings acting as boundary adapters.
Use the existing Pydantic dependency, not another settings framework. Follow
`installation.loader`'s shared-setting dispatch and
`config._warm_pool_settings`'s validated runtime binding. Publish the same shape
as a non-secret `MISSION_CONTROL_LEASE_POLICY_JSON` value; adapters serialize
and validate the canonical type, rather than maintain provider-specific models,
field defaults or arithmetic. No catalog, policy database, strategy registry,
digest protocol or separate settings service is needed for four scalar fields.

Validation rejects unknown fields, explicit nulls, non-object blocks, booleans
in integer fields, fractional/string durations, non-boolean switches, nonpositive
durations, and initial greater than maximum. Omitted fields use the canonical
defaults; an omitted env variable does too, while a present blank/malformed
value is an error. Increment greater than maximum is valid: an extension is
bounded by the remaining lifetime. Validate supported numeric/date bounds so
huge input cannot overflow `timedelta`, deadline addition, persistence or an
applicable credential encoder at launch. Bound extension arithmetic by remaining
time before addition; do not add an arbitrary 365-day product ceiling.

**A generation owns its lease.** In `cms.services._range_lease`, resolve the
effective policy once for a new user lease and persist its deadlines through the
existing launch transaction. Snapshot the extension increment on that generation
too: reading today's increment for an older generation would violate the issue's
new-generation rollout rule. The existing `RangeLease` already carries this
increment, but `RangeInstance` currently does not persist it. A small additive
generation field is sufficient; do not store another policy object in
`range_spec`, a new table, or Engine's provisioning envelope.

Existing Mission Control generations retain their old 30-day increment and
their exact stored deadlines. An upgrade can record that historical increment
without touching either deadline. Historical migration
`cms/migrations/0037_rangeinstance_lease.py` remains deterministic and unchanged;
never make it read current settings. Legacy rows with absent lease bounds keep
the existing unavailable projection and cannot acquire invented deadlines on
read. Ordinary ownership transfer, pause/resume and retries do not restart a
lifetime. CTF ranges, spares and recovery remain event-owned through
`CTFEvent.get_cleanup_time`, CTF bridges and `reconcile_ctf_range_leases`, including
its immutable maximum check; they do not inherit Mission Control increments.

**Disabling extensions is a live admission restriction.** The deployment switch
applies to subsequent extension attempts on all Mission Control generations
after process rollout, including old generations. This is distinct from the
three durations, which are generation snapshots. Both `can_extend` and the
locked mutation enforce the switch. Turning it off neither shortens deadlines
nor stops expiry; turning it on cannot revive expired generations or raise their
persisted maximum. Setting initial equal to maximum only prevents extensions
for new generations and is not a substitute for the switch.

**One lifecycle and one wire surface.** Retain `RangeLeaseProjection`,
`CurrentRangeView`, `ExtendRangeLeaseView`, `RangeLeaseSerializer` and the
`lifecycle` response. Its increment comes from the generation; its eligibility
also reflects the live restriction. Keep `extension_days` positive on the
Mission Control wire even when extensions are disabled. The existing SPA
`ActiveRangePanel` already renders the increment and obeys `can_extend`.
If launch-time policy display needs all three durations, expose an optional
policy projection on the existing current-range response, including its
no-range branch, from the same typed settings. Label this as the policy for
new leases, distinct from the active generation's bounds. Do not add a policy
endpoint or expose Django's full settings. Response DTOs document projections;
they do not become another policy validator.

## Whole-repository incumbents and gates

Paths below are repository-relative; platform module names refer to
`shifter/shifter_platform`.

| Layer | Canonical incumbent and required behavior |
| --- | --- |
| Installation shape and validation | `shifter/installation/schema.py`, `loader.py`, `settings_aws.py`, `settings_gcp.py`. Register the shared block in both normal loading and aggregated-error validation, strip it before each closed backend settings model, then normalize it with the same semantic type. Also account for `GcpBackendSettings.from_root_settings`'s filtering. Keep `extra="forbid"`; do not permit arbitrary settings to get one key through. |
| Packaging and published schemas | `shifter/installation/pyproject.toml`, `model_access.py`, `canonical_model_access`, `publication.py`, `published_contract/`; platform `Dockerfile` and package dependencies. The installer is independently packaged: a source-checkout import is insufficient. Reuse its existing packaging approach for a pure shared contract without importing Django or copying the model. Preserve generated-artifact freshness and append-only published snapshots (ADR-011-R8). Generated schema constraints and the semantic validator must agree; cross-field rules still require semantic validation. |
| AWS runtime producer | `scripts/bootstrap/aws_eks.py::_runtime_env` / `render_aws_values`, `installation.render`, `runtime_inventory_aws.py`, bundle generated-output classification. Render from validated root config, classify the policy as public portal/worker config, and reject competing overrides using the existing renderer-owned-key check. New AWS deployments use EKS. |
| GCP runtime producer | `scripts/gcp/render_runtime_env.py`, `scripts/bootstrap` deploy callers, `_gcp-dev.yml`, `installation.render`, `runtime_inventory_gcp.py`. Pass the validated root-derived policy into the existing env producer/caller path; it currently builds its output primarily from Terraform outputs and selected process env. Merely accepting a YAML key does not deliver it. Do not rebuild a provider-specific parser in the workflow. |
| Supported AWS compatibility surface | `scripts/portal-deploy/deploy_portal.sh`, `_shifter-platform.yml`, `platform/terraform/modules/portal/ssm/` and environment roots. Audit any supported ECS/ASG path that assembles runtime env separately and use the same policy projection there. Compatibility wiring must not become a second source of defaults or activate two control planes (ADR-044). |
| Helm and process rollout | `platform/charts/shifter/values.schema.json`, `templates/configmap-runtime.yaml`, `_helpers.tpl::shifter.runtimeConfigChecksum`, web/worker/scheduler templates. Env keys must fit the uppercase grammar; JSON must arrive as one quoted string, never a nested ConfigMap object. Existing checksums roll consuming pods. Include web, CMS launch workers, reconciler and CTF scheduler; no live reload or additional restart controller. |
| Django composition and env inventory | Split `config/*_settings.py`, `config/settings.py`, `_env_manifest.py`, `env-manifest.json`. Parse at settings import and raise `ImproperlyConfigured` with authored key/constraint diagnostics. Consume via `django.conf.settings`, not repeated `os.environ` reads or imported module constants in services. Regenerate the manifest; its AST extractor recognizes literal `os.environ.get` calls, not arbitrary helper indirection. |
| Import and service boundaries | `.importlinter`, ADR-001, public `cms.services` and CTF bridges. The shared policy has no Django, CMS, Engine or provider dependency. Config binds it without importing domain models; callers use public service boundaries rather than importing another app's model or private lease helper. |
| Authentication and authority | `MissionControlAPIView`, `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, `_range_write_permission`, `block_participant_lifecycle_permission`, `shared.api_tokens`, `cms.services._range_workspace`, `workspaces.services`. Preserve session CSRF, token scope/actor resolution, participant denial, owner filtering and `WorkspaceOperation.MANAGE_RANGE`, including reauthorization under the lock. CTF event authority and deployment-operator authority remain distinct. |
| Request and response shapes | `ExtendRangeLeaseView` rejects every nonempty body and query; clients cannot choose duration, deadline, source, owner or switch value. Preserve that gate, existing 400/404/409 behavior and authenticated read permissions. DRF serializers and `drf-spectacular` own the API contract; `openapi/v1.json` and frontend `schema.d.ts` are generated (`npm run gen:api`), never hand-edited. ADR-040 compatibility checks apply even when only response metadata changes. |
| Persistence and concurrent operations | `cms.models.RangeInstance`, `SoftDeleteManager`, active-range uniqueness, `ck_rangeinstance_lease_bounds`, `cms.services._range_lease` and `_range_launch_common._reserve_active_range_slot`. Preserve `transaction.atomic`, row locks and persisted maximum checks. Extend from current expiry, not now; reject expiry equal to now, terminal/destroying state and exhausted caps. Recheck eligibility while locked; a displayed button is not authority. |
| Destruction and recovery | `expire_due_ranges`, `_range_destroy.destroy_expired_range`, `_transition_then_dispatch`, Engine service/substrate boundaries, `reconcile_range_events`, `run_ctf_scheduler`, existing outbox/reconciliation (ADR-025). Keep bounded batches, `skip_locked` and the locked deadline recheck, rollback/retry behavior, system-attributed destruction and failed-row isolation. Never delete cloud resources directly from lease settings or add another scheduler. |
| Error envelopes and audit/logging | Existing `RangeLeaseConflict` / `RangeLeaseNotFound` under `CMSError`, installation `ConfigIssue` / `InstallationConfigError`, Django `ImproperlyConfigured`, `shared.api.errors`, `shared.errors`, `shared.audit` and `shared.log_sanitize`. Translate at boundaries; no new exception hierarchy. Retain user extension audit, system destruction audit, request correlation and sanitized cleanup identifiers with existing structured logging. Do not return raw validation/provider exceptions, stacks or config objects. |
| Secret and OS exposure | `RootConfig` secret-reference validation, backend reference grammars, entrypoint hydration, `bootstrap_core.run_cmd_secret_stdin`, AWS Helm stdin and GCP env-file delivery. Lease policy contains only validated integers/boolean and is safe for public runtime config. It contains no tokens or secret references. Preserve existing argv/stdin boundaries, file protections and hydration; never dump surrounding env, Terraform outputs, credentials or settings into logs, Actions output or API responses. Do not source/eval the JSON as shell code. |
| Provisioner/host boundary | The policy is platform lifecycle input, not RAES scenario intent, a task command, provider credential or machine TTL. Do not forward it into provisioner Jobs or expand their env allowlist/admission policy. Keep existing access/credential deadlines authoritative: a lease extension cannot renew credentials, raise an existing credential ceiling or mint a new access capability. |

## Launch-path gotcha: warm claims

The inspected checkout has a second successful launch path beyond the issue's
July description. `_raes_range_create` constructs a lease, then attempts a warm
claim and returns before its cold `_persist` callback. `_warm_pool_reconcile`
creates an unleased system-owned CMS row, and `_warm_pool_claim` rehomes that row
without assigning lease bounds. Changing only the cold builder leaves warm
Mission Control launches without automatic lease expiry.

Pass the trusted lease through the existing claim seam and persist the initial
user lease and increment in the claim/ownership transaction before activation.
This is first assignment for an unleased warm row, not rewriting an existing
user lease. Start the user lifetime at that launch; the separate warm ledger's
`idle_deadline` continues to own pre-claim pool cost and retirement. Preserve
claim rollback, capacity admission and fresh-access activation. A previously
leased generation must not have its ceiling reset by rehoming. CTF spare
handover is not a warm-pool policy and keeps its event deadline. Include a real
warm-hit assertion in acceptance evidence; a cold-launch-only test is inadequate.

## Rollout, cost and evidence

Operator guidance must document all four keys, units/defaults, validation,
deployment render/restart procedure, generation snapshots and the live switch.
A lower maximum does not shorten existing ranges; a higher maximum does not
raise their ceilings. Mixed old/new pods can launch with different policies or
continue accepting extensions until rollout completes. Use the existing
atomic/waiting deployment and readiness evidence; do not advertise instant
revocation from editing a ConfigMap. Upgrade/backfill and rollback must account
for older writers lacking the increment field and preserve historical bounds.

Longer leases increase resource, storage and access exposure; short leases can
expire while provisioning. Expiry is asynchronous destruction dispatch, not a
promise that billing stops exactly at the deadline. Existing cleanup excludes
FAILED rows and reports rows missing a request as failed: retain canonical
terminal cleanup/recovery and operator visibility rather than claim this policy
repairs all historical orphans. Keep cleanup workers running when extensions
are disabled. Repeated successful extension requests may each consume one
increment up to the cap; do not introduce a new idempotency protocol or assume
exactly-once HTTP delivery. UI refresh after mutation should reuse existing
query invalidation and error handling.

Required implementation evidence builds on `tests/config`,
`tests/cms/test_range_lease.py`, warm-pool claim/reconcile tests,
`tests/mission_control/test_range_api.py`, audit/permission tests,
`tests/ctf/test_mid_event_operations.py`, CTF lease/recovery/spare tests,
installation loader/render/publication tests, AWS bootstrap/GCP renderer tests
and chart contract tests. Cover defaults/custom policy, all invalid shapes and
numeric bounds, initial equals maximum, increment exceeds remaining lifetime,
expiry equals now, sequential/concurrent extensions and extension-versus-expiry,
rollback on dispatch failure, mixed-generation config changes, switch off/on,
legacy nulls, migration invariants, warm hits and CTF isolation. Use real
PostgreSQL transactions for row-lock evidence; SQLite cannot prove those races.
Follow ADR-019: exercise real first-party services and patch only actual
framework/process/cloud boundaries, not `_projection` or the destroy facade.

Frontend tests should use custom increments and a disabled-but-unexpired lease;
assert generated contract/projection parity and no client fallback constants.
Standalone installer/package and subprocess startup tests must catch imports
that work only from a repository checkout. No new global test harness is needed.

Architecture validation is `python3 scripts/adr_guard/adr_guard.py --all --level ci`.
Implementation also requires the relevant Python Ruff/import-linter checks,
env/publication/OpenAPI freshness and compatibility gates, chart render/security
checks, and actionlint, TFLint or Kubernetes linters when those surfaces change.
A passing documentation guard does not prove any runtime guarantee above.

## Extensibility and non-goals

The seam is a pure policy value consumed once at user-lease creation and a live
extension-admission boolean consumed by the existing service. New duration
values therefore require deployment input changes only. Transport adapters and
response projections reuse that value; generation state remains authoritative.
Future sub-day units or tenant/scenario overrides need an explicit contract
decision, not hidden reinterpretation of `*_days` or client-selected policy.

This preflight changes documentation only. Implementation scope is configuration
delivery/validation, the minimal generation snapshot and launch/claim binding,
existing lease projections/actions, operator documentation and behavioral tests.
Non-goals are a billing/budget engine, capacity or warm-pool redesign, idle-user
expiry, pause-based lease suspension, retroactive deadline normalization, CTF
rescheduling redesign, credential rotation, tenant policy hierarchy, new cloud
cleanup jobs, generic policy infrastructure, auth changes or a new API major.
Do not conflate lease lifetime with warm idle TTL, access credential expiry,
capacity reservations, model-access request leases or task timeouts.
