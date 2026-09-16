# Scenario and event model-admission preflight — #2119

**Requirement:** PLAT-202 (M02)
**Status:** pre-implementation guidance; complements ADR-059 through ADR-061

## Boundary and decision

CTF owns authenticated organizer event intent and CTF-908 demand declarations.
CMS owns scenario/package hydration, current launch authorization, workspace and
egress admission, then calls the public Engine service. Engine owns the final,
durable model-admission decision and any allocation/accounting effects. The
provisioner realizes only an admitted, non-secret operation projection.

`shared.model_access.ScenarioNeed` is the canonical logical-need contract. A
Shifter-owned binding must key it to the exact released scenario/package digest
and workload role unless the installed RAES release supplies an equivalent
qualified field. Do not add a local RAES field or infer access from pack text,
tool names, images, or a selected cloud backend. Compute placement and model
routing remain independent.

### Resolved: two lifecycles — where the need binding lives

This note originally emphasized the mounted `ModelAccessCatalog` for
model-access configuration. That is correct for **deployment policy** but **not**
for the per-pack scenario need. Env/scenario packs are **tenant/staff-managed
runtime data** (registered and removed at runtime via `PackRegisterView` →
`cms.services.register_pack`, backed by `RaesPackageSource` and the
`ScenarioMetadata` staff overlay). Storing per-pack needs in the deploy-time
mounted catalog would make a newly-registered model-requiring pack fail closed
until an operator redeploys the catalog. Split the two lifecycles:

- **Deployment policy (operator, deploy-time):** the mounted `ModelAccessCatalog`
  owns profiles, shards, quota pools, and sharing pools/bindings. This is what a
  need's `profile_id` references and what admission intersects against via
  `shared.model_access.policy.intersect_profile`.
- **Per-pack scenario need (tenant/staff, runtime):** a dedicated staff overlay
  model (`ScenarioModelNeeds`, sibling to `ScenarioMetadata`), keyed by
  `scenario_id`, storing the authored-against `package_digest` plus
  `{workload_role → ScenarioNeed}` validated by the `shared.model_access` DTOs,
  managed through the existing staff scenario admin/API surface. Not on
  `RaesPackageSource` (contractually provenance-only). Admission verifies the
  registered pack's current `package_digest` matches the digest the need was
  authored against and fails closed for a required need on mismatch. No binding
  means no required-model gate; a binding with `required=true` fails closed.

See the issue decision comment for the full rationale.

Typed model demand belongs in the incumbent CTF-908 declaration path, not a
second event JSON contract. It is organizer input constrained by the scenario
need and deployment/event envelope: cohort/spares, concurrency, bounded
per-participant request/input/output demand, event window, and allowed
strategy. It cannot name a provider, account, project, region, credential,
endpoint, shard, or price.

## Required admission behavior

The current `ctf.services.range.capacity` declaration, assessment and draw
helpers are deliberately best-effort for PLAT-201. They must remain so for
general compute planning, but they are not an authorization mechanism.
Required model access needs a distinct typed result at the existing CTF → CMS →
Engine launch seam: missing, denied, stale/indeterminate, artifact-digest
mismatch, unauthorized policy expansion, incompatible egress posture, or an
unavailable enforcing authority rejects before dispatch. Optional access may be
absent only as an explicit admitted result with no broker capability.

Apply that result consistently to participant, spare, replacement/recovery,
warm activation and standalone launch families. Keep the existing request ID,
stable participant/spare draw key, generation fences, launch cleanup, and
idempotency behavior; do not invent a second lifecycle, job ID, retry loop or
range state. A launch retry must reuse its recorded model decision rather than
recalculate routing or turn an ambiguous outcome into permission.

The effective sharing-policy compiler and its persisted authority/membership
fences are the only overlap-resolution path. Resolve all matching bindings
before capacity/allocation effects; restrictions intersect, account references
coalesce and are each enforced, and equal-priority incompatible choices deny.
Dynamic membership is not a grant: a new member performs normal admission.

## Security and runtime guardrails

Validate at every owning boundary: DRF/form + CTF service validates the closed
event shape and event authority; CMS rehydrates and verifies the released
artifact, authorizes the actor/workspace and egress posture; Engine rechecks
the complete trusted projection, catalog digest, authority/membership revisions
and required result transactionally. Reuse `shared.model_access` closed DTOs,
catalog parser/digest rules and bounded `ContractError` codes; do not create
parallel serializers, Pydantic models or exception trees.

The installed catalog remains a mounted non-secret, digest-bound artifact
validated by `installation.loader`, `installation.model_access`,
`shared.model_access.runtime` and `config._model_access_settings`. Pass its
path/digest only through environment; never put catalog content, credential
material, endpoint secrets or tokens in an operation payload, Terraform state,
Helm command, process environment or argv. Use the admitted GCE broker-capability
projection and `shared.model_access.network` / range-cell firewall validation;
zero-egress cannot silently mean external-model access, and the private broker
exception is valid only when explicitly admitted.

Logs, audit records and API errors use existing safe helpers and bounded codes:
`shared.log_sanitize`, `shared.audit`, `shared.errors`, and
`shared.api.errors`. They must not include prompts, completions, tool data,
credential references/values, raw provider errors, headroom, account topology
or rejected payload values.

## Non-goals and anti-patterns

- No provider SDK, provider credential, cloud-account routing, or Engine ORM
  access in CTF/CMS; no provider/backend switch on a scenario or event.
- No direct guest credentials, general outbound-internet exception, or
  automatic fallback from an enforcing denial to advisory/optional behavior.
- No duplicate capacity reservation, policy precedence, scenario hydration,
  RAES schema, validation, exception, or background workflow.
- No model-broker implementation, request accounting, live provider admission,
  autoscaling, queueing, cross-cloud migration, or new public endpoint in M02.
