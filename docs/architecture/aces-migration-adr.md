# ADR-024: ACES migration uses a parity-gated parallel cutover

## Status

Accepted.

## Date

2026-06-29

## Context

Shifter currently has several scenario, runtime, experiment, and backend
contract surfaces that predate ACES:

- CMS scenario templates and the scenario registry/hydrator under
  `shifter/shifter_platform/cms/scenarios/`.
- CyberScript contracts re-exported through `shared` and consumed by CMS,
  engine, CTF, and experiment code.
- Polaris scenario material under `scenario-dev/polaris/`, including ACES SDL
  drafts, content packages, container realization files, CTFd sync manifests,
  walkthroughs, and smoke tests.
- CTF event, challenge, scoring, participant, and range services under
  `shifter/shifter_platform/ctf/`.
- Legacy experiment execution planning under `cms.experiments`, which was
  removed by ADR-027 / issue #1195 instead of serving as a current runtime
  authority.
- Mission Control views, range state, terminal access, Guacamole integration,
  uploaded artifacts, and status/event consumers.
- Engine and provisioner service boundaries that materialize hydrated specs
  into database rows, Terraform, cloud tasks, and runtime state.

ACES is the target scenario and experiment contract family, but Shifter cannot
switch by declaration alone. Current Shifter behavior remains authoritative
until an ACES path proves parity against the existing stack and passes explicit
cutover gates. The exception is legacy experiments: ADR-027 removes that
half-built runtime path, so future experiment capability starts from a new
ACES-backed design rather than parity against `cms.experiments`.

APTL provides the migration precedent. Its ACES adoption used a parallel path,
a parity inventory as the audit surface, manifest/conformance gates, and
archive-after-cutover cleanup. Shifter should reuse that pattern while keeping
Shifter-specific backend responsibilities in Shifter instead of pushing them
into ACES SDL.

## Decision

Shifter will migrate toward ACES through a parity-gated parallel cutover.

ACES may become the canonical scenario, runtime, experiment, and backend
contract surface only after Shifter proves that the ACES path covers the
legacy surfaces identified in
`docs/architecture/aces-migration-parity-inventory.yaml`.

The migration has three boundaries:

1. **Authoring and contract boundary.** ACES owns authored scenario and
   experiment meaning, published schemas, backend manifests, profiles, and
   conformance vocabulary.
2. **Shifter backend boundary.** Shifter owns portal behavior, CMS/CTF service
   semantics, Mission Control, user authorization, range lifecycle, cloud
   provisioning, artifacts, logs, status, audit, and operator runbooks.
3. **Validation boundary.** A cutover can happen only when parity inventory
   rows are reconciled, ACES manifest/conformance gates pass, and Shifter's
   portal/engine/provisioner validation passes without weakening current
   guards.

The extension boundary is an explicit ACES contract/profile discriminator at
the scenario registry and hydrator boundary, not implicit YAML shape detection
and not Polaris-specific branches in Shifter core.

## Goals

- Preserve current Shifter runtime behavior until parity and cutover readiness
  are proven.
- Make the migration reviewable by mapping every legacy surface to exactly one
  owner category in the parity inventory.
- Keep ACES semantic ownership separate from Shifter backend realization.
- Reuse existing Shifter service boundaries, shared contracts, persisted-spec
  envelopes, authorization helpers, redaction helpers, status models, and
  provisioner orchestration.
- Let implementation issues cite stable inventory row ids instead of
  re-litigating broad migration scope in every PR.

## Non-Goals

- This ADR does not cut over Shifter to ACES.
- This ADR does not remove CyberScript, current scenario templates, Polaris
  runtime material, CTF behavior, Mission Control, provisioner code,
  artifacts, status models, or validation gates. ADR-027 separately removes
  the legacy experiment execution path.
- This ADR does not add an ACES parser, ACES runtime target, ACES backend
  manifest, new API endpoint, data migration, or cloud workflow.
- This ADR does not make Polaris the public type system for the ACES adapter.
  Polaris is the primary parity proving case, not the adapter contract.

## Migration Constraints

- CyberScript work during the parallel phase is limited to current-stack
  compatibility, production bug fixes, documentation, and migration/archive
  support. New scenario meaning, scenario DSL semantics, participant-runtime
  semantics, or backend contract semantics belong in ACES SDL, an ACES
  Shifter profile, or a later accepted ADR that explicitly widens the legacy
  surface.
