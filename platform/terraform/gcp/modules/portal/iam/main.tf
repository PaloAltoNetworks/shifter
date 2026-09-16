data "google_project" "platform" {
  project_id = var.project_id
}

data "google_project" "dynamic_secrets" {
  project_id = var.dynamic_secret_project_id
}

locals {
  dynamic_secret_project_is_dedicated = var.dynamic_secret_project_id != var.project_id
  canonical_secret_prefix             = "projects/${data.google_project.dynamic_secrets.number}/secrets/shifter-${var.environment}-dynamic-"
  canonical_participant_secret_prefix = "${local.canonical_secret_prefix}participant-"
  legacy_secret_prefixes = [
    "projects/${data.google_project.platform.number}/secrets/shifter-range-",
    "projects/${data.google_project.platform.number}/secrets/shifter-${var.environment}-range-",
    "projects/${data.google_project.platform.number}/secrets/shifter-${var.environment}-ngfw-user-",
  ]
  legacy_secret_name_condition = join(" || ", [
    for prefix in local.legacy_secret_prefixes : "resource.name.startsWith('${prefix}')"
  ])
  # IAM Conditions supports extract (not arbitrary contains/regex) on
  # resource.name. An empty range_scope excludes the legacy RAES directory
  # namespace, which must remain workload-only even for account-password. Keep
  # this positive form to remain within Google's condition complexity limit.
  # Payload access is evaluated against a version resource, so suffix checks
  # extract its parent secret ID before matching the participant audience.
  legacy_raes_directory_name_condition = "resource.name.extract('projects/${data.google_project.platform.number}/secrets/shifter-range-{range_scope}-raes-domain-') == ''"
  legacy_secret_version_id             = "resource.name.extract('/secrets/{secret_id}/versions/')"
  legacy_participant_secret_condition = join(" || ", [
    "(resource.name.startsWith('${local.legacy_secret_prefixes[0]}') && (${local.legacy_secret_version_id}.endsWith('-participant-ssh') || ${local.legacy_secret_version_id}.endsWith('-rdp-password') || ${local.legacy_secret_version_id}.endsWith('-profile') || ((${local.legacy_raes_directory_name_condition}) && (${local.legacy_secret_version_id}.endsWith('-account-password') || ${local.legacy_secret_version_id}.endsWith('-account-publickey')))))",
    "(resource.name.startsWith('${local.legacy_secret_prefixes[1]}') && (${local.legacy_secret_version_id}.endsWith('-ssh') || ${local.legacy_secret_version_id}.endsWith('-rdp-password')))",
    "(resource.name.startsWith('${local.legacy_secret_prefixes[2]}') && ${local.legacy_secret_version_id}.endsWith('-ssh'))",
  ])
  # The closed roles below contain only Secret Manager permissions. Fully
  # qualified secret-name prefixes scope both Secret and SecretVersion calls;
  # do not add a resource.type predicate (live GKE authorization rejects it).
  dynamic_lifecycle_condition = local.dynamic_secret_project_is_dedicated ? (
    "resource.name.startsWith('${local.canonical_secret_prefix}')"
    ) : (
    "(${local.legacy_secret_name_condition})"
  )
  portal_dynamic_read_condition = local.dynamic_secret_project_is_dedicated ? (
    "resource.name.startsWith('${local.canonical_participant_secret_prefix}')"
    ) : (
    "(${local.legacy_participant_secret_condition})"
  )

  workload_service_accounts = toset([
    "portal",
    "workers",
    "ctf-scheduler",
    "provisioner-launcher",
    "provisioner",
  ])

  # GCP service-account account_id is capped at 30 chars. The account_id is
  # "${replace(name_prefix, "-", "")}-${key}"; for name_prefix "shifter-gcp-dev"
  # the prefix collapses to "shiftergcpdev-" (14), leaving a 16-char budget for
  # the key. "provisioner-launcher" (20) overflows (34 chars); it also overflows
  # in prod ("shifterprod-provisioner-launcher", 32). Map long keys to a bounded
  # account_id suffix (#1719). The logical key stays the GKE KSA name / output
  # key; only the GCP SA email localpart is shortened, and every downstream
  # reference resolves through google_service_account.workload[key].email.
  workload_account_id_suffix = {
    "provisioner-launcher" = "prov-launcher"
  }

  workload_identity_members = {
    portal               = "serviceAccount:${var.project_id}.svc.id.goog[shifter-platform/portal]"
    workers              = "serviceAccount:${var.project_id}.svc.id.goog[shifter-platform/workers]"
    ctf-scheduler        = "serviceAccount:${var.project_id}.svc.id.goog[shifter-platform/ctf-scheduler]"
    provisioner-launcher = "serviceAccount:${var.project_id}.svc.id.goog[shifter-platform/provisioner-launcher]"
    provisioner          = "serviceAccount:${var.project_id}.svc.id.goog[shifter-jobs/provisioner]"
  }

  node_roles = toset([
    "roles/artifactregistry.reader",
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/stackdriver.resourceMetadata.writer",
  ])

  # ADR-008-R7 (docs/architecture/gcp-workload-resource-iam-preflight-1517.md):
  # workload identities receive project-level IAM only for APIs whose Google
  # roles are inherently project scoped (Firebase Auth, Pub/Sub, Artifact
  # Registry, Compute). Secret Manager payload access and Cloud Storage object
  # access are bound per named resource below, never at project scope. The
  # check_tf_gcp_iam_resource_scope guard fails closed on any secret/storage
  # payload/admin role added here.
  workload_project_roles = {
    portal = toset([
      "roles/firebaseauth.viewer",
      "roles/pubsub.publisher",
    ])
    workers = toset([
      "roles/pubsub.publisher",
      "roles/pubsub.subscriber",
    ])
    # The CTF scheduler polls Postgres for due tasks and triggers range
    # provisioning via cms.services.create_range, which publishes a request to
    # Pub/Sub for the provisioner to consume. It reads platform secrets at
    # startup (bound per named secret below) but never subscribes or touches
    # storage, so its project identity is bounded to publish.
    "ctf-scheduler" = toset([
      "roles/pubsub.publisher",
    ])
    # The launch worker reaches Postgres and Kubernetes only. It receives no
    # project-scoped cloud role and is deliberately distinct from provisioner.
    provisioner-launcher = toset([])
    provisioner = toset([
      # The provision Job runs under this identity and mints a short-lived
      # Artifact Registry access token, planting it as an imagePullSecret so the
      # isolated GDC range cluster can pull the version-matched setup-runner
      # image (RangePodSSHExecutor). AR read is the minimal grant that makes that
      # token authorize; the range cluster has no native AR pull identity.
      "roles/artifactregistry.reader",
      # The GCE range-cell backend (default per #1387) has the provisioner
      # create the range VPC, subnets, firewall rules, Cloud NAT, and guest
      # instances directly, so it needs full Compute admin on the range-cell
      # project. For the default same-project range cell this is the platform
      # project; a cross-project range cell (GCP_RANGE_CELL_PROJECT_ID) must
      # grant the equivalent role in that project (follow-up, see #1509).
      "roles/compute.admin",
      "roles/pubsub.publisher",
    ])
  }

  # Named runtime secrets the shared portal image hydrates at container startup
  # via entrypoint.sh (app, db, guacamole-json-auth, dc-domain-password, redis,
  # and email when configured). guacamole-db is excluded: it is delivered to the
  # separate guacamole-client pod as a native Kubernetes Secret, never fetched
  # from Secret Manager by these identities. The provisioner is absent: it
  # receives DB / field-key / DC-password values through its per-Job ephemeral
  # Kubernetes Secret and does not read runtime bundles from Secret Manager.
  secret_reader_workloads    = toset(["portal", "workers", "ctf-scheduler", "provisioner-launcher"])
  runtime_secret_reader_keys = [for key in keys(var.runtime_secret_ids) : key if key != "guacamole-db"]
  workload_secret_bindings = {
    for pair in setproduct(tolist(local.secret_reader_workloads), local.runtime_secret_reader_keys) :
    "${pair[0]}:${pair[1]}" => {
      workload  = pair[0]
      secret_id = var.runtime_secret_ids[pair[1]]
    }
  }

  # Per-bucket object access. Assets bucket: portal read/write (uploads,
  # finalize, delete, signed URLs), workers read-only, provisioner read-only
  # (agent-installer signed URL). Provisioner also owns per-range Terraform /
  # Pulumi state (read/write) and, when configured, the VM-Series bootstrap
  # bucket (read/write).
  workload_bucket_bindings = merge(
    {
      "portal:assets"      = { workload = "portal", bucket = var.assets_bucket_name, role = "roles/storage.objectAdmin" }
      "workers:assets"     = { workload = "workers", bucket = var.assets_bucket_name, role = "roles/storage.objectViewer" }
      "provisioner:assets" = { workload = "provisioner", bucket = var.assets_bucket_name, role = "roles/storage.objectViewer" }
      "provisioner:state"  = { workload = "provisioner", bucket = var.terraform_state_bucket_name, role = "roles/storage.objectAdmin" }
    },
    var.vmseries_bootstrap_bucket_name == "" ? {} : {
      "provisioner:vmseries" = { workload = "provisioner", bucket = var.vmseries_bootstrap_bucket_name, role = "roles/storage.objectAdmin" }
    },
    # Object-storage-backed RAES packages (#1567, ADR-034-R5): the portal reads
    # (never writes) the single immutable pack archive at launch. Least-privilege
    # objectViewer, bound per named bucket (ADR-008-R7); empty disables it.
    var.raes_package_bucket_name == "" ? {} : {
      "portal:raes-packages" = { workload = "portal", bucket = var.raes_package_bucket_name, role = "roles/storage.objectViewer" }
    },
    # Native CTF content bundles are a distinct deployment concern from RAES
    # packages. The portal needs read-only access to the explicitly configured
    # bucket; content publication stays outside the runtime identity.
    var.ctf_content_bucket_name == "" ? {} : {
      "portal:ctf-content" = { workload = "portal", bucket = var.ctf_content_bucket_name, role = "roles/storage.objectViewer" }
    },
  )
}

