# ADR-034: Uniform content-ingestion contract

## Status

Accepted.

## Date

2026-07-11

Amended 2026-07-27 to replace the pull-or-bake dichotomy with RAES artifact
requirement satisfaction semantics and to correct the claim that every
published image is a rebuildable cache.

## Context

An operator running a packaged Shifter tenant must be able to add new images to
the runtime catalog, import environment packs (see `raes-env-packs` for the
pack format), and author their own scenarios. Today these read as three
different mechanisms, and the in-box default content is loaded through a
privileged path distinct from how an operator would add anything.

Several facts constrain the design:

- **Provenance is diverse and mostly irrelevant to the platform.** Content may
  ship in-box, come from a public source Shifter hosts, be licensed/private, or
  be authored by the operator. Whether an operator is *entitled* to a piece of
  content is a question resolved at acquisition, outside the platform. Only if
  the platform itself auto-fetches gated content does a credential enter, and
  even then it is operator-supplied config (like a private registry login), not
  an entitlement system the platform owns.
- **Trust is a separate axis from entitlement.** Once content is in hand, the
  platform does care whether a pack and its artifacts are authentic and safe to
  use. That is signing, verification, provenance, and admission policy keyed on
  the producer and bytes, not an access gate keyed on the operator.
- **Not every pack has images.** Some packs are structure only; large parts of
  an experiment (the multi-run unit of a scenario) are parameterized, with
  images supplied per run or not at all.
- **We do not create loopholes in RAES.** If a scenario requires an image or
  capability the backend cannot provide, that scenario is not realizable, and
  the author should be told, ideally in the scenario editor, rather than
  discovering it at provision time.
- Image distribution is asymmetric: container images distribute globally via a
  public registry, while VM images are region/project-scoped and expensive to
  host and cross-copy.

## Decision

Content ingestion is one uniform contract, governed by the surface separation in
ADR-053.

- **The pack is the universal unit.** "Add an image to the catalog," "import a
  scenario pack," and "author a scenario" are the same operation: register a
  pack. The in-box packs are simply the tenant's default registered content,
  seeded through the same path; they are not a privileged path and are not a
  BigRAE-shipped distribution catalog.

- **Import is source-agnostic and entitlement-blind.** The ingestion path is
  identical for packs from any origin, whether upstream-published, private, or
  self-authored. The platform never asks how the operator obtained a pack. Adding
  content is *just a content update*; how the operator got it is out of scope.

- **Repo pack identity is byte-bound at ingestion and use.** A repository
  `package_ref` identifies a containment-checked pack root. Registration uses
  the canonical RAES associated-artifact manifest to bind the advertised digest
  to the exact inventory and payload bytes; native launch verifies that digest
  again before resolving or executing SDL. This trust control is identical for
  packs from any origin and is not entitlement.

- **Artifact satisfaction preserves RAES author intent.** Artifact requirements
  follow the RAES exact, constrained, open, and absent realization classes. An
  exact artifact MUST be honored; a constrained requirement may be satisfied
  only by a candidate within its bounds; an open concern may be delegated only
  to a backend that declares the matching capability; and absence is not an
  implicit request for an image. Shifter does not downgrade or replace those
  classes with a pack-local pull-or-bake mode.

- **Satisfaction mechanism, acquisition transport, and timing are independent.**
  Depending on the requirement and backend, a feasible realization may use an
  exact immutable artifact, an already-available backend artifact, an
  upstream-published pack candidate, dynamic composition, or an explicitly
  permitted materialization specification. This is not a closed list. Pulling, copying,
  importing, or locally finding an artifact describes acquisition, not author
  intent. Preparation may happen at publication, ingestion, explicit backend
  staging, or realization as the governing contract permits. Shifter never
  starts a long-running VM-image bake on the provisioning critical path.

- **Packs may carry no images and may define parameterized experiment runs.**
  Ingestion, the catalog, and realizability treat "image-bearing" as optional.

- **Ingestion validates realizability against the backend manifest.** A pack
  that a conformant Shifter backend cannot realize is flagged (no silent
  loopholes) and surfaced to the author (the scenario editor is the natural
  place). This uses the RAES backend manifest and realizability ledger.

- **Authority is declared, not inferred from artifact form.** The portable RAES
  requirement is the semantic authority. A published image may itself be the
  exact required artifact, one allowed candidate, or an optimization over a
  reproducible materialization path. It is not inherently a cache or substitute,
  and Shifter does not assume that licensed, opaque, externally governed, or
  exact-required artifacts can be rebuilt from source. Public and private
  acquisition origins differ in acquisition policy; trust and provenance remain
  orthogonal.

## Consequences

- One ingestion path serves operators and maintainers; the in-box packs load
  through it (dogfooding, per ADR-053).
- Repo content must be staged immutably with a conformant associated-artifact
  manifest; changed or ambiguously rooted content fails closed at registration
  or launch.
- The pack publication contract carries or references only the artifacts,
  locked inputs, materialization specifications, and availability claims
  permitted by the upstream RAES requirement. It must allow zero images and
  parameterized runs, and it must not invent alternatives to an exact
  requirement.
- Realizability becomes a first-class, author-visible check, wired from the
  manifest/ledger into the scenario editor.
- The platform carries no entitlement system; private content is gated at
  acquisition. In-platform pull-through, if added, consumes an operator-supplied
  credential only.
- This contract is realized by the issues under program #1584 and cross-links
  the REV1.2 realizability ledger (#1563) and object-storage package sources
  (#1567), and the RAES catalog/registry work under ADR-024 (#1252, #1253,
  #1254). It builds on backend bundles (ADR-011) and the substrate interface
  (#1322).

## Alternatives considered

- **Distinct paths for shipped vs. imported vs. authored content.** Rejected:
  privileges the in-box default content, blocks turnkey operator extension, and
  duplicates logic.
- **A platform-owned entitlement system for private content.** Rejected:
  entitlement is an acquisition/business concern; embedding it couples the
  product to a licensing system and violates entitlement-blind ingestion.
- **Per-pack pull-or-bake.** Rejected because it conflates acquisition with
  materialization and treats two mechanisms as exhaustive. It also incorrectly
  turns exact artifacts into substitutes and assumes every non-published
  requirement has a build recipe.
- **Global "ship images" or global "ship content-to-build" policy.** Rejected:
  artifact authority, available candidates, backend capability, location, and
  permitted realization timing vary independently.
