# GCP-native GitHub Actions runner root (issue #1546).
#
# Dev-tenant containment: each dev tenant provisions its own GCP runner in its
# own project so a GCP dev tenant runs CI/deploy without borrowing the AWS fleet
# (and neither dev tenant assumes the other exists). This root has a Terraform
# state prefix separate from the gcp-dev platform root, so the platform destroy
# workflow never removes the runner; the runner is re-creatable by
# `deploy.py runners --cloud gcp` (the real deploy mechanism lives in the repo,
# not the tenant -- preserving ADR-033's intent; see the ADR-033-R2 amendment).
#
# The instance is private-only (no external IP), Shielded, OS Login-only, in a
# dedicated custom VPC reachable for registration over IAP alone. The startup
# script installs a pinned, checksum-verified runner but NEVER registers it: a
# single-use token is delivered out-of-band over IAP SSH stdin
# (scripts/bootstrap/gcp_runner.py), so the token never touches Terraform state,
# instance metadata, Secret Manager, argv, or logs.

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  name_prefix = "shifter-${var.environment}"
}

# Dedicated, least-privilege runner VM service account: host logging/monitoring
# only. Never the project default service account, never roles/owner, Editor, or
# a deploy role. Workflow WIF remains the deployment identity (ADR-003-R5).
resource "google_service_account" "runner" {
  project      = var.project_id
  account_id   = "${local.name_prefix}-runner"
  display_name = "Shifter ${var.environment} GitHub Actions runner"
}

resource "google_project_iam_member" "runner_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.runner.email}"
}

resource "google_project_iam_member" "runner_metric_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.runner.email}"
}

# The dedicated custom VPC is mandatory and non-bypassable (ADR-008-R8): there is
# no "use an existing subnet" opt-out, so a runner can never land in a default or
# shared network with arbitrary firewall policy. The runner-network module is the
# single source of the runner's network; it is guarded by check_tf_gcp_runner_network.
module "runner_network" {
  source = "../../modules/github-runner-network"

  project_id                   = var.project_id
  region                       = var.region
  name_prefix                  = local.name_prefix
  runner_subnet_cidr           = var.runner_subnet_cidr
  runner_service_account_email = google_service_account.runner.email
}

resource "google_compute_instance" "runner" {
  # checkov:skip=CKV_GCP_38:Boot disk uses Google-managed at-rest encryption (AES-256). CSEK/CMEK would add customer-key + IAM management to this dedicated root for marginal gain on a re-creatable dev-tenant runner. See ADR-004-R11 exception (gcp-runner-boot-disk-csek); CMEK revisit tracked with the runner hardening follow-up.
  count = var.runner_count

  name         = "${local.name_prefix}-runner-${count.index + 1}"
  project      = var.project_id
  zone         = var.zone
  machine_type = var.machine_type

  boot_disk {
    initialize_params {
      image = var.runner_image
      size  = var.runner_disk_size_gb
      type  = "pd-balanced"
    }
  }

  # Private-only: the absence of an access_config block means no external IP.
  # Outbound traffic (github.com, the runner download) egresses via Cloud NAT.
  network_interface {
    subnetwork = module.runner_network.subnet_self_link
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  # OS Login for IAP SSH; block project-wide SSH keys; disable serial-port
  # access. The startup script installs a pinned, checksum-verified runner and
  # carries NO token (registration is out-of-band over IAP SSH).
  metadata = {
    enable-oslogin         = "TRUE"
    block-project-ssh-keys = "TRUE"
    serial-port-enable     = "FALSE"
  }

  metadata_startup_script = templatefile("${path.module}/startup-script.sh.tftpl", {
    runner_user     = var.runner_user
    runner_version  = var.runner_version
    runner_checksum = var.runner_checksum
  })

  service_account {
    email = google_service_account.runner.email
    scopes = [
      "https://www.googleapis.com/auth/logging.write",
      "https://www.googleapis.com/auth/monitoring.write",
    ]
  }

  labels = {
    environment = var.environment
    managed_by  = "terraform"
    project     = "shifter"
    role        = "github-runner"
  }

  allow_stopping_for_update = true
}
