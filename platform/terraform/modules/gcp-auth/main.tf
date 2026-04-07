# Firebase Auth (Identity Platform) for Shifter Portal
#
# GCP equivalent of Cognito. Provides:
# - Email/password authentication
# - MFA (TOTP)
# - OIDC provider for Django integration (django-allauth or similar)
#
# Firebase Auth on GCP is built on Identity Platform. Terraform enables
# the API and configures project-level settings. Detailed provider config
# (email templates, domain restrictions, etc.) is managed via Firebase
# console or Admin SDK — not all settings are Terraform-manageable.
#
# The portal Django app integrates via:
# - Firebase Admin SDK (server-side token verification)
# - Firebase JS SDK (client-side auth UI)
# - Or OIDC flow with Identity Platform as the provider

terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

# Enable Identity Platform API
resource "google_project_service" "identity_platform" {
  project = var.project_id
  service = "identitytoolkit.googleapis.com"

  disable_on_destroy = false
}

# Identity Platform configuration
resource "google_identity_platform_config" "this" {
  project = var.project_id

  sign_in {
    allow_duplicate_emails = false

    email {
      enabled           = true
      password_required = true
    }
  }

  mfa {
    provider_configs {
      state = var.require_mfa ? "ENABLED" : "DISABLED"
      totp_provider_config {
        adjacent_intervals = 1
      }
    }
  }

  # Authorized domains (where auth redirects are allowed)
  authorized_domains = concat(
    ["localhost"],
    var.authorized_domains,
  )

  depends_on = [google_project_service.identity_platform]
}

# OAuth client for the portal web app (OIDC integration)
resource "google_identity_platform_oauth_idp_config" "portal" {
  count = var.create_oauth_client ? 1 : 0

  name          = "oidc.portal"
  display_name  = "Shifter Portal"
  enabled       = true
  issuer        = "https://securetoken.google.com/${var.project_id}"
  client_id     = var.oauth_client_id
  client_secret = var.oauth_client_secret
  project       = var.project_id

  depends_on = [google_identity_platform_config.this]
}
