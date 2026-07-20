# ACES GCE Network Address-Family Preflight

Issue: GitHub #1568, "fix: ACES range cells reject IPv6 subnets (IPv4-only
limitation)."

Status: pre-implementation architecture guidance. This note does not add IPv6
realization, change the backend manifest, alter validation, or modify runtime
behavior. The issue is the shipping contract for this requirement-free run.

## Boundary and Decision

Take the issue's explicit-unsupported outcome, not a partial IPv6 implementation.
The current GCE range-cell substrate is IPv4-only across planning, firewall
posture, instance addressing, configuration, and output contracts. Publishing
that limitation honestly is a bounded change; making the substrate genuinely
IPv6 or dual-stack is a separate cross-cutting capability.

Keep `switch` in `SHIFTER_PROVISIONER_CAPABILITIES`: it truthfully admits the
IPv4 network resources Shifter realizes and is required for any networked ACES
plan. Qualify that claim through the existing
`ProvisionerCapabilities.constraints` map with one provider-neutral constraint:

```text
network-address-family = ipv4-only
```

The checked-in `shared/aces/backend-manifest.json` must render the same
constraint. The accompanying capability documentation must state plainly that
IPv6-only and mixed IPv4/IPv6 topologies are unsupported. Do not add a new
manifest model, capability enum, profile, environment variable, or Shifter-owned
network schema.

The manifest constraint is disclosure, not an upstream planner policy: the
pinned ACES runtime preserves the map but does not enforce arbitrary constraint
keys. Normal Shifter launches should therefore also reject a compiled network
whose address family is outside the declared constraint through the existing
pure `shared.aces.runtime_target` diagnostic path, before the dispatch port can
persist an engine range or start the provisioner. Keep
`aces_gcp_plan._usable_host_ips`'s `AcesGcePlanError` check as the separate
provisioner trust-boundary defense for persisted/replayed plans.

ADR-031 and ADR-032 already require an honest capability ledger, common
validate/apply admission, bounded diagnostics, direct ACES plan transport, and
fail-closed consumer validation. No new ADR or exception is needed.

## Canonical Incumbents to Reuse

| Concern | Canonical incumbent | Required boundary |
| --- | --- | --- |
| Authored network shape | Pinned `aces_sdl.infrastructure.SimpleProperties` and the ACES planner | ACES remains authoritative for SDL syntax, IP parsing, and gateway membership. Do not add a Shifter SDL or DTO. ACES intentionally accepts IPv4 and IPv6, so backend support must be narrower and explicit. |
| Capability publication | `shared.aces.manifest.SHIFTER_PROVISIONER_CAPABILITIES`, `render_shifter_backend_manifest_payload()`, and `shared/aces/backend-manifest.json` | Put the limitation in the existing provisioner `constraints` map and keep builder/artifact equality. Do not use top-level config or a second capability ledger. |
| Plan/apply admission | `shared.aces.runtime_target.interpret_provisioning_plan`, `_capability_envelope_diagnostics`, `_diagnostic`, and `_serialized_for_apply` | Reuse the one no-I/O path shared by `validate()` and `apply()`. An unsupported family must yield one bounded typed `Diagnostic`, return no serialized plan, and never call the dispatch port. |
| Transport validation | `serialize_provisioning_plan` and `shifter/engine/provisioner/aces_plan.py::parse_plan` | Keep the serialized ACES `ProvisioningPlan` as the only process boundary. Do not add an address-family field to a parallel envelope or process-local projection. |
| GCE IPv4 realization | `aces_gcp_plan._usable_host_ips`, legacy `gcp_range_cell_plan._assign_instance_ips`, and `shared.range_cells._validate_network_bindings` | Preserve their fail-closed IPv4 invariants. The legacy closed range-cell request is corroborating substrate policy, not a contract ACES should be translated into. |
| GCE resource rendering | `gcp_range_cell_resources`, `gcp_range_cells`, `gcp_range_cell_outputs`, and `RangeCellPlan` | Leave these unchanged for the unsupported-capability slice. They currently model one IPv4 CIDR/private address and an IPv4 firewall posture. |
| Exceptions and product errors | ACES `Diagnostic`, `AcesPlanError`, `AcesGcePlanError`, `AcesPackageError`, and `CMSError` | Reuse the existing families. Plan-time rejection is a `Diagnostic`; the provisioner backstop remains `AcesGcePlanError`; the CMS boundary remains the generic existing rejection. |
| Logging and evidence | `shared.log_sanitize`, provisioner `log_redact`, ACES operation-record validation/projections, and request-id correlation | Log stable code/stage/request identifiers only. Sanitizers bound/control-escape text but do not make an authored address safe to disclose. |
| Launch and persistence | `create_aces_native_range`, `CmsAcesDispatchPort`, `engine.services.create_aces_range`, `engine.ecs`, and `aces_range_ops` | Keep existing admission, CMS reservation/failure bookkeeping, request-id dispatch, `range_config`, sidecar, and status flows. Add no model, repository, event, or CLI payload. |
| Feature flag and runtime config | `SHIFTER_ACES_NATIVE_PROVISIONING`, `config/_aces_settings.py`, `config/env-manifest.json`, and `GCERangeCellConfig` | Keep the flag default off and add no address-family toggle. A capability limitation is not tenant configuration. |
| Architecture/workflow enforcement | `.importlinter`, `scripts/check_layer_imports`, `scripts/adr_guard`, and the existing shared/provisioner pytest suites | Keep ACES imports confined to `shared.aces`; provisioner code continues to consume plain serialized data. Do not weaken or bypass any gate. |

