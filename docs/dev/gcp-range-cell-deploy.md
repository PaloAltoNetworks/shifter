# GCP GCE range-cell deploy runbook

The GCP range backend defaults to the GCE range-cell path. This runbook covers
enabling it in a real environment, mapping images, and rolling back to GDC.

For the backend design see
`docs/architecture/gcp-range-cell-backend-preflight-1341.md`; for the Polaris
port see `docs/dev/polaris-gcp-range-cell.md`. For the image build see
`docs/architecture/gcp-guest-images.md`.

## Backend selection

`GCP_RANGE_BACKEND` selects the GCP range backend:

- `gce` (default): provision each range as an isolated GCE range cell.
- `gdc`: the retained GDC VM Runtime path.

The default lives in `config.py` (`get_gcp_range_backend`) and the generated
runtime config (`scripts/gcp/render_runtime_env.py`). To roll back an
environment, set the `GCP_RANGE_BACKEND=gdc` repository/environment variable and
redeploy. The GDC configuration block is retained in the rendered contract and
is inert while the backend is `gce`.

## Required configuration

Set the GCE range-cell variables documented in
`docs/dev/deploy-secrets.md` ("GCE range-cell backend variables"). The
minimum for a live range is: `RANGE_NETWORK_ZONE`, `GCP_RANGE_LINUX_IMAGE`,
`GCP_RANGE_DC_IMAGE`, and `GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL`. Polaris also
needs `GCP_RANGE_VERTEX_SERVICE_ACCOUNT_EMAIL`.

`GCP_RANGE_CELL_PROJECT_ID` defaults to the project parsed from the range VPC
self-link, so the range backend targets the real range project even when the
control-plane `GCP_PROJECT_ID` is a deploy-overlay placeholder.

## Network mode

`GCP_RANGE_CELL_NETWORK_MODE` selects how range guests are networked:

- `shared-vpc` (default): each range gets its own subnet in the pre-existing,
  platform-peered range VPC (`RANGE_NETWORK_ID`/`RANGE_VPC_ID`). This mirrors the
  AWS shared-VPC + per-range-subnet model, so the provisioner reaches guests over
  the existing platform↔range peering. Isolation is by per-range subnet and
  target-tag firewall rules (see `docs/architecture/range-isolation-model.md`).
  Requires `RANGE_NETWORK_ID` (or `RANGE_VPC_ID`); both are rendered from the
  `range_network_id` Terraform output.
- `vpc-per-range`: each range mints its own isolated VPC. This gives VPC-hard
  isolation but currently has **no provisioner reachability path** (no peering or
  IAP is created), so guests are unreachable and ranges cannot reach READY. It is
  retained as a selectable mode for a future peering/IAP implementation; do not
  use it for live deployments yet.

## Image mapping

A range instance resolves to one of four image profiles by role and OS
(`GCERangeCellConfig.get_profile`):

| Instance | Profile | Variable |
|---|---|---|
| Domain controller (`role=dc`) | dc | `GCP_RANGE_DC_IMAGE` |
| Kali / attacker | kali | `GCP_RANGE_KALI_IMAGE` |
| Windows guest | windows | `GCP_RANGE_WINDOWS_IMAGE` |
| Everything else (Linux host) | linux | `GCP_RANGE_LINUX_IMAGE` |

For a Polaris deployment the Docker host maps to the linux profile and the
`BOREAS.LOCAL` DC to the dc profile, so set `GCP_RANGE_LINUX_IMAGE` to the
`shifter-polaris-vm` family and `GCP_RANGE_DC_IMAGE` to `shifter-polaris-dc`.
Because there is one image per profile per deployment, a single environment
serves either Polaris hosts or generic Linux guests, not both; run generic
scenarios in a separate deployment or environment.

Images are native GCE images referenced by family:
`projects/<project>/global/images/family/shifter-<type>`. Unlike the GDC path
there is no qcow2 export or CDI import.

## Service accounts

The GCE range-cell backend uses two service accounts:

- **Host SA** (`GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL`): attached to every range
  guest. Grant logging write and monitoring write, plus (for Polaris)
  `roles/storage.objectViewer` on the assets bucket so the range host can fetch
  the smoketest tarball (`AGENT_STORAGE_BUCKET`). The host also reads its own
  per-range Vertex key from Secret Manager, but you do not grant that at the
  project level: the provisioner binds `roles/secretmanager.secretAccessor` for
  this SA on each `shifter-range-<N>-vertex-key` secret at mint time and drops it
  with the secret at teardown, so the host never sees the platform secrets
  (`app`, `db`, `guacamole-*`).

  The guest VM is created with the `cloud-platform` OAuth scope
  (`GCERangeCellConfig.service_account_scopes`); scope is a coarse legacy gate,
  so these IAM roles are the real access control. `cloud-platform` is required,
  not just convenient: Secret Manager has no narrower OAuth scope, so a
  narrow logging/monitoring scope makes both the Storage and Secret Manager
  reads fail with a generic 403 regardless of IAM.
- **Vertex SA** (`GCP_RANGE_VERTEX_SERVICE_ACCOUNT_EMAIL`): the identity whose
  short-lived, per-range key the a14-kali agent uses for Vertex AI. Grant only
  `roles/aiplatform.user`. The participant container is blocked from the
  metadata server and reads the key from Secret Manager (see
  `shifter/engine/provisioner/gcp_range_vertex_creds.py`).

