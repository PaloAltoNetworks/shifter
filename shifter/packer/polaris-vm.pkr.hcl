// polaris-vm: the POLARIS Linux scenario host AMI — one Ubuntu 24.04 VM running
// the 17-container polaris docker compose stack (a14-kali, dns, splice, etc.),
// baked from the operator-supplied private build tarball. This is the Packer
// twin of the retired .github/workflows/polaris-scenario-bake.yml, which stood
// up a Terraform bake range and imaged instance 0; Packer now owns
// launch/provision/image/teardown for the single VM being imaged. The Windows
// DC half of a polaris range is a separate Packer build (polaris-dc.pkr.hcl).
//
// The stack is baked RUNNING with the range-0 override values (a placeholder DC
// IP and a throwaway bake-time kali key). This exactly preserves the runtime
// contract: PolarisRangeBootstrapPlan force-recreates ONLY the dns + a14-kali
// containers at range launch with the real per-range DC IP and per-instance
// key, and relies on the other 15 containers already being up from the baked
// state. Baking build-only (stack down) would break range launch, and rewriting
// the range plan to recreate all containers is a stated non-goal (#1469
// preflight). See shifter/engine/provisioner/plans/polaris_range_bootstrap.py
// and docs/architecture/polaris-scenario-bake-preflight-618.md.
//
// The private scenario content (flags/solutions) is NOT in this public repo; it
// reaches the bake as the operator-supplied S3 tarball (polaris_tarball_s3_uri).
// No participant or per-range credential is baked.
//
// No-inbound bake over the AWS Session Manager SSH tunnel: no inbound SG rule is
// needed (the tunnel is agent-initiated egress); isolation is the no-inbound
// security group, and the builder keeps the bake subnet's default public IP for
// SSM egress. The operator supplies the isolated bake subnet, no-inbound
// security group, and an SSM-enabled instance profile with read access to the
// tarball bucket.
//
// The amazon required_plugins block is declared once for the whole directory in
// kali.pkr.hcl; Packer treats the directory as one config, so it is not repeated
// here.

source "amazon-ebs" "polaris-vm" {
  ami_name        = "${var.ami_prefix}-polaris-vm-{{timestamp}}"
  ami_description = "Polaris 17-container scenario host (baked running, range-0 override) — encrypted root"
  instance_type   = var.scenario_instance_type
  region          = var.aws_region

  shutdown_behavior = "terminate"

  source_ami_filter {
    filters = {
      name                = "ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
      architecture        = "x86_64"
    }
    most_recent = true
    owners      = ["099720109477"] // Canonical
  }

  ssh_username = "ubuntu"

  communicator            = "ssh"
  ssh_interface           = "session_manager"
  iam_instance_profile    = var.builder_instance_profile
  pause_before_connecting = "1m"
  ssh_timeout             = "10m"

  vpc_id             = var.vpc_id != "" ? var.vpc_id : null
  subnet_id          = var.subnet_id != "" ? var.subnet_id : null
  security_group_ids = var.security_group_id != "" ? [var.security_group_id] : null

  launch_block_device_mappings {
    device_name           = "/dev/sda1"
    volume_size           = var.root_volume_size
    volume_type           = "gp3"
    delete_on_termination = true
    encrypted             = true
    kms_key_id            = var.kms_key_id != "" ? var.kms_key_id : null
  }

  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }
  imds_support = "v2.0"

  // The baked AMI carries the full 17-container stack, so the post-create
  // snapshot can take well past Packer's default AMI-ready wait (which fails with
  // ResourceNotReady after a successful bake). Poll up to 60 min.
  aws_polling {
    delay_seconds = 30
    max_attempts  = 120
  }

  tags = {
    Name      = "${var.ami_prefix}-polaris-vm"
    Project   = "polaris-bake"
    Scenario  = "polaris"
    ManagedBy = "packer"
    BuildDate = "{{timestamp}}"
  }

  run_tags = {
    Name    = "packer-builder-polaris-vm"
    Project = "polaris-bake"
  }
}

build {
  sources = ["source.amazon-ebs.polaris-vm"]

  // Faithful port of the retired range's user_data.sh.tpl: install docker /
  // compose / awscli, pull the private build tarball, write the range-0
  // docker-compose.override.yml (placeholder DC IP + throwaway key + generated
  // splice keys), then `docker compose build && up -d` so the AMI bakes with
  // the stack running. Left running (no cleanup) to preserve range-launch
  // auto-start.
  provisioner "shell" {
    scripts          = ["scripts/polaris/bootstrap.sh"]
    environment_vars = ["POLARIS_TARBALL_S3_URI=${var.polaris_tarball_s3_uri}"]
    execute_command  = "sudo -S bash -c '{{ .Vars }} {{ .Path }}'"
  }

  post-processor "manifest" {
    output     = "polaris-vm-manifest.json"
    strip_path = true
  }
}
