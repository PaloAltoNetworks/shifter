# GCE Machine-Image Range Host Preflight (#1896)

Status: implementation architecture record

Date: 2026-07-29

## Decision

Extend the existing keyed `GCERangeImageProfile` seam with one generic
`preconfigured-machine-host` capability. The profile selects an exact Compute
Engine machine-image resource and declares only the host-management login and
participant container/account needed by the established setup and RDP broker
paths. It does not add a scenario field, scenario-id branch, package executor,
or new participant access channel.

The original machine-image-only source decision is extended by #2382 for
single-boot-disk hosts: the same `preconfigured-machine-host` capability may
use an exact `projects/<project>/global/images/<name>` custom image. Image
kind describes the Compute source; bootstrap capability describes guest
readiness. A custom image is appropriate only when the complete preconfigured
runtime is on its boot disk. Multi-disk captures retain the machine-image path.

Machine-image profiles are administrator-managed runtime configuration. Their
concrete image, container, account, and service-account values do not belong in
catalog content. Legacy ranges may still use the bounded deployment-owned map
established by #1761. RAES pack launches use either the tenant image registry or
an organization administrator's image profile stored with an adapter target;
the latter is pinned with the adapter, pack digest, and range operation.

## Required Controls

- Accept exactly one source per profile. A preconfigured host uses either an
  exact project-qualified custom image in `source_image` or the exact
  `projects/<project>/global/machineImages/<name>` form. Families and inferred
  names are not accepted for either preconfigured-host source.
- Replace inherited metadata, SSH material, network interfaces, external-IP
  posture, labels, tags, machine type, and service account at clone time.
  Captured disks are the only inherited resources.
- Enable nested virtualization explicitly and use the existing private
  per-range subnet, firewall, pinned host-key SSH transport, dynamic guest
  credential secrets, and Guacamole RDP broker.
- Select the host service account from a bounded Terraform-created pool by
  sharding the range's existing allocation index across the configured pool.
  These identities authorize common host infrastructure and are not a tenant
  isolation boundary; subnet and firewall policy remain authoritative. The
  provisioner receives
  `serviceAccountUser` on each specific pool member, never project-wide service
  account administration.
- After create and on reconcile, set `autoDelete=true` on every attached disk.
  Destroy performs the same convergence before deleting the instance, so
  machine-image data disks cannot be orphaned.
- A custom-image host creates one explicitly auto-deleting boot disk. Preserve
  Shielded VM settings, nested virtualization, fresh metadata and SSH keys,
  private networking, and an explicit runtime identity (or explicit absence).
- Treat the image as owning its internal realization. The fixed volatile marker,
  running configured participant container, and host RDP listener are boot-
  liveness prerequisites only. Issue #1910 additionally requires the
  profile-bound, image-owned participant canary in
  `nested-ctf-participant-readiness-preflight-1910.md` before terminal readiness.
  Shifter still uses the existing secret-backed container password plan and does
  not run generic Linux bootstrap against the captured host.
- Keep readiness bounded and fail the normal range operation when readiness or
  required participant credential setup fails.

## Existing Architecture Reused

| Concern | Incumbent |
| --- | --- |
| Logical image selection | Legacy keyed profiles, the tenant RAES image registry, and pinned adapter-target image profiles |
| Scenario boundary | `gcp_range_cell_scenario` legacy compatibility adapter and digest-bound range-cell request |
| Provider lifecycle | `gcp_range_cell_plan`, `gcp_range_cell_resources`, `gcp_range_cells`, and deterministic destroy |
| Identity | ADR-008-R7's pre-created identity-pool precedent, with deterministic sharding for common host access |
| Management transport | Provisioner-issued host key, pinned private SSH, and existing management-port routing |
| Participant access | Existing `rdp` declaration, per-instance password secret, and Guacamole broker |
| State and reconciliation | Existing GCP provider metadata and image-profile fingerprint |

No new ADR is required. This specializes ADR-008-R7's bounded identity pattern,
ADR-030's backend lifecycle ownership, ADR-037's participant access boundary,
and ADR-039's provider realization seam. ADR-008-R7 is updated to name the
second bounded pool explicitly.

## Non-Goals

- No package-specific values, topology, bootstrap commands, or content.
- No public HTTPS endpoint, arbitrary redirect, or new participant channel.
- No execution of package-supplied scripts by the provisioner.
- No machine-image bake or promotion workflow.
- No replacement for ACES-native materialization.
- No platform-scale scheduler or fleet-capacity design.

## Evidence

Focused tests must cover conditional profile validation, exact source
selection, pool bounds, clone request shape, inherited-field replacement,
attached-disk ownership on apply and destroy, setup-path routing, runtime-env
transport, and regressions for ordinary image-backed guests.