These are independent inputs. In an account that requires it, both variables may
name the same service account; nothing in the render or provisioner assumes they
differ.

## Baking a new pre-promoted DC image

Domain controllers are **pre-promoted at bake time** so a range boots an
already-promoted DC with no per-range promotion (promotion takes ~15-20 minutes
and would dominate time-to-serve). One parameterized Packer template,
`shifter/packer/gcp/dc-prebaked.pkr.hcl`, bakes many DC images. At range setup
the DC is only **verified** (that it is already the expected promoted domain),
never promoted.

Runtime DC mutation is **disabled and unreachable**. Two paths are locked off,
each retained as code for a future, explicitly authorized decision but selectable
by nothing:

- **Runtime promotion**: `_should_promote_dc_at_runtime` always returns `False`
  (no provider default, no `DC_RUNTIME_PROMOTION` env escape hatch). A DC image
  that is not actually pre-promoted fails verification at setup rather than
  silently promoting.
- **Runtime bootstrap/rename**: `_should_run_dc_bootstrap_plan` always returns
  `False` (no provider default, no `DC_BOOTSTRAP_VIA_SETUP_PLAN` env escape
  hatch). The DC `BootstrapPlan` renames the guest, which would mutate a
  pre-promoted DC's AD identity; the provisioner instead gets SSH to the DC from
  the guest metadata startup script (host key + `administrators_authorized_keys`).

Each DC image is a **profile** var-file in `shifter/packer/gcp/dc-profiles/`. The
profile sets the domain, NetBIOS name, AD-content seed, and purpose (which names
the image family `shifter-<purpose>-dc`). To add a DC for a new domain:

1. Copy `dc-profiles/example.pkrvars.hcl` to `dc-profiles/<name>.pkrvars.hcl` and
   set `dc_image_purpose`, `dc_domain_name`, `dc_netbios_name`, and
   `dc_content_script`.
2. Add the AD-content seed script the profile points at (path relative to
   `shifter/packer/gcp`). It creates the scenario's OUs/users/groups/SPNs and
   accepts a `-DnsForwarder` parameter; the Polaris one is
   `scripts/polaris-aws-range/a2_setup.ps1`.
3. Run the **Packer GCE Image Build** workflow with `image_type=dc-prebaked` and
   `dc_profile=<name>`. It publishes image family `shifter-<purpose>-dc`.
4. Point the consuming scenario at that family. The scenario's `dc_config`
   `domain_name` must match the baked domain, because setup verifies the
   already-promoted DC against it (it never promotes).

The `polaris` profile reproduces the Polaris `shifter-polaris-dc`
(`BOREAS.LOCAL`) image and is the default.

## Baking the polaris-vm host image (compose stack)

The Polaris range host (`shifter-polaris-vm`) is a Debian Docker host that boots
the **prebaked** Polaris docker-compose stack (~17 containers including the
participant `a14-kali`). Genuine dynamic realization is separate future work; for
now the stack is baked into the image so time-to-serve is a range launch, not a
full container build. `host-setup.sh` fetches the stack tarball from GCS at bake
time and `docker compose build`s it in; the range bootstrap then only rewrites
the DC IP into `docker-compose.override.yml` and `docker compose up`.

The compose stack lives outside this repo (the AWS polaris-vm AMI is baked from
the same external stack), so the GCE bake fetches it from GCS:

1. **Get the stack tarball.** It is the assembled `scenario-dev/polaris/build/`
   tree (a `docker-compose.yml` plus each service's local build context). It is
   platform-neutral: every service is a local `docker build` (no registry/ECR or
   cloud-specific references), so the GCS copy is the same content as the AWS S3
   build tarball (`s3://shifter-polaris-bake-<env>-<acct>/polaris/build-*.tar.gz`).
2. **Pack it for GCP's layout.** `host-setup.sh` extracts *into*
   `.../scenario-dev/polaris/build` and expects `docker-compose.yml` at the
   tarball root, so pack the *contents* of `build/` at the root
   (`cd build && tar czf polaris-stack.tar.gz .`), not the `scenario-dev/...`
   prefix the AWS tarball uses.
3. **Upload** to `gs://<GCP_POLARIS_STACK_BUCKET>/polaris/stack/polaris-stack.tar.gz`
   (the default `POLARIS_STACK_KEY`), and grant the packer builder SA
   `roles/storage.objectViewer` on the bucket.
4. **Set the `GCP_POLARIS_STACK_BUCKET` repository variable** to that bucket
   (see `docs/dev/deploy-secrets.md`). The build exports it as
   `PKR_VAR_polaris_stack_bucket`; empty leaves the host range-ready without the
   stack baked.
5. **Run the Packer GCE Image Build** workflow with `image_type=polaris-vm`. It
   publishes image family `shifter-polaris-vm`, which `GCP_RANGE_LINUX_IMAGE`
   points at.

The DC's Administrator password baked by `a2_setup.ps1` must match
`DC_DOMAIN_PASSWORD` in the deploy config (see `docs/dev/deploy-secrets.md`), so
the provisioner's `set_admin_password` step succeeds against the prebaked DC.

## NGFW

There is no GCE-native NGFW (Palo Alto VM-Series) path; that path exists only
under the GDC backend. A GCP range that requests an NGFW is not supported while
the backend is `gce`.
