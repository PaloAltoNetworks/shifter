# Foundation-Only GCP Image Bootstrap Preflight (#2338)

Status: pre-implementation guidance

Date: 2026-09-20

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/2338>

This note fixes the ownership and handoff boundaries for importing the public
GCE base set after foundation bootstrap and before platform Terraform. It is
not an implementation plan. ADR-037-R9 remains the governing image-delivery
decision; this note clarifies its bootstrap side.

## Decision and boundaries

- `scripts/bootstrap/gcp_base_images.py` remains the one owner of public GHCR
  discovery, OCI validation, digest-derived GCE naming, import/reuse, readiness,
  and role-to-`GCP_RANGE_*_IMAGE` projection. Do not reproduce those rules in
  Terraform, workflow shell, `gcp_control_plane.py`, or the provisioner.
- The import uses a CLI-owned, same-project **ephemeral GCS bucket**. Its name is
  built from the explicitly selected project, a Shifter import prefix, and a
  per-invocation nonce; every `gcloud` operation carries `--project`. Creation
  enforces the selected region, uniform bucket-level access, public-access
  prevention, and zero soft-delete duration. No platform Terraform output is an
  input.
- The importer owns a bucket only after its create call succeeds and never
  adopts or deletes a pre-existing name. The outermost `try/finally` empties and
  deletes that exact run-owned bucket after success or failure; per-image cleanup
  still removes its exact object promptly. Cleanup failure is a command failure,
  not a warning or reported success. Per-run buckets also keep concurrent imports
  from racing each other's payload or cleanup.
- Do not add a standing or project-wide storage grant. The local operator
  identity already authorized for foundation/platform bootstrap performs the
  upload and image creation. If a live API proves that a Google-managed service
  identity needs object read access, the only acceptable fallback is a
  run-owned, exact-bucket/object-scoped temporary binding recorded in the same
  cleanup stack and removed on every exit. Never use `allUsers`,
  `allAuthenticatedUsers`, a project-wide Storage role, or a service-account key.
- The supported fresh-project command is a **single local orchestration**:
  the existing GCE control-plane bootstrap opts into public-base-image import,
  publishes all three exact references to its selected GitHub deployment
  Environment, overlays those same three existing env keys in the current
  process, and then calls the existing `gdc_bootstrap_cluster` path. The overlay
  is restored in `finally`. Standalone `gcp-images` remains useful for image
  refreshes, but the documented first bootstrap must not require shell `eval`,
  `source`, a custom wrapper, or a new persisted handoff schema.
- Resolve and validate Kali, Ubuntu, and DC before the first mutation. Import
  only missing digests, require every imported or reused image to be `READY`,
  then publish the three GitHub variables as one logical phase. The platform
  bootstrap starts only after all publication calls succeed. A rerun converges
  after partial image or GitHub-variable completion.
- Durable digest-named GCE images are intended outputs, not temporary resources.
  Do not roll back a valid imported image merely because a later role, GitHub
  publication, or platform step failed. Retry reuses it after revalidating its
  full source reference, role metadata, and `READY` state.

