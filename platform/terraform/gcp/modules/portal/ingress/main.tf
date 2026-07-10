resource "google_compute_global_address" "platform_ingress" {
  name    = "${var.name_prefix}-platform-ip"
  project = var.project_id
}

resource "google_compute_security_policy" "platform_edge" {
  name        = "${var.name_prefix}-edge"
  project     = var.project_id
  description = "Baseline Cloud Armor policy for the public Shifter ingress"

  rule {
    action      = "deny(403)"
    priority    = 1000
    description = "Block common SQL injection requests"

    match {
      expr {
        # Sensitivity 1 = OWASP CRS paranoia level 1, the recommended baseline.
        # Higher levels (this was 4) false-positive on legitimate request bodies
        # such as the base64url JWT the portal POSTs to /auth/identity/session/,
        # which Cloud Armor denied as `body_denied_by_security_policy` and broke
        # sign-in. PL1 keeps high-confidence SQLi coverage without that blast
        # radius (the prior per-rule opt-out was a symptom of the PL4 over-block).
        expression = "evaluatePreconfiguredWaf('sqli-v33-stable', {'sensitivity': 1})"
      }
    }
  }

  rule {
    action      = "deny(403)"
    priority    = 1010
    description = "Block common cross-site scripting requests"

    match {
      expr {
        expression = "evaluatePreconfiguredWaf('xss-v33-stable')"
      }
    }
  }

  rule {
    action      = "allow"
    priority    = 2147483647
    description = "Default allow"

    match {
      versioned_expr = "SRC_IPS_V1"

      config {
        src_ip_ranges = ["*"]
      }
    }
  }
}

resource "google_dns_managed_zone" "platform" {
  count = var.create_dns_managed_zone ? 1 : 0

  name        = var.dns_managed_zone_name
  project     = var.project_id
  dns_name    = var.dns_zone_dns_name
  description = "Public DNS zone for ${var.environment}"
  labels      = var.common_labels

  dnssec_config {
    state = "on"
  }
}

resource "google_dns_record_set" "platform_ingress" {
  count = var.normalized_public_hostname != "" && var.dns_managed_zone_name != "" ? 1 : 0

  project      = var.project_id
  managed_zone = var.dns_managed_zone_name
  name         = "${var.normalized_public_hostname}."
  type         = "A"
  ttl          = var.dns_record_ttl
  rrdatas      = [google_compute_global_address.platform_ingress.address]

  depends_on = [google_dns_managed_zone.platform]
}
