# The beforeCreate blocking function enforces the corporate-domain sign-up
# allowlist at the Identity Platform layer. It is gen1-only and Identity Platform
# invokes it unauthenticated, so its invoker must be granted to `allUsers`
# (Google issuetracker/228462612: GCIP cannot call functions that require auth).
# Projects under a Domain Restricted Sharing org policy
# (constraints/iam.allowedPolicyMemberDomains) cannot create that `allUsers`
# binding, so the function is optional. When disabled, the portal application
# still enforces the same allowlist fail-closed at session creation
# (config/identity_platform.py::is_allowed_identity_email), so access control is
# preserved; only the provider-level early rejection (a UX nicety) is dropped.
locals {
  enable_blocking_function = var.enable_identity_blocking_function
}

data "archive_file" "identity_platform_before_create" {
  count       = local.enable_blocking_function ? 1 : 0
  type        = "zip"
  source_dir  = "${path.module}/functions/identity-platform"
  output_path = "${path.root}/.terraform/${var.name_prefix}-identity-platform-before-create.zip"
}

resource "google_storage_bucket_object" "identity_platform_before_create" {
  count  = local.enable_blocking_function ? 1 : 0
  name   = "identity-platform/identity-platform-before-create-${data.archive_file.identity_platform_before_create[0].output_md5}.zip"
  bucket = var.assets_bucket_name
  source = data.archive_file.identity_platform_before_create[0].output_path
}

resource "google_cloudfunctions_function" "identity_platform_before_create" {
  count                 = local.enable_blocking_function ? 1 : 0
  name                  = "${var.name_prefix}-identity-before-create"
  project               = var.project_id
  region                = var.region
  runtime               = "nodejs22"
  available_memory_mb   = 128
  timeout               = 10
  source_archive_bucket = var.assets_bucket_name
  source_archive_object = google_storage_bucket_object.identity_platform_before_create[0].name
  trigger_http          = true
  entry_point           = "beforeCreate"

  environment_variables = {
    ALLOWED_EMAIL_DOMAIN = var.identity_allowed_email_domain
    ALLOWED_EMAILS       = join(",", var.identity_allowed_emails)
  }
}

resource "google_cloudfunctions_function_iam_member" "identity_platform_before_create_invoker" {
  count          = local.enable_blocking_function ? 1 : 0
  project        = var.project_id
  region         = var.region
  cloud_function = google_cloudfunctions_function.identity_platform_before_create[0].name
  role           = "roles/cloudfunctions.invoker"
  member         = "allUsers"
}

resource "google_identity_platform_config" "platform" {
  project = var.project_id

  authorized_domains = var.identity_authorized_domains

  sign_in {
    allow_duplicate_emails = false

    anonymous {
      enabled = false
    }

    email {
      enabled           = true
      password_required = true
    }

    phone_number {
      enabled = false
    }
  }

  client {
    permissions {
      disabled_user_deletion = true
      disabled_user_signup   = false
    }
  }

  dynamic "blocking_functions" {
    for_each = local.enable_blocking_function ? [1] : []
    content {
      triggers {
        event_type   = "beforeCreate"
        function_uri = google_cloudfunctions_function.identity_platform_before_create[0].https_trigger_url
      }
    }
  }

  mfa {
    state = "ENABLED"

    provider_configs {
      state = "ENABLED"

      totp_provider_config {
        adjacent_intervals = 1
      }
    }
  }

  monitoring {
    request_logging {
      enabled = true
    }
  }

  # Email enumeration protection (Identity Platform's "improved email privacy")
  # is enabled by default for new projects and returns generic responses so
  # callers cannot probe which addresses have accounts. The provider does not
  # expose this field on google_identity_platform_config, so it is left at the
  # secure default rather than managed here. The portal login page uses a native
  # signInWithEmailAndPassword form (not FirebaseUI's fetchSignInMethodsForEmail
  # email-first flow), so it stays fully functional with the protection on.
}
