output "domain_identity_arn" {
  description = "ARN of the SES domain identity"
  value       = aws_ses_domain_identity.this.arn
}

output "verification_token" {
  description = "TXT record value for domain verification"
  value       = aws_ses_domain_identity.this.verification_token
}

output "dkim_tokens" {
  description = "DKIM CNAME tokens for DNS"
  value       = aws_ses_domain_dkim.this.dkim_tokens
}
