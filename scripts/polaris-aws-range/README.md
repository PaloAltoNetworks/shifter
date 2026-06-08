# Polaris AWS Standalone Range

This directory provisions a standalone Polaris/NORTHSTORM range: one Ubuntu
Docker host plus one Windows Server 2022 A2 domain controller per range index.

## aws-dev default VPC bring-up

Use this path for the no-SSO `aws-dev` account in `us-east-2` when the range
must live in the account default VPC, not the Shifter range VPC or portal VPC.

1. Confirm the target account and default VPC:

   ```bash
   AWS_PROFILE=aws-dev AWS_REGION=us-east-2 aws sts get-caller-identity
   AWS_PROFILE=aws-dev AWS_REGION=us-east-2 aws ec2 describe-vpcs \
     --filters Name=is-default,Values=true
   ```

2. Build a tarball that includes both runtime content and tests. The build
   directory is enough for `user_data`, but `tests/` must be present on the EC2
   host if you want to run the smoke/capture checks via SSM.

   ```bash
   python -m pip install --quiet reportlab
   out="$(mktemp -d)"
   python scenario-dev/polaris/build/A0-boreas-website/build_pdfs.py "$out"
   python scenario-dev/polaris/build/verify_flags_baked.py \
     scenario-dev/polaris/build/ctfd-challenges.json "$out"
   tar czf /tmp/polaris-build.tar.gz \
     scenario-dev/polaris/build \
     scenario-dev/polaris/tests
   ```

3. Create or reuse a private S3 bucket in aws-dev and upload the tarball:

   ```bash
   bucket=shifter-polaris-bake-dev-741140496509
   AWS_PROFILE=aws-dev AWS_REGION=us-east-2 aws s3api create-bucket \
     --bucket "$bucket" \
     --create-bucket-configuration LocationConstraint=us-east-2
   AWS_PROFILE=aws-dev AWS_REGION=us-east-2 aws s3api put-public-access-block \
     --bucket "$bucket" \
     --public-access-block-configuration \
       BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
   AWS_PROFILE=aws-dev AWS_REGION=us-east-2 aws s3 cp \
     /tmp/polaris-build.tar.gz \
     "s3://${bucket}/polaris/build-aws-dev-default-vpc.tar.gz"
   ```

4. Apply Terraform from this directory. For the current aws-dev default VPC the
   local values are:

   ```hcl
   aws_profile        = "aws-dev"
   aws_region         = "us-east-2"
   name_prefix        = "polaris-dev-default"
   deployment_purpose = "default-vpc-standalone"

   range_vpc_id           = "vpc-02c81b9b197f058b1"
   polaris_cidr_block     = "172.31.240.0/24"
   availability_zone      = "us-east-2a"
   egress_route_target    = "igw"
   internet_gateway_id    = "igw-0a4c93d3a0ac0463e"
   portal_vpc_cidr        = ""
   portal_peering_id      = ""
   management_ingress_cidrs = []
   publish_kali_host_ports  = false

   build_tarball_bucket = "shifter-polaris-bake-dev-741140496509"
   build_tarball_s3_uri = "s3://shifter-polaris-bake-dev-741140496509/polaris/build-aws-dev-default-vpc.tar.gz"
   ```

   Keep the values in `local.auto.tfvars` or another ignored tfvars file, then:

   ```bash
   terraform init
   terraform apply
   terraform output -json
   ```

5. Wait for the Ubuntu host bootstrap marker over SSM. Poll for the marker
   instead of sleeping for a fixed duration:

   ```bash
   polaris_id="$(terraform output -json range_polaris_instance_ids | jq -r '."0"')"
   AWS_PROFILE=aws-dev AWS_REGION=us-east-2 aws ec2 wait instance-status-ok \
     --instance-ids "$polaris_id"
   AWS_PROFILE=aws-dev AWS_REGION=us-east-2 aws ssm send-command \
     --instance-ids "$polaris_id" \
     --document-name AWS-RunShellScript \
     --parameters 'commands=["grep -c \"polaris bootstrap complete\" /var/log/polaris-bootstrap.log || true"]'
   ```

