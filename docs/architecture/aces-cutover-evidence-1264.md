# ACES-native provisioning: cutover evidence (#1264)

This note describes the live-validation evidence path that proves the Shifter
ACES-native provisioning-only backend can provision a range and report its
operational evidence through the normal Shifter path, not a demo shortcut. It is
the cutover evidence gate for ADR-031 / ADR-032.

Design source: `docs/architecture/aces-runtime-target-backend-manifest-preflight-1233.md`.

## What it proves

A registered ACES package, launched with `SHIFTER_ACES_NATIVE_PROVISIONING`
enabled, travels the same path a product range launch takes:

1. `cms.services.create_range_dispatch` routes the ACES scenario to
   `create_range_dispatch -> create_aces_native_range` (ADR-031-R5).
2. `shared.aces.package_loader` resolves the registered pack root after CMS
   verifies its canonical content digest, selects its single direct SDL entry,
   compiles it with `aces-sdl`, plans it against the provisioning-only backend,
   and dispatches the compiled plan through `CmsAcesDispatchPort ->
   engine.services.create_aces_range`.
3. The engine persists the serialized plan keyed by `request_id`, writes the
   operation receipt, and starts the provisioner `aces-range` task.
4. The provisioner realizes the topology and emits `operation_status` and
   `runtime_snapshot` evidence back through the outbox to the sidecar records.
5. The evidence is read back through the redacted Mission Control read seam
   (`shared.aces.projections`).

The validation asserts a non-vacuous realization: an accepted operation receipt,
a `succeeded` operation status, and a runtime snapshot carrying at least one
realized resource. It re-asserts the redaction contract (ADR-031-R4) as defense
in depth, tears the range down by `request_id`, and maps every failure to a
bounded, sanitized diagnostic.

For an admitted `active_directory` topology, `succeeded` is downstream of a
stronger guest-state gate: the provisioner has promoted and read back the exact
domain controller, reconnected as the authored RID-500 authority, joined and
read back every Windows member through a machine-scoped offline-domain-join
package without disclosing the authority password, created each domain-bound account, registered
each SPN with uniqueness-preserving semantics, and read the resulting
`servicePrincipalName` from AD. A marker file, successful VM creation, or a
write without directory readback cannot produce successful operation evidence.

## Running the validation

The evidence path is the `run_aces_backend_validation` management command,
modeled on `run_post_deploy_smoke`. Run it inside the portal Django context in a
deployed environment:

```bash
SHIFTER_ACES_NATIVE_PROVISIONING=true \
SMOKE_TEST_USER_EMAIL=<operator-email> \
SHIFTER_ACES_VALIDATION_SCENARIO=<registered-aces-scenario-id> \
python manage.py run_aces_backend_validation
```

Options: `--scenario` (overrides `SHIFTER_ACES_VALIDATION_SCENARIO`),
`--poll-interval`, `--timeout`, and `--keep` (leave the range up for manual
inspection instead of tearing it down).

Prerequisites:

- `SHIFTER_ACES_NATIVE_PROVISIONING=true` (the command refuses otherwise).
- A registered `AcesPackageSource` whose `scenario_id` is passed to the command,
  with `conformance_status=passed` and a `package_ref` that resolves under
  `ACES_PACKAGE_ROOT` to an immutable pack root. Its associated-artifact
  manifest and persisted `package_digest` must verify, and the pack must contain
  exactly one direct SDL entry. The in-repo
  `scenario-dev/shifter-aces-validation/` pack is a minimal,
  provisioning-only input suitable for this purpose.
- An enabled ACES image-registry mapping for the validation package's authored
  image source: provider `gce`, `source_name=alpine`, and
  `source_version=3.19`, pointing at the tenant's concrete Alpine-compatible
  GCE image or image family. Register it through the tenant-facing registry
  surface added for #1566; do not use Django admin or seed a one-off fixture.
  Optional sizing defaults such as `machine_type`, `disk_size_gb`, and
  `disk_type` are backend-owned policy on the mapping, not authored ACES
  semantics. Register it with the management command (or the equivalent
  `POST /api/v1/cms/aces-image-mappings/` call, or the ACES Images page in the
  SPA Author area):

  ```sh
  python manage.py aces_image_registry --action register \
      --provider gce --source-name alpine --source-version 3.19 \
      --image-ref projects/<project>/global/images/family/<alpine-family>
  ```

  See [manage-aces-image-registry](../how-to/manage-aces-image-registry.md) for
  the full register / list / disable reference.

