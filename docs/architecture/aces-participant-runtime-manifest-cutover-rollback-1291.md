# ACES Participant Runtime Manifest Cutover And Rollback

Issue: GitHub #1291, "22 - ACES migration: add participant runtime manifest
and conformance gate."

This note documents the cutover and rollback posture for Shifter's ACES
`participant_runtime` backend-manifest capability claim. It does not widen the
manifest. Shifter's published manifest (`shared.aces.manifest`) still declares
`participant_runtime: null` and infers as `BackendCapabilityProfile.PROVISIONING_ONLY`.
That stays correct: Shifter has no ACES participant-episode lifecycle/history/
evidence protocol implementation, only product-specific Mission Control,
Guacamole, and CTF participant surfaces (see "Current workflows that remain
authoritative and untouched" below).

What #1291 ships instead is the falsifiable *conformance gate* that must stay
green before, during, and after any future cutover:
`tests/shared/aces/test_participant_runtime_conformance_gate.py`. It locks the
current honest state (no claim, no gaps) and proves the ACES
`participant_runtime_capability_contract_gaps` detector actually catches a
premature claim -- and clears once the claim is genuinely backed by the
required published contracts -- so the gate cannot rubber-stamp an
over-claim.

## Cutover posture

The widening selector for a future, genuine `participant_runtime` claim is
the pairing of:

- **Backend manifest capability discriminator** -- `shared.aces.manifest`
  would add a `ParticipantRuntimeCapabilities` value to the `BackendCapabilitySet`
  the manifest builder constructs, declaring specific participant roles,
  behavior features, and interaction features from the ACES controlled
  vocabulary (`aces_contracts.controlled_vocabularies`). `SHIFTER_SUPPORTED_CONTRACT_VERSIONS`
  in `shared/aces/contracts.py` would need to grow to cover every contract
  `PARTICIPANT_RUNTIME_CAPABILITY_REQUIRED_CONTRACTS` requires for each
  declared term (see `aces_backend_protocols.capabilities` for the current
  required-contract table).
- **`SHIFTER_SUPPORTED_PARTICIPANT_RUNTIME_PROFILES` seam** in
  `shared/aces/contracts.py` -- today this governs which participant-runtime
  *sidecar* profiles Shifter's `AcesParticipantRuntimeRecord` persistence
  layer accepts (#1288), a separate concern from the backend manifest
  capability claim above. A genuine cutover that lets Shifter both persist
  sidecars for and claim ACES participant-runtime protocol conformance for a
  given profile would need both seams to move together: the manifest claim is
  the ACES-facing capability declaration, the sidecar profile set is the
  Shifter-internal record-acceptance list. They must not drift, or the
  manifest would claim more (or less) than what the sidecar layer actually
  accepts.

The evidence bundle required to widen the claim, in order:

1. ACES publishes the participant lifecycle, history, and evidence contracts
   the claimed roles/features require (the contracts already exist as ids in
   `aces_backend_protocols.capabilities.PARTICIPANT_RUNTIME_CAPABILITY_REQUIRED_CONTRACTS`,
   but Shifter does not implement the protocol surface those ids describe
   today).
2. `shared.aces.manifest` declares the claim, `SHIFTER_SUPPORTED_CONTRACT_VERSIONS`
   covers the required contract set, and `tests/shared/aces/test_participant_runtime_conformance_gate.py`
   plus `tests/shared/aces/test_backend_manifest_publication.py` pass green
   with the widened manifest (no gaps from `participant_runtime_capability_contract_gaps`,
   no hollow-claim regression in the existing publication tests).
3. A live-target conformance run (`aces conformance backend` /
   `run_target_conformance` against a real `RuntimeTarget`) proves the
   backend's `ParticipantRuntime` protocol implementation -- `initialize`,
   `reset`, `restart`, `terminate`, and the `status`/`results`/`history`
   observation methods -- actually round-trips through `RuntimeSnapshot.participant_episode_results`
   and `participant_episode_history`, not just that the manifest text parses.

The claim is an output of contract support plus conformance evidence. It is
never a feature flag, a config toggle, or a documentation update by itself --
per `docs/architecture/aces-participant-runtime-manifest-conformance-gate-preflight-1291.md`,
turning current product surfaces into an ACES participant-runtime protocol by
naming them in the manifest is explicitly out of bounds.

## Rollback posture

Rolling back is reverting the manifest claim: set `capabilities.participant_runtime`
back to `None` in `shared.aces.manifest.create_shifter_backend_manifest()` and
drop the added contract ids from `SHIFTER_SUPPORTED_CONTRACT_VERSIONS` if they
were added solely to back the claim.

- `test_shifter_manifest_declares_no_participant_runtime` and
  `test_current_manifest_has_no_participant_runtime_contract_gaps` in the
  conformance gate test file catch a rollback regression immediately: they
  assert the *current* manifest (whatever it is at the time the suite runs)
  has no participant-runtime capability and produces no gaps. Reverting the
  manifest change makes them pass again with no test edits required.
- No data migration is needed. Participant-runtime sidecar storage
  (`AcesParticipantRuntimeRecord`, `shared.schemas.aces_participant_runtime`,
  `shared.aces.participant_runtime`) is already separate from the backend
  capability claim -- sidecars record that Shifter persisted bounded
  participant-runtime data, not that Shifter's backend manifest claims ACES
  participant-runtime protocol conformance. Rolling back the manifest claim
  does not touch, invalidate, or require replaying sidecar rows.
- `SHIFTER_SUPPORTED_PARTICIPANT_RUNTIME_PROFILES` (the sidecar-profile
  acceptance seam) is independent of the manifest claim and does not need to
  be rolled back merely because the manifest claim is reverted; it only needs
  to move if the sidecar-profile set itself changes.

## Current workflows that remain authoritative and untouched

None of the following justify, or are affected by, a `participant_runtime`
manifest claim. They are Shifter product/runtime access surfaces, not ACES
participant-runtime protocol implementations, and #1291 does not redirect,
weaken, or replace any of their gates:

- **Mission Control terminal access** -- `mission_control.consumers.SSHConsumer`,
  `terminal_sessions`, `terminal_executor`, `engine.services.connect_terminal`,
  and `engine.ssh.SSHConnection` keep their existing authorization, key
  retrieval, capacity, and close-code behavior.
- **Guacamole URLs and token lifecycle** -- `mission_control.guacamole`,
  `mission_control.guacamole_bootstrap`, and `GuacamoleBootstrapRequest` keep
  their signing, TTL, consume-and-clear, and owner-scoped polling semantics
  (see `docs/architecture/guacamole-token-lifecycle-preflight-939.md`).
- **CTF participant range status** -- `ctf.services.participant`,
  `ctf.services.range`, and `ctf.bridges` keep CTF product identity, event
  access, scoring, and range lifecycle behind CTF services.
- **`AcesParticipantRuntimeRecord` sidecars** -- sidecar persistence,
  validation, digesting, idempotency, ownership, retention, and redaction
  stay exactly as implemented for #1288; they prove Shifter can store bounded
  participant-runtime data, not that Shifter implements the ACES
  `ParticipantRuntime` protocol.
- **Command dispatch** -- existing product-level command/action dispatch
  paths stay Shifter-owned and are not reinterpreted as ACES participant
  lifecycle transitions.

## Cross-references

- `docs/architecture/aces-participant-runtime-manifest-conformance-gate-preflight-1291.md`
  -- pre-implementation architecture guidance for #1291; this note fulfills
  its cutover/rollback documentation requirement.
- `docs/architecture/aces-participant-runtime-mission-control-preflight-1236.md`
  -- the participant/Mission Control boundary this note's "untouched
  workflows" section restates.
- `docs/architecture/aces-runtime-target-backend-manifest-preflight-1233.md`
  -- the original manifest/profile design this note extends with
  participant-runtime-specific cutover and rollback detail.
- `docs/architecture/aces-cutover-archive-plan-preflight-1238.md` -- the
  overall ACES cutover and archive doctrine (ADR-024/ADR-027) this note's
  posture is a specific instance of.
- `docs/architecture/aces-migration-parity-inventory.yaml` row
  `validation.participant-runtime-conformance` -- tracks this gate as the
  parity-inventory evidence for the participant-runtime validation surface.
