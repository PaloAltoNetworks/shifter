# Running Polaris on the GCP range-cell backend

Part of the Shifter deploy and operations docs; start at the [documentation home](../index.md).

This runbook covers deploying the Polaris CTF scenario on the GCP Compute
Engine range-cell backend (issue #1342). It complements the architecture
guardrails in
[polaris-gcp-range-cell-preflight-1342.md](../architecture/polaris-gcp-range-cell-preflight-1342.md).

## Shape

Each participant gets one isolated range cell:

- One Linux range-host VM (`polaris-vm` image) runs the Polaris
  docker-compose stack, including the `a14-kali` participant container.
- One Windows Server domain-controller VM (`dc` image) hosts `BOREAS.LOCAL`.
- The CTF participant flow provisions the range through the normal
  CMS to engine to provisioner path with `GCP_RANGE_BACKEND=gce`.

## Images

Build the images with the GCP Packer workflow
(`.github/workflows/packer-gcp.yml`):

- `polaris-vm`: the Debian Docker host that runs the compose stack. The full
  compose stack source (a `docker-compose.yml` plus its build context under
  `scenario-dev/polaris/build`) must be present at bake time, the same way the
  AWS `polaris-vm` AMI is baked. The host bake installs Docker, the Google
  Cloud SDK, and moves the host sshd to the management port so the Kali
  container can publish host port 22 and port 3389 for participants.
- `polaris-dc`: use the pre-promoted Polaris DC image family. It ships Windows
  Server 2022 with the `boreas.local` / `BOREAS` domain and scenario AD content
  baked in; runtime setup verifies that identity and does not promote or rename
  the DC.

Keep the generic `GCP_RANGE_KALI_*` and `GCP_RANGE_DC_*` defaults available for
unkeyed scenarios. In `GCP_RANGE_IMAGE_KEY_PROFILES_JSON`, configure a complete
`kali.polaris-vm` profile pointing at the promoted `shifter-polaris-vm` family
and a complete `dc.polaris-dc` profile pointing at the promoted Polaris DC
family. Declare `bootstrap_capability=polaris-docker-host` for the host and
`bootstrap_capability=prepromoted-domain-controller`,
`domain_dns_name=boreas.local`, and `domain_netbios_name=BOREAS` for the DC.
Include the GCE machine type, disk size, and disk type in each entry; the
Polaris host disk must be at least 210 GB.

The scenario keeps its logical `ami_key: polaris-vm` and
`ami_key: polaris-dc` values. The GCE plan performs an exact class/key lookup and
ignores the AWS `instance_type`. A missing or misspelled entry fails before
cloud mutation instead of booting the generic Kali or DC image. See
[GCP range-cell deploy](gcp-range-cell-deploy.md#legacy-rangespec-image-mapping)
for the closed JSON shape and rollout sequence.

## Kali agent credentials (Vertex AI)

The `a14-kali` agent runs Claude Code against Vertex AI on GCP, which replaces
the AWS Bedrock path.

The `a14-kali` container is participant-facing: a CTF participant has shell in
it. It must never reach the range-host service account, or a participant could
mint that token and use it off-box. So the credential model is per-range and
Vertex-only:

- Pre-provision a dedicated, Vertex-only service account (for example
  `range-vertex@<project>.iam.gserviceaccount.com`) with only
  `roles/aiplatform.user`, and set `GCP_RANGE_VERTEX_SERVICE_ACCOUNT_EMAIL` to
  it. This is provisioned once out-of-band (Terraform), not per range.
- Grant the range provisioner service account permission to mint and delete
  keys on that Vertex-only SA (`iam.serviceAccountKeys.create` and
  `iam.serviceAccountKeys.delete`).
- The range-cell backend mints a per-range key on that SA at provision, stores
  it in Secret Manager, and destroys it at teardown. The range bootstrap
  fetches the key host-side and injects it into the `a14-kali` container as a
  key file, then blocks every container from the metadata server. A leaked key
  is Vertex-scoped and revoked when the range is destroyed.

Also set:

- `GCP_RANGE_VERTEX_PROJECT_ID` (defaults to `GCP_PROJECT_ID`).
- `GCP_RANGE_VERTEX_REGION` (defaults to `global`, required by the default Claude Sonnet 4.6 model).
- `GCP_RANGE_KALI_ANTHROPIC_MODEL` and
  `GCP_RANGE_KALI_ANTHROPIC_SMALL_FAST_MODEL` for the Vertex model ids.

If the deploy organization blocks service-account key creation
(`iam.disableServiceAccountKeyCreation`) or is tight on the per-project
service-account quota, fall back to a single Vertex-only SA that mints
per-range short-lived downscoped tokens with a host-side refresh helper.

## Network access for Google APIs

The range VMs have no external IP. The range host reaches Vertex AI and Cloud
Storage over Private Google Access; the participant containers are blocked from
the metadata server. Enable Private Google Access and allow egress to the
Google API virtual IP:

- `GCP_RANGE_PRIVATE_GOOGLE_ACCESS=true`.
- Add the Google API restricted VIP range to `GCP_RANGE_EGRESS_ALLOW_CIDRS`.

## Smoketest tarball

Set `POLARIS_TESTS_BUCKET` to the Cloud Storage bucket holding the tests
archive and `POLARIS_TESTS_KEY` to its object path. The range host fetches it
with `gcloud storage` during bootstrap.

## Management access

The provisioner drives host guest setup over SSH on the management port
(`GCP_RANGE_HOST_MGMT_SSH_PORT`, default 2222), because the Kali container
binds host port 22. The range firewall opens ports 22, 3389, and the
management port only from the portal or management CIDRs
(`PORTAL_NETWORK_CIDRS`). Participants reach the Kali container on port 22 and
port 3389 through the approved management path.

## Post-merge validation checklist

The code change cannot verify these live outcomes, so run them after the
images are built and the environment is configured:

1. Launch a Polaris range through the CTF participant flow.
2. Confirm the participant Kali, RDP, and SSH path works through the approved
   management path.
3. Run the Polaris smoke tests from inside the range cell.
4. Destroy the range through the CMS or CTF lifecycle and confirm clean
   teardown.
5. Run the cross-range and platform-escape tests from the validation suite
   before treating the backend as event ready.
