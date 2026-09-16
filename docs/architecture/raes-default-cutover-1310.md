# RAES default cutover (#1310)

Status: activated by #1311.

RAES is the sole scenario catalog, authoring, launch, and realization authority.
The temporary native-provisioning flag and catalog route selector have been
removed from application settings and every deployment renderer. A catalog id
resolves directly to one digest-bound `RaesPackageSource`; there is no legacy
fallback or in-process rollback selector.

## Polaris activation

The stable public id `polaris` is the identity of the canonical in-repository
environment pack at `scenario-dev/polaris`. The shipped inbox manifest registers
that pack through the same validated registration service used for external
packs and binds its canonical digest. Catalog presentation and range dispatch
consume that registered source directly.

The previous YAML portal scenario and standalone AWS Terraform/script harness
are retired. They are not alternative launch authorities or rollback paths.
Polaris changes now follow the environment-pack validation, provenance,
conformance, digest, realizability, and publication gates.

## Lifecycle and rollback

Range creation always compiles and persists a serialized RAES provisioning plan.
Lifecycle operations select the provisioner family from the persisted plan kind,
not from current catalog configuration. Rollback is therefore an ordinary code
rollback that preserves persisted lifecycle compatibility; it is not an
environment toggle that restores legacy scenario creation.

## Evidence boundary

Repository tests prove the hard cut, package identity, conformance inputs, and
absence of the retired selectors and authoring paths. They do not claim a live
tenant deployment. At cutover time there were no live or development Shifter
deployments. Final live validation on both AWS and GCP is tracked as GitHub issue
#2043, the final child of #1319.
