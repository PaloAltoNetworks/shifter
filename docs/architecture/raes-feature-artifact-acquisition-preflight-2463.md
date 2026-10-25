# RAES Feature-Artifact Acquisition Preflight

Issue: GitHub #2463, "Realize Claude Code as a scenario-declared feature instead
of baking it into images."

Status: pre-implementation architecture guidance. This note revises ADR-034
(rules R4, R6, R7, and new R11 and R12) and ADR-032 (rules R3 and R9). It
does not implement acquisition, resolution, or streaming delivery.

## Problem

Range images bake third-party software that Shifter must not redistribute. The
motivating case is Claude Code: its package license reserves all rights, so a
published image or pack that contains it redistributes it. The software has to
reach range guests at realization without any Shifter artifact carrying its
bytes.

Today a source-backed RAES feature can only resolve to bytes inside the pack
(ADR-034-R6, R7). A pack that carried such software would redistribute it, so
that route is closed. Shifter also has no step that obtains an artifact from
upstream, and the provisioner reads a whole payload into memory, which is why
`RAES_CONTENT_DELIVERY_MAX_PAYLOAD_BYTES` caps delivery at 256 MiB.

## Decision

1. **Scenarios declare, packs never carry.** A scenario declares the software as
   a standard RAES feature on the hosts that need it, by source name and
   version only. No pack (in-box or external) bundles the bytes, and no scenario
   adapter carries software-specific logic.
2. **Backend-owned artifacts acquired by platform recipes.** A feature source
   with no matching pack projection entry may be satisfied by a backend-owned
   artifact (RAES mechanism `backend-owned-artifact`, or `exact-artifact` for an
   exact requirement) that Shifter acquires with a platform-owned recipe
   (acquisition `pull`, timing `backend-preparation`).
   - A recipe is reviewed platform code that maps one known source name to an
     upstream location, an integrity check, and an extraction rule. Unknown
     source names fail; there is no generic URL fetch and no pack-supplied
     recipe.
   - Recipes fetch only publicly available packages without credentials. The
     deploying organization holds the license relationship. Shifter never
     republishes acquired bytes in an image, pack, or registry.
3. **RAES semantics choose the version.** An exact version is honored exactly; a
   constrained requirement admits only a conforming version. An unspecified
   version (`"*"`) with an open scope lets the platform choose, deterministically,
   from a platform-configured default version per source. The resolved version
   is recorded in the range binding and evidence. Declared `permitted_routes` are
   honored; a requirement that does not permit backend acquisition fails
   satisfaction.
4. **Tracked in the platform database, stored where delivery already reads.** An
   Engine-owned inventory row records each acquired artifact: source name, resolved version, platform,
   content-addressed object key, sha256, byte count, upstream reference and
   integrity, state, and attempt timestamps. The bytes live in the existing
   provider-neutral object storage under the existing content-addressed delivery
   prefix. The row is an inventory of backend-owned artifacts, owned by Engine
   beside `RaesImageMapping` for images (the layering lets CMS call
   `engine.services`, not the reverse, and the launcher that runs acquisition
   Jobs is Engine); it is not a parallel artifact store.
5. **Acquire once, before ranges need it.** Registering or updating a pack
   triggers acquisition for its declared feature sources, and deploy bootstrap
   does the same for registered packs. A request first checks for a `ready` row
   whose object is present with a matching digest; if found, nothing is fetched.
   Otherwise the first requester claims the row and starts one dedicated
   acquisition Job. Concurrent requesters wait on that attempt; there is never a
   second concurrent download. No operator step exists.
6. **Per-range hard failure.** Materialization requires every declared feature
   to resolve to a `ready` artifact. A launch waits a bounded time for an
   in-flight attempt. If the artifact cannot be acquired, that range fails
   materialization before any cloud mutation, as the RAES runtime contract
   requires. Failure is per range: scenarios are stamped into many independent
   ranges, and one range failing is not a failure for the others. A failed
   attempt is not cached as permanent; a later request starts a fresh attempt
   after a short backoff.
7. **Streaming delivery, no fixed size cap.** The provisioner downloads the
   payload to a temporary file while hashing it, streams it to the guest in
   chunks over the existing authenticated channel, and keeps the in-guest digest
   readback. Memory stays constant regardless of payload size. The fixed
   256 MiB policy cap is removed; the remaining bounds are real ones (the stored
   object's exact size and the destination's free space, checked before
   transfer). The delivery binding stays byte-free and its contract is
   unchanged.

## ADR Changes

- **ADR-034-R4:** recipe acquisition of publicly available packages without
  credentials is not an entitlement system; licensing stays with the deploying
  organization, and acquired bytes are never republished.
- **ADR-034-R6:** a source binds to pack-associated input, or, for a feature
  artifact only, to a backend-owned artifact acquired under ADR-034-R11.
- **ADR-034-R7:** the acquired-artifact inventory is not a parallel feature
  artifact store; it uses the same content-addressed storage, binding, guest
  transport, and readback.
- **ADR-034-R11 (new):** platform-owned recipe acquisition of feature artifacts.
- **ADR-034-R12 (new):** acquisition timing, single flight, and per-range
  failure.
- **ADR-032-R3:** the delivery binding carries the stored object's exact byte
  count rather than a policy-bounded one.
- **ADR-032-R9:** delivery streams with constant memory and no fixed payload cap.

## Canonical Incumbents To Reuse

- Feature authoring and admission: RAES `Feature`, `Source`, and
  `ArtifactRequirement`; `shared/raes/composition_envelope.py`.
- Content-addressed storage and keys: `ObjectStorage`
  (`shared/cloud/types.py`), `normalized_storage_key`
  (`shared/raes/content_delivery.py`), the upload-if-absent promotion in
  `shared/raes/content_delivery_prep.py`.
- Delivery binding and transport: `DeliveryBinding` v2 (feature-binding, file,
  executable), `RaesContentDeliveryBinding`, the operation-input projection in
  `engine/operation_inputs.py`.
- Provisioner delivery and readback: `raes_delivery_contract.py`,
  `raes_content_delivery.py`, `plans/raes_content_delivery.py`.
- Satisfiability: `shared/raes/artifact_inventory.py`
  (`resolve_plan_artifact_bindings`), extended from node sources to feature
  sources.
- Isolated execution: the provisioner Job launch path and the jobs-namespace
  egress policy, reused for the acquisition Job.

## Gotchas And Anti-Patterns

- Do not add a recipe field to packs or scenarios; recipes are platform code.
- Do not resolve open versions to "latest upstream" at fetch time; resolution is
  deterministic and recorded.
- Do not let guests fetch from upstream or from object storage.
- Do not treat a failed attempt as permanent, and do not fail other ranges
  because one range failed.
- Do not introduce an operator command into the normal flow.
- Do not reintroduce a fixed payload cap through a different setting.

## Non-Goals

- No scenario-specific images, bakes, or content in Shifter. External scenario
  packs keep their own content in their own repositories and declare software by
  version.
- No credentialed or private upstream sources in this revision.
- No change to service features, which still install from the guest package
  repository.
- Removing the software from existing bakes happens only after this capability
  is live, so ranges never lose it in between.
