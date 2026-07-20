# Polaris SDL — design rationale

This directory holds the Polaris Operation Northstorm scenario in
[aces-sdl][aces-sdl] form:

- `polaris-operation-northstorm.sdl.yaml` — full event scenario (~1.7k LOC,
  17 nodes: domain controller + 16 mission assets).
- `polaris-demo-minimal.sdl.yaml` — small smoke variant used by the
  scenario-content smoketest harness (issue #617).

## Why a single monolithic file

Issue #691 ("Refactor Polaris scenario support scripts and large scenario
assets") asks that large scenario assets either be **split for review** or
be **explicitly justified as authored/static artifacts**. The Polaris SDL
takes the second path:

1. **The SDL is the source of truth.** Splitting it into per-asset or
   per-mission files would create a generator / merge step. The aces-sdl
   loader does not own one today; the live-event deploy and the scenario
   smoketest both read the YAML directly.
2. **No generator means no verification gate for splits.** A multi-file
   layout that is hand-merged loses the topology and credential-coupling
   invariants the YAML enforces today. The preflight note for this issue
   (`docs/architecture/polaris-support-decomposition-preflight-691.md`,
   §157) is explicit that "split or generate only when the source,
   generator, and verification path stay reviewable."
3. **#620 is the path forward.** The scenario-expressiveness work tracked
   in #620 owns the long-term move toward declarative composition (and
   away from monolithic SDL). When that lands, an aces-sdl generator and
   per-asset review surface fall out of it; until then, this file stays as
   the authored single source.
4. **Review is already mission-scoped.** Every block has a `name:` /
   `category:` aligned with the mission table in
   `../design/architecture.md`, so reviewers can locate a mission's nodes
   by jumping to its name. The intent is reviewable as-is.

If you change a Polaris asset, change it here. Do not generate this file
from a parallel source until #620 supplies the generator.

[aces-sdl]: ../design/aces-sdl-validation-path.md

## Related

- `../README.md` — overall Polaris layout (build/ vs sdl/ vs containers/).
- `../design/architecture.md` — zone map and per-mission asset table.
- `../design/shared-constants.md` — cross-asset constants and credentials.
- `../tests/run-all-smoketests.sh` — per-asset smoketests; topology
  assertions live here and must keep passing after any SDL edit.
- Live-event deploy path stays through `build/`, not `sdl/`; this
  directory feeds the aces-sdl / APTL validation path.
