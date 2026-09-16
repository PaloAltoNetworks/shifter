# GCE Range Guest Image Pipeline Preflight (#1343)

Status: pre-implementation guidance

Date: 2026-07-13

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1343>

Issue title: Build GCE guest image pipeline for range hosts and Windows DCs

This note fixes the architecture boundary for native Compute Engine range-cell
images. It is not an implementation plan. The issue is requirement-free; its
title, body, deliverables, and acceptance criteria are the shipping contract.

> **Later clarification (#1761, 2026-07-20):**
> [gce-per-instance-image-resolution-preflight-1761.md](./gce-per-instance-image-resolution-preflight-1761.md)
> supersedes only this note's original single-profile selection constraint for
> legacy instances with a non-empty `ami_key`. Unkeyed instances retain the four
> defaults below; keyed instances select a complete, platform-mapped GCE profile.
> The authored key remains a logical selector and is never passed to Compute
> Engine or interpreted as a provider image reference.

## Decision Boundary

Extend the existing GCE Packer and range-profile paths. Do not introduce a
second image registry, image DTO, promotion controller, provisioner config
schema, or scenario-specific range lifecycle.

The artifacts for this issue are native GCE images:

- a Linux range-host image, including the `polaris-vm` Docker/Compose profile;
- a generalized Windows Server image when a scenario needs an ordinary Windows
  guest; and
- purpose-specific, pre-promoted DC images such as `shifter-polaris-dc` for
  `BOREAS.LOCAL`.

GDC VM Runtime qcow2 artifacts and AWS AMIs are different delivery products.
They may share provider-neutral guest provisioning scripts where those scripts
are genuinely portable, but their boot, driver, image-reference, promotion, and
runtime contracts must remain separate.

No new ADR is required while implementation stays within ADR-030's GCE
range-cell boundary, ADR-037's VM-image provenance distinction, the existing
GCE image-family contract, and the no-sysprep DC decision documented in
`gdc-windows-dc-image-build.md`. A new or revised ADR is required only if the
work changes one of those durable decisions, makes a different artifact the
image source of truth, or changes the live guest credential boundary.

## Architecture Decisions And Guardrails

- `shifter/packer/gcp/` remains the single native-GCE build surface and
  `.github/workflows/packer-gcp.yml` remains the build entrypoint. Keep it a
  separate Packer configuration from the parent AWS templates.
- An immutable candidate image is the unit of validation and promotion. A GCE
  family is a mutable deployment channel, not evidence that a particular image
  was tested. Promotion must copy the exact candidate identity that produced
  the validation evidence; it must not re-resolve "newest in dev family" after
  validation.
- The candidate manifest must bind at least the concrete GCE project/image
  identity, image type and optional checked-in profile, source revision, base
  image identity, external input checksums, build run, and validation result.
  Packer VM images are not OCI images and must not be represented as OCI
  provenance. Reuse the immutable Packer-manifest/SBOM direction in ADR-037.
- Consumer configuration continues to use the four existing logical role
  profiles: Linux host, Kali/attacker, Windows, and DC. The
  `GCP_RANGE_{LINUX,KALI,WINDOWS,DC}_*` variables remain the unkeyed defaults;
  #1761 adds one backend-owned map from a legacy logical image key to a complete
  profile within those classes. No Packer manifest, AWS SSM parameter, GDC
  `gs://` disk URL, scenario-supplied provider reference, or local hard-coded
  value becomes a second runtime lookup path.
- A promoted family URL is the stable configured channel. The provisioner must
  validate its shape before cloud mutation and retain the actual concrete image
  used by a created VM in existing GCP provider metadata for audit/debugging.
  Do not add a database image registry for this issue.
- The Polaris host is an image profile of the logical attacker/range-host role,
  not a new public OS type. Its participant Kali endpoint remains a container;
  the VM remains a GCE-native Debian Docker host with the established host SSH
  management-port split.
- A `polaris-vm` candidate is invalid when the external Compose stack is absent,
  its checksum is not the declared checksum, Compose config is invalid, a
  required image/build is missing, the full declared stack is not created and
  started before image capture, or required containers cannot become healthy
  after a clean boot. A warning or `|| true` may not turn any of those
  conditions into a promotable image.
- The GCP `polaris-vm` bake must mirror the AWS `polaris-vm` AMI contract:
  `docker compose build` is not enough. The bake has to run the full
  `docker compose up -d` before capture so all scenario containers and their
  `restart: unless-stopped` state exist in the image. The runtime
  `PolarisRangeBootstrapPlan` remains the per-range override/credential refresh
  seam; it should not become the normal creator of the 14 static target
  containers unless the provider-specific runtime contract is intentionally
  changed.
- DC promotion and scenario AD seeding happen during the image bake. Runtime
  setup verifies the expected domain and services and rotates the live domain
  Administrator credential through the existing sensitive setup path; it must
  not silently fall back to first-boot promotion.
- Preserve the intentional no-sysprep decision for isolated identical
  `BOREAS.LOCAL` ranges. This permits identical DC machine/domain identity; it
  does not permit a durable operator credential, DSRM secret, transient WinRM
  password, private key, or build transcript containing secrets to be published
  in the image. Build-only credentials must be generated, masked, passed as
  sensitive Packer environment variables, and removed or rotated before
  capture. Live credentials continue through the existing per-range secret and
  `DC_DOMAIN_PASSWORD` handling.
- Build and validation VMs run with no external IP, on the existing Packer/IAP
  network, with purpose-specific least-privilege service accounts. A Windows DC
  whose guest firewall is intentionally disabled must never be validated on a
  publicly reachable builder or validation network.
- Validation is a promotion gate, not a step summary recommendation. A failed,
  missing, cancelled, stale, or candidate-mismatched validation result blocks
  family promotion. The previous production family head stays available until
  the replacement is successfully copied; deprecate the previous head only
  after the new head exists and is verified.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| GCE Packer configuration | `shifter/packer/gcp/*.pkr.hcl`, `variables.pkr.hcl`, `locals.pkr.hcl`, and `dc-profiles/*.pkrvars.hcl` | Add behavior to the current provider-scoped templates and parameterized DC profile. Do not copy a template or workflow per scenario/domain. |
| Build and promotion workflow | `.github/workflows/packer-gcp.yml`, `.github/workflows/packer-gcp-promote.yml` | Preserve manual dispatch, GitHub Environment gates, SHA-pinned actions, WIF/OIDC, `PKR_VAR_*`, manifest upload, annotations, and summaries. Promotion must consume exact validated-candidate evidence. |
| Linux/Polaris guest setup | `gcp/polaris-vm.pkr.hcl`, `gcp/scripts/polaris/host-setup.sh`, `gcp/scripts/polaris/verify-stack.sh`, shared Packer cleanup, and `PolarisRangeBootstrapPlan` / `_polaris_scripts_gcp.py` | Bake immutable runtime dependencies and start the full compose stack before image capture; leave only per-range addresses, credentials, and targeted service refresh/verification work to the established bootstrap plan. |
| DC build and verification | `gcp/dc-prebaked.pkr.hcl`, `gcp/scripts/dc-prebaked/*`, checked-in DC profiles, `scripts/polaris-aws-range/a2_setup.ps1`, `dc_setup.py`, and `plans/dc_setup.py` | Reuse the parameterized domain/content seam and existing AD readiness/domain verification. Keep AWS transport and GDC disk mechanics out of the GCE path. |
| Runtime image configuration | `GCERangeImageProfile`, `GCERangeCellConfig.get_profile`, `load_gce_range_cell_config` | Keep one typed role-to-image/sizing contract and fail before instance creation for a missing or malformed selected image. Do not add a parallel resolver. |
| Runtime env propagation | `.github/workflows/_gcp-dev.yml`, `scripts/gcp/render_runtime_env.py`, `shifter/installation/runtime_inventory.py`, `engine.ecs._GCP_PROVISIONER_ENV_KEYS`, Helm/Kubernetes provisioner Job admission policy | Every image/profile knob must traverse the existing generated-env inventory and allowlists. Image references are non-secret configuration; credentials remain sensitive values/references. |
| GCE realization and state | `gcp_range_cell_plan.py`, `gcp_range_cell_resources.py`, `gcp_range_cells.py`, `provisioner_db.py`, and `state_helpers.py` | Let the existing plan create Shielded VMs without external IPs and persist concrete provider metadata. Do not let Packer or workflows create live range resources. |
| Secrets and redaction | `shared.cloud.sensitive_env`, provisioner cloud secret adapters, `gcp_guest_secrets.py`, `DC_DOMAIN_PASSWORD`, setup-orchestrator sensitive output handling, and `log_redact.safe_log_fingerprint` | Keep values out of metadata, argv, summaries, manifests, transcripts, events, and provider state. Log safe identifiers/fingerprints and failure categories only. |
| Error and lifecycle handling | Existing GitHub `::error::` fail-loud convention; provisioner `CloudError` family, cleanup, CMS/engine status and sanitized error envelopes | Image workflows fail before promotion; range boot failures continue through existing provisioner cleanup/status paths. Do not add image-specific public status values or an exception hierarchy. |
| Static and live validation | `shifter/packer/tests/test_packer_gcp.py`, `packer validate`, provisioner GCE tests, `scenario-dev/polaris/tests/*`, and existing Polaris range health/smoke conventions | Static tests protect template shape; disposable candidate boots prove the guest; a fresh range-cell smoke proves the provisioner/config hand-off. Do not claim one layer substitutes for another. |
| Architecture and supply chain policy | ADR-030, ADR-037, `gcp-cicd-packer-preflight-505.md`, `vm-guest-credential-preflight-762.md`, and repo ADR/workflow guards | Preserve range isolation, verified downloads/package repositories, action pinning, secret hygiene, and honest VM-image provenance. |

## Cross-Cutting Layers The Design Must Pass

### Security and auth

- **Workflow authorization:** build runs only from the dispatched repository
  revision; promotion retains the protected production GitHub Environment.
  Continue using GCP WIF with `contents: read` and only the required
  `id-token: write`. Do not add a service-account key, PAT, arbitrary ref input,
  or promotion bypass.
- **Workflow input shape:** `image_type`, environment, and DC profile/purpose
  must be selected from supported checked-in values or validated as strict
  slugs and resolved beneath `dc-profiles/`. Never interpolate an unchecked
  profile into a path, family, label, or shell fragment. Candidate identity and
  checksum inputs must have exact expected GCE/hash shapes.
- **Supply chain inputs:** resolve and record the concrete base image; use
  signed package repositories or verified upstream checksums for executable
  downloads. The external Polaris tarball must be an immutable object generation
  or equivalent immutable locator plus a required digest. A mutable GCS key by
  itself is not reproducible provenance. Every Compose service pulled from a
  registry must use an immutable `@sha256:` image reference; only services built
  from the checksum-bound stack may use a local tag.
- **Secret-handling surface:** WinRM, domain Administrator, DSRM, content-seed,
  SSH, and cloud credentials are distinct secrets. Packer receives build-only
  secrets as sensitive environment variables, never `-var` argv. Validation
  receives only disposable credentials. No secret may enter the image manifest,
  GCE labels/description, GCS object name, GitHub artifact, step summary, or
  Packer command line.
- **OS/network exposure:** builder and validation instances have no external
  NIC and use the established IAP-restricted subnet/firewall. Validation must
  also prove the runtime Shielded-VM posture used by
  `gcp_range_cell_resources.instance_resource`: Secure Boot, vTPM, integrity
  monitoring, blocked project SSH keys, and no public address. Do not weaken
  guest or VPC controls to make a candidate boot.
- **Guest metadata:** image validation must not use metadata as a secret
  transport. Public bootstrap keys and non-secret flags may use the established
  shape; passwords, private keys, stack credentials, and validation reports may
  not. Do not copy live range startup metadata into a reusable image.
- **Published-disk hygiene:** remove transient installers, tarballs, Packer
  credentials, shell/PowerShell histories, unattested build inputs, and
  secret-bearing transcripts before capture. The no-sysprep DC exception does
  not waive disk hygiene.

### Config, validation, and runtime shapes

- **Packer shape gate:** `packer init`/`validate` plus
  `test_packer_gcp.py` validate template/provider separation, required
  variables, profile parameterization, family naming, and the presence of
  fail-closed validation hooks. This gate does not prove a booted guest.
- **Bake gate:** for `polaris-vm`, the Packer provisioner must fetch the
  immutable stack tarball, verify its digest, validate Compose, build/pull the
  images, run the full compose stack, and fail before image capture when any
  declared service cannot be created and started. Images without created
  containers are not equivalent to a prebaked stack because `restart:
  unless-stopped` has no stopped container to restart on the range VM.
  Before executing entrypoints, the bake must reject privileged/host-namespace
  services, dangerous capabilities and sensitive host binds, then install and
  verify metadata-server blocks for both host and Docker-forwarded traffic. This
  prevents an externally pulled workload from using the attached builder identity.
- **Candidate gate:** boot the concrete candidate in a disposable isolated GCE
  validation cell and reboot it at least once. Linux validation checks Google
  guest networking/agent, host SSH on the configured management port, Docker
  daemon, Compose plugin/config, required local images, the already-created
  full stack after startup/restart, and required service health. DC validation
  checks the expected domain/forest, AD DS, DNS, Netlogon, OpenSSH and required
  management/access services, AD content invariants, and successful reboot without promotion or
  manual input. The candidate validator must not run `docker compose up`; doing
  so would manufacture missing containers and mask an incomplete release image.
- **Promotion gate:** validation evidence names the exact candidate. Promotion
  verifies that identity/evidence before copy and verifies the new prod image
  before moving/deprecating the family head. Family resolution is prohibited
  between validation and copy because it creates a time-of-check/time-of-use
  race.
- **Runtime env gate:** configured family/full-image URLs pass through the GCP
  deploy renderer, runtime inventory, engine task allowlist, Kubernetes
  admission allowlist, and `load_gce_range_cell_config`. Reject malformed
  references, invalid disk sizes/types, and image/profile mismatches before
  calling Compute Engine. In particular, the configured boot disk cannot be
  smaller than the source image.
- **Fresh-range gate:** the actual GCE range provisioner, not a workflow-only
  substitute, launches a clean cell from the promoted configured families with
  no manual setup. Existing guest setup verifies the DC and starts/verifies the
  Polaris stack; existing state/error/cleanup behavior remains authoritative.

### Errors, observability, and persistence

- GitHub logs and summaries may include image type/profile, project, concrete
  image name/ID, family, source revision, validation phase, duration, and safe
  failure category. They must not include environment dumps, command tracing,
  raw manifests with secret-bearing fields, WinRM output, AD transcripts,
  compose overrides, or credentials.
- Use `::error::` plus non-zero exit for build/validation/promotion failures.
  Preserve the prior prod family head on failure and clean disposable builder
  and validation resources. Cleanup failure is separately visible and must not
  overwrite the primary failure.
- Runtime failures keep the provisioner's ECS logging, request/range/instance
  correlation, safe fingerprints, idempotent cleanup, and existing sanitized
  CMS/engine error envelope. Do not surface raw Google API responses, startup
  output, AD exception bodies, or external artifact URLs to participants.
- Packer manifests and validation evidence are workflow artifacts; they are not
  application persistence. Live instance state uses the existing provisioned
  state/provider-metadata fields, storing non-secret concrete image identity and
  secret references only.

## Extensibility Seam

The durable seam is one image release descriptor with:

- logical image type (`linux`, `kali`/`polaris-vm`, `windows`, or `dc`);
- optional checked-in purpose/profile (for example `polaris`);
- source environment/project and destination channel/project;
- immutable candidate image identity and evidence identity; and
- the stable consumer family URL.

Keep family naming, validation selection, promotion, and runtime binding derived
from that descriptor. The next region, base OS revision, non-Polaris Linux
range host, or new AD domain should require a profile/config/evidence change,
not another workflow, provisioner DTO, scenario field, or copy of the DC
template. The profile/purpose is the required parameter; it must not be inferred
from a filename, domain string, or mutable family head.

## Whole-Repo Surfaces In Scope

- Packer: `shifter/packer/gcp/**`, shared portable scripts under
  `shifter/packer/scripts/**`, and `shifter/packer/tests/test_packer_gcp.py`.
- Credentialed workflows and routing: `.github/workflows/packer-gcp.yml`,
  `packer-gcp-promote.yml`, `_quality.yml`, `_gcp-dev.yml`, and
  `.github/quality-path-filters.yaml` if a new owned path is added.
- Configuration: `scripts/gcp/render_runtime_env.py` and tests,
  `shifter/installation/runtime_inventory.py`,
  `shifter/shifter_platform/engine/ecs.py` and tests, Helm/Kubernetes
  provisioner Job templates, and the validating admission policy.
- Runtime consumption: provisioner `config.py`, GCE range plan/resources/cells,
  DC and Polaris setup plans, state writers, logging/redaction, and focused
  tests.
- Scenario acceptance: `scenario-dev/polaris/tests/**` and the existing
  Polaris health/isolation conventions; reuse them for full-range evidence,
  while keeping guest-local image checks image-owned.
- Operations and architecture docs: `shifter/packer/gcp/README.md`,
  `docs/architecture/gcp-guest-images.md`,
  `docs/dev/gcp-range-cell-deploy.md`, `docs/dev/deploy-secrets.md`, and the
  GDC Windows/DC note where provider distinctions need clarification.
- Guardrails: ADR guard for architecture/workflow changes, actionlint for
  workflows, Packer tests/validation, gitleaks/SAST, and the required
  import/Terraform/Kubernetes checks for any additionally touched surfaces.

## Known Gaps The Implementation Must Close

- `host-setup.sh` currently warns and succeeds when the Polaris stack is absent,
  and tolerates a Compose pull failure. That behavior cannot satisfy a
  promotable `polaris-vm` contract.
- Current Packer tests are structural/static. They do not prove Docker/Compose,
  a GCE reboot, or AD/DC services on a captured image.
- Current promotion resolves the newest dev-family member at promotion time,
  so it cannot prove it copied the candidate that was validated.
- Current promotion choices/family derivation cover generic image types but not
  `polaris-vm` or purpose-specific `dc-prebaked` families.
- The DC bake is intentionally un-sysprepped, while existing workflow comments
  describe all Windows/DC build credentials as discarded by sysprep. The
  implementation and docs must distinguish generalized Windows/DC builders
  from the pre-promoted DC path and prove credential/transcript cleanup for the
  latter.
- The current DC scripts contain baked credential defaults. Identical
  `BOREAS.LOCAL` identity is allowed; shared privileged operator credentials are
  not. Reuse the runtime secret/rotation boundary and remove secret defaults
  from the release contract.
- Runtime configuration checks presence but does not currently provide a full
  syntactic/compatibility gate for image URLs, disk types, and source-image
  minimum disk size. Provider rejection after resource creation is too late.
- GCP `polaris-vm` stack verification currently proves the tarball, Compose
  config, and images, but a build that never creates the full compose stack can
  still pass candidate validation because the disposable validation VM runs
  `docker compose up -d`. That masks the range-launch gap where
  `PolarisRangeBootstrapPlan` recreates only `dns`, `a14-kali`, and
  `a9-splice`.

## Gotchas And Anti-Patterns

- Do not treat `packer validate`, a successful image capture, or "instance is
  RUNNING" as guest readiness.
- Do not validate a family and then promote whichever image is newest in that
  family. Validate and promote one immutable candidate.
- Do not auto-promote directly from build, accept a skip-validation flag, or
  deprecate the current prod head before the replacement is verified.
- Do not let an empty external stack bucket, missing tarball, mutable object,
  checksum mismatch, failed Compose pull, unhealthy container, or missing AD
  service degrade to a warning.
- Do not treat "all 17 images are present" as equivalent to "all 17 range
  containers exist and will restart on boot." Compose restart policy only
  restarts containers that were already created.
- Do not rely on `packer-gcp-validate.yml` to create the stack for the first
  time; validation proves an image candidate, but the promoted disk is still the
  pre-validation captured image.
- Do not change the shared Polaris runtime bootstrap from targeted recreate to
  full-stack recreate without making the provider boundary explicit and
  preserving AWS's metadata-firewall and Bedrock credential ordering.
- Do not bake a live domain password, DSRM secret, WinRM bootstrap password,
  private SSH key, cloud credential, compose secret, or transcript containing
  one into a reusable image.
- Do not interpret no-sysprep as permission to skip cleanup, validation,
  per-range credential rotation, or range isolation.
- Do not expose DC, WinRM, RDP, SSH, Docker, or validation services on a public
  builder/validation VM. Do not disable Secure Boot or widen VPC firewalls to
  accommodate a broken image.
- Do not conflate a Packer manifest, GCE image family, concrete GCE image,
  exported GDC qcow2, AWS AMI/SSM parameter, and provisioner image profile.
  They have different identities and consumers.
- Do not put provider image references in scenario YAML or infer a GCE family
  name from `ami_key`. Per #1761, an existing logical `ami_key` may select only
  an exact platform-configured profile within the existing role/profile routing.
  Do not add a Polaris-only runtime config object.
- Do not duplicate AD seed logic, DC readiness checks, Compose bootstrap logic,
  runtime env allowlists, secret adapters, logging sanitizers, exception types,
  or workflow promotion logic.
- Do not upload rendered Packer vars, raw environment dumps, validation disks,
  build workspaces, or guest logs as artifacts. Upload bounded non-secret
  manifest/evidence only.

## Non-Goals And Implementation Boundaries

- No issue implementation in this preflight change.
- No redesign of CMS/CTF range lifecycle, public scenario schemas, GCE network
  cells, Secret Manager adapters, Guacamole, or provisioner state envelopes.
- No replacement of the retained GDC VM Runtime image pipeline or AWS AMI/SSM
  pipeline, and no promise that a native GCE Windows image is portable to GDC.
- No first-boot AD promotion fallback, per-range forest/domain naming, multi-DC
  replication topology, or sysprep of a promoted DC.
- No general image catalog/database, custom signer service, OCI-attestation
  claim for VM images, or automatic production deployment.
- No dynamic realization of the external Polaris source tree; immutable
  artifact assembly and validation for the existing prebaked-stack model are
  in scope, while a new packaging system is not.
- No broad IAM expansion, public builder networking, or weakening of workflow,
  ADR, Packer, SAST, secret, Terraform, or Kubernetes guardrails.
