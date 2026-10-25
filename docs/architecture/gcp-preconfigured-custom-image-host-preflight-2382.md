# GCE Preconfigured Custom-Image Host Preflight (#2382)

Status: implementation guidance

## Decision and boundary

`preconfigured-machine-host` describes guest realization and readiness; `image`
versus `machine-image` describes the Compute Engine source. Permit the host
capability with either an exact `projects/<project>/global/images/<name>` custom
image or the existing exact machine-image reference. A custom image is suitable
only when the complete runtime is on its one boot disk. Keep ordinary boot-image
and machine-image behavior, and the existing generic RAES image/profile binding.
Do not introduce a third image kind or a scenario-specific selector.
This updates the machine-image-only source assumption in the #1896 preflight;
its host security and readiness controls still apply.

The machine-image source limit is six creations per source in 60 minutes; Google
documents 20 instances per second for custom-image API/CLI creation. The latter
still has image access, quota, and capacity constraints; it is not an unbounded
fleet guarantee. See [machine-image restrictions](https://cloud.google.com/compute/docs/machine-images/create-instance-from-machine-image)
and [custom-image creation](https://cloud.google.com/compute/docs/instances/create-vm-from-custom-image).

## Cross-cutting gates and incumbents

| Layer | Existing boundary and required guardrail |
| --- | --- |
| Authorization and administrator binding | CMS image-registry writes use `CMS_WRITE_PERMISSIONS`, `RaesImageMappingRegisterSerializer`, and `engine.services._raes_image.upsert_raes_image_mapping`; adapter target profiles use `cms.api.runtime_plugin_packs` and `shared.runtime_plugin_binding.RuntimeTargetImageProfile`. Keep image choice in those administrator-owned bindings, frozen with the operation or plugin pin. Pack authors cannot install executable adapters or choose a host by private identity. |
| Shapes and validation | Reuse registry service validation, `shared.raes.operation_input_candidates`' closed projection, `shared.raes.image_policy.ResolvedImage`, `raes_gce_image`, `config._gce_image_keys`' closed JSON shape, and `config._gce_profile`'s profile validation. Validate source syntax by image kind, then validate complete host identity/readiness by bootstrap capability. Exact custom-image refs must exclude families, bare names, and URLs. Preserve the ordinary-image and AWS restrictions. The UI forms and API choices must express both independent dimensions. |
| Plan and persistence | Reuse `GCERangeImageProfile`, `gce_image_profile_fingerprint`, deterministic `gcp_range_cell_plan`/`raes_gcp_plan` names and labels, registry rows, operation-input candidates, and pinned plugin bindings. No second profile schema, table, range status, or scenario field. An exact resource name is not a physical image ID: retain `source_image_id` checks for prepared artifacts through `raes_substrate_observation`, and do not claim name-only pins detect delete/recreate of an image. |
| Compute request and security | Reuse `gcp_range_cell_resources.instance_resource` and `gcp_range_cells._insert_instance`. The custom-image host uses one boot disk with `source_image` and `auto_delete=true`, plus explicit `advanced_machine_features.enable_nested_virtualization=true`. Preserve current Shielded VM flags, fresh metadata/host key, private subnetwork and IP, no external IP, labels/tags, `can_ip_forward=false`, and the explicit selected service-account list or explicit empty list. Never inherit machine-image identity or metadata. Keep the existing host identity pool where the legacy path requires it; do not infer a new role or broaden IAM. |
| Guest and access | Reuse `instance_orchestrator`, `plans.preconfigured_machine_host`, `raes_guest_plan.assert_management_login_separate`, `gcp_range_cell_outputs`, guest secret ops, private SSH host-key pinning, and declared participant access. A custom-image host follows the same bounded liveness, credential installation, and `participant-readiness/v1` canary checks; it skips ordinary guest bootstrap. The fixed canary receives only validated container/user/contract/digest arguments, never a profile-supplied command or secret in argv. A bootable image alone does not establish readiness. |
| Reconcile and cleanup | Both `gcp_range_cells._ensure_instance` and `raes_gcp_apply._ensure_raes_instance` must reject an existing deterministic VM with conflicting range ownership or image/profile labels before returning its host key. The present keyed legacy check skips empty RAES image keys, so it cannot be the sole guard. Reuse shared binding checks and `gcp_range_cell_destroy`/`raes_gcp_destroy`; keep the custom-image boot disk `auto_delete=true` on create, adoption, and destroy. Machine-image disk convergence remains in place. A late ownership conflict must preserve the foreign VM and release only resources journaled as created by this apply attempt. Do not silently adopt a VM after an ambiguous insert result. |
| Errors and observability | Preserve `RaesImageMappingError`, `RaesOperationInputError`, provisioner plan errors, `shared.api.errors.api_error_response`, `log_redact.safe_log_fingerprint`, and `terraform_ops._safe_failure_message`. Fail at the owning validator before cloud mutation where possible. Log bounded identifiers/operation context; never log request metadata, SSH material, credentials, or raw provider payloads. The failure-message boundary truncates but does not redact, so new exceptions must contain safe text. |

The only runtime configuration transport implicated by a legacy keyed profile is
`GCP_RANGE_IMAGE_KEY_PROFILES_JSON`: `shifter/installation/runtime_inventory_gcp.py`,
`scripts/gcp/render_runtime_env.py`, `config._gce_image_keys`, and the provisioner
Job admission allowlists in `platform/k8s/gcp/base` and the Helm template already
carry that variable. Keep the change inside its existing closed shape. A new
environment variable would have to pass each of those gates and the platform
environment manifest; it is unnecessary here. The provider call uses the SDK in
process, so no image reference, token, or credential belongs in process argv.

## Gotchas and verification boundary

- `image_kind == "image"` currently means ordinary bootstrap in the registry
  service, operation-input parser, plugin profile validator, and both UI forms.
  Update those gates together. Do not key host readiness or nested virtualization
  solely on `source_machine_image`.
- The RAES path has an empty `image_key`; its existing legacy drift check returns
  early. Verify range ownership and the full profile fingerprint on reconcile
  before adopting a preconfigured image-backed host.
- The current RAES GCE apply and existing-cell activation paths do not run the
  fixed participant canary before terminal readiness. Composition verification
  is a different proof. Route both preconfigured source forms through the same
  bounded canary, or reject that capability on any path lacking it. A host image
  must also boot under the retained Shielded VM settings on a machine type that
  supports nested virtualization; validation cannot assume the bake has this.
- Keep `image_kind` as the source discriminator and `bootstrap_capability` as the
  guest contract. The next boot-disk-backed capability should pass through the
  same profile/request seam without another image kind or copied workflow.
- Synthetic evidence must cover registry and plugin validation, closed operation
  input, exact reference rejection, request shape and explicit nested feature,
  RAES realization/reconcile and conflicting-VM rejection, boot-disk ownership,
  readiness routing, and ordinary-image/machine-image regressions.

## Non-goals and anti-patterns

No image bake or promotion pipeline, extra disk support for custom-image hosts,
global retry policy for machine-image throttling, new participant channel, new
public network exposure, new service-account privilege, pack-specific code, or
new persistence or general exception hierarchy. A typed ownership conflict may
protect foreign VMs during partial cleanup. No fallback from a failed exact image
to a family, another image, or a machine image. Existing ADR boundaries on
administrator binding, range lifecycle, and participant access remain intact;
this note clarifies their intersection without changing an ADR.