### Active Directory and SPN evidence profile

The minimal `scenario-dev/shifter-aces-validation/` pack exercises the generic
provisioning cutover only; it does not claim domain/SPN evidence. To validate the
`active_directory`/`spn` capability, point the same command at a separately
registered, digest-verified validation pack whose single SDL entry explicitly
contains all of the following public ACES terms:

- one Windows controller related to one `active_directory` identity domain by
  `domain_controller_for`;
- one Windows member related by `joins_domain`, with that controller in
  `controller_refs` and a shared authored network;
- an enabled password-backed `Administrator` authority account on the
  controller; and
- a password-backed member account with the same `domain_ref` and a syntactically
  valid, unique `spn`.

Register enabled GCE image mappings for every Windows source/version authored by
that pack. The mapped image must provide the Shifter Windows management baseline
(Windows OpenSSH and the startup-script prerequisites) and support installation
of AD DS; image-family inference from `os_family` is not evidence. Run
`run_aces_backend_validation` with that pack's registered scenario id. The normal
operation receipt/status/snapshot evidence is sufficient because range success is
now conditional on the in-directory readbacks above; do not export usernames,
SPNs, secret references, or raw AD command output into the evidence surface.

### Source-backed content delivery (#1564)

A pack that authors source-backed `file` / `directory` content (a content item
with a `source`, as opposed to an inline `text` file or an empty directory) is
genuinely delivered as of #1564: the CMS side materializes the payload from the
digest-verified pack against the pack's author-declared delivery projection
(`delivery/content-projection.json`, validated against the associated-artifact
inventory), promotes it content-addressed to the platform assets bucket, and
hands the engine a byte-free delivery binding; the provisioner downloads +
digest-verifies the payload, delivers it over the authenticated guest channel,
and gates range readiness on an in-guest digest readback. `file` and `directory`
are declared manifest capabilities again because every admitted shape now has a
genuine, verified guest effect (ADR-032-R3, ADR-034-R6).

Cutover prerequisites for source-backed content (in addition to the image
mapping above):

- The provisioner runtime must resolve the assets bucket via
  `ACES_CONTENT_DELIVERY_BUCKET` or `STORAGE_BUCKET_NAME` (the same assets
  bucket the portal promotes to). An unset bucket fails closed at delivery time.
- The provisioner already holds `roles/storage.objectViewer` on the assets
  bucket (`platform/terraform/gcp/modules/portal/iam` `provisioner:assets`), so
  reusing that bucket needs no new IAM grant; the payload objects live under the
  `SHIFTER_ACES_CONTENT_DELIVERY_PREFIX` key prefix within it.
- A validation pack exercising this capability must ship a
  `delivery/content-projection.json` mapping each source-backed content
  `source` to its pack-relative input; a pack that authors source-backed content
  without a valid projection is non-realizable and fails closed before dispatch.

## What does not satisfy the gate

Direct Terraform / cloud / provisioner calls, demo-only launchers, seeded
sidecar rows, raw logs, provider dumps, and ACES-authored backend realization
details do not satisfy this gate. The evidence must come from the normal launch
path and the redacted read seam. For content, a structural target (a created
parent directory or destination), a descriptor, a marker file, or a successful
object upload / SSH exit is not delivery: only an in-guest digest readback of
the realized artifact does.

## Boundaries

Backend-owned realization details (image ids, machine sizes, subnets, provider
configuration, secrets) never appear in authored ACES semantics or in the
evidence. With the flag off, ACES entries are not launchable and this path is
inert.

The GCE range-cell substrate is IPv4-only across planning, addressing, firewall
posture, and outputs. IPv6-only and mixed IPv4/IPv6 topologies are unsupported:
the provisioner manifest publishes a `network-address-family = ipv4-only`
constraint and non-IPv4 authored networks are rejected at admission before
dispatch (issue #1568). See
[aces-gce-network-address-family-preflight-1568.md](aces-gce-network-address-family-preflight-1568.md).

Image-registry management is a separate operator concern from package-source
registration and conformance. A registered validation package without an
enabled `alpine@3.19` mapping must fail loudly during realization rather than
falling back to `os_family` or a hard-coded image.