No new database, repository, service, DTO, exception family, logger, or generic
cross-cloud image abstraction belongs in this change.

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Required use |
| --- | --- | --- |
| CLI and orchestration | `scripts/bootstrap/cli.py`, `deploy.py`, `GDCBootstrapConfig`, `gdc_bootstrap_cluster` | Extend the existing command/config path. The selected project, environment, region, zone, dry-run, and confirmation behavior stay one target contract. |
| Command execution and operator output | `bootstrap_core.run_cmd`, `_validate_argv`, redacted argv logging, `header`/`info`/`success`/`error` | Use argv lists only. Do not add direct subprocess calls, shell strings, or a second logging/error surface. |
| Temporary cloud privilege cleanup | `gcp_control_plane.gcp_terraform_bootstrap_credentials` and its stale-key pruning/finally cleanup | Mirror its explicit ownership, restoration, best-effort revocation ordering, and fail-loud cleanup semantics for the transfer bucket and any proven-necessary temporary binding. |
| OCI/GCE image contract | `gcp_base_images.ResolvedArtifact`, `ImportedImage`, `validate_artifact_manifest`, `image_name_for`, `render_range_image_env` | Preserve public package allowlisting, digest pinning, exact role mapping, traceable descriptions/labels, and idempotent reuse. Tighten these validators in place rather than adding another parser. |
| Runtime env ownership | `scripts/gcp/render_runtime_env.py::_GCE_RANGE_ENV_KEYS`, `gcp_control_plane.check_gce_range_preconditions`, `shifter/engine/provisioner/config/_gce_profile.py` | Carry the existing three env names. The renderer owns projection and the provisioner owns the general Compute Engine image-reference grammar. |
| CI publication | `gh variable set` in `gcp_base_images_import`; `_gcp-dev.yml` explicit `vars.GCP_RANGE_*_IMAGE` projection | Publish exact image resources to the selected Environment; do not write a repository variable, secret, mutable family reference, or workflow output substitute. |
| Tests and architecture gates | `scripts/bootstrap/tests/test_gcp_base_images.py`, `test_cli.py`, `test_gcp_control_plane.py`, `scripts/adr_guard/tests/test_deploy_workflow.py` | Mock only the `run_cmd`/cloud boundary, retain pure parser tests, and keep the full quality/ADR gates authoritative. |

## Cross-cutting layers

### Security and validation

1. **Target/auth surface.** `argparse` and `GDCBootstrapConfig` select the
   project, Environment, region, and zone. Narrow read-only auth checks follow
   the `gcp_runner._verify_prerequisites` pattern (`gh auth status` and GCP
   credentials) before mutation. Every cloud call names the project; ambient
   `gcloud config project` is never authority. The GitHub Environment used for
   publication is the same `config.environment` used by the local bootstrap.
2. **Registry shape.** Public discovery remains credential-free: no `oras
   login`, PAT, Docker auth handoff, or package secret. The existing manifest
   validator must shape-check the manifest, layer descriptors, artifact/layer
   media types, allowlisted role, full SHA-256 descriptors, and protected-source
   revision before download. Tags are discovery pointers only; pulls and stored
   provenance use `package@sha256`.
3. **GCS/GCE policy.** The temporary bucket is private, uniform-access,
   same-project, retention-free scratch. Object paths and GCE image names derive
   only from the validated role/digest mapping. Reuse compares the exact recorded
   OCI package plus full digest and code-owned role metadata, not merely the
   12-character name suffix, and verifies `READY`. A conflicting pre-existing
   image fails closed. A code-owned non-ready partial image may be reconciled;
   an unowned image must never be deleted.
4. **Env/config shapes.** The in-memory overlay contains exactly
   `GCP_RANGE_LINUX_IMAGE`, `GCP_RANGE_KALI_IMAGE`, and
   `GCP_RANGE_DC_IMAGE`, with exact
   `projects/<project>/global/images/<digest-derived-name>` values. It passes
   through `check_gce_range_preconditions`, the existing GCP runtime renderer,
   `_GCE_RANGE_ENV_KEYS`, Kubernetes ConfigMap/admission allowlists, and finally
   `_gce_profile._validate_gce_image_reference`. Do not add aliases or another
   env/JSON schema.
5. **Secret and OS exposure.** Image refs, bucket names, and digests are
   non-secret; the importer does not copy cloud/GitHub credentials from their
   existing auth mechanisms into argv, the image-reference environment overlay,
   Terraform, GitHub variables, temp payloads, or logs. Local disk payloads stay
   inside `TemporaryDirectory`. Do not print a credential file, access token,
   command environment, or unbounded child stderr.
6. **Errors and observability.** Keep `BaseImageError` as the domain failure and
   translate it once at the CLI boundary to the existing operator error/nonzero
   exit shape. Messages may name role, package, digest, image, bucket, and failed
   cleanup action. Do not add per-command exception subclasses or report success
   before transfer cleanup, all three `READY` checks, GitHub publication, and
   handoff binding complete.

