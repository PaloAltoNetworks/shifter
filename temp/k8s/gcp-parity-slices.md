# GCP Parity Slices

Date:
- 2026-04-10

Scope:
- Goal: AWS feature parity on GCP for the Shifter platform.
- Deferred for now:
  - NGFW-specific implementation
  - experiments execution portability work
  - CTF-specific scenario/image/service modeling beyond what the core platform already supports

Status:
- `P1` reopened on 2026-04-10 after a production-quality lifecycle audit.
- Current implementation status: GCP pause/resume is intentionally disabled until parity-safe lifecycle semantics exist.
- Bootstrap prerequisite status: `gdc-bootstrap` rerun safety for the substrate stages is now implemented and locally/live-readonly verified before the next full bootstrap proof run.
- Pre-bootstrap hardening status: the next GCP bootstrap now has enforced secure prerequisites, IAP-only GDC admin access, GKE master authorized networks, and Cloud Armor wiring in code and tests before the next fresh rebuild proof.
- `P5` live proof succeeded on 2026-04-10/11: `gdc-bootstrap` now reconciles the GDC substrate, control-plane Terraform, image pushes, Helm release, and public ingress to a usable Shifter platform in `gcp-dev`.
- Bootstrap auth status on 2026-04-11:
  - AWS path remains Cognito/OIDC.
  - GCP path now provisions Identity Platform directly, seeds the first operator during bootstrap, and elevates the configured bootstrap operator through runtime config without committing identities to source.

Guiding rule:
- Parity means every existing Shifter platform capability that works on AWS must work on GCP.
- Parity means business-logic parity and semantic parity, not surface-level, UI-only, or shallow behavioral similarity.
- Infrastructure and implementation details may differ.
- CMS, Mission Control, and the SDL/shared scenario contract should not need semantic changes in order to support GCP backend selection.
- The provisioner/runtime layer is the decision engine for how a hydrated scenario is instantiated.
- The provisioner must accept any existing scenario expressible in the current SDL and derive the correct runtime backend per instance without requiring SDL changes.
- Backend selection must be inferred from scenario semantics and required guest capabilities, not from new author-facing schema fields.
- `scenario_pod` may remain as an internal/runtime concept if needed, but it must not be required to author or preserve normal Shifter behavior.
- Optional lower-fidelity execution must never silently degrade or replace normal Shifter semantics for existing scenarios.
- No slice is complete without proof. Every slice must end with concrete evidence that the implemented behavior matches Shifter's business logic and semantics on GCP.
- TDD is mandatory for every slice. Tests must be written to prove the required behavior and must only pass when the implementation genuinely satisfies the business logic and semantic contract.
- Shallow tests are not acceptable. Avoid tests that only validate mocks, function calls, or status transitions when the real requirement is deeper semantic behavior.

## Slice P1: GCP Range Lifecycle Parity

Status:
- Reopened on 2026-04-10.

Objective:
- Make range pause/resume fully work on GCP with business-logic and semantic parity to the AWS path.

Work:
- Replace the AWS-only provider guard in `engine/provisioner/range_ops.py`.
- Implement provider-routed pause/resume for GDC VM Runtime guests.
- Implement real start/stop behavior for pod-backed assets in mixed ranges.
- Preserve status transitions, event publication, and idempotency semantics expected by CMS/Engine/CTF.
- Add tests for ready -> pausing -> paused -> resuming -> ready on GCP.

Exit criteria:
- `pause_range()` and `resume_range()` work end-to-end for GCP VM Runtime ranges.
- Mixed ranges stop and restart both VM Runtime guests and pod-backed assets.
- The deployed provisioner image contains the runtime dependencies needed to execute GCP lifecycle operations.
- Pod-backed asset pause/resume preserves guest state at a level that is meaningfully equivalent to AWS stop/start semantics.
- Proof:
  - automated TDD coverage proves GCP lifecycle success, failure, and idempotency behavior in a way that cannot pass if lifecycle semantics are fake or shallow
  - live validation demonstrates create -> pause -> resume -> destroy on GCP with observed state continuity
  - evidence is recorded in temp notes with any residual risk called out explicitly

## Slice P2: Provisioner Backend Resolution Engine

Objective:
- Make backend choice automatic from the hydrated `RangeSpec` and owned entirely by the provisioner/runtime layer, while preserving Shifter business logic and semantics.

Work:
- Add an internal backend-resolution phase after hydration and before provider-specific resource creation.
- Resolve each instance onto the correct backend using only existing scenario semantics in the hydrated spec.
- Resolution must be based on current guest requirements, including at least:
  - Windows guest requirements
  - domain controller / domain join requirements
  - XDR/agent install requirements
  - any other setup path that requires full guest bootstrap
- Treat pod execution, if preserved, as an internal optimization/placement result rather than scenario intent.
- Store the resolved runtime plan in engine/provisioner-owned state, not in CMS/shared authoring contracts.
- Add tests that prove existing Shifter scenarios are resolved correctly without SDL changes.

Exit criteria:
- Any existing scenario in the current SDL can be handed to the provisioner and resolved onto the correct backend mix automatically from the hydrated spec.
- No scenario silently lands on an under-capable runtime backend.
- The resolver is internal to the provisioner/runtime path and does not require SDL/CMS changes.
- Proof:
  - automated TDD coverage demonstrates representative existing scenarios resolve to the correct backend choices without SDL changes, and cannot pass if backend selection is only superficially routed
  - live or fixture-backed evidence shows backend resolution preserves the same scenario meaning and setup obligations as AWS
  - evidence is recorded in temp notes with any unresolved edge cases enumerated

## Slice P3: Resolved-Capability Access and Runtime Surfaces

