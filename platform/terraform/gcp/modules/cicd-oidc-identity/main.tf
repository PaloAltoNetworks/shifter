# GitHub Actions -> GCP federation for purpose-scoped CI identities.

locals {
  build_enabled        = contains(keys(var.purpose_contexts), "build")
  validate_enabled     = contains(keys(var.purpose_contexts), "validate")
  promote_enabled      = contains(keys(var.purpose_contexts), "promote")
  release_scan_enabled = contains(keys(var.purpose_contexts), "release_scan")
  deploy_enabled       = contains(keys(var.purpose_contexts), "deploy")
  destroy_enabled      = contains(keys(var.purpose_contexts), "destroy")

  service_account_ids = {
    build        = "${replace(var.name_prefix, "-", "")}-packer"
    validate     = "${replace(var.name_prefix, "-", "")}-validate"
    promote      = "${replace(var.name_prefix, "-", "")}-promote"
    release_scan = "${replace(var.name_prefix, "-", "")}-scan"
    deploy       = "${replace(var.name_prefix, "-", "")}-deploy"
    destroy      = "${replace(var.name_prefix, "-", "")}-destroy"
  }
  service_account_emails = {
    for purpose, account_id in local.service_account_ids : purpose => "${account_id}@${var.project_id}.iam.gserviceaccount.com"
  }
  service_account_names = {
    for purpose, email in local.service_account_emails : purpose => "projects/${var.project_id}/serviceAccounts/${email}"
  }
  subject_prefix = var.github_subject_format == "immutable" ? "repo:${var.github_org}@${var.github_owner_id}/${var.github_repo}@${var.github_repository_id}" : "repo:${var.github_org}/${var.github_repo}"
  purpose_subjects = {
    for purpose in ["build", "validate", "promote", "release_scan", "deploy", "destroy"] :
    purpose => distinct([for context in lookup(var.purpose_contexts, purpose, []) : "${local.subject_prefix}:environment:${context.environment}"])
  }
  federated_subjects = toset(flatten(values(local.purpose_subjects)))
  purpose_subject_principals = {
    for purpose, subjects in local.purpose_subjects : purpose => {
      for sub in subjects :
      sub => "principal://iam.googleapis.com/projects/${var.project_number}/locations/global/workloadIdentityPools/${var.name_prefix}-github/subject/${sub}"
    }
  }
  terraform_state_bucket_name = var.terraform_state_bucket_name
  platform_storage_bucket_names = toset([
    lower("${var.project_id}-${replace(var.environment, "_", "-")}-assets"),
    lower("${var.project_id}-${replace(var.environment, "_", "-")}-audit-logs"),
    lower("${var.project_id}-${var.name_prefix}-gdc-vm-images"),
  ])
  platform_storage_condition = join(" || ", concat(
    [for bucket in local.platform_storage_bucket_names : "resource.name == 'projects/_/buckets/${bucket}'"],
    [for bucket in local.platform_storage_bucket_names : "resource.name.startsWith('projects/_/buckets/${bucket}/objects/')"],
  ))
  lifecycle_iam_bucket_names = setunion(
    toset([local.terraform_state_bucket_name]),
    var.platform_external_bucket_names,
  )
}

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "${var.name_prefix}-github"
  display_name              = "GitHub Actions (${var.environment})"
  description               = "Purpose-scoped federation for ${var.github_org}/${var.github_repo}."
}

# Preserve the provider address during migration. Bootstrap validates the
# resolved plan against the common inventory and scans that exact saved plan.
resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC"
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }
  attribute_condition = "assertion.repository == '${var.github_org}/${var.github_repo}' && assertion.repository_id == '${var.github_repository_id}' && assertion.repository_owner_id == '${var.github_owner_id}' && assertion.event_name == 'workflow_dispatch' && (${join(" || ", flatten([
    for purpose, contexts in var.purpose_contexts : [
      for context in contexts : "(assertion.sub == '${local.subject_prefix}:environment:${context.environment}' && assertion.ref == '${context.ref}' && assertion.workflow_ref == '${context.workflow_ref}'${context.reusable_workflow_ref == "" ? "" : " && assertion.job_workflow_ref == '${context.reusable_workflow_ref}'"})"
    ]
  ]))})"
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "packer_build" {
  project      = var.project_id
  account_id   = "${replace(var.name_prefix, "-", "")}-packer"
  display_name = "Shifter ${var.environment} GCE image builder"
}

