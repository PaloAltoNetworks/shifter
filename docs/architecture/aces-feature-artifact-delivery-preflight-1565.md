# ACES Feature Artifact Delivery Preflight

Issue: GitHub #1565, "deliver ACES feature artifacts beyond package-manager/baked
packages."

Status: pre-implementation architecture guidance. This note and the accompanying
ADR guardrails do not implement delivery, widen the backend manifest, change the
feature flag, or claim conformance evidence.

Implementation for #1565 follows this contract by extending the existing
inventory-bound delivery projection and byte-free binding relation with a v2
`feature-binding` identity, while retaining v1 content-binding reads. Artifact
and configuration payloads reuse the existing authenticated file/tree delivery
and independent digest-readback path; package/baked services now run through a
synchronous post-boot install/enable/verify plan instead of best-effort startup
metadata. The public backend manifest remains unchanged because its released
capability contract has no feature-type matrix; the independent shared admission
ledger carries the supported shape precision.

## Boundary And Decision

#1565 takes the genuine-delivery route allowed by the issue. It must preserve a
small, explicit feature-realization set and reject every other feature shape
before dispatch. A destination directory, descriptor, parsed field, or successful
VM boot is not feature realization.

The supported set is intentionally shape-aware:

| Authored feature shape | Required realization |
| --- | --- |
| `service` with a source resolved through the guest's configured package manager or already baked into the image | Install or locate the authored source identity, honor an exact authored version, enable and start the service, then verify package presence plus enabled/running service state over the authenticated guest channel before `READY`. The initial bounded mapping may require package name = service name; any wider mapping belongs behind the resolver seam below. |
| `artifact` with source + destination and one exact, inventory-bound regular-file projection | Reuse the immutable delivery channel, install atomically with the bounded executable policy for the guest dialect, and verify the installed file digest in guest before `READY`. |
| `configuration` with source + destination and one exact, inventory-bound file/tree projection | Reuse the same channel, install atomically with restrictive non-executable permissions, and verify file/tree digest readback before `READY`. |

Fail closed on a source or destination required by the selected shape being
missing, an unprojected custom source, ambiguous projection, unsupported payload
kind, unsupported guest OS, unhonored exact source version, non-empty feature
`environment` until it has an explicit safe realization contract, or a custom
service binary that lacks a declarative service-install contract. Preserve and
honor compiled ordering dependencies; do not replace the ACES dependency graph
with a hard-coded account/content/feature loop.

`description` and `vulnerabilities` are authoring metadata, not guest effects.
They need no realization. `environment` is different: silently dropping it can
change runtime behavior and may expose secret-like values, so it is rejected
rather than echoed into scripts, logs, process environments, or evidence.

## Architecture Decisions And Reuse

- ACES remains the authoring and compiled-plan contract. Use the released
  `aces_sdl.features.Feature`, `Source`, planner payload, resource address, and
  ordering dependencies. Do not add a Shifter feature DTO or mutate
  `range_config`.
- Add a shape-aware feature gate to the existing pure
  `shared.aces.composition_envelope` path used by both `validate()` and
  `apply()`. It must inspect resources and materializing CREATE/UPDATE
  operations, as the account gate does. The evidence-backed supported-shape
  policy must remain independently variable from the manifest declaration so a
  manifest over-claim still fails before dispatch.
- The current `ProvisionerCapabilities` has no feature-type matrix. Keep the
  supported matrix explicit in this architecture contract and the independent
  shared admission policy; do not invent a Shifter-only `constraints` string or
  overload content types, account features, or participant-runtime features.
  Adopt a public manifest feature surface only when a released ACES contract
  provides one.
- Reuse the #1564 pipeline: verified pack root, associated-artifact inventory,
  explicit projection, deterministic materializer, provider-neutral
  `ObjectStorage`, content-addressed key, portal writer/provisioner reader IAM,
  authenticated guest executor, `SetupOrchestrator`, atomic install, and
  independent digest readback.
- Evolve that delivery contract rather than creating a parallel feature store,
  table, downloader, exception hierarchy, or setup runner. Its next binding
  version must identify the compiled `resource_type` and `resource_address` and
  the bounded payload kind. Version-1 content bindings remain readable during
  the rolling window; feature bindings must never masquerade in the legacy
  `content_address` field.
- Evolve the inventory-bound projection as a discriminated, versioned
  composition projection. Content and feature entries keep distinct match keys
  and install policies while sharing containment, inventory, materialization,
  size, digest, and storage machinery. Continue reading the existing content
  projection version; do not introduce a second file-selection convention.
- Persist only the byte-free binding beside the plan in the existing private
  delivery relation, using a rolling-deploy-safe schema evolution. The engine
  remains the sole writer and the provisioner remains SELECT-only. No payload,
  URL, bucket, credential, destination, command, environment value, or generated
  script belongs in the row.
