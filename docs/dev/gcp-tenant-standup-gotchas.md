# GCP tenant standup gotchas

Part of the Shifter deploy and operations docs; start at the [documentation home](../index.md).

A running log of operator gotchas hit while standing up or re-pointing a GCP
Shifter tenant that are **not** fixed in code, only in operator procedure. Fixes
that belong in the scripts, workflows, or Terraform go into the code, not here.
Use this alongside the authoritative runbooks:
[`deploy-secrets.md`](deploy-secrets.md),
[`gcp-range-cell-deploy.md`](gcp-range-cell-deploy.md),
[`setup.md`](../technical/dev/setup.md),
[`gcp-guest-images.md`](../architecture/gcp-guest-images.md), and
[`scripts/bootstrap/README.md`](https://github.com/Brad-Edwards/shifter/blob/dev/scripts/bootstrap/README.md).

The local `gdc-bootstrap` path (`--environment <tenant>`) is the fresh-tenant
bring-up. It runs Terraform under operator Application Default Credentials, so a
new tenant needs the local ADC quota project set: export
`USER_PROJECT_OVERRIDE=true` and `GOOGLE_BILLING_PROJECT=<project>` (see the ADC
quota-project note in `scripts/bootstrap/README.md`).

## Local tooling `gdc-bootstrap` needs beyond the setup.md list

`setup.md` lists Docker, `gcloud`, Terraform, `gh`, `uv`, and Python, but the GCP
control-plane bootstrap also requires `kubectl`, `helm`, `oras`, and
`gke-gcloud-auth-plugin` on `PATH`, plus a usable Docker daemon (it builds and
pushes the portal, provisioner, guacd, and guacamole-client images). Pin `helm`
to the version CI uses (`v3.15.4` in `_gcp-dev.yml`); Helm 4 is a separate major
release and is not what the chart is exercised against. `kubectl`, `helm`, and
`oras` install as static binaries into a `PATH` directory without root.

## Installing `gke-gcloud-auth-plugin` without root

`gdc-bootstrap` installs `gke-gcloud-auth-plugin` if it is missing, but on a
Debian/apt `gcloud` the component manager is disabled, so `gcloud components
install` fails, and the fallback runs `sudo apt-get`, which fails on a non-TTY or
non-passwordless-sudo host. Install it without root by extracting the apt
package:

```bash
cd "$(mktemp -d)"
apt-get download google-cloud-cli-gke-gcloud-auth-plugin
dpkg-deb -x google-cloud-cli-gke-gcloud-auth-plugin_*.deb ./x
cp ./x/usr/lib/google-cloud-sdk/bin/gke-gcloud-auth-plugin ~/.local/bin/
```

`gdc-bootstrap` then finds it on `PATH` and skips its own install. Real fix: have
the bootstrap prefer its `install_gke_gcloud_auth_plugin_user_space` path
(which does exactly this extraction) whenever `sudo apt-get` is not viable, not
only when `sudo` is absent.

## Export the range-plane variables before `gdc-bootstrap`

The GCE range precondition gate fails closed unless `RANGE_NETWORK_ZONE` and
`GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL` are set in the bootstrap process
environment (`setup.md` step 4 documents this; the `README.md` `gdc-bootstrap`
example does not show them inline, so it is easy to miss). The range-host SA
follows the Terraform naming contract, the `shifter-<environment>` account-id
prefix with hyphens removed plus `-range-host`, for example
`shifternazgul-range-host@<project>.iam.gserviceaccount.com`. Terraform creates
that SA during the same apply, so supply the derived value for the first run;
after the first apply, read the authoritative value from the environment root
`range_host_service_account_email` output and reuse it for retries and the CI
Environment.

## GCE stockout on the provisioner node pool

The regional cluster places one provisioner node per zone. A zone can return
`GCE_STOCKOUT` for the configured `provisioner_machine_type` and leave the node
pool in `RUNNING_WITH_ERROR`, failing the apply after the roughly 35-minute
node-pool timeout, while every other pool comes up. The stockout is
machine-type and zone specific. Confirm an alternative type has capacity in all
of the cluster's zones (the `access` pool already proves `e2-standard-8`
availability), then override `provisioner_machine_type` in the gitignored
`local.auto.tfvars` to that type of the same size class (`e2-standard-8` is the
same 8 vCPU / 32 GB shape as `n2-standard-8`). Do not try to pin the GKE node
zones: there is no tfvar for it, so that would be a module change, not an
operator override.

## Never run get-credentials against the default kubeconfig during bootstrap

`gdc-bootstrap` pins the tenant Connect Gateway context on the default kubeconfig
and polls the managed certificate through it. Running `gcloud container clusters
get-credentials` against the default kubeconfig for a progress check overwrites
that context with the private control-plane endpoint, which the workstation
cannot reach when `gke_master_authorized_cidrs = []`, and the bootstrap then
crashes with an i/o timeout to the private endpoint. For any parallel checks,
isolate them with a separate `KUBECONFIG` and Connect Gateway credentials:

```bash
KUBECONFIG=/tmp/tenant-check gcloud container fleet memberships get-credentials \
  <cluster> --project <project>
KUBECONFIG=/tmp/tenant-check kubectl -n shifter-platform get pods
```

## DNS record and the Google-managed certificate

The public hostname needs a DNS-only (unproxied) A record at the ingress IP
before the Google-managed certificate leaves `Provisioning`. The ingress IP is
the `shifter-<environment>-platform-ip` global address (the bootstrap also prints
it in its DNS instructions). On a Cloudflare-managed zone, watch for a stale
record left by a prior tenant: a hostname reused from a torn-down environment can
still hold a CNAME to a dead load balancer, which blocks creating the A record
until you convert it. Keep the record unproxied so the load balancer can serve
the certificate challenge. First issuance can exceed the bootstrap's 30-minute
certificate wait, so the certificate may reach `ACTIVE` out of band; once it is
active, a final `gdc-bootstrap` re-run fast-forwards (cached images, no-op
Terraform) and completes green after the portal HTTPS check.

## The k8s overlay ships a placeholder project: never hand-edit it

The committed tenant overlay ships a `shifter-<environment>` placeholder project
in `platform/k8s/gcp/overlays/<environment>/kustomization.yaml` (the image
`newName`s) and `patch-serviceaccounts.patch` (the Workload Identity
annotations). **Do not replace the placeholder with the real project and do not
commit a real project id or service-account email into the overlay.** The real
deploy identity is reconnaissance-sensitive and tenant-specific; it must never
land in the repo (ADR-004-R14, ADR-011) and is enforced by the
`no-live-gcp-deploy-identity` adr-guard check.

The CI deploy renders the real identity into the overlay at deploy time from the
Terraform outputs: `scripts/gcp/render_overlay_identity.py` rewrites the image
`newName`s from `artifact_registry_image_roots` and the GSA annotations from
`workload_service_accounts` (matched by localpart) in the ephemeral runner
checkout, before the digest-pin step. Nothing is written back to git. Only the
project changes at deploy time; the repository segment
(`shifter-<environment>-portal`) and the SA localparts
(`shifter<environment>-portal`) are already correct in the committed placeholder
and stay. The local `gdc-bootstrap` path uses the Helm chart, not this overlay,
and takes the project from `--project-id` / `local.auto.tfvars`, so the
placeholder never blocks the local standup either.
