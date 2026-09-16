# RAES hard-cutover architecture preflight

Date: 2026-07-28
Issue: #1862
Requirement: none; the issue and its clarified hard-cut policy are the contract.

## Decision

Shifter cuts directly to the released RAES distribution pair:

- `raes==2.0.0`; and
- `raes-env-packs==3.0.0`, whose published metadata requires
  `raes==2.0.0`.

The cutover is intentionally incompatible. Current code, dependencies,
configuration, API and event identifiers, database model and physical object
names, user-facing labels, generated artifacts, tests, and technical
documentation use RAES only. There are no fallback imports, old-name aliases,
dual-read configuration keys, redirects, old transport readers, legacy pack
validators, compatibility views, or deprecation shims.

The retired name remains only where changing it would falsify history:
pre-cutover migrations, dated architecture evidence, frozen published
snapshots, changelog history, and migration tests that prove the old database
state upgrades and reverses correctly.

## Contract boundaries

| Surface | Hard-cut rule |
| --- | --- |
| Python distributions | Pin the exact released pair and remove every retired distribution from project and lock metadata. |
| Python imports | `shared.raes` is the only platform layer allowed to import the RAES module family supplied by the `raes` distribution. Environment-pack validation uses `raes_env_packs` behind the existing pack-validation boundary. |
| Environment packs | Accept only the current environment-pack schemas, `raes-environment-pack:/` identities, and maintained validators. Existing content must be republished and registered in the current format; no old validator or schema copy remains. |
| Provisioner transport | Producers emit only `raes_provisioning_plan` with `raes-provisioning-plan-v1` and `raes_version: "2.0.0"`. Consumers accept that exact producer version and reject every other version. |
| Configuration | Rename deployed keys and all renderers/manifests together. No old-key fallback, precedence rule, or dual projection exists. |
| API, events, and persistence | Rename current wire discriminators, routes, fields, event families, model classes, tables, indexes, constraints, and grants. Do not relabel bytes produced under a different versioned contract. |
| Generated artifacts | Regenerate the lock, environment manifest, OpenAPI, frontend types, locale output, and backend manifest from their canonical producers. |
| Architecture enforcement | Keep ADR/rule identities stable while updating active decisions, paths, check names, import contracts, pre-commit wiring, and tests to RAES. Historical evidence paths retain their factual filenames. |

## LilRAE and TechVault scenario-pack excision

The bespoke Shifter implementation that delivered the TechVault scenario pack
using LilRAE (formerly APTL) is removed in full:
scenario templates, Packer definitions, bake scripts and locks, validation
profiles, bootstrap/provisioner modules, workflow branches, configuration,
tests, runbooks, and current technical or user documentation. Shifter does not
depend on LilRAE through the cutover.

If the TechVault scenario pack returns, it enters through the ordinary
`raes-env-packs` ingestion and realization contract. It does not regain
scenario-specific Packer, bootstrap, parser, or platform branches.

## Persistence migration

The cutover uses new Django migrations to rename the model state and physical
tables in place. Indexes and constraints receive current RAES names. The
migrations do not recursively edit JSON or relabel old producer versions.

Deployment requires a complete operational drain. The engine migration aborts
when a retired-plan range or instance is nonterminal, a matching launch intent
is nonterminal, a matching operation result is pending, or a matching event is
still publishable. Terminal historical envelopes remain byte-for-byte factual
and inert. Retired package-source and operation-sidecar rows are removed rather
than advertised through current RAES models and APIs; their packages must be
republished and registered in the current format.

There is no mixed-version database rollback. Operational rollback restores the
pre-cutover database backup and preceding release together, with old and new
workers stopped during the transition. No data-copy table, alias model,
compatibility view, old-contract reader, or runtime selector is introduced.

## Admission and security invariants

- Foreign packs still pass upstream validation, containment checks, bounded
  extraction, canonical digest verification, immutable-object handling, and
  launch-time re-verification.
- RAES parsing and semantic validation remain inside `shared.raes`; the
  separate provisioner repeats plain-data structural and topology admission
  before mutation.
- Existing authorization, ownership, instantiation-policy, redaction, audit,
  and feature-gate boundaries remain in force.
- Delivery bindings remain byte-free and carry no bucket, URL, credential,
  guest path, command, or secret.
- The cutover does not broaden the backend manifest or claim a RAES capability
  merely because the new distribution exposes it.

## Completion gates

- Exact package and transitive-pin tests pass from installed metadata.
- Retired-name scans find only the explicitly historical allowlist.
- LilRAE/APTL legacy-name and TechVault scenario-pack scans find no active
  bespoke surface.
- Forward and reverse migration proofs pass.
- The migration refuses undrained old-version work and preserves opaque
  terminal plan/envelope payloads without rewriting them.
- RAES conformance, pack validation, portal, engine, provisioner, frontend,
  generated-artifact, import-boundary, ADR, workflow, Terraform, Kubernetes,
  and full repository checks pass without weakening an enforcement rule.