## Cross-Cutting Layers the Design Must Pass

### Security and validation

1. **Authentication and launch authorization:** no endpoint or permission changes.
   Launch continues through `create_aces_native_range`, reusing user/scenario
   validation, launchability, active-range exclusion, ownership, and audit
   helpers. A manifest capability is never authorization.
2. **Package and SDL validation:** package containment, digest verification,
   single-entry selection, ACES Pydantic validation, and gateway-in-network
   checks remain first. IPv6 is syntactically valid ACES input; it must fail as
   an unsupported backend capability, not be mislabeled malformed SDL.
3. **Backend validate/apply:** inspect every compiled `network` resource in the
   common pure RuntimeTarget path. Parse with Python `ipaddress`, classify only
   the family, and compare it with the published constraint. Do not echo the
   authored address, gateway, payload, or provider details in the diagnostic.
4. **Dispatch and persistence:** an unsupported plan must not reach
   `CmsAcesDispatchPort`, `engine.Range.range_config`, operation receipts, task
   dispatch, or cloud mutation. The CMS `Request`/`RangeInstance` reservation is
   made before package dispatch by the incumbent launch workflow and must be
   marked `FAILED` by its existing exception path; do not invent rollback or a
   second reservation flow.
5. **Provisioner trust boundary:** `parse_plan` still validates transport
   version, producer window, resource shapes, identities, and references.
   `_usable_host_ips` remains the family/size backstop before any `_ensure_*`
   cloud mutation. A replayed pre-change plan must still fail closed.
6. **Firewall and isolation:** do not create any IPv6 subnet/interface until
   base ingress, management access, same-range service sources, authored ACLs,
   allowed egress, and default-deny egress are defined for both families. The
   current terminal deny covers only `0.0.0.0/0`; accepting IPv6 without an
   equivalent posture would create an isolation bypass.

### Secrets, config shapes, OS exposure, and error envelopes

- **Secrets:** no secret lookup, credential, metadata, startup-script, or
  account path changes. Never put a plan or network value into secret storage to
  carry it between layers.
- **Config/env shapes:** add no setting. `GCERangeCellConfig` keeps its current
  IPv4-only portal/egress boundary validation, and
  `SHIFTER_ACES_NATIVE_PROVISIONING` remains the only feature gate.