- Package/baked service realization must move behind, or be followed by, the
  same synchronous post-boot guest verification gate. Remove swallowed install
  and service failures (`|| true`, `SilentlyContinue` as success). Startup-script
  completion is asynchronous and cannot gate range readiness.
- A failure at projection, binding, download, install, service activation, or
  readback follows the existing failed-apply cleanup and neutral range-status
  path. `publish_ready` remains after all feature verification.

## Canonical Incumbents

| Concern | Canonical incumbent to extend/reuse |
| --- | --- |
| SDL and plan shape | Released `aces_sdl.features.Feature` / `Source`, ACES planner, `serialize_provisioning_plan`, `aces_plan.parse_plan` |
| Shared admission | `shared.aces.runtime_target`, `shared.aces.composition_envelope`, independent-policy pattern in `shared.aces.realization_ledger` |
| Manifest publication | `shared.aces.manifest.SHIFTER_PROVISIONER_CAPABILITIES`, `render_shifter_backend_manifest_payload()`, checked-in `backend-manifest.json` |
| Pack trust and selection | `cms.scenarios.pack_validation`, `shared.aces.package_loader`, `shared.aces.object_source`, ACES associated-artifact inventory |
| Artifact preparation | `shared.aces.content_delivery`, `content_delivery_prep`, its exact projection parser/materializers and size bounds |
| Storage and IAM | `shared.cloud.ObjectStorage`, `STORAGE_BUCKET_NAME`, existing assets bucket, portal objectAdmin and provisioner objectViewer bindings |
| Dispatch and persistence | `CmsAcesDispatchPort`, `engine.services.create_aces_range`, the existing delivery-binding relation and SELECT-only provisioner grant |
| Consumer validation | `aces_plan`, `aces_content_delivery.assert_content_delivery_bindings_complete`, early gates in `aces_gcp_apply` |
| Guest realization | `build_guest_execution_context`, `GuestSSHExecutor`, `SetupOrchestrator`, `AcesContentDeliveryPlan` and its Linux/Windows atomic install/readback scripts |
| Lifecycle/evidence | `aces_range_ops`, `_cleanup_failed_apply`, neutral `publish_failed`/`publish_ready`, redacted ACES operation status and runtime snapshot |
| Errors and logs | ACES `Diagnostic`, `AcesPackageError`/`CMSError`, bounded delivery/composition errors, `shared.log_sanitize` and provisioner `log_redact` |
| Flag/config/workflow | `SHIFTER_ACES_NATIVE_PROVISIONING`, `_aces_settings.py`, `env-manifest.json`, runtime inventory, GCP provisioner-job admission policy |

## Cross-Cutting Security And Validation Layers

1. **SDL/parser:** upstream Pydantic models validate feature type, source, and
   destination shapes. Shifter does not weaken or duplicate them.
2. **Pack trust:** the repo/object resolver performs bounded extraction,
   containment, symlink/special-file rejection, package validation, and canonical
   digest re-verification. The projection and every selected input are members of
   the digest-bound associated-artifact inventory.
3. **Plan admission:** `RuntimeManager.plan` and the common
   `composition_envelope` gate reject unsupported feature shapes and values before
   the dispatch port, database, object promotion, or cloud mutation. Normalized
   feature type/source version may appear in bounded diagnostics; source paths,
   destinations, environment values, and bytes may not.
4. **Product authorization:** launch still enters through
   `create_aces_native_range` and reuses user, ownership, launchability,
   active-range, reservation, audit, and default-off feature-flag gates. Pack or
   feature validity is not authorization. No endpoint or permission is added.
5. **Configuration and IAM:** reuse the existing assets bucket, prefix, size cap,
   workload identity, portal write, and provisioner read grants. Add no guest
   cloud credential and no feature-specific secret/env variable. Any config
   change must also satisfy `_aces_settings.py`, `env-manifest.json`, installation
   runtime inventory, Kubernetes job env allowlists, and Terraform least
   privilege.
6. **Transport/persistence:** a versioned byte-free binding rides beside the ACES
   plan, is exact-key validated, and is transactionally bound to the range. It
   never enters `range_config`, launch argv, events, snapshots, or public APIs.
7. **Provisioner trust boundary:** `parse_plan` repeats envelope/version/resource,
   payload, target, path/dialect, source-version, and dependency checks. Binding
   schema/version/digest/size/content-addressed-key checks and an exact one-to-one
   `(resource_type, resource_address)` join run before infrastructure creation.
8. **Object/guest boundary:** the provisioner reads with workload identity,
   pins object identity during bounded download, checks byte count and digest,
   then uses the authenticated host-management SSH channel with the injected host
   key. Guests never receive object-store credentials or URLs.