### Maintainability and persistence

The only persistent state added by the operation is the intended native GCE
image and the existing GitHub Environment variables. The exact OCI source stays
on the image description/labels; no local state file, Terraform resource, or
database row becomes an authority. The existing role tuple/mapping is the base
set contract. Keep durable image reconciliation separate from temporary
transfer-resource cleanup, and keep build/export infrastructure separate from
tenant import scratch.

### Extensibility seam

The seam required here is
`(project_id, environment, region, logical role, public package, immutable
digest, runtime env key)`. Project/environment/region belong to the existing
bootstrap config; role/package/env-key policy stays in `gcp_base_images.py` as
data. This permits another tenant/region or public base role without another
workflow or provider-neutral image abstraction. Private registry credentials,
attestation, and qualification remain separate policy seams and must not be
smuggled into this one.

## Whole-repository surfaces in scope

- `scripts/bootstrap/{cli,deploy,gcp_base_images,gcp_control_plane,bootstrap_core}.py`
  and their focused tests.
- `scripts/bootstrap/README.md`, `docs/technical/dev/setup.md`,
  `docs/dev/deploy-secrets.md`, and `docs/architecture/gcp-guest-images.md` for
  one executable command/order and removal of the platform-bucket dependency.
- `.github/workflows/_gcp-dev.yml` and `scripts/gcp/render_runtime_env.py` only to
  preserve the existing GitHub-variable-to-runtime projection; no new workflow
  or renderer key is required.
- `shifter/engine/provisioner/config/{_gce,_gce_profile}.py`,
  `shifter/shifter_platform/engine/ecs/_env.py`, the chart/Kubernetes
  provisioner-job admission allowlists, and installation runtime inventories as
  downstream validators to keep passing, not as new import owners.
- `docs/adr/index.yaml`, ADR guard, actionlint, Terraform/TFLint/Checkov where
  touched, and the full CI suite.

## Gotchas and anti-patterns

- Do not read `gce_base_image_bucket` from platform Terraform, reuse the
  release-evidence/state bucket, or retain a new foundation bucket solely for
  transient imports.
- Do not create a bucket per role, leave soft-deleted object payloads, swallow a
  failed delete, or delete a name without first proving target-project ownership.
- Do not let two imports share a transfer bucket or adopt a colliding bucket
  name. Cleanup is limited to the bucket successfully created by this process.
- Do not publish a family URL or tag when the importer produced an exact image
  resource. Do not let the local overlay and GitHub Environment use separately
  recomputed values.
- Do not mutate GitHub variables until all artifacts validate and all GCE images
  are `READY`; do not start platform bootstrap after partial publication.
- Do not call Packer, dispatch `packer-gcp.yml`, fall back to a tenant bake, or
  treat package publication/import as candidate qualification or attestation.
- Do not use shell `source`/`eval`, a committed `.env`, `local.auto.tfvars`, a
  generated JSON DTO, or a second env parser for the local handoff.
- Do not move import logic into Terraform provisioners, GitHub workflow shell,
  the Django runtime, or the range provisioner.

Targeted tests must fault each boundary after bucket creation (download, upload,
image create, readiness, and GitHub publication) and prove object/bucket cleanup,
environment restoration, and retry reuse. Dry-run must execute manifest and
target validation while recording no ORAS payload pull, GCS/GCE mutation,
GitHub mutation, or Packer/workflow dispatch. The full suite remains the CI gate.

## Non-goals

- Private GHCR/authentication (#2312), stronger build attestation (#2328), and
  optional image qualification (#2296).
- Changes to Packer recipes, protected build/promotion workflows, Windows/DC
  licensing policy, AWS AMIs, GDC cleanup, DNS automation, or pack-owned images.
- Rollback/garbage collection of older valid digest-named GCE images. Their
  lifecycle needs an explicit retention policy and is not temporary cleanup.
- A generic cross-cloud image importer, durable bootstrap state service, or new
  runtime configuration key.