- **OS/process exposure:** local/ECS launch remains the structured argv
  `aces-range provision --request-id <uuid>`; the plan stays DB-backed. No
  network value, manifest constraint, token, or serialized plan belongs in argv,
  environment overrides, shell fragments, or workflow output.
- **Error envelopes:** use a stable code such as
  `shifter-provisioner.unsupported-network-address-family` with a generic message
  naming only `ipv4` as the supported family. Do not include the authored CIDR.
  The current provider exception includes that literal, and `aces_range_ops`
  forwards `str(exc)` into operation/status events; the unsupported-family path
  must not rely on `safe_log_value` as redaction. Keep the provider backstop
  message generic as defense in depth for persisted/replayed plans.
- **Observability:** request id, stable diagnostic code, network resource
  address, and failure stage are sufficient. Do not add metrics labels or logs
  containing network literals, full payloads, raw SDK errors, or GCE resource
  bodies. Sidecars remain status/topology evidence, not another capability
  surface.

## Maintainability and Concept Boundaries

- Do not route ACES through `shared.range_cells` merely because its GCP request
  validator is already IPv4-only. That contract owns the legacy closed range-cell
  request and would re-model the ACES plan, violating ADR-032.
- Validation at the shared RuntimeTarget and provisioner planner is deliberate
  trust-boundary defense, not a reason to introduce two network schemas. Both
  consume the same authored CIDR string with `ipaddress`; neither owns an ACES
  network DTO.
- Do not remove `switch` support to make all networked scenarios fail. The
  supported capability is IPv4 networking, not no networking.
- Do not add a made-up `ip-family` entry to
  `RealizationSupportDeclaration.supported_constraint_kinds`. The pinned ACES
  vocabulary has no such public kind, and Shifter's publication tests map those
  terms to governed capability fields. The existing opaque provisioner
  `constraints` map is the correct disclosure surface.
- Do not create an address-family exception hierarchy. Unsupported plan intent
  is already represented by ACES diagnostics, while the separate provisioner
  process already owns `AcesGcePlanError`.
- Do not add a database field, sidecar kind, API property, catalog projection,
  runtime flag, or provider selector for this limitation.

## Extensibility Seam

`ProvisionerCapabilities.constraints["network-address-family"]` is the single
published parameter, and the common RuntimeTarget network diagnostic is its
admission seam. A later IPv6 issue changes that capability only after the
provider implementation and evidence move together; it must not scatter
`supports_ipv6` booleans across CMS, engine, provisioner, Terraform, and UI.

Genuine IPv6/dual-stack support is larger than accepting an `IPv6Network`. It
must define, at minimum, multi-family subnet/interface/address resource bodies,
deterministic guest address assignment without enumerating IPv6 spaces, node
attachment semantics, management reachability, dual-family ACL/service firewall
translation, `::/0` egress default-deny, config validation, output/access address
selection, destroy/reconcile behavior, and live evidence. Nodes may reference
multiple ACES networks today, but `aces_gcp_plan._primary_network` attaches only
the first; that must not be presented as dual-stack support.

## Regression Evidence Expectations

- Manifest publication asserts the exact
  `network-address-family=ipv4-only` constraint, validates against the published
  `backend-manifest-v2` model, preserves `switch`, infers the same
  `provisioning-only` profile, and matches the checked-in JSON artifact.
- A real ACES plan with an IPv6 network passes upstream SDL validation but fails
  both `ShifterProvisioner.validate()` and `apply()` with the stable family code;
  apply records no dispatch. The diagnostic contains neither the authored
  address nor forbidden provider/secret detail.
- An IPv4 plan still serializes and dispatches unchanged. The default-off flag
  path and cyberscript path remain unchanged.
- Provisioner tests retain an IPv6 negative for `_usable_host_ips`/plan building,
  prove the failure happens before `_ensure_network` or any other client
  mutation, and prove the error/event text does not contain the authored network
  literal.