resource "google_service_account" "gke_nodes" {
  project      = var.project_id
  account_id   = "${replace(var.name_prefix, "-", "")}nodes"
  display_name = "Shifter ${var.environment} GKE nodes"
}

resource "google_service_account" "workload" {
  for_each = local.workload_service_accounts

  project      = var.project_id
  account_id   = "${replace(var.name_prefix, "-", "")}-${lookup(local.workload_account_id_suffix, each.key, each.key)}"
  display_name = "Shifter ${var.environment} ${each.key}"
}

resource "google_project_iam_member" "node_roles" {
  for_each = local.node_roles

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.gke_nodes.email}"
}

# The CI deploy SA that runs `terraform apply` for this stack must be able to
# actAs the GKE node SA to create node pools that run as it. Scoped to this one
# SA (not a project-wide roles/iam.serviceAccountUser, which trips CKV_GCP_41),
# mirroring the self-scoped actAs pattern in modules/cicd-oidc-identity. The
# node_service_account_email output depends_on this binding so the node pools
# (which consume that output) are never created before the deployer can actAs the
# node SA. Cluster-independent, so it does not hit the workload-identity binding
# deadlock documented in platform-core's portal_gke call.
resource "google_service_account_iam_member" "deploy_act_as_gke_nodes" {
  count = var.deploy_service_account_email != "" ? 1 : 0

  service_account_id = google_service_account.gke_nodes.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.deploy_service_account_email}"
}

