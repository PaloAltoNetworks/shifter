# Packer build infrastructure: a dedicated builder subnet (internal-IP builds
# reachable over IAP, so no external IP is needed under the project's
# compute.vmExternalIpAccess org policy), an IAP-scoped ingress firewall, and
# the GCS bucket the built GCE images are exported into for the GDC VM Runtime
# (gs:// disk sources).

resource "google_compute_subnetwork" "packer_builder" {
  project                  = var.project_id
  name                     = "${var.name_prefix}-packer-builder"
  region                   = var.region
  network                  = var.platform_network
  ip_cidr_range            = var.build_subnet_cidr
  private_ip_google_access = true

  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

# Allow Identity-Aware Proxy to reach the builder VM for SSH (Linux) and WinRM
# (Windows/DC). Scoped to the IAP range and to the build service account, so
# no broad tag-based exposure and no packer-template change is required.
resource "google_compute_firewall" "packer_iap_ingress" {
  project   = var.project_id
  name      = "${var.name_prefix}-packer-iap-ingress"
  network   = var.platform_network
  direction = "INGRESS"

  # Must out-prioritise the platform deny-external-ssh-rdp rule (priority 900),
  # which denies tcp:22 from 0.0.0.0/0. A lower number wins, so this scoped IAP
  # allow sits just ahead of it; the deny still covers all other sources.
  priority = 800

  source_ranges           = ["35.235.240.0/20"] # NOSONAR - Google IAP TCP forwarding range.
  target_service_accounts = [google_service_account.packer_build.email]

  allow {
    protocol = "tcp"
    ports    = ["22", "5986"] # SSH (Linux) + WinRM-HTTPS (Windows/DC).
  }

  log_config {
    metadata = "INCLUDE_ALL_METADATA"
  }
}

resource "google_storage_bucket" "gdc_vm_images" {
  project = var.project_id
  # Project-prefixed for global uniqueness (GCS bucket names are global). The bare
  # "${name_prefix}-gdc-vm-images" collides across projects and stays reserved in
  # GCS's deletion cooldown after a project teardown, matching the project-prefixed
  # naming the portal GCS buckets already use.
  name                        = "${var.project_id}-${var.name_prefix}-gdc-vm-images"
  location                    = var.image_bucket_location
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }
}

# The packer build/export workflow writes exported disk images here.
resource "google_storage_bucket_iam_member" "packer_build_image_writer" {
  bucket = google_storage_bucket.gdc_vm_images.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.packer_build.email}"
}

# The GDC VM Runtime reads the gs:// disk images using the bare-metal GCR
# service account key (carried in GDC_VM_IMAGE_GCS_SECRET_ID).
resource "google_storage_bucket_iam_member" "vm_runtime_image_reader" {
  for_each = toset(var.image_reader_service_accounts)

  bucket = google_storage_bucket.gdc_vm_images.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${each.value}"
}