Objective:
- Make engine/runtime/API behavior follow resolved instance capability instead of SDL/backend hints, with semantic parity to current AWS user flows.

Work:
- Drive SSH/RDP/terminal behavior from resolved runtime capability and provisioned state, not from scenario-layer fields.
- Ensure Mission Control-visible data is derived from engine/runtime state and remains backend-agnostic.
- Prevent click-path failures by making exposed actions reflect what the resolved instance actually supports.
- Add tests for mixed resolved ranges so access paths match resolved guest capability.

Exit criteria:
- UI/API behavior matches the resolved capability instead of failing at click time.
- Proof:
  - automated TDD coverage proves SSH, RDP, terminal, and related runtime access behavior for resolved backends, and cannot pass if exposed actions are merely cosmetically present
  - live validation shows the same user-facing flows succeed on GCP where they succeed on AWS
  - evidence is recorded in temp notes with any residual mismatches called out explicitly

## Slice P4: GCP Documentation Reconciliation

Objective:
- Make the docs describe the architecture we actually have and the parity posture we are enforcing, including the semantic-parity bar.

Work:
- Update `platform/k8s/gcp/README.md`.
- Update `platform/terraform/gcp/README.md`.
- Update technical GCP/GDC provisioning docs to describe:
  - active GDC VM Runtime guest path
  - VM Runtime as the parity path
  - internal provisioner-owned backend resolution from hydrated scenario specs
  - `scenario_pod` as optional lower-fidelity/additive runtime mode, not authoring contract
  - current deferred items: NGFW, experiments
- Remove stale statements that claim guest/runtime integration is a non-goal.

Exit criteria:
- A reader can tell from the docs which GCP path is authoritative for feature parity.
- Proof:
  - docs reference the real active architecture and no longer describe known-non-parity behavior as complete
  - all parity-relevant deviations and deferred items are explicitly documented
  - evidence is recorded in temp notes with the affected docs listed

## Slice P5: Control-Plane Live Bring-Up and Smoke Verification

Status:
- Completed on 2026-04-10/11 with live proof in `prod-rwctxzl6shxk`.

Objective:
- Prove the GCP control plane is operational in the target project/environment at a level consistent with Shifter production behavior.

Work:
- Deploy/bootstrap the `gcp-dev` control plane from clean state.
- Verify core platform services:
  - web
  - CMS/Engine/Mission Control workers
  - Guacamole stack
  - database connectivity
  - Redis
  - queue/topic wiring
  - secret delivery
  - ingress / edge path
- Verify provisioner Jobs launch correctly with the GCP runtime contract.

Exit criteria:
- The Shifter portal is reachable and core background services are healthy on GCP.
- Proof:
  - automated and live verification together prove the portal, workers, queueing, secrets, ingress, and provisioner jobs operate correctly, not merely that resources exist
  - failures are treated as implementation defects, not waived as environmental noise without hard evidence
  - evidence is recorded in temp notes with timestamps and observed results
- Observed proof:
  - `./scripts/bootstrap/deploy.py gdc-bootstrap --project-id prod-rwctxzl6shxk --cluster-id cluster1` completed successfully
  - external portal ingress at `http://34.54.58.95/` returned `HTTP/1.1 200 OK`
  - external Mission Control ingress returned the expected secure login redirect
  - Google backend health for the portal NEG converged to `HEALTHY` after the chart-owned `BackendConfig` switched the health check path to `/health/`

## Slice P6: Core Scenario Parity Verification on GCP

Objective:
- Prove the main Shifter scenario/runtime features work on GCP through VM Runtime with business-logic and semantic parity to AWS.

Work:
- Run and verify representative non-NGFW scenarios on GCP:
  - `basic`
  - `ad_attack_lab`
  - one multi-subnet, non-NGFW equivalent if available, or a custom VM-only parity scenario
- Validate for each:
  - provisioning succeeds
  - Kali terminal access works
  - RDP works where expected
  - Windows bootstrap works
  - DC promotion works
  - domain join works
  - XDR install path works
  - destroy works cleanly
- Capture issues as implementation defects, not test notes.

Exit criteria:
- We have evidence that the core AWS-era Shifter scenario feature set works on GCP, excluding NGFW.
- Proof:
  - automated TDD coverage plus representative end-to-end scenario runs on GCP validate the same expected behavior as AWS
  - operator-visible and attacker-visible behaviors are checked, not just resource creation success
  - evidence is recorded in temp notes with scenario names, observed outcomes, and any parity gaps

## Slice P7: Operational Hardening for the Parity Path

Objective:
- Make the parity path reliable enough for repeated operator use at a true Shifter production bar.

Work:
- Verify idempotent reprovision/destroy behavior.
- Verify cleanup of GDC namespaces, VM Runtime disks/VMs, and SSH secrets.
- Verify failure handling leaves the system recoverable.
- Tune cluster/job defaults that are required for stable repeated range operations.
- Remove or quarantine dead/stale GCP code paths that reflect superseded assumptions.

Exit criteria:
- Repeated provision/destroy cycles on GCP are operationally sane and recoverable.
- Proof:
  - repeated live runs plus automated hardening tests demonstrate stable reprovision/destroy and clean recovery from failures
  - cleanup and idempotency are observed in the real environment, not inferred only from unit tests
  - evidence is recorded in temp notes with observed failure modes and mitigations

## Parked Work

Not part of the immediate parity slices:
- NGFW implementation and validation
- experiments portability cleanup
- scenario-pack-specific CTF runtime modeling:
  - service-specific pod images
  - AI-enabled Kali container image
  - Samba-first AD path
  - event-scale sizing/tuning specific to NORTHSTORM
