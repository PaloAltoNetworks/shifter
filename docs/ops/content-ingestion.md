# Registering content packs

Shifter has one way to add scenario content: register a pack. It does not matter
whether the pack shipped in-box, came from a public source, was licensed and
private, or was authored by the operator. The platform never asks how the pack
was obtained. Acquisition and any entitlement are handled out-of-band, before the
pack reaches Shifter (ADR-034).

A pack is registered as a provenance-only reference: Shifter records where the
pack lives (`package_ref`), its version and digest, its contract and profile, and
bounded provenance. It does not copy the pack body into the catalog. Pack content
is defined by the `raes-env-packs` contract. Shifter pins
`raes-env-packs==5.2.0` with its required `raes==3.5.0`, and delegates
validation, canonical content identity, and the artifact-requirement publication
profile to those released libraries. A broken, malformed, or non-conformant pack
is rejected.

All entrypoints use the same source-agnostic, entitlement-blind registration
service. Tenant installation requires organization-admin authority; deployment-wide
registration requires active staff or Threat Research membership (or the
corresponding `cms:authoring:write` token scope).

## Tenant installation

Open **Administer → Adapters → Install packs and assign adapters**. Select the
organization, enter the author's pack name and upload its `.tar` or `.tar.gz`
archive. Review and confirm installation. Shifter validates the archive and pack
contract before registering it for that organization. The content pack and its
executable adapter are installed independently; assign an adapter if required.
No cloud-console or command-line step is needed.

To update a pack, select **Update** for the existing pack and upload the new
version. The request includes the displayed digest; a concurrent update fails
and requires reloading the current version. Existing ranges retain their original
inputs. Assign the adapter to the new pack digest before launching again.

The session API is `POST /api/v1/cms/organizations/<uuid>/packs/`, with multipart
fields `name`, `archive`, and optional `expected_digest` for an update. The server
selects the storage object and catalog identity. Ownership stays outside the
portable pack contract. Organization membership gates reads and workspace binding
gates launch; staff status alone does not disclose tenant-owned packs.

The tenant assets bucket is the default upload destination. An explicit
`SHIFTER_RAES_PACKAGE_BUCKET` overrides it. Standard deployment permissions include
upload and failed-upload cleanup for the portal, while isolated adapters have no
storage access. Archives are bounded to 256 MiB compressed, 1 GiB expanded and
20,000 entries by default. Interrupted uploads may leave unreferenced objects;
previous registered revisions are retained for in-flight operations.

## API

`POST /api/v1/cms/catalog/packs/` with the `cms:authoring:write` scope:

