# SES Domain Identity and DKIM for transactional email
#
# DNS records (TXT for verification, CNAME for DKIM) must be added to the
# domain's DNS provider (Cloudflare) for verification to succeed.

resource "aws_ses_domain_identity" "this" {
  domain = var.domain
}

resource "aws_ses_domain_dkim" "this" {
  domain = aws_ses_domain_identity.this.domain
}