6. Promote and populate the A2 DC after Terraform creates the Windows instance:

   ```bash
   a2_id="$(terraform output -json range_a2_instance_ids | jq -r '."0"')"
   AWS_PROFILE=aws-dev AWS_REGION=us-east-2 ./a2_cold_bootstrap_parallel.sh "$a2_id"
   ```

7. Validate from the Polaris host via SSM:

   ```bash
   cd /opt/polaris/scenario-dev/polaris/tests
   bash run-all-smoketests.sh
   python3 -m scenario_smoketest --only 1,2,3,4,5,6,31 \
     --json-report /tmp/polaris-scenario-smoketest.json
   ```

   `run-all-smoketests.sh` is the full infrastructure and capture sweep. The
   full `scenario_smoketest` command intentionally fails today because only the
   registered adapters are executable; use `--only` for the covered challenge
   ids until adapter coverage is complete.

8. After validation passes, publish both standalone instances as the golden
   Polaris AMIs that the normal Shifter range provisioner consumes. The range
   provisioner resolves `/shifter/ami/polaris-vm` and
   `/shifter/ami/polaris-dc` at deploy time, so do not update either SSM
   parameter until the corresponding AMI is available and smoke-tested. The DC
   AMI is expected to be a prebaked BOREAS.LOCAL domain controller; the AWS
   provisioner verifies and applies runtime credentials, but does not promote a
   base Windows image for Polaris.

   ```bash
   image_name="shifter-polaris-vm-$(date -u +%Y%m%d%H%M%S)"
   image_id="$(AWS_PROFILE=aws-dev AWS_REGION=us-east-2 aws ec2 create-image \
     --instance-id "$polaris_id" \
     --name "$image_name" \
     --description "Validated Polaris golden range host" \
     --tag-specifications "ResourceType=image,Tags=[{Key=Name,Value=$image_name},{Key=Project,Value=polaris},{Key=Purpose,Value=golden-ami}]" \
     --query ImageId \
     --output text)"

   AWS_PROFILE=aws-dev AWS_REGION=us-east-2 aws ec2 wait image-available \
     --image-ids "$image_id"

   AWS_PROFILE=aws-dev AWS_REGION=us-east-2 aws ssm put-parameter \
     --name /shifter/ami/polaris-vm \
     --type String \
     --value "$image_id" \
     --overwrite

   AWS_PROFILE=aws-dev AWS_REGION=us-east-2 aws ssm get-parameter \
     --name /shifter/ami/polaris-vm \
     --query Parameter.Value \
     --output text
   ```

   Then publish the A2/DC image:

   ```bash
   dc_image_name="shifter-polaris-dc-$(date -u +%Y%m%d%H%M%S)"
   dc_image_id="$(AWS_PROFILE=aws-dev AWS_REGION=us-east-2 aws ec2 create-image \
     --instance-id "$a2_id" \
     --name "$dc_image_name" \
     --description "Validated Polaris BOREAS.LOCAL A2 domain controller" \
     --tag-specifications "ResourceType=image,Tags=[{Key=Name,Value=$dc_image_name},{Key=Project,Value=polaris},{Key=Purpose,Value=golden-ami}]" \
     --query ImageId \
     --output text)"

   AWS_PROFILE=aws-dev AWS_REGION=us-east-2 aws ec2 wait image-available \
     --image-ids "$dc_image_id"

   AWS_PROFILE=aws-dev AWS_REGION=us-east-2 aws ssm put-parameter \
     --name /shifter/ami/polaris-dc \
     --type String \
     --value "$dc_image_id" \
     --overwrite

   AWS_PROFILE=aws-dev AWS_REGION=us-east-2 aws ssm get-parameter \
     --name /shifter/ami/polaris-dc \
     --query Parameter.Value \
     --output text
   ```

   Keep the Terraform-created validation range until a fresh portal/engine
   range launched from the new AMI has passed smoke tests. Then destroy the
   temporary standalone range with `terraform destroy`.

## Portal/engine validation path

After the golden AMIs are published, validate Polaris through the normal
Shifter provisioner path before treating the AMIs as release candidates.

1. Confirm these SSM parameters resolve in the target account:

   ```bash
   AWS_PROFILE=aws-dev AWS_REGION=us-east-2 aws ssm get-parameter \
     --name /shifter/ami/polaris-vm \
     --query Parameter.Value \
     --output text
   AWS_PROFILE=aws-dev AWS_REGION=us-east-2 aws ssm get-parameter \
     --name /shifter/ami/polaris-dc \
     --query Parameter.Value \
     --output text
   ```

