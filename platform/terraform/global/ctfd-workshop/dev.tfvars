# dev.tfvars — example values for OSS deployers.
# Copy this file to dev.tfvars (gitignored) and replace example.com placeholders
# with your real domains / email senders / alarm destinations before
# `terraform apply`. Secrets remain in AWS Secrets Manager / GCP Secret Manager,
# never in tfvars.

# REPLACE: the subnet id your CTFd workshop host will run in.
subnet_id = "subnet-REPLACE_WITH_SUBNET_ID"
# REPLACE: AMI id for the CTFd host (Ubuntu 22.04 LTS or equivalent).
ctfd_ami_id = "ami-REPLACE_WITH_AMI_ID"

domain                 = "ctf.shifter.example.com"
ctfd_git_ref           = "b5f0cf2b7f0e29f72c9227ea9bc08024230b4f06"
docker_buildx_version  = "v0.21.2"
docker_compose_version = "v5.1.0"
