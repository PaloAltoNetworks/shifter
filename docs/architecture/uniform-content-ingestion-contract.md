# ADR-034: Uniform content-ingestion contract

## Status

Accepted.

## Date

2026-07-11

## Context

An operator running a packaged Shifter tenant must be able to add new images to
the runtime catalog, import scenario packs (see `../aces-scenario-packs` for the
pack format), and author their own scenarios. Today these read as three
different mechanisms, and the shipped catalog is loaded through a privileged
in-box path distinct from how an operator would add anything.

Several facts constrain the design:

- **Provenance is diverse and mostly irrelevant to the platform.** Content may
  ship in-box, come from a public source Shifter hosts, be licensed/private, or
  be authored by the operator. Whether an operator is *entitled* to a piece of
  content is a question resolved at acquisition, outside the platform. Only if
  the platform itself auto-fetches gated content does a credential enter, and
  even then it is operator-supplied config (like a private registry login), not
  an entitlement system the platform owns.
- **Trust is a separate axis from entitlement.** Once content is in hand, the
  platform does care whether a pack is authentic and safe to run (it bakes
  images and runs privileged content). That is optional signing/verification, a
  trust signal keyed on the producer, not an access gate keyed on the operator.
- **Not every pack has images.** Some packs are structure only; large parts of
  an experiment (the multi-run unit of a scenario) are parameterized, with
  images supplied per run or not at all.
- **We do not create loopholes in ACES.** If a scenario requires an image or
  capability the backend cannot provide, that scenario is not realizable, and
  the author should be told, ideally in the scenario editor, rather than
  discovering it at provision time.
- Image distribution is asymmetric: container images distribute globally via a
  public registry, while VM images are region/project-scoped and expensive to
  host and cross-copy.

## Decision

Content ingestion is one uniform contract, governed by the surface separation in
ADR-033.

- **The pack is the universal unit.** "Add an image to the catalog," "import a
  scenario pack," and "author a scenario" are the same operation: register a
  pack. The in-box catalog is simply the packs that ship by default; it is not a
  privileged path.

- **Import is source-agnostic and entitlement-blind.** The ingestion path is
  identical for shipped, public, private, and self-authored packs. The platform
  never asks how the operator obtained a pack. Adding content is *just a content
  update*; how the operator got it is out of scope.

- **Repo pack identity is byte-bound at ingestion and use.** A repository
  `package_ref` identifies a containment-checked pack root. Registration uses
  the canonical ACES associated-artifact manifest to bind the advertised digest
  to the exact inventory and payload bytes; native launch verifies that digest
  again before resolving or executing SDL. This trust control is identical for
  shipped, public, private, and self-authored content and is not entitlement.

- **Materialization is per-pack pull-or-bake.** Each image a pack needs carries
  a reference (pull) and/or a bake recipe (build). At provision time the tenant
  pulls a published image when one is available for its cloud/region, otherwise
  bakes it in-tenant from the recipe. Pull-vs-bake is a property of the pack, not
  a global mode; a pack may offer both.

- **Packs may carry no images and may define parameterized experiment runs.**
  Ingestion, the catalog, and realizability treat "image-bearing" as optional.

- **Ingestion validates realizability against the backend manifest.** A pack
  that a conformant Shifter backend cannot realize is flagged (no silent
  loopholes) and surfaced to the author (the scenario editor is the natural
  place). This uses the ACES backend manifest and realizability ledger.

- **Content is the source of truth; a published image is a cache.** Distribution
  (ADR-033) publishes finished images as a convenience over the real artifact
  (content + recipe). Public and private distribution tiers differ only in where
  the output is served; entitlement for the private tier is handled out-of-band,
  and trust/verification is an orthogonal, optional signal.

## Consequences

- One ingestion path serves operators and maintainers; the shipped catalog loads
  through it (dogfooding, per ADR-033).
- Repo content must be staged immutably with a conformant associated-artifact
  manifest; changed or ambiguously rooted content fails closed at registration
  or launch.
- The pack schema must express, per image, a reference and/or a bake recipe, and
  must allow zero images and parameterized runs.
- Realizability becomes a first-class, author-visible check, wired from the
  manifest/ledger into the scenario editor.
- The platform carries no entitlement system; private content is gated at
  acquisition. In-platform pull-through, if added, consumes an operator-supplied
  credential only.
- This contract is realized by the issues under program #1584 and cross-links
  the REV1.2 realizability ledger (#1563) and object-storage package sources
  (#1567), and the ACES catalog/registry work under ADR-024 (#1252, #1253,
  #1254). It builds on backend bundles (ADR-011) and the substrate interface
  (#1322).

## Alternatives considered

- **Distinct paths for shipped vs. imported vs. authored content.** Rejected:
  privileges the in-box catalog, blocks turnkey operator extension, and
  duplicates logic.
- **A platform-owned entitlement system for private content.** Rejected:
  entitlement is an acquisition/business concern; embedding it couples the
  product to a licensing system and violates entitlement-blind ingestion.
- **Global "ship images" or global "ship content-to-bake" policy.** Rejected in
  favor of per-pack pull-or-bake, because image types distribute asymmetrically
  and some packs cannot ship a pullable image at all.
