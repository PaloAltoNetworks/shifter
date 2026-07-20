# Registering content packs

Shifter has one way to add scenario content: register a pack. It does not matter
whether the pack shipped in-box, came from a public source, was licensed and
private, or was authored by the operator. The platform never asks how the pack
was obtained. Acquisition and any entitlement are handled out-of-band, before the
pack reaches Shifter (ADR-034).

A pack is registered as a provenance-only reference: Shifter records where the
pack lives (`package_ref`), its version and digest, its contract and profile, and
bounded provenance. It does not copy the pack body into the catalog. Pack content
is defined by the `aces-scenario-packs` contract. Shifter pins
`aces-scenario-packs==2.0.1` with its required `aces-sdl==0.23.0`, and delegates
validation and canonical content identity to those released libraries. A
broken, malformed, or non-conformant pack is rejected.

There are three entrypoints onto the same registration service. All of them are
source-agnostic and entitlement-blind; the only access check is who is authorized
to register content (active staff or Threat Research membership, or a token with
the `cms:authoring:write` scope), never whether they were entitled to obtain the
pack.

## API

`POST /api/v1/cms/catalog/packs/` with the `cms:authoring:write` scope:

```json
{
  "scenario_id": "example-pack",
  "source_kind": "repo",
  "contract_kind": "aces",
  "contract_profile": "shifter",
  "package_ref": "scenario-dev/example-pack",
  "package_version": "0.1.0",
  "package_digest": "sha256:<64 hex>",
  "provenance": {"repo": "acme/catalog"}
}
```

A `201` returns the registered `scenario_id`, `source_kind`, and
`conformance_status`. Validation and conflict failures return the standard error
envelope.

## CLI

```sh
python manage.py register_pack \
  --scenario-id example-pack \
  --source-kind repo \
  --package-ref scenario-dev/example-pack \
  --package-version 0.1.0 \
  --package-digest "sha256:<64 hex>" \
  --actor <username>
```

## In-box catalog

The packs Shifter ships by default are declared in
`cms/scenarios/inbox_packs/manifest.yaml` and registered through the same service
by `python manage.py bootstrap_inbox_catalog --actor <username>`. There is no
privileged load path for the in-box catalog: it is registered exactly the way an
operator registers their own content. The bootstrap is idempotent, so it is safe
to run after each deploy. It validates the complete declaration before writing
and registers the batch atomically: a missing/malformed manifest or any invalid
or drifted entry fails visibly and leaves no partially installed batch. No
conformant default packs ship yet, so the manifest is currently empty.

## Resolution and launchability

`repo` packs resolve under `ACES_PACKAGE_ROOT` with containment enforcement, and
`package_ref` names the pack root, not an SDL file. The root directory name,
catalog id, and `pack.yaml` name must agree, so one immutable pack cannot be
registered under arbitrary aliases. The current Shifter profile requires
exactly one direct `sdl/*.sdl.yaml` entry; zero or multiple entries fail closed
until an explicit variant selector is part of the contract.

Every repo pack must declare `associated_artifact_manifest` in `pack.yaml`. That
ACES manifest must cover the exact pack inventory and bind every payload byte to
one canonical `sha256:<64 lowercase hex>` set digest. Registration verifies the
advertised `package_digest` before persistence. Native launch verifies the same
digest again before SDL resolution, parsing, planning, or dispatch, so a pack
changed or replaced after registration cannot execute. Stage repo packs
immutably for both operations; mutable working trees are not a supported
deployment surface.

`object` (object-storage) packs are launchable (#1567). `package_ref` names a
single immutable archive object holding the pack (one archive per ref, not a
storage prefix used as a directory). At launch the resolver downloads that
archive from the configured package bucket into a private temporary directory,
safely extracts it under fail-closed bounds (archive/uncompressed size and entry
caps; absolute paths, `..` traversal, symlinks, hardlinks, and device/special
files are rejected), then re-runs the upstream pack contract validation, asserts
the extracted pack identity equals the registered `scenario_id`, and verifies the
same canonical `package_digest` (the equivalent containment and immutable-identity
guarantees repo packs get, ADR-034-R5), all before SDL resolution, parsing,
planning, or dispatch. The staged directory is always removed afterward.

Object launch requires deployment configuration: set `SHIFTER_ACES_PACKAGE_BUCKET`
(and optionally `SHIFTER_ACES_PACKAGE_PREFIX`) on the app, and grant the portal
workload least-privilege read-only access to that bucket/prefix in Terraform
(`aces_package_bucket_arn` on AWS, `aces_package_bucket_name` on GCP). With no
bucket configured an object row stays registrable and visible in the catalog but
non-launchable (fail closed): a readiness decision, not a catalog-time network
probe. Size and traversal bounds are tunable via `SHIFTER_ACES_PACKAGE_MAX_ARCHIVE_BYTES`,
`SHIFTER_ACES_PACKAGE_MAX_UNCOMPRESSED_BYTES`, and `SHIFTER_ACES_PACKAGE_MAX_ENTRIES`.

Registration is not conformance and is not launchability. A caller cannot assert
that a pack has passed conformance: every registration lands non-passed, and
conformance is promoted out of band by a trusted conformance process. A
registered pack may remain review-only or non-realizable, and launchability
continues to be decided by the registry.

## Image-optional packs and parameterized runs

Image-bearing is optional (ADR-034). A pack whose SDL declares no VM image
`source` is valid content: it imports through the same registration service,
appears in the catalog, and is not failed by realizability merely for lacking
images. Image count is never a realizability proxy. Absence of an authored image
is not the same as "always launchable": a source-less VM still needs the backend
to supply a base OS at realization (the tenant-managed ACES image registry), and
a scenario whose plan requires an unsupported backend term still fails closed.

A scenario's runs may be parameterized through ACES SDL `variables`: the
multi-run experiment unit over one scenario/profile. Shifter represents a
parameterized run as `scenario_id + profile + parameter binding identity`,
validated against the scenario's declared variables (via the ACES SDL
instantiation contract) before planning. Parameter values are never persisted:
the package record stays provenance-only, a run is identified by a one-way digest
of its binding, and the catalog-model run-capability projection surfaces only a
bounded schema (each variable's name, type, whether it is required, whether it
has a default, and how many allowed values it declares), never the authored
defaults, allowed-value enumerations, or per-run values.