2. Upload the smoke-test bundle to the portal user-storage bucket. The
   provisioner defaults to `POLARIS_TESTS_KEY=polaris/tests/polaris-tests.tar.gz`
   and resolves the bucket from `POLARIS_TESTS_BUCKET`, `AGENT_STORAGE_BUCKET`,
   or `AGENT_S3_BUCKET`.

3. Launch a `polaris` range through the portal/engine provisioning path and
   wait for the provisioner task to exit 0. The provisioner should publish a
   `range.status.updated` event with `new_status=ready`, and the CMS
   `RangeInstance` row should become `ready`.

4. Health-check the Kali host or hosts:

   ```bash
   python3 scripts/polaris-aws-range/check_range_health.py \
     --profile aws-dev \
     --region us-east-2 \
     --instance-ids <kali-instance-id>[,<kali-instance-id>...] \
     --output /tmp/polaris-range-health.md \
     --verbose
   ```

   A pristine Polaris range has 17 Docker Compose services. The splice watcher
   should be active, and the splice link should remain gated until the scenario
   opens it.

5. Run the participant smoke tests from the Kali host via SSM:

   ```bash
   cd /opt/polaris/scenario-dev/polaris
   sudo bash tests/run-all-smoketests.sh
   python3 -m scenario_smoketest --only 1,2,3,4,5,6,31 \
     --json-report /tmp/polaris-scenario-smoketest.json
   ```

   The full smoke script should pass before imaging or load-testing. The
   scenario adapter subset proves the documented early path plus the
   splice/bunker bridge behavior. Do not require bunker reachability on a
   pristine participant range before the splice gate opens.

## Native CTF API validation

Use this path to validate that CTF bulk provisioning works without logging in
through the public web UI.

1. Run Django code inside the portal EC2/container, usually through SSM:

   ```bash
   AWS_PROFILE=aws-dev AWS_REGION=us-east-2 aws ssm start-session \
     --target <portal-ec2-instance-id>
   ```

   Direct `manage.py shell` may miss runtime secrets. For one-off scripts, use
   the same Secrets Manager bootstrap pattern as `polaris_ctf_setup.py`, then
   call `django.setup()`.

2. Create an active `CTFEvent` with `scenario_id="polaris"` and an organizer
   owner. Add fake participants with `ctf.services.participant.invite_participant`;
   this creates the participant Django users. If you are not testing email or
   magic-link delivery, do not call `resend_invite`, and do not print or store
   invite tokens in evidence.

3. Trigger deployment through the same view the organizer UI calls:
   `ctf.views.api_provision_ranges`. A `RequestFactory` POST with the event
   owner as `request.user` should return a JSON payload where `successful`
   equals `total`.

4. Verify each participant through both data paths:

   - `cms.models.RangeInstance` should be `ready` and have the provisioned
     engine `range_id`.
   - `ctf.services.range.get_range_status(participant_id)` should refresh the
     cached participant status to `ready`.
   - `ctf.views.api_range_status` should return HTTP 200 with `status=ready`
     when invoked as each participant user.

5. If the provisioner tasks exit 0 but CMS/CTF status remains `pending`, check
   `docker logs worker-cms` on the portal EC2. `KMS.AccessDeniedException` on
   the portal messaging CMK means the portal EC2 role cannot decrypt encrypted
   SQS messages; the Terraform `portal/ec2` module must pass
   `module.messaging.kms_key_arn` and attach the `sqs-kms-access` policy.

## Networking notes

Default-VPC mode creates Polaris-owned /28 subnets inside the default VPC. The
instances receive public IPs for outbound SSM and package/build traffic, but
the security group has no public inbound management ingress by default. Use SSM
for operator access. Only set `management_ingress_cidrs` when SSH/RDP from a
known operator CIDR is required. Keep `publish_kali_host_ports = false` unless
portal/Guacamole needs the host-level A14 SSH/RDP mappings and the security
group has matching restricted ingress.

The older private range-VPC path is still available by setting
`egress_route_target = "nat"`, `nat_gateway_id`, `range_vpc_id`,
`polaris_cidr_block`, and optional portal peering variables explicitly.
