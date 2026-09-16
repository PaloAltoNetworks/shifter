# REV1 Architecture And Roadmap Review

## What is sound

The project has made several correct architectural choices:

- The ADR registry couples decisions to named checks and evidence rather than
  treating ADRs as narrative only.
- Cross-layer dependencies use service facades and shared contracts for the
  layers currently classified by the guardrails.
- The ACES transition is parallel, feature flagged, parity gated, and reversible.
  CyberScript remains authoritative until evidence supports cutover.
- ACES is correctly treated as the authored contract owner while Shifter retains
  authorization, lifecycle, cloud realization, audit, status, and operations.
- Provider protocols exist in both platform and provisioner code and reject an
  explicitly unknown provider.
- The SPA plan preserves one Django origin, one session/CSRF posture, and the
  canonical `/api/v1` surface.

These decisions should be retained. The review findings concern gaps between
the stated architecture and the current implementation.

## A1: ACES transport is not version-safe or fail-closed

**Severity: high**

ADR-032 says the process-boundary artifact is the serialized ACES
`ProvisioningPlan` and prohibits a Shifter-owned intermediate provisioning
model. The provisioner nevertheless defines `AcesPlanImage`, `AcesPlanNode`,
`AcesPlanNetwork`, and `AcesPlan`, then reconstructs them from untyped maps in
[`aces_plan.py`](../../../shifter/engine/provisioner/aces_plan.py). The producer
records an `aces_sdl_version` in
[`runtime_target.py`](../../../shifter/shifter_platform/shared/aces/runtime_target.py),
but the consumer accepts any version. It also ignores unknown resource types
and drops unresolved network references rather than rejecting the plan.

The parity test imports private reference-backend helpers. That makes an
upstream private refactor part of Shifter's compatibility surface without an
explicit contract.

**Impact:** process version skew or an ACES payload change can provision a
partial or incorrect topology while appearing successful.

**Action:** the ACES transport issue must gate #1477 and #1264. Define supported
producer/contract versions, reject unknown resources and dangling references,
use only public ACES compatibility fixtures/APIs, and pin upgrades to an
explicit conformance review. If a Shifter realization projection is necessary,
ADR-032 should say so rather than asserting that none exists.

## A2: The provisioner is coupled to Django's mutable schema

**Severity: high**

[`provisioner_db.py`](../../../shifter/engine/provisioner/provisioner_db.py)
reads and writes Django-owned range, instance, subnet, and outbox tables through
raw SQL. Django migrations grant the provisioner access to those tables and
columns. ACES work extends this integration surface.

**Impact:** schema evolution is a distributed deployment contract; a model
change can break a separately deployed worker, and every new operation tends to
expand database privilege.

**Action:** existing issue #478 already describes the right work. Freeze new
direct-table integrations and move toward a versioned command/inbox and
outbox/reconciliation boundary, or a narrow engine-owned API. Do not create a
duplicate REV1 implementation issue.

## A3: Backend bundles are intent, not runtime authority

**Severity: high**

The installation registry calls backend bundles provisional but labels both
current bundles stable. Runtime settings and several factories still default a
missing provider to AWS, while some selection sites treat every non-GCP value as
AWS. A missing or malformed root configuration can therefore select behavior
instead of failing closed.

**Impact:** open-source operators can believe the root bundle is authoritative
when runtime defaults still determine provider behavior.

**Action:** use existing #721, #726, #728, #729, #1322, and #1323. Provider
selection should be a validated injected value; missing and unknown values must
fail outside explicit local/test modes. Bundle maturity should reflect actual
conformance evidence.

## A4: Boundary-enforcement finding resolved

**Status: resolved by #1374**

The import checks classify the installed first-party packages and the
`INSTALLED_APPS` guard rejects unclassified additions. The cross-cutting audit
contract, model, writer, administration, archive command, and health reporting
are owned by `shared`; feature layers use that neutral boundary rather than an
upward feature-app dependency.

## A5: Presentation orchestration ownership remains ambiguous

**Severity: medium**

Mission Control calls both CMS and engine services, while CMS also calls engine
services. This permitted diamond leaves no obvious owner for new runtime/UI use
cases and creates multi-boundary view tests.

**Action:** existing #994 is the correct decision issue. Resolve it before the
Mission Control SPA workspace (#1370) expands the same surface. Existing #991
then provides a concrete refactor target for remote-access orchestration.

## A6: Documentation volume obscures the current architecture

**Severity: medium**

`docs/architecture` contains 186 tracked files, of which 163 are issue-specific
preflight documents. These are useful implementation records but are not a
current-system handbook. The root README still presents CyberScript as the
unqualified long-term platform language and contains upstream organization
links, while the accepted ADRs describe an ACES target and a different canonical
repository.

**Impact:** contributors must reconstruct the current system from historical
preflights, and stale public documentation undermines open-source onboarding.

**Action:** publish a short, maintained architecture handbook with a system
context, trust boundaries, deployables, ownership/dependency map, data and event
flows, extension points, and migration-state page. Mark preflights as decision
records, not current authority.

## Roadmap assessment

The direction of the ACES and backend-bundle programs is sound, but the combined
work-in-progress is too broad. ACES-native provisioning (#1477-#1479), backend
substrate contracts (#1320/#1322), live-fire GCP isolation, Workspaces/API,
SPA phase 2, and AWS cleanup all modify adjacent boundaries.

Recommended sequence:

1. Close trust-boundary and contract-integrity findings, prioritize #478, and
   resolve #994.
2. Make provider configuration fail closed and land the substrate contract
   before expanding adapters.
3. Complete ACES realization, projections, conformance, and live validation;
   cut over only through #1310's rollback gate.
4. Resume additive Workspaces/API and SPA phase 2 work only when their required
   platform boundaries are stable. These programs should not be used to expand
   the product's remit during stabilization.

With 417 open issues, milestone membership is not prioritization by itself. The
REV1 program issue should identify the small set of blockers above, explicitly
defer non-blocking enhancements, and close or rescope stale issues whose premise
has already changed (for example #530).