resource "google_project_iam_member" "workload_roles" {
  for_each = merge([
    for account_name, roles in local.workload_project_roles : {
      for role in roles : "${account_name}:${role}" => {
        account_name = account_name
        role         = role
      }
    }
  ]...)

  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${google_service_account.workload[each.value.account_name].email}"
}

# Static runtime-secret reads, bound per named secret (ADR-008-R7). Replaces the
# former project-level roles/secretmanager.secretAccessor grant on portal,
# workers, and ctf-scheduler.
resource "google_secret_manager_secret_iam_member" "workload_secret_readers" {
  for_each = local.workload_secret_bindings

  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.workload[each.value.workload].email}"
}

# Operator-created inputs (GDC image credentials, shared Vertex key, and any
# future static provisioning input) stay outside the dynamic range-secret
# project and are granted by exact full resource ID only.
resource "google_secret_manager_secret_iam_member" "provisioner_static_secret_readers" {
  for_each = var.provisioner_static_secret_ids

  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.workload["provisioner"].email}"
}

# Cloud Storage object access, bound per named bucket (ADR-008-R7). Replaces the
# former project-level roles/storage.objectAdmin / objectViewer grants on
# portal, workers, and provisioner.
resource "google_storage_bucket_iam_member" "workload_buckets" {
  for_each = local.workload_bucket_bindings

  bucket = each.value.bucket
  role   = each.value.role
  member = "serviceAccount:${google_service_account.workload[each.value.workload].email}"
}

