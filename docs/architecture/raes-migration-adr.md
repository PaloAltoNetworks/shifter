# ADR-024: RAES is a hard cutover

## Status

Accepted. Amended by issues #1862 on 2026-07-28, #1580 on 2026-07-30, and
#1937 on 2026-09-06, and #1583 on 2026-09-13.

## Context

Shifter previously planned a parity-gated parallel migration. That plan has
been superseded. Maintaining two package contracts, transport readers,
configuration surfaces, catalog paths, or provisioning selectors would make
the boundary ambiguous and leave the retired implementation operational.

The released contract pair is `raes==3.5.0` and
`raes-env-packs==5.2.0`. Environment packs require that exact RAE version.
The provisioning transport is `raes-provisioning-plan-v2`; it preserves the
public operations, authority, envelope, constraints, and operation identity.

## Decision

Shifter cuts directly to RAES. The current application has one package
contract, one catalog and ingestion path, one serialized provisioning plan
shape, one provisioner resource family, and one configuration/API/event
vocabulary. It contains no fallback import, old-name alias, dual configuration
read, redirect, old transport reader, compatibility model/view, reversible
runtime selector, or scenario-specific pack path.

Existing scenario content must be republished and registered as a current
`raes-env-packs` environment pack. Retired package-source and operation-sidecar
rows are removed during the schema cutover because their bytes and versions
are not RAES contracts and must not be relabeled as such.

Persisted authored plans and immutable operation envelopes are opaque,
versioned records. The migration never rewrites their nested keys or values
and never claims that an old producer version is RAES 2.0.0. Deployment is
allowed only after all retired provisioning work has drained:

- every range using the retired plan discriminator is terminal;
- every matching instance operation is terminal;
- every matching launch intent is terminal;
- no matching operation result remains pending; and
- no matching range event remains publishable.

The migration fails closed when any of those conditions is false. Terminal
historical operation envelopes remain factual and inert; the current runtime
does not read them.

## Boundaries

- Only `shared.raes` imports the module family supplied by `raes`.
- The standalone provisioner validates and reads serialized plans as plain
  data. Released public RAES accessors are a typed semantic and parity oracle,
  not a reason to import the monolithic RAES distribution across that process
  boundary and not a substitute for exact-pin wire validation.
- The provisioner accepts only `raes_provisioning_plan`,
  `raes-provisioning-plan-v2`, and producer version `3.5.0` for new realization.
  Cleanup alone may read the previous exact `v1` / `2.0.0` pair through an
  isolated view that preserves its resource and secret identities. Persisted
  bytes are never relabeled or rewritten. This narrow RAE version transition
  does not restore the retired pre-RAE runtime.
- Package ingestion accepts only current RAES contract identities and upstream
  environment-pack validation.
- ADR-040 retirement metadata removes the exact retired API paths and response
  fields from the trusted v1 baseline. Current RAES operations are new paths
  and fields; no old-name route, redirect, or response alias remains.
- Shifter-specific authorization, lifecycle, cloud realization, CTF, Mission
  Control, audit, redaction, and operator behavior remain Shifter-owned service
  responsibilities.
- LilRAE (formerly APTL) has no bespoke Shifter surface. TechVault is a
  scenario pack; any future Shifter delivery of it is an ordinary environment
  pack and does not create a separate product or runtime boundary.

## Rollback

There is no in-process or same-schema compatibility rollback. Rollback means
stopping the deployment, restoring the pre-cutover database backup, and
redeploying the preceding release as one coordinated operation. Operators must
not run old and new workers concurrently against one database or re-enable a
retired selector.

## Consequences

- The cutover cannot proceed while old work is in flight.
- Existing packs require republishing and registration.
- Retired package and sidecar records are not presented through current RAES
  models or APIs.
- Historical ADRs, migrations, dated preflights, frozen snapshots, and
  changelog entries keep their factual names; they are not current runtime or
  compatibility surfaces.

## RAE 3.5 completion boundary (#1583)

Native launch returns an enqueue receipt. Queue acceptance does not create a
realized runtime snapshot or satisfy an upstream synchronous apply result.
The worker reads guest OS identity and VM existence independently, verifies
composition, and returns bounded evidence bound to the immutable plan digest,
RAE operation identity, and Shifter execution generation. The engine validates
that evidence through the public RAE realization boundary before READY. Warm
activation produces fresh evidence after access rotation; source content is
verified without installation. Directory access uses the existing idempotent
reconciliation and readback path.

The published manifest includes its configuration-bound realization envelope.
Provisioning protocol tests use a simulated completed dispatch port and cannot
certify cloud effects. RAE 3.5 reports generic-envelope qualification as
unsupported without a constructive specimen and native harness. The test
asserts that limitation explicitly; it does not claim an overall qualification
pass. Live GCP qualification remains tracked by #2082.

The standalone reader rejects malformed present metadata and unsupported
incremental operations. Fresh-create refresh dependencies are accepted only
when they agree with the full plan and are ordering dependencies; this does not
claim support for incremental refresh. Canonical `key` authentication keeps the
stored `account-publickey` secret suffix for cleanup. Authored VM and OS
requirements migrate to explicit substrate constraints and coupled OS fields.
