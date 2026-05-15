# dev.tfvars — committed example.com baseline for OSS deployers.
# This file IS `dev.tfvars` (committed). Deployment-specific overrides go in
# a sibling `local.auto.tfvars` (gitignored) — Terraform auto-loads
# `*.auto.tfvars` and the local values win. CI deploys render the overrides
# from GitHub secrets/repository variables; see docs/dev/deploy-secrets.md.


# REPLACE: the subnet id your CTFd workshop host will run in.
subnet_id = "subnet-REPLACE_WITH_SUBNET_ID"
# REPLACE: AMI id for the CTFd host (Ubuntu 22.04 LTS or equivalent).
ctfd_ami_id = "ami-REPLACE_WITH_AMI_ID"

domain                 = "ctf.shifter.example.com"
ctfd_git_ref           = "b5f0cf2b7f0e29f72c9227ea9bc08024230b4f06"
docker_buildx_version  = "v0.21.2"
docker_compose_version = "v5.1.0"
