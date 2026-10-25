# RAES default cutover (#1310)

Status: activated by #1311.

RAES is the sole scenario catalog, authoring, launch, and realization authority.
The temporary native-provisioning flag and catalog route selector have been
removed from application settings and every deployment renderer. A catalog id
resolves directly to one digest-bound `RaesPackageSource`; there is no legacy
fallback or in-process rollback selector.

## External pack registration

Scenario packs are installed through validated tenant registration. Catalog
presentation and range dispatch consume the registered source and immutable
pack digest. An administrator separately installs and binds an isolated adapter;
pack content cannot select or authorize executable installation. Core ships no
private scenario implementation or private image recipes.

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
