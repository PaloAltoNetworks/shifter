# GitHub Actions -> GCP federation for the packer GCE image builds
# (packer-gcp.yml). The GCP analog of platform/terraform/global/iam/
# github-oidc.tf (AWS). GitHub's OIDC token is exchanged for short-lived
# credentials that impersonate the packer build service account; no long-lived
# service-account keys are issued.

locals {
  # Exact-subject WIF federation (ADR-004-R23, #1690) layered on the ADR-037-R7
  # ref-allowlist (#1685). `federated_subjects` is the single source of truth for
  # the exact GitHub Actions subjects trusted to impersonate the shared CI build
  # SA: it drives BOTH the exact-subject WIF bindings below AND the static
  # `assertion.sub ==` allow-list in the provider condition, which MUST stay in
  # sync. Checkov CKV_GCP_125 needs a LITERAL `assertion.sub ==` and does not
  # render `join()`, so those clauses are written out statically; the
  # check-tf-gcp-wif-trust guard fails the build if they diverge from this list.
  # Each subject impersonates the SA by its EXACT `sub`
  # (principal://.../subject/<sub>), never a repository-wide principalSet, which
  # would trust every workflow, ref, and actor in the repo. An `environment:`
  # subject does not carry the source branch, so the ref allowlist (below) is what
  # denies a feature-branch/tag dispatch that reuses an environment subject. The
  # default is the current single-pool caller union; a future per-purpose pool
  # narrows it (#1699).
  federated_subjects = [
    "repo:${var.github_org}/${var.github_repo}:environment:gcp-dev", # _gcp-dev.yml deploy
    "repo:${var.github_org}/${var.github_repo}:environment:dev",     # packer-gcp build/validate (dev)
    "repo:${var.github_org}/${var.github_repo}:environment:proof",   # packer-gcp build/validate (proof)
    "repo:${var.github_org}/${var.github_repo}:environment:prod",    # packer-gcp-promote
    "repo:${var.github_org}/${var.github_repo}:ref:refs/heads/dev",  # gcp-dev-destroy (no environment:)
    "repo:${var.github_org}/${var.github_repo}:ref:refs/heads/main", # gcp-dev-destroy (no environment:)
  ]
  wif_subject_principals = {
    for sub in local.federated_subjects :
    sub => "principal://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/subject/${sub}"
  }

  # CEL fragment: assertion.ref must be one of the allowed protected integration
  # branches (ADR-037-R7, #1685). Single quotes so the composite condition needs
  # no HCL escaping and Checkov's CKV_GCP_125 `assertion.sub ==` regex still
  # matches the static sub clauses below.
  ref_condition = join(" || ", [for r in var.allowed_workflow_refs : "assertion.ref == '${r}'"])
}

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "${var.name_prefix}-github"
  display_name              = "GitHub Actions (${var.environment})"
  description               = "Federates ${var.github_org}/${var.github_repo} GitHub Actions for image builds."
}

resource "google_iam_workload_identity_pool_provider" "github" {
  # No CKV_GCP_125 waiver: the attribute_condition below pins an exact
  # `assertion.sub ==` allow-list (ADR-004-R23, #1690), which satisfies the check
  # for real - superseding the ADR-037-R7 ref-only justification for the skip.
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # Three-layer external trust boundary; a token is accepted only when ALL hold:
  #   1. Repository (ADR-037-R7): tokens from any other repository are rejected
  #      before the SA binding is consulted.
  #   2. Ref (ADR-037-R7, #1685): the source ref must be in allowed_workflow_refs
  #      (the protected integration branches), via local.ref_condition. An
  #      `environment:` subject does not carry the branch, so THIS layer is what
  #      denies a feature-branch/tag dispatch that reuses an environment subject.
  #   3. Subject (ADR-004-R23, #1690): assertion.sub must be one of the exact
  #      allow-listed subjects. These clauses are written out statically (Checkov
  #      cannot render join()) and MUST equal local.federated_subjects
  #      (check-tf-gcp-wif-trust enforces it). Single-quoted CEL literals so the
  #      HCL string needs no escaping and the exact `assertion.sub ==` pin
  #      satisfies CKV_GCP_125 - no waiver needed.
  attribute_condition = "assertion.repository == '${var.github_org}/${var.github_repo}' && (${local.ref_condition}) && (assertion.sub == 'repo:${var.github_org}/${var.github_repo}:environment:gcp-dev' || assertion.sub == 'repo:${var.github_org}/${var.github_repo}:environment:dev' || assertion.sub == 'repo:${var.github_org}/${var.github_repo}:environment:proof' || assertion.sub == 'repo:${var.github_org}/${var.github_repo}:environment:prod' || assertion.sub == 'repo:${var.github_org}/${var.github_repo}:ref:refs/heads/dev' || assertion.sub == 'repo:${var.github_org}/${var.github_repo}:ref:refs/heads/main')"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "packer_build" {
  project      = var.project_id
  account_id   = "${replace(var.name_prefix, "-", "")}-packer"
  display_name = "Shifter ${var.environment} packer GCE image builder"
}

# Allow only the exact allow-listed GitHub Actions subjects to impersonate the
# build SA via the pool - one binding per subject, never a repository-wide
# principalSet (ADR-004-R23, #1690).
resource "google_service_account_iam_member" "packer_build_wif" {
  for_each           = local.wif_subject_principals
  service_account_id = google_service_account.packer_build.name
  role               = "roles/iam.workloadIdentityUser"
  member             = each.value
}

# The builder VM runs as this same service account, so the build SA needs
# serviceAccountUser on ITSELF (not project-wide, which would let it run VMs as
# any SA and trips CKV_GCP_49). This also satisfies the `actAs` the caller needs
# when it pins both the Cloud Build identity (--cloudbuild-service-account) and
# the export worker VM (--compute-service-account) to this same SA.
resource "google_service_account_iam_member" "packer_build_act_as_self" {
  service_account_id = google_service_account.packer_build.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.packer_build.email}"
}

# `gcloud compute images export` runs as a Cloud Build job that mints a
# short-lived access token for the export worker's compute service account. With
# the build pinned to this SA (--cloudbuild-service-account), it generates that
# token for itself, so it needs serviceAccountTokenCreator on ITSELF. Scoped to
# this SA, not project-wide (mirrors the provisioner signBlob self-binding).
resource "google_service_account_iam_member" "packer_build_token_creator_self" {
  service_account_id = google_service_account.packer_build.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.packer_build.email}"
}

resource "google_project_iam_member" "packer_build_roles" {
  # checkov:skip=CKV_GCP_42:A CI GCE image builder requires compute/storage admin to create builder VMs, disks and images; no non-admin predefined role can create images. Scope is one dedicated, federation-only build SA (#615).
  # checkov:skip=CKV_GCP_49:cloudbuild.builds.editor is required for `gcloud compute images export` (runs as a Cloud Build job); the SA only impersonates the Cloud Build agent for image export (#615).
  for_each = toset(var.build_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.packer_build.email}"
}