resource "google_service_account" "validate" {
  count        = local.validate_enabled ? 1 : 0
  project      = var.project_id
  account_id   = "${replace(var.name_prefix, "-", "")}-validate"
  display_name = "Shifter ${var.environment} GCE image validator"
}

resource "google_service_account" "promote" {
  count        = local.promote_enabled ? 1 : 0
  project      = var.project_id
  account_id   = "${replace(var.name_prefix, "-", "")}-promote"
  display_name = "Shifter prod GCE image promoter"
}

resource "google_service_account" "deploy" {
  count        = local.deploy_enabled ? 1 : 0
  project      = var.project_id
  account_id   = "${replace(var.name_prefix, "-", "")}-deploy"
  display_name = "Shifter ${var.environment} platform deployer"
}

resource "google_service_account" "release_scan" {
  count        = local.release_scan_enabled ? 1 : 0
  project      = var.project_id
  account_id   = "${replace(var.name_prefix, "-", "")}-scan"
  display_name = "Shifter ${var.environment} exact-release image scanner"
}

resource "google_service_account" "destroy" {
  count        = local.destroy_enabled ? 1 : 0
  project      = var.project_id
  account_id   = "${replace(var.name_prefix, "-", "")}-destroy"
  display_name = "Shifter ${var.environment} platform destroyer"
}

resource "google_service_account_iam_member" "packer_build_wif" {
  depends_on         = [google_service_account.packer_build, google_iam_workload_identity_pool_provider.github]
  for_each           = local.purpose_subject_principals.build
  service_account_id = local.service_account_names.build
  role               = "roles/iam.workloadIdentityUser"
  member             = each.value
}

resource "google_service_account_iam_member" "validate_wif" {
  depends_on         = [google_service_account.validate, google_iam_workload_identity_pool_provider.github]
  for_each           = local.purpose_subject_principals.validate
  service_account_id = local.service_account_names.validate
  role               = "roles/iam.workloadIdentityUser"
  member             = each.value
}

resource "google_service_account_iam_member" "promote_wif" {
  depends_on         = [google_service_account.promote, google_iam_workload_identity_pool_provider.github]
  for_each           = local.purpose_subject_principals.promote
  service_account_id = local.service_account_names.promote
  role               = "roles/iam.workloadIdentityUser"
  member             = each.value
}

resource "google_service_account_iam_member" "deploy_wif" {
  depends_on         = [google_service_account.deploy, google_iam_workload_identity_pool_provider.github]
  for_each           = local.purpose_subject_principals.deploy
  service_account_id = local.service_account_names.deploy
  role               = "roles/iam.workloadIdentityUser"
  member             = each.value
}

resource "google_service_account_iam_member" "release_scan_wif" {
  depends_on         = [google_service_account.release_scan, google_iam_workload_identity_pool_provider.github]
  for_each           = local.purpose_subject_principals.release_scan
  service_account_id = local.service_account_names.release_scan
  role               = "roles/iam.workloadIdentityUser"
  member             = each.value
}

resource "google_service_account_iam_member" "destroy_wif" {
  depends_on         = [google_service_account.destroy, google_iam_workload_identity_pool_provider.github]
  for_each           = local.purpose_subject_principals.destroy
  service_account_id = local.service_account_names.destroy
  role               = "roles/iam.workloadIdentityUser"
  member             = each.value
}

resource "google_service_account_iam_member" "packer_build_act_as_self" {
  count              = local.build_enabled ? 1 : 0
  depends_on         = [google_service_account.packer_build]
  service_account_id = local.service_account_names.build
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${local.service_account_emails.build}"
}

resource "google_service_account_iam_member" "packer_build_token_creator_self" {
  count              = local.build_enabled ? 1 : 0
  depends_on         = [google_service_account.packer_build]
  service_account_id = local.service_account_names.build
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${local.service_account_emails.build}"
}

resource "google_project_iam_member" "packer_build_roles" {
  depends_on = [google_service_account.packer_build]
  for_each   = local.build_enabled ? toset(var.build_roles) : toset([])
  project    = var.project_id
  role       = each.value
  member     = "serviceAccount:${local.service_account_emails.build}"
}

# Build inputs are granted by their owning bucket, not through project-wide
# Storage Admin. The exported-image bucket writer lives in packer-build-infra.
resource "google_storage_bucket_iam_member" "packer_build_reader" {
  depends_on = [google_service_account.packer_build]
  for_each   = local.build_enabled ? var.build_read_bucket_names : toset([])
  bucket     = each.value
  role       = "roles/storage.objectViewer"
  member     = "serviceAccount:${local.service_account_emails.build}"
}