# Secret creation is authorized on the parent project before a Secret resource
# (and therefore resource.name) exists. This custom role contains only create
# and is deliberately unconditioned inside the dedicated project boundary.
resource "google_project_iam_custom_role" "dynamic_secret_creator" {
  project     = var.dynamic_secret_project_id
  role_id     = "shifterDynamicSecretCreator"
  title       = "Shifter dynamic secret creator"
  description = "Create Secret containers only in this deployment's range-secret project."
  permissions = ["secretmanager.secrets.create"]
}

resource "google_project_iam_member" "provisioner_dynamic_secret_create" {
  project = var.dynamic_secret_project_id
  role    = google_project_iam_custom_role.dynamic_secret_creator.id
  member  = "serviceAccount:${google_service_account.workload["provisioner"].email}"
}

# Existing-secret lifecycle permissions are separate from create and are
# conditioned on the canonical deployment prefix (or legacy prefixes only
# while the two project IDs intentionally remain equal during expand).
resource "google_project_iam_custom_role" "dynamic_secret_lifecycle" {
  project     = var.dynamic_secret_project_id
  role_id     = "shifterDynamicSecretLifecycle"
  title       = "Shifter dynamic secret lifecycle"
  description = "Read, version, update, delete, and bind canonical range secrets."
  permissions = [
    "secretmanager.secrets.delete",
    "secretmanager.secrets.get",
    "secretmanager.secrets.getIamPolicy",
    "secretmanager.secrets.setIamPolicy",
    "secretmanager.secrets.update",
    "secretmanager.versions.access",
    "secretmanager.versions.add",
  ]
}

resource "google_project_iam_member" "provisioner_dynamic_secret_lifecycle" {
  project = var.dynamic_secret_project_id
  role    = google_project_iam_custom_role.dynamic_secret_lifecycle.id
  member  = "serviceAccount:${google_service_account.workload["provisioner"].email}"

  condition {
    title       = "canonical_dynamic_range_secrets"
    description = "Existing-secret lifecycle is limited to this deployment's dynamic range-secret namespace."
    expression  = local.dynamic_lifecycle_condition
  }
}

# Portal payload access is read-only and limited to participant-delivery
# credentials. Workload-only secrets (host management, Vertex, VPN server and
# issuer material) never satisfy this prefix.
resource "google_project_iam_member" "portal_dynamic_secret_accessor" {
  project = var.dynamic_secret_project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.workload["portal"].email}"

  condition {
    title       = "participant_dynamic_range_secrets"
    description = "Portal reads participant-delivery secrets only."
    expression  = local.portal_dynamic_read_condition
  }
}

