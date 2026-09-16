# ACES CyberScript issue triage

Status: historical decision record. The dispositions below were made during the
parallel-operation phase and are no longer a current decision surface. The
migration has since completed (see "Post-cutover reconciliation" below); the
table is retained as the record of what was decided, not as pending work.

Issue #1231 re-scopes scenario and CyberScript work around ADR-024:
ACES is the target scenario, runtime, experiment, and backend contract
surface, while current Shifter behavior remains authoritative until parity
and cutover gates pass.

## Post-cutover reconciliation

The gating migration is complete: #1231 (re-scope), #1310 (controlled default
cutover), and #1311 (legacy scenario/CyberScript/Polaris surface archival) have
all merged and closed. RAES is the current scenario/runtime/backend authority
(ADR-024/031/032/034/043); CyberScript source packages and the legacy scenario
loader/hydrator/templates have been removed. The dispositions below are realized:

- Every Supersede/Migrate/Close issue in the table (#620, #676, #433, #313,
  #314, #330, #328, #368, #355, #376, #383, #401, #374, #427–#432) is now
  closed.
- Only two Maintain issues remain open, and both are current-stack work
  unaffected by the migration: #776 (PLAT-221 scenario-level egress allowlist
  overrides) and #349 (DC instances XDR-agent production correctness bug).

No issue is opened or closed by this reconciliation note; it records state that
the migration issues themselves already produced.

## Triage rules

- **Maintain** means the issue protects current production behavior, legacy
  documentation, or mechanical cleanup that is still useful while CyberScript
  remains the live path.
- **Migrate** means the need may still be valid, but the implementation target
  is ACES SDL, an ACES Shifter profile, a Shifter backend adapter, or a later
  ADR-backed contract. Do not implement it as a new CyberScript semantic.
- **Supersede** means ADR-024, the parity inventory, or the ACES migration
  issue series has replaced the investigation or design question.
- **Close** means the issue describes a CyberScript expansion that is no
  longer aligned unless a later ADR deliberately reopens that surface.

## Requirement posture

- PLAT-007 tracks scenario expressiveness gaps as ACES migration/profile gaps,
  not as private provisioner behavior or new CyberScript semantics. The binding
  recording requirement is the `governance` block in
  `docs/architecture/aces-migration-parity-inventory.yaml`, so the two
  documents cannot drift.
- PLAT-209 tracks the parity-gated convergence path toward ACES as the
  canonical scenario definition surface. CyberScript compatibility is
  transition support, not a co-equal new authoring target.
- PLAT-210 tracks the Shifter ACES compatibility profile and legacy diagnostic
  posture. Additional non-ACES profiles require a future ADR or requirement.

## Issue disposition

| Issues | Disposition | Follow-up |
| --- | --- | --- |
| #620 | Supersede, then close after #1231 lands. The investigation goal is covered by ADR-024, the parity inventory, and this triage. | Point readers to #1231 and the ACES migration issue series. |
| #676 | Migrate into the ACES Migration Architecture milestone as the PLAT-007 tracking issue. | Update the issue body after the Ground Control requirement text is updated. |
| #776 | Maintain as current-stack platform work. | Future ACES adapter work must preserve the behavior if it becomes part of the supported Shifter profile. |
| #433 | Maintain as legacy/current documentation while CyberScript remains the live path. | Archive or replace only after the cutover gate. |
| #349 | Maintain as a current production correctness bug. | Fix against the current Shifter path; do not wait for ACES. |
| #313 | Maintain as low-risk legacy cleanup. | Keep scoped to shared schema cleanup; do not broaden into new DSL design. |
| #314, #330 | Close after #1231 lands as no longer aligned unless recast as ACES migration tooling. | A future tool should validate ACES profiles or migration parity, not create a new standalone CyberScript product surface. |
| #328, #368 | Migrate. These are terminal/UI and participant-runtime capabilities that should be represented through the ACES profile or Shifter backend adapter. | Reopen only as ACES profile/backend-adapter work if needed by #1232-#1237. |
| #355, #376, #383, #401 | Migrate. These ask for adversary behavior, goals, tools, or agentic options; those belong in ACES semantics or Shifter adapter responsibilities. | Convert only when an ACES issue identifies a concrete profile gap. |
| #374 | Supersede. ADR-024 makes `InstanceConfig` a Shifter backend boundary, not a CyberScript architecture-conformance target. | Reference the parity inventory rows `scenario.any-template-union` and `scenario.hydration-range-spec`. |
| #427, #428, #429, #430, #431, #432 | Migrate as future ACES-authored scenario content. | Do not implement as CyberScript-only scenario expansion; bind to ACES catalog/back-end work after #1232 and #1233. |

No current production behavior is removed by this triage. It changes backlog
intent and requirement wording only.