resource "google_project_iam_custom_role" "validate" {
  count       = local.validate_enabled ? 1 : 0
  project     = var.project_id
  role_id     = "${replace(var.name_prefix, "-", "_")}_validate"
  title       = "Shifter GCE image validator"
  description = "Disposable no-SA validation VM lifecycle and exact-candidate evidence labels."
  permissions = var.validate_permissions
}

resource "google_project_iam_member" "validate_roles" {
  depends_on = [google_service_account.validate, google_project_iam_custom_role.validate]
  for_each   = local.validate_enabled ? toset(concat(var.validate_roles, ["projects/${var.project_id}/roles/${replace(var.name_prefix, "-", "_")}_validate"])) : toset([])
  project    = var.project_id
  role       = each.value
  member     = "serviceAccount:${local.service_account_emails.validate}"
}

resource "google_project_iam_custom_role" "promote" {
  count       = local.promote_enabled ? 1 : 0
  project     = var.project_id
  role_id     = "${replace(var.name_prefix, "-", "_")}_promote"
  title       = "Shifter GCE image promoter"
  description = "Verified prod image copy, channel commit, and previous-head deprecation."
  permissions = var.promote_permissions
}

resource "google_project_iam_member" "promote_role" {
  depends_on = [google_service_account.promote, google_project_iam_custom_role.promote]
  count      = local.promote_enabled ? 1 : 0
  project    = var.project_id
  role       = "projects/${var.project_id}/roles/${replace(var.name_prefix, "-", "_")}_promote"
  member     = "serviceAccount:${local.service_account_emails.promote}"
}

resource "google_project_iam_member" "promotion_source_image_reader" {
  count   = var.promotion_reader_service_account_email == "" ? 0 : 1
  project = var.project_id
  role    = "roles/compute.imageUser"
  member  = "serviceAccount:${var.promotion_reader_service_account_email}"
}

resource "google_project_iam_member" "deploy_roles" {
  depends_on = [google_service_account.deploy]
  for_each   = local.deploy_enabled ? toset(var.deploy_roles) : toset([])
  project    = var.project_id
  role       = each.value
  member     = "serviceAccount:${local.service_account_emails.deploy}"
}

resource "google_project_iam_member" "destroy_roles" {
  depends_on = [google_service_account.destroy]
  for_each   = local.destroy_enabled ? toset(var.destroy_roles) : toset([])
  project    = var.project_id
  role       = each.value
  member     = "serviceAccount:${local.service_account_emails.destroy}"
}

# Bucket lifecycle and object access are limited to the three deterministic
# platform-core buckets. In particular, neither lifecycle identity receives a
# project-wide Storage Admin grant that could alter retained release evidence.
resource "google_project_iam_custom_role" "deploy_storage" {
  count       = local.deploy_enabled ? 1 : 0
  project     = var.project_id
  role_id     = "${replace(var.name_prefix, "-", "_")}_deploy_storage"
  title       = "Shifter platform deploy storage"
  description = "Terraform lifecycle for deterministic platform-owned buckets only."
  permissions = var.deploy_storage_permissions
}

resource "google_project_iam_member" "deploy_storage" {
  depends_on = [google_service_account.deploy, google_project_iam_custom_role.deploy_storage]
  count      = local.deploy_enabled ? 1 : 0
  project    = var.project_id
  role       = "projects/${var.project_id}/roles/${replace(var.name_prefix, "-", "_")}_deploy_storage"
  member     = "serviceAccount:${local.service_account_emails.deploy}"

  condition {
    title       = "platform-buckets-only"
    description = "Deploy may manage assets, audit-log, and GDC image buckets, never release evidence."
    expression  = local.platform_storage_condition
  }
}

resource "google_project_iam_custom_role" "destroy_storage" {
  count       = local.destroy_enabled ? 1 : 0
  project     = var.project_id
  role_id     = "${replace(var.name_prefix, "-", "_")}_destroy_storage"
  title       = "Shifter platform destroy storage"
  description = "Terraform teardown for deterministic platform-owned buckets only."
  permissions = var.destroy_storage_permissions
}