- ACES integration must enter through `shared`, `cms.scenarios.*`,
  `cms.services`, and `engine.services` boundaries. Direct ACES or CyberScript
  imports outside `shared` remain disallowed unless a later ADR changes the
  import contract.
- Current CMS scenario id validation, path containment, YAML `safe_load`,
  Pydantic validation, persisted-spec wrapping, and model validation remain in
  force until replaced by an equal or stronger ACES-backed gate.
- CTF scoring, participant access, challenge release, flag validation, hint
  behavior, event lifecycle, and organizer/admin authorization remain Shifter
  service responsibilities unless ACES publishes a matching contract and
  Shifter deliberately binds to it.
- Any future experiment command rendering must go through an accepted
  ACES-backed runtime contract and an equal or stronger prompt, artifact, and
  command boundary. The deleted `cms.experiments` rendering path is not current
  authority.
- Mission Control remains the operator/user runtime UI and status boundary.
  ACES may supply contract payloads, but it does not own Shifter UI behavior.
- Provisioning remains behind Shifter's engine/provisioner service boundary.
  ACES backend work must adapt to that boundary rather than invoking cloud,
  Terraform, Docker, or shell behavior directly from CMS/CTF/Mission Control.
- No secrets, private keys, real flags, live cloud ids, rendered runtime
  config, or backend credentials may be embedded in ADR examples or inventory
  rows.

## Parity Inventory Boundary

The parity inventory is an audit manifest, not a runtime schema. It exists to
route each legacy surface to one owner category and to identify the next issue
kind needed for that row.

Every row must use exactly one of these categories:

- **ACES SDL**: the surface belongs in authored ACES scenario or experiment
  content.
- **ACES schema/profile gap**: the surface belongs in ACES, but ACES does not
  yet publish the needed schema, profile, vocabulary, or conformance support.
- **Shifter backend responsibility**: the surface is portal, service,
  provisioner, runtime, artifact, status, audit, or operator behavior that
  Shifter must keep owning.
- **validation gate**: the surface is not authored directly, but parity must
  be proven by tests, smoke checks, conformance, ADR guards, import guards,
  static checks, or live validation.
- **archive/delete**: the surface is eligible for archive or removal only after
  the cutover gate proves that no current runtime path depends on it.

Inventory rows cite canonical owners. They must not copy secret-bearing data,
become a second scenario schema, duplicate ACES models, duplicate CyberScript
models, duplicate status taxonomies, or replace existing runtime manifests.

## Cutover Gates

A future cutover PR must satisfy all of these gates:

- Every inventory row is reconciled to one category and any candidate issue
  named by the row is resolved or explicitly marked not needed by a reviewed
  inventory update.
- ACES SDL parsing, semantic validation, manifest/profile validation, and
  backend conformance pass against the Shifter-supported profile.
- The Shifter ACES path launches the relevant scenario through the normal
  portal, CMS, engine, and provisioner path, not only through an external demo.
- Polaris passes its existing infrastructure and content validation in the
  Shifter path that operators actually use.
- Existing CTF, experiment, Mission Control, artifact, status, audit, and
  provisioner tests remain green.
- `python3 scripts/adr_guard/adr_guard.py --all --level ci` and the
  stack-native checks required by changed paths remain green.
- Archive/delete rows are moved only after imports, runtime loaders, docs, and
  tests no longer treat the legacy surface as current authority.

## Rollback Posture

During the parallel phase, rollback is simple: keep the current Shifter path as
the default and disable or remove the ACES path if validation fails.

At cutover, rollback requires a preserved legacy reference surface and a
reversible runtime selector until one release has proven the ACES path. The
cutover PR must identify the selector or operational rollback path it uses.
Archive/delete cleanup happens only after that rollback posture is explicit.

## Consequences

- Issue and PR discussions can cite inventory rows by stable id.
- ACES expressivity gaps are routed to ACES or ACES-profile work instead of
  being patched into Shifter as a private scenario language.
- Existing CyberScript and scenario backlog items are triaged in
  `docs/architecture/aces-cyberscript-issue-triage.md` so implementation work
  can distinguish current-stack maintenance from ACES migration candidates.
- Shifter backend responsibilities remain visible and testable.
- The migration can progress incrementally without breaking current operators
  before parity is proven.