- Existing malformed, oversized, too-small, unknown-reference, portal-overlap,
  ACL, service, and configuration negatives remain in force. Address family must
  not become a shortcut around those gates.

## Whole-Repo Scope

The implementation must evaluate changes against:

- `docs/adr/index.yaml` ADR-031 and ADR-032;
- `docs/architecture/aces-cutover-evidence-1264.md` and
  `docs/architecture/aces-backend-manifest-realizability-preflight-1563.md`;
- `shifter/shifter_platform/shared/aces/manifest.py` and
  `shared/aces/backend-manifest.json`;
- `shifter/shifter_platform/shared/aces/runtime_target.py` and
  `shared/aces/package_loader.py`;
- manifest publication, RuntimeTarget, package-loader, conformance, and real-plan
  parity tests under `shifter/shifter_platform/tests/shared/aces/`;
- `shifter/engine/provisioner/aces_plan.py`, `aces_gcp_plan.py`,
  `aces_gcp_firewall.py`, `aces_gcp_apply.py`, `aces_range_ops.py`, and their
  tests;
- `shifter/engine/provisioner/gcp_range_cell_plan.py`,
  `gcp_range_cell_resources.py`, `gcp_range_cell_outputs.py`, `config.py`, and
  `shifter/shifter_platform/shared/range_cells.py` as unchanged substrate
  constraints;
- `cms/services/_aces_range_create.py`, `cms/aces/dispatch.py`,
  `engine/services/_aces_range.py`, `engine/ecs.py`, `engine/handlers.py`, and
  ACES status/evidence schemas as unchanged workflow and error surfaces;
- `config/_aces_settings.py`, `config/env-manifest.json`, installation runtime
  inventory, platform manifests, and task-runner env allowlists as unchanged
  config/host surfaces; and
- `.importlinter`, `scripts/check_layer_imports`, `scripts/adr_guard`, and the
  existing quality workflows.

## Gotchas and Anti-Patterns

- Deleting the `IPv4Network` check is not IPv6 support. The current host-list
  slicing, reserved-address assumptions, `private_ip`/`network_i_p` fields,
  address resource, management CIDRs, Private Google API route, outputs, and
  firewall default deny are IPv4-shaped.
- Never enumerate a typical IPv6 subnet. Preserve the address-count DoS guard;
  future IPv6 allocation needs arithmetic/indexed assignment.
- Do not treat GCE API acceptance of an IPv6 field or an IPv6 firewall range as
  end-to-end realization evidence.
- Do not silently choose the IPv4 network when a node also references an IPv6
  network. `_primary_network` currently drops secondary attachment semantics.
- Do not call an IPv4 VM plus a disconnected IPv6 subnet “dual-stack.”
- Do not derive support from the manifest constraint alone. It is a declaration;
  normal launch validation and the independent provider backstop must agree.
- Do not expose authored network literals in diagnostics, logs, events, range
  error messages, snapshots, or conformance output. `safe_log_value` prevents
  log injection; it is not confidentiality redaction.
- Do not hand-edit only `backend-manifest.json`; the Python builder is canonical.
- Do not add provider names, subnet details, or CIDR examples to the manifest;
  its existing publication guard intentionally excludes backend-owned detail.

## Non-Goals and Implementation Boundaries

- No IPv6-only or dual-stack GCE realization and no claim of such support.
- No change to ACES SDL, pinned dependency versions, backend profile, contract
  versions, `switch` vocabulary, or serialized-plan envelope.
- No change to legacy cyberscript range realization or the version-1
  `shared.range_cells` request/result contract.
- No new API/UI, auth scope, model/migration, repository, event, sidecar,
  snapshot field, CLI argument, setting, environment variable, Terraform,
  Kubernetes, workflow, cloud permission, secret-store path, or cutover.
- No change to the default-off feature flag or authorization to enable ACES in
  any environment.
