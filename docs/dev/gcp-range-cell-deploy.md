# GCP GCE range-cell deploy runbook

Part of the Shifter deploy and operations docs; start at the [documentation home](../index.md).

The GCP range backend defaults to the GCE range-cell path, the approved GCP
live-fire backend (ADR-030). This runbook covers enabling it in a real
environment and mapping images.

For the backend design see
`docs/architecture/gcp-range-cell-backend-preflight-1341.md`; for the Polaris
port see `docs/dev/polaris-gcp-range-cell.md`. For the image build see
`docs/architecture/gcp-guest-images.md`.

## Backend selection

`GCP_RANGE_BACKEND` selects the GCP range backend:

- `gce` (default): provision each range as an isolated GCE range cell. This is
  the only approved GCP **live-fire** backend (ADR-030).
- `gdc`: the retained GDC VM Runtime path (**development/validation only**). It is
  **not** a live-fire rollback: normal Mission Control and CTF range provisioning
  fails closed on `gdc` (the CMS service gate rejects the launch and the
  provisioner independently denies a live-fire GDC apply; issue #1348). Do not set
  `GCP_RANGE_BACKEND=gdc` to "roll back" a live-fire environment when GCE is
  unhealthy. A GCE availability problem must be fixed on the GCE path, never by
  downgrading containment.

The default lives in `config.py` (`get_gcp_range_backend`) and the generated
runtime config (`scripts/gcp/render_runtime_env.py`). The GDC configuration block
is retained in the rendered contract and is inert while the backend is `gce`.

### Switching the selector on an environment with existing GDC ranges

Range destroy currently routes from the deploy-wide `GCP_RANGE_BACKEND` selector,
so **tear down any existing GDC ranges before flipping `GCP_RANGE_BACKEND` from
`gdc` to `gce`**. Flipping while GDC ranges are still live would route their
teardown down the GCE path and strand the GDC namespaces, VMs, disks, secrets,
L2 Networks, and subnet allocations (recover those with the manual GDC cleanup
runbook). Binding the backend to per-range state so this ordering is no longer
required is tracked by #1666.

The environment setting is an operator/backend-policy input, not scenario
metadata. Issue #1354 owns the policy that decides which requests may use each
backend. Once a request has been admitted to the GCP VM range-cell contract, the
provisioner refuses to route it to GDC, GKE, or the legacy Terraform path; an
operator must not treat `gdc` as a per-request fallback for a contract-tagged
live-fire user range.

## Scenario-to-cell contract

The boundary is the closed, versioned `shifter.gcp-vm-range-cell` contract in
`shifter/shifter_platform/shared/range_cells.py`. Its responsibilities are:

- The scenario producer owns VM count and roles, containers or nested
  Kubernetes, topology and connectivity, ports and DNS, fixed addresses,
  images, startup/bootstrap behavior, services, and validation. The existing
  wrapped `RangeSpec` is validated by its canonical Pydantic contract before the
  Engine persists it as an immutable SHA-256-bound artifact. The standalone
  provisioner verifies that producer-minted digest without loading the scenario
  schema graph; the platform does not copy scenario fields into a universal
  placement model.
- The platform owns admission to the approved GCP/GCE live-fire capability,
  operation and cell identity, allocated network bindings, isolation, resource
  membership and ownership, lifecycle/recovery state, logical access, and
  cleanup. Allocated CIDRs are bindings and are not written back into the
  scenario artifact. A later destroy rehydrates those bindings from the
  platform allocation table when available and otherwise uses the validated
  authored membership and deterministic resource identity; it never requires a
  blank CIDR to pass request validation.
- The outer request and result reject unknown fields and versions. A digest or
  backend mismatch, malformed/duplicate membership, or missing/foreign network
  binding fails before any Compute Engine or Secret Manager mutation. Results
  reject dangling access targets and inline credentials, trigger cell cleanup
  if output validation fails, and expose credential references rather than
  credential values. Participant access is a closed scenario declaration keyed
  by authored member plus `ssh` or `rdp` channel. The result must match that
  declaration exactly. Participant SSH keys are distinct from host-management
  setup keys, and host/bootstrap credential references never enter the closed
  access result.

`gcp_range_cell_scenario.py` is the compatibility adapter for the current
legacy `RangeSpec`; it owns role/image/host-access interpretation. Polaris is
one composition supported by that adapter, not a platform range class. A future
scenario artifact can use a new discriminator/version adapter while retaining
the same cell lifecycle contract. See
`docs/architecture/scenario-gcp-range-cell-contract-preflight-1344.md` for the
full boundary analysis.

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

## Legacy RangeSpec image mapping

The scenario-owned legacy `RangeSpec` adapter resolves current instances to one
of four approved image profiles by role and OS (`GCERangeCellConfig.get_profile`):

| Instance | Profile | Variable |
|---|---|---|
| Domain controller (`role=dc`) | dc | `GCP_RANGE_DC_IMAGE` |
| Kali / attacker | kali | `GCP_RANGE_KALI_IMAGE` |
| Windows guest | windows | `GCP_RANGE_WINDOWS_IMAGE` |
| Everything else (Linux host) | linux | `GCP_RANGE_LINUX_IMAGE` |

Instances without an `ami_key` continue to use those four defaults. An instance
with an `ami_key` requires an exact entry in
`GCP_RANGE_IMAGE_KEY_PROFILES_JSON` under its derived profile class. Each entry
is complete: image, machine type, disk size, and disk type. Unknown keys and
keys placed under the wrong class fail before any Compute or secret client is
created; they never fall back to the default role image.

The value is a non-secret JSON object, limited to 32,768 bytes and 64 total
entries. Profile classes and fields are closed. Logical keys must be lowercase
letters, digits, and hyphens. For example:

```json
{
  "kali": {
    "polaris-vm": {
      "source_image": "projects/PROJECT/global/images/family/shifter-polaris-vm",
      "machine_type": "e2-standard-8",
      "disk_size_gb": 210,
      "disk_type": "pd-balanced"
    },
    "techvault": {
      "source_image": "projects/PROJECT/global/images/family/shifter-techvault",
      "machine_type": "n2-standard-8",
      "disk_size_gb": 150,
      "disk_type": "pd-balanced"
    }
  },
  "dc": {
    "polaris-dc": {
      "source_image": "projects/PROJECT/global/images/family/shifter-polaris-dc",
      "machine_type": "e2-standard-4",
      "disk_size_gb": 100,
      "disk_type": "pd-balanced"
    }
  }
}
```

The provisioner records a bounded key/profile fingerprint on each new VM and
in existing provider metadata. Reconciliation rejects a keyed same-name VM if
that binding differs from the current plan. Destroy remains independent of the
mapping. Configure the keyed map and validate both keyed and unkeyed launches
before returning the default Kali/DC variables from a temporary single-scenario
workaround to their generic families. Cross-project image families require the
narrow image-project grant for the provisioner GSA; do not broaden portal or
launcher identities.

The Polaris host's `polaris_range_bootstrap` step fetches a smoketests tarball
from `gs://$POLARIS_TESTS_BUCKET/$POLARIS_TESTS_KEY` (default
`polaris/tests/polaris-tests.tar.gz`). Build it from the in-repo tests tree and
upload it before launching a range:
`tar czf polaris-tests.tar.gz -C scenario-dev/polaris tests` then
`gcloud storage cp polaris-tests.tar.gz gs://<assets-bucket>/polaris/tests/polaris-tests.tar.gz`.

Images are native GCE images referenced by family:
`projects/<project>/global/images/family/shifter-<type>`. Unlike the GDC path
there is no qcow2 export or CDI import.

## Service accounts

For the default same-project range cell, Terraform (`modules/portal/iam`)
creates both range service accounts, grants their roles, and grants the
provisioner workload SA the access it needs to drive them: `roles/compute.admin`
on the range-cell project (create the range VPC, subnets, firewall, Cloud NAT,
and instances), `roles/iam.serviceAccountUser` on the host SA (attach it to
guests) and the Vertex SA, and `roles/iam.serviceAccountKeyAdmin` on the Vertex
SA (mint per-range keys). The two emails are exposed as the
`range_host_service_account_email` / `range_vertex_service_account_email`
Terraform outputs; set `GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL` /
`GCP_RANGE_VERTEX_SERVICE_ACCOUNT_EMAIL` to those values (a cross-project range
cell, `GCP_RANGE_CELL_PROJECT_ID`, provisions its own SAs in that project and
grants the provisioner the equivalent roles there; follow-up tracked in #1509).

The two service accounts:

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
   publishes image family `shifter-polaris-vm`, which `GCP_RANGE_KALI_IMAGE`
   points at (the Polaris host uses the kali/attacker profile).

`DC_DOMAIN_PASSWORD` is provisioned automatically: Terraform seeds a
`dc-domain-password` Secret Manager secret and `render_runtime_env` emits
`DC_DOMAIN_PASSWORD_SECRET_ID`, which the entrypoint resolves and `ecs.py`
passes into the provisioner Job. The provisioner authenticates to the prebaked
DC over SSH (injected key, not a password) and its `set_admin_password` step
resets the domain Administrator password to `DC_DOMAIN_PASSWORD` per range, so
the value baked by `a2_setup.ps1` does not need to match.

## NGFW

There is no GCE-native NGFW (Palo Alto VM-Series) path; that path exists only
under the GDC backend. A GCP range that requests an NGFW is not supported while
the backend is `gce`.