9. **OS/process exposure:** preserve #1564's transport: Linux receives a rendered,
   strictly quoted script over SSH stdin; Windows receives runtime values over
   PowerShell stdin. Artifact bytes, destinations, digests, and environment values
   do not enter host/provisioner argv, container env, GCE metadata, process-list
   command lines, or Event 4688. Linux executable modes are allowlisted (never
   setuid/setgid); Windows paths reject UNC/device namespaces, alternate data
   streams, wildcards, traversal, and reparse points.
10. **Error envelopes and observability:** errors are single-line, bounded, and
    value-free through `Diagnostic` -> package launch -> `CMSError`, and through
    provisioner failed operation/range status. Do not use `logger.exception` on
    provider/guest exceptions whose messages can contain keys, paths, command
    output, or bytes. Log request correlation plus stable codes/class names; do
    not turn runtime snapshots or sidecars into an artifact ledger.

## Extensibility Seam

The seam is the versioned, data-only feature source resolver/projection keyed by
`(feature type, source name, source version, guest dialect)`. It returns a bounded
realization kind (package/baked service, delivered file, delivered tree), payload
identity when applicable, and a fixed verifier/install policy. Destination and
ordering remain authored ACES intent; object location, package/service mapping,
file mode, and dialect mechanics remain backend realization detail.

This permits the next reasonable variations—package name differing from service
name, an additional deterministic archive format, or a released upstream
feature-capability matrix—without changing the plan transport or adding another
workflow. It must remain data-only: no pack-supplied executable hooks, shell,
PowerShell, package-manager command, or arbitrary probe.

## Whole-Repo Scope And Evidence

The implementation must evaluate ADR-024/031/032/034 and these surfaces:

- `shared/aces/{manifest,runtime_target,composition_envelope,realization_ledger,content_delivery,content_delivery_prep,package_loader}.py` and manifest artifact;
- `cms/aces/dispatch.py`, `cms/services/_aces_range_create.py`,
  `engine/services/_aces_range.py`, delivery model/migration, and engine ECS/GCP
  job launchers;
- `aces_{plan,composition,gcp_composition,gcp_apply,content_delivery,range_ops}.py`,
  `provisioner_db_aces.py`, guest executor/orchestrator, and setup plans;
- `_aces_settings.py`, `env-manifest.json`, installation runtime inventory,
  Terraform bucket IAM, and Kubernetes provisioner-job admission policy;
- manifest/runtime-target/compiler E2E tests, delivery producer/persistence/DB
  tests, Linux/Windows provisioner and setup-plan tests, flag-off tests, and live
  backend validation.

Evidence must include real compiler -> serialized plan -> binding -> provisioner
coverage for feature bindings (the current composition E2E explicitly omits
them), negative independent-ledger tests, package/baked service success and hard
failure, Linux and Windows artifact/configuration readback, tampered object and
binding rejection, wrong/missing/extra binding rejection, unsafe path/archive
cases, exact-version behavior, dependency ordering, no-leak assertions, cleanup,
and no `READY` before verification. Unit tests that merely inspect generated
commands are not realization evidence.

## Gotchas And Anti-Patterns

- Do not model a feature as `content-placement`, reuse `content_address` for a
  feature, or add feature types to content/account capability sets.
- Do not add a feature-specific object bucket, table, IAM role, downloader,
  event, sidecar, exception hierarchy, guest executor, or workflow.
- Do not infer pack input by filename/extension/order, infer install behavior
  from a destination suffix, or execute contributor-supplied installers.
- Do not claim all `feature-binding` resources because one service/package works.
  The public manifest is coarse; the independent shape gate carries the missing
  precision.
- Do not discard `Source.version`, compiled resource address, or ordering
  dependencies in the provisioner projection.
- Do not equate package installation with service activation. Package and service
  names can differ, a baked package can be disabled, and package managers can
  succeed while the service fails to start.
- Do not keep `|| true`, broad `SilentlyContinue`, marker files, destination-only
  directories, or echoed snapshot values as proof.
- Do not put payloads in startup metadata. The existing post-boot channel is the
  security boundary and readiness gate.
- Do not weaken archive/path/link checks for "trusted" packs; registration and
  launch verification are necessary but the provisioner and guest are separate
  trust boundaries.
- Do not delete content-addressed objects on range destroy; they are immutable
  and may be shared. Existing lifecycle/retention owns orphan cleanup.

## Non-Goals

- No arbitrary installer/plugin framework, remote URL fetch, package repository,
  entitlement system, public artifact API, guest object-store access, or image
  bake redesign.
- No custom service registration from raw binaries until a released or explicitly
  approved declarative contract can name service identity and fixed install/probe
  semantics without executable hooks.
- No realization of arbitrary feature environment values, secrets, ownership,
  ACLs, setuid bits, kernel modules, drivers, reboots, or uninstall/downgrade
  semantics.
- No new ACES SDL, parallel plan/DTO, participant-runtime feature claim, database
  event schema, feature flag, or change to the cyberscript path.
- No cutover or change to `SHIFTER_ACES_NATIVE_PROVISIONING` default-off posture.

For this architecture-only change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```
