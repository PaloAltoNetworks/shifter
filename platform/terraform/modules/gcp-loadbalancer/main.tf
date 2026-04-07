# External Application Load Balancer + Cloud Armor
#
# GCP equivalent of portal/alb. Provides HTTPS ingress for the portal
# with TLS termination and WAF protection.
#
# Architecture (GCP LB is composed of several resources):
#   Client → Global Forwarding Rule (external IP)
#          → HTTPS Proxy (TLS termination with managed cert)
#          → URL Map (routing rules)
#          → Backend Service (health checks, Cloud Armor policy)
#          → NEG (network endpoint group — targets GKE pods via Ingress)
#
# The NEG is NOT created here — it's created by GKE Ingress controller
# when the portal Kubernetes Ingress resource is applied. This module
# creates the Cloud Armor security policy that the Ingress references.
#
# In practice, you apply this module first (creates the Cloud Armor policy
# and reserves the static IP), then deploy the portal Kubernetes Ingress
# with annotations referencing these resources.

terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

# ------------------------------------------------------------------------------
# Static External IP (for DNS A record)
# ------------------------------------------------------------------------------

resource "google_compute_global_address" "portal" {
  name    = "${var.name_prefix}-portal-ip"
  project = var.project_id
}

# ------------------------------------------------------------------------------
# Google-Managed SSL Certificate
#
# GCP equivalent of ACM. Automatically provisions and renews a TLS cert.
# Requires the domain to point to the static IP (DNS must be configured
# before the cert validates — same as ACM DNS validation).
# ------------------------------------------------------------------------------

resource "google_compute_managed_ssl_certificate" "portal" {
  name    = "${var.name_prefix}-portal-cert"
  project = var.project_id

  managed {
    domains = var.domain_names
  }
}

# ------------------------------------------------------------------------------
# Cloud Armor Security Policy (WAF)
#
# GCP equivalent of AWS WAF. Attached to the backend service via
# Kubernetes Ingress annotation:
#   cloud.google.com/backend-config: '{"default": "portal-backend-config"}'
# The BackendConfig references this policy by name.
# ------------------------------------------------------------------------------

resource "google_compute_security_policy" "portal" {
  name    = "${var.name_prefix}-portal-waf"
  project = var.project_id

  # Default: allow all traffic
  rule {
    action   = "allow"
    priority = "2147483647"
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    description = "Default allow"
  }

  # Rate limiting — 2000 requests per minute per IP
  rule {
    action   = "rate_based_ban"
    priority = "1000"
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      rate_limit_threshold {
        count        = 2000
        interval_sec = 60
      }
      ban_duration_sec = 300
    }
    description = "Rate limit: 2000 req/min per IP, ban 5 min on exceed"
  }

  # Block /admin from public access
  rule {
    action   = "deny(403)"
    priority = "100"
    match {
      expr {
        expression = "request.path.matches('/admin.*')"
      }
    }
    description = "Block /admin from public access"
  }

  # OWASP ModSecurity CRS (preconfigured WAF rules)
  rule {
    action   = "deny(403)"
    priority = "2000"
    match {
      expr {
        expression = "evaluatePreconfiguredExpr('sqli-v33-stable')"
      }
    }
    description = "SQL injection protection"
  }

  rule {
    action   = "deny(403)"
    priority = "2001"
    match {
      expr {
        expression = "evaluatePreconfiguredExpr('xss-v33-stable')"
      }
    }
    description = "XSS protection"
  }

  rule {
    action   = "deny(403)"
    priority = "2002"
    match {
      expr {
        expression = "evaluatePreconfiguredExpr('lfi-v33-stable')"
      }
    }
    description = "Local file inclusion protection"
  }

  rule {
    action   = "deny(403)"
    priority = "2003"
    match {
      expr {
        expression = "evaluatePreconfiguredExpr('rfi-v33-stable')"
      }
    }
    description = "Remote file inclusion protection"
  }

  rule {
    action   = "deny(403)"
    priority = "2004"
    match {
      expr {
        expression = "evaluatePreconfiguredExpr('rce-v33-stable')"
      }
    }
    description = "Remote code execution protection"
  }
}