resource "google_project_iam_member" "destroy_storage" {
  depends_on = [google_service_account.destroy, google_project_iam_custom_role.destroy_storage]
  count      = local.destroy_enabled ? 1 : 0
  project    = var.project_id
  role       = "projects/${var.project_id}/roles/${replace(var.name_prefix, "-", "_")}_destroy_storage"
  member     = "serviceAccount:${local.service_account_emails.destroy}"

  condition {
    title       = "platform-buckets-only"
    description = "Destroy may tear down assets, audit-log, and GDC image buckets, never release evidence."
    expression  = local.platform_storage_condition
  }
}

# Terraform maintains per-workload object grants on the pre-existing state and
# explicitly declared content buckets. Bucket Owner is attached to each exact
# bucket resource, never inherited from the project and never applied to the
# release-evidence bucket.
resource "google_storage_bucket_iam_member" "deploy_bucket_iam_admin" {
  depends_on = [google_service_account.deploy]
  for_each   = local.deploy_enabled ? local.lifecycle_iam_bucket_names : toset([])
  bucket     = each.value
  role       = "roles/storage.legacyBucketOwner"
  member     = "serviceAccount:${local.service_account_emails.deploy}"
}

resource "google_storage_bucket_iam_member" "destroy_bucket_iam_admin" {
  depends_on = [google_service_account.destroy]
  for_each   = local.destroy_enabled ? local.lifecycle_iam_bucket_names : toset([])
  bucket     = each.value
  role       = "roles/storage.legacyBucketOwner"
  member     = "serviceAccount:${local.service_account_emails.destroy}"
}

# Raw release evidence never enters public Actions artifacts. This foundational
# bucket outlives platform-core and is writable only by the exact purpose that
# produced each evidence class. ObjectCreator prevents overwrite or deletion;
# retention and versioning make the evidence independently auditable.
resource "google_storage_bucket" "release_evidence" {
  # checkov:skip=CKV_GCP_62:This foundational bucket must exist before and outlive platform-core, including its audit-log sink. Pointing it at that sink creates a bootstrap/destroy dependency; self-logging recurses. See the time-bounded ADR-004-R11 exception (#2084).
  name                        = var.release_evidence_bucket_name
  project                     = var.project_id
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels = {
    environment = replace(var.environment, "_", "-")
    managed_by  = "terraform"
    project     = "shifter"
  }

  versioning {
    enabled = true
  }

  retention_policy {
    retention_period = 7776000
    is_locked        = true
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age = 365
    }
  }
}

resource "google_storage_bucket_iam_member" "packer_build_evidence_writer" {
  depends_on = [google_service_account.packer_build]
  count      = local.build_enabled ? 1 : 0
  bucket     = google_storage_bucket.release_evidence.name
  role       = "roles/storage.objectCreator"
  member     = "serviceAccount:${local.service_account_emails.build}"

  condition {
    title       = "packer-build-evidence-only"
    description = "Build identity may create immutable source-binding records only."
    expression  = "resource.name.startsWith('projects/_/buckets/${google_storage_bucket.release_evidence.name}/objects/packer-builds/')"
  }
}

resource "google_storage_bucket_iam_member" "validate_build_evidence_reader" {
  depends_on = [google_service_account.validate]
  count      = local.validate_enabled ? 1 : 0
  bucket     = google_storage_bucket.release_evidence.name
  role       = "roles/storage.objectViewer"
  member     = "serviceAccount:${local.service_account_emails.validate}"

  condition {
    title       = "packer-build-evidence-read-only"
    description = "Validation identity may read immutable source-binding records only."
    expression  = "resource.name.startsWith('projects/_/buckets/${google_storage_bucket.release_evidence.name}/objects/packer-builds/')"
  }
}

resource "google_storage_bucket_iam_member" "validate_evidence_writer" {
  depends_on = [google_service_account.validate]
  count      = local.validate_enabled ? 1 : 0
  bucket     = google_storage_bucket.release_evidence.name
  role       = "roles/storage.objectCreator"
  member     = "serviceAccount:${local.service_account_emails.validate}"

  condition {
    title       = "packer-validation-evidence-only"
    description = "Validation identity may create immutable validation records only."
    expression  = "resource.name.startsWith('projects/_/buckets/${google_storage_bucket.release_evidence.name}/objects/packer-validation/')"
  }
}