# During cut-over, exact legacy ids remain readable/deletable in the platform
# project so persisted full references and old-generation teardown keep working.
# No legacy role includes secrets.create, so fallback can never mint new legacy
# material. These resources disappear once the project IDs converge to the
# dedicated value after drain/contract.
resource "google_project_iam_custom_role" "legacy_dynamic_secret_lifecycle" {
  count       = local.dynamic_secret_project_is_dedicated ? 1 : 0
  project     = var.project_id
  role_id     = "shifterLegacySecretLifecycle"
  title       = "Shifter legacy secret lifecycle"
  description = "Drain and revoke legacy range secrets without creation rights."
  permissions = google_project_iam_custom_role.dynamic_secret_lifecycle.permissions
}

resource "google_project_iam_member" "provisioner_legacy_dynamic_secret_lifecycle" {
  count   = local.dynamic_secret_project_is_dedicated ? 1 : 0
  project = var.project_id
  role    = google_project_iam_custom_role.legacy_dynamic_secret_lifecycle[0].id
  member  = "serviceAccount:${google_service_account.workload["provisioner"].email}"

  condition {
    title       = "legacy_dynamic_range_secrets"
    description = "Migration-only lifecycle for exact legacy range-secret namespaces."
    expression  = "(${local.legacy_secret_name_condition})"
  }
}

resource "google_project_iam_member" "portal_legacy_dynamic_secret_accessor" {
  count   = local.dynamic_secret_project_is_dedicated ? 1 : 0
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.workload["portal"].email}"

  condition {
    title       = "legacy_participant_dynamic_range_secrets"
    description = "Migration-only portal reads for participant-facing legacy credentials."
    expression  = "(${local.legacy_participant_secret_condition})"
  }
}

# OpenVPN gateway identity pool (ADR-008-R7). Each active range that requests
# OpenVPN reserves one member of this pre-provisioned, no-role service-account
# pool (Range.vpn_gateway_pool_slot -> sh-vpn-pool-<slot>) and the range VM runs
# as it, isolated to that range's server secret. The provisioner holds
# serviceAccountUser on each *specific* pool member (a resource-scoped binding),
# so it can attach a pool identity WITHOUT any project-wide
# create/delete/setIamPolicy grant. This deletes the former project-level
# `vpnGatewayIdentityAdmin` custom role, which let the runtime provisioner call
# setIamPolicy against any service account in the project (e.g. the build SA) and
# escalate cross-identity -- GCP IAM cannot condition setIamPolicy on a service
# account's resource name, so a dynamic-creation grant could not be name-scoped.
# The pool assumes a single isolated tenant/project (no cross-project SA usage,
# no org-policy change); `vpn_gateway_pool_size` bounds concurrent OpenVPN ranges
# and must match VPN_GATEWAY_POOL_SIZE in the engine runtime env.
resource "google_service_account" "vpn_gateway_pool" {
  count        = var.vpn_gateway_pool_size
  project      = var.project_id
  account_id   = "sh-vpn-pool-${count.index}"
  display_name = "Shifter OpenVPN gateway pool member ${count.index}"
}

resource "google_service_account_iam_member" "provisioner_vpn_gateway_pool_act_as" {
  count              = var.vpn_gateway_pool_size
  service_account_id = google_service_account.vpn_gateway_pool[count.index].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.workload["provisioner"].email}"
}

resource "google_service_account" "range_host_pool" {
  count        = var.range_host_identity_pool_size
  project      = var.project_id
  account_id   = "sh-range-host-${count.index}"
  display_name = "Shifter preconfigured range host pool member ${count.index}"
}

resource "google_service_account_iam_member" "provisioner_range_host_pool_act_as" {
  count              = var.range_host_identity_pool_size
  service_account_id = google_service_account.range_host_pool[count.index].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.workload["provisioner"].email}"
}

