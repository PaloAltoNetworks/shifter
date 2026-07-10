# Running Polaris on the GCP range-cell backend

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
- `polaris-dc`: use the generic `dc` image family. It ships Windows Server
  2022 with the AD DS role and OpenSSH. The `boreas.local` domain is promoted
  per range by the provisioner, not baked into the image.

Point the range profiles at the built image families:

- `GCP_RANGE_KALI_IMAGE` at the `polaris-vm` family.
- `GCP_RANGE_DC_IMAGE` at the `dc` family.

The scenario keeps its `ami_key: polaris-vm` and `ami_key: polaris-dc` values.
The GCE plan translates those to the profiles above and ignores the AWS
`instance_type`; machine size comes from `GCP_RANGE_KALI_MACHINE_TYPE` and
`GCP_RANGE_DC_MACHINE_TYPE`.

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
- `GCP_RANGE_VERTEX_REGION` (defaults to `us-east5`).
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