resource "google_storage_bucket_iam_member" "release_scan_evidence_writer" {
  depends_on = [google_service_account.release_scan]
  count      = local.release_scan_enabled ? 1 : 0
  bucket     = google_storage_bucket.release_evidence.name
  role       = "roles/storage.objectCreator"
  member     = "serviceAccount:${local.service_account_emails.release_scan}"

  condition {
    title       = "release-scan-evidence-only"
    description = "Release scanner may create exact-digest scan records only."
    expression  = "resource.name.startsWith('projects/_/buckets/${google_storage_bucket.release_evidence.name}/objects/release-scans/')"
  }
}

resource "google_storage_bucket_iam_member" "deploy_evidence_writer" {
  depends_on = [google_service_account.deploy]
  count      = local.deploy_enabled ? 1 : 0
  bucket     = google_storage_bucket.release_evidence.name
  role       = "roles/storage.objectCreator"
  member     = "serviceAccount:${local.service_account_emails.deploy}"

  condition {
    title       = "deployment-evidence-only"
    description = "Deploy identity may create running-image records only."
    expression  = "resource.name.startsWith('projects/_/buckets/${google_storage_bucket.release_evidence.name}/objects/deployments/')"
  }
}

# `gcloud storage cp` issues a pre-flight object GET plus a bucket-level object
# LIST to choose its upload strategy; create-only (objectCreator) alone makes the
# evidence cp fail (403 on get, then on the bucket list). A bucket-level list
# cannot be scoped by an object-name condition, so each evidence writer gets an
# unconditioned objectViewer (get+list) on the release-evidence bucket. This only
# grants read over provenance metadata; objectCreator still blocks
# overwrite/deletion, so evidence immutability is preserved.
resource "google_storage_bucket_iam_member" "packer_build_evidence_reader" {
  count  = local.build_enabled ? 1 : 0
  bucket = google_storage_bucket.release_evidence.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.packer_build.email}"
}

resource "google_storage_bucket_iam_member" "validate_evidence_reader" {
  count  = local.validate_enabled ? 1 : 0
  bucket = google_storage_bucket.release_evidence.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.validate[0].email}"
}

resource "google_storage_bucket_iam_member" "release_scan_evidence_reader" {
  count  = local.release_scan_enabled ? 1 : 0
  bucket = google_storage_bucket.release_evidence.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.release_scan[0].email}"
}

resource "google_storage_bucket_iam_member" "deploy_evidence_reader" {
  count  = local.deploy_enabled ? 1 : 0
  bucket = google_storage_bucket.release_evidence.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.deploy[0].email}"
}

resource "google_storage_bucket_iam_member" "promotion_evidence_reader" {
  count  = var.promotion_reader_service_account_email == "" ? 0 : 1
  bucket = google_storage_bucket.release_evidence.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${var.promotion_reader_service_account_email}"

  condition {
    title       = "packer-validation-evidence-read-only"
    description = "Promotion identity may read immutable validation records only."
    expression  = "resource.name.startsWith('projects/_/buckets/${google_storage_bucket.release_evidence.name}/objects/packer-validation/')"
  }
}


# The foundational root owns CI access to its pre-existing backend bucket.
# These bindings outlive platform-core and replace workflow-time self-grants.
resource "google_storage_bucket_iam_member" "deploy_state_object_admin" {
  depends_on = [google_service_account.deploy]
  count      = local.deploy_enabled ? 1 : 0
  bucket     = local.terraform_state_bucket_name
  role       = "roles/storage.objectAdmin"
  member     = "serviceAccount:${local.service_account_emails.deploy}"
}

resource "google_storage_bucket_iam_member" "deploy_state_bucket_reader" {
  depends_on = [google_service_account.deploy]
  count      = local.deploy_enabled ? 1 : 0
  bucket     = local.terraform_state_bucket_name
  role       = "roles/storage.legacyBucketReader"
  member     = "serviceAccount:${local.service_account_emails.deploy}"
}

resource "google_storage_bucket_iam_member" "destroy_state_object_admin" {
  depends_on = [google_service_account.destroy]
  count      = local.destroy_enabled ? 1 : 0
  bucket     = local.terraform_state_bucket_name
  role       = "roles/storage.objectAdmin"
  member     = "serviceAccount:${local.service_account_emails.destroy}"
}

resource "google_storage_bucket_iam_member" "destroy_state_bucket_reader" {
  depends_on = [google_service_account.destroy]
  count      = local.destroy_enabled ? 1 : 0
  bucket     = local.terraform_state_bucket_name
  role       = "roles/storage.legacyBucketReader"
  member     = "serviceAccount:${local.service_account_emails.destroy}"
}