resource "google_service_account_iam_member" "workload_identity" {
  for_each = local.workload_identity_members

  service_account_id = google_service_account.workload[each.key].name
  role               = "roles/iam.workloadIdentityUser"
  member             = each.value
}

# The portal signs V4 GCS upload/download URLs (agent uploads, experiment
# artifact downloads) via the IAM credentials signBlob API: Workload Identity
# credentials carry only an access token and have no private key to sign URLs
# locally. signBlob requires the service account to be able to mint signing
# tokens for itself, so it holds serviceAccountTokenCreator scoped to its own
# identity (not a project-wide grant).
resource "google_service_account_iam_member" "portal_sign_blob" {
  service_account_id = google_service_account.workload["portal"].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.workload["portal"].email}"
}

# The provisioner signs a V4 GCS download URL for each range instance's XDR
# agent object so the range VM can fetch it during provisioning. Like the
# portal, it runs under Workload Identity (token-only, no private key) and
# signs via the IAM signBlob API, which requires serviceAccountTokenCreator
# scoped to its own identity.
resource "google_service_account_iam_member" "provisioner_sign_blob" {
  service_account_id = google_service_account.workload["provisioner"].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.workload["provisioner"].email}"
}

# GCE range-cell service accounts (#1509). Distinct from the workload SAs: these
# are NOT Workload-Identity-bound to a KSA. The host SA is attached only to
# range hosts that need host-side GCS/Secret Manager access; participant/native
# guests receive no service account. The vertex SA backs the short-lived
# per-range key the a14-kali agent uses for Vertex AI. Created in the platform
# project for the default same-project range cell; a cross-project range cell
# overrides the emails and provisions the SAs in that project.
resource "google_service_account" "range_host" {
  project      = var.project_id
  account_id   = "${replace(var.name_prefix, "-", "")}-range-host"
  display_name = "Shifter ${var.environment} range host"
}

resource "google_service_account" "range_vertex" {
  project      = var.project_id
  account_id   = "${replace(var.name_prefix, "-", "")}-range-vertex"
  display_name = "Shifter ${var.environment} range Vertex"
}

# The range host SA is attached to participant-controllable POLARIS GCE guests
# with cloud-platform scope, so a participant with root on the guest can mint its
# token from the metadata server. It therefore holds NO project-level Cloud
# Storage role: a project (or shared-assets-bucket) objectViewer would let a
# compromised guest read across tenants (#1644). Its only host-side GCS need --
# the POLARIS smoketest tarball -- is delivered as a short-lived, provisioner-
# minted V4 signed download URL (agent_assets.get_polaris_tests_presigned_url),
# so the guest needs no GCS identity at all. logging/monitoring writes stay; the
# per-range Vertex-secret grant is bound elsewhere. check_tf_gcp_iam_resource_scope
# fails closed on any project-level roles/storage.* re-added to this SA.
resource "google_project_iam_member" "range_host_roles" {
  for_each = toset([
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.range_host.email}"
}

resource "google_project_iam_member" "range_vertex_aiplatform" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.range_vertex.email}"
}

# The provisioner attaches the host SA only to range hosts that need cloud APIs
# (actAs -> serviceAccountUser) and mints per-range Vertex keys on the vertex SA
# (serviceAccountKeyAdmin).
resource "google_service_account_iam_member" "provisioner_range_host_user" {
  service_account_id = google_service_account.range_host.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.workload["provisioner"].email}"
}

resource "google_service_account_iam_member" "provisioner_range_vertex_user" {
  service_account_id = google_service_account.range_vertex.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.workload["provisioner"].email}"
}

resource "google_service_account_iam_member" "provisioner_range_vertex_key_admin" {
  service_account_id = google_service_account.range_vertex.name
  role               = "roles/iam.serviceAccountKeyAdmin"
  member             = "serviceAccount:${google_service_account.workload["provisioner"].email}"
}
