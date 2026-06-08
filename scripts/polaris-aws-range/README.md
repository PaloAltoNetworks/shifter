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

8. After validation passes, publish the Ubuntu host as the golden Polaris AMI
   that the normal Shifter range provisioner consumes. The range provisioner
   resolves `/shifter/ami/polaris-vm` at deploy time, so do not update the SSM
   parameter until the AMI is available and smoke-tested:

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

   Keep the Terraform-created validation range until a fresh portal/engine
   range launched from the new AMI has passed smoke tests. Then destroy the
   temporary standalone range with `terraform destroy`.

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