```json
{
  "scenario_id": "example-pack",
  "source_kind": "repo",
  "contract_kind": "raes",
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

To move a registered scenario to a new package version, include
`expected_package_digest` with its current digest and supply the new version,
reference and digest. The CLI accepts the same precondition as
`--expected-package-digest`. Shifter locks the current registration, rejects a
stale precondition or a changed identity under the same version, and audits the
previous and new references together. The replacement starts with pending
conformance; it must pass the trusted conformance process again. Existing range
operation inputs remain unchanged.

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

## In-box bootstrap seed

The packs Shifter registers into the tenant by default (an in-box bootstrap
seed, not a shipped distribution catalog) are declared in
`cms/scenarios/inbox_packs/manifest.yaml` and registered through the same service
by `python manage.py bootstrap_inbox_catalog --actor <username>`. There is no
privileged load path for the seed: it is registered exactly the way an
operator registers their own content. The bootstrap is idempotent, so it is safe
to run after each deploy. It validates the complete declaration before writing
and registers the batch atomically: a missing/malformed manifest or any invalid
or drifted entry fails visibly and leaves no partially installed batch. The
manifest declares the in-box bootstrap seed.

A shipped revision declares its expected predecessor explicitly. The RAES 3.5
smoke pack is version `0.2.0`; bootstrap upgrades the known `0.1.0` digest through
the same registration service, then runs release conformance. A customized or
unexpected tenant digest remains a visible conflict.

## Resolution and launchability

`repo` packs resolve under `RAES_PACKAGE_ROOT` with containment enforcement, and
`package_ref` names the pack root, not an SDL file. The root directory name,
catalog id, and `pack.yaml` name must agree, so one immutable pack cannot be
registered under arbitrary aliases. The current Shifter profile requires
exactly one direct `sdl/*.sdl.yaml` entry; zero or multiple entries fail closed
until an explicit variant selector is part of the contract.

Every repo pack must declare `associated_artifact_manifest` in `pack.yaml`. That
RAES manifest must cover the exact pack inventory and bind every payload byte to
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
planning, or dispatch. The pinned env-packs flat export format is staged under
the registered scenario name; single-directory wrapped archives remain supported.
Both formats pass the same guards and identity checks. The staged directory is
always removed afterward.

Object launch requires deployment configuration: set `SHIFTER_RAES_PACKAGE_BUCKET`
(and optionally `SHIFTER_RAES_PACKAGE_PREFIX`) on the app, and grant the portal
workload least-privilege read-only access to that bucket/prefix in Terraform
(`raes_package_bucket_arn` on AWS, `raes_package_bucket_name` on GCP). With no
bucket configured an object row stays registrable and visible in the catalog but
non-launchable (fail closed): a readiness decision, not a catalog-time network
probe. Size and traversal bounds are tunable via `SHIFTER_RAES_PACKAGE_MAX_ARCHIVE_BYTES`,
`SHIFTER_RAES_PACKAGE_MAX_UNCOMPRESSED_BYTES`, and `SHIFTER_RAES_PACKAGE_MAX_ENTRIES`.

Registration is not conformance and is not launchability. A caller cannot assert
that a pack has passed conformance: every registration lands non-passed, and
conformance is promoted out of band by a trusted conformance process. A
registered pack may remain review-only or non-realizable, and launchability
continues to be decided by the registry.

Run conformance for a newly registered or replaced pack with the trusted command:

```sh
python manage.py validate_pack_conformance --actor OPERATOR_USERNAME \
  --scenario-id example-pack --expected-package-digest 'sha256:<64 hex>'
```

The command retrieves and verifies the registered bytes, loads the public SDL,
compiles through the real backend planner and validates the provisioner contract.
It commits the result only if the entire package reference still matches. The
caller cannot supply a passing result or report. This works for both repo and
private object packs after tenant setup, using the same check as in-box packs.

Contract conformance is separate from current artifact availability. A pack may
pass structural conformance while its explicitly permitted preparation remains
necessary. Ordinary launch must still resolve its actual artifacts and pass
backend admission. Follow [artifact preparation](artifact-preparation.md) to
install private adapters, prepare supported artifacts and inspect cleanup.

## Artifact requirements, image-optional packs, and parameterized runs

Image-bearing is optional (ADR-034). A pack whose SDL declares no VM image
`source` is valid content: it imports through the same registration service,
appears in the catalog, and is not failed by realizability merely for lacking
images. Image count is never a realizability proxy.

For each artifact concern, Shifter preserves the RAES author posture:

- an exact artifact must resolve to that artifact and cannot be replaced by a
  "close enough" catalog entry or a newly built image;
- a constrained concern may use only a candidate satisfying every bound;
- an open concern may be delegated only when the selected backend declares the
  corresponding realization capability; and
- an absent concern is not an implicit image or bake request.

An artifact already present in the tenant, a published release artifact,
backend composition, and an explicitly permitted preparation specification are
possible satisfaction mechanisms, not a required or exhaustive menu. Pulling is
an acquisition operation, while baking is one possible preparation operation;
they are not opposite semantic choices. Absence of an authored image is not the
same as "always launchable": a source-less VM may still need the backend to
supply a base OS at realization, and a scenario whose plan requires an
unsupported backend term still fails closed.

A scenario's runs may be parameterized through RAES SDL `variables`: the
multi-run experiment unit over one scenario/profile. Shifter represents a
parameterized run as `scenario_id + profile + parameter binding identity`,
validated against the scenario's declared variables (via the RAES SDL
instantiation contract) before planning. Parameter values are never persisted:
the package record stays provenance-only, a run is identified by a one-way digest
of its binding, and the catalog-model run-capability projection surfaces only a
bounded schema (each variable's name, type, whether it is required, whether it
has a default, and how many allowed values it declares), never the authored
defaults, allowed-value enumerations, or per-run values.
