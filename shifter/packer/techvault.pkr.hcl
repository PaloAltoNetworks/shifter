// techvault: the TechVault golden AMI — one Ubuntu 24.04 host running the APTL
// `techvault-operational` docker compose stack (~30 long-running containers)
// plus the VS Code + Claude Code seat, baked so a range launch is a boot plus
// the containers' own `restart:` auto-start (no `aptl lab start` at range
// launch). This is the Packer twin of the retired
// .github/workflows/techvault-scenario-bake.yml SSM shell driver; the bake
// steps are the same, Packer now owns launch/provision/image/teardown.
//
// The stack is baked RUNNING on purpose: Packer stops the builder to snapshot
// (like `create-image` without --no-reboot), and docker restarts the
// unless-stopped/always containers on first boot. Do NOT add a stack-stopping
// cleanup step here — range launch relies on the baked stack auto-starting.
// See docs/ops/techvault-bake-runbook.md and
// docs/architecture/techvault-encrypted-ami-preflight-1455.md.
//
// No-inbound bake: the builder is driven over the AWS Session Manager SSH
// tunnel (ssh_interface = "session_manager"), so it needs no inbound
// security-group rule. Isolation is enforced by the operator-supplied no-inbound
// security group; the builder still gets the bake subnet's default public IP so
// its SSM agent can reach the Session Manager endpoints over the subnet's IGW
// egress (the documented bake subnet is public, no NAT / VPC endpoints). The
// operator supplies the isolated bake subnet, no-inbound security group, and an
// SSM-enabled instance profile.
//
// The amazon required_plugins block is declared once for the whole directory in
// kali.pkr.hcl; Packer treats the directory as one config, so it is not repeated
// here.

source "amazon-ebs" "techvault" {
  ami_name        = "${var.ami_prefix}-techvault-{{timestamp}}"
  ami_description = "TechVault techvault-operational stack + VS Code seat, aptl-labs ${var.aptl_version} (baked running) — encrypted root"
  instance_type   = var.scenario_instance_type
  region          = var.aws_region

  // Ensure the builder is terminated (not just stopped) if Packer exits
  // ungracefully, per the builder-termination guardrail (issue #342).
  shutdown_behavior = "terminate"

  // Canonical Ubuntu 24.04 (Noble), matching scripts/polaris-aws-range/main.tf.
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

  // No-inbound bake over AWS Session Manager. No inbound SG rule is needed (the
  // SSM tunnel is agent-initiated egress); isolation is the no-inbound security
  // group. associate_public_ip_address is intentionally left to the subnet
  // default (matches the retired run-instances bake) so a public bake subnet
  // gives the SSM agent egress without a NAT.
  communicator            = "ssh"
  ssh_interface           = "session_manager"
  iam_instance_profile    = var.builder_instance_profile
  pause_before_connecting = "1m" // let the SSM agent register before the tunnel
  ssh_timeout             = "10m"

  vpc_id             = var.vpc_id != "" ? var.vpc_id : null
  subnet_id          = var.subnet_id != "" ? var.subnet_id : null
  security_group_ids = var.security_group_id != "" ? [var.security_group_id] : null

  // Encrypted root volume (fail-closed publish gate, issue #1455). An encrypted
  // launch volume yields an encrypted AMI snapshot without a re-encrypt copy;
  // the workflow re-verifies every EBS mapping is encrypted before SSM publish.
  launch_block_device_mappings {
    device_name           = "/dev/sda1"
    volume_size           = var.root_volume_size
    volume_type           = "gp3"
    delete_on_termination = true
    encrypted             = true
    kms_key_id            = var.kms_key_id != "" ? var.kms_key_id : null
  }

  // Require IMDSv2 on the builder and stamp the resulting AMI as IMDSv2-only.
  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }
  imds_support = "v2.0"

  // The techvault AMI is large (100 GiB root + the full baked stack), so the
  // post-create snapshot routinely takes 30-60 min - well past Packer's default
  // AMI-ready wait, which fails with ResourceNotReady after a successful bake.
  // Poll up to 60 min (mirrors the retired workflow's create-image wait loop).
  aws_polling {
    delay_seconds = 30
    max_attempts  = 120
  }

  tags = {
    Name         = "${var.ami_prefix}-techvault"
    Project      = "techvault-bake"
    Scenario     = "techvault"
    aptl_version = var.aptl_version
    ManagedBy    = "packer"
    BuildDate    = "{{timestamp}}"
  }

  run_tags = {
    Name    = "packer-builder-techvault"
    Project = "techvault-bake"
  }
}

build {
  sources = ["source.amazon-ebs.techvault"]

  // Faithful port of the retired workflow's SSM bake phases (see the runbook):
  //   1. toolchain — docker, node, claude-code, pipx (root)
  //   2. stack     — aptl lab as the ubuntu user (uid 1000), all container groups
  //   3. seat      — XFCE + xrdp + VS Code (root)
  // The stack is left RUNNING; no cleanup step (parity with the current bake).
  provisioner "shell" {
    scripts = [
      "scripts/techvault/toolchain.sh",
      "scripts/techvault/stack.sh",
      "scripts/techvault/seat.sh",
      "scripts/techvault/wait-stack.sh",
    ]
    environment_vars = ["APTL_VERSION=${var.aptl_version}"]
    execute_command  = "sudo -S bash -c '{{ .Vars }} {{ .Path }}'"
  }

  post-processor "manifest" {
    output     = "techvault-manifest.json"
    strip_path = true
  }
}
